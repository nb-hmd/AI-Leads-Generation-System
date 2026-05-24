import sys
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import os
import csv
import time
import random
import logging
import threading
import queue as queue_module
from io import StringIO

import gradio as gr
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# ── Project imports ───────────────────────────────────────────────────────────
from config import (
    SCRAPE_DELAY_MIN, SCRAPE_DELAY_MAX,
    EMAIL_DELAY_MIN, EMAIL_DELAY_MAX, MAX_LEADS_PER_RUN,
    SENDER_TEAM, SENDER_COMPANY, SENDER_CONTACT, SENDER_LOCATION,
    SMTP_USER,
)
from database.db import (
    init_db, get_all_leads, insert_lead, update_lead,
    delete_lead, delete_all_leads,
)
from scrapers.google_maps import scrape_with_expansion
from scrapers.website_scraper import scrape_website
from data_cleaner.cleaner import filter_leads
from ai.processor import analyze_website_content, generate_cold_email
from email_sender.sender import send_email

# ── Ensure DB exists ──────────────────────────────────────────────────────────
init_db()

# ── Display columns for the leads table ───────────────────────────────────────
DISPLAY_COLS = [
    "id", "name", "email", "phone", "website", "rating",
    "facebook", "instagram", "twitter", "linkedin",
    "business_type", "email_subject", "contacted", "created_at",
]

# ─────────────────────────────────────────────────────────────────────────────
# Live-log helper  (captures all logging output into a queue)
# ─────────────────────────────────────────────────────────────────────────────

class _QueueHandler(logging.Handler):
    def __init__(self, q: queue_module.Queue):
        super().__init__()
        self.q = q

    def emit(self, record):
        self.q.put(self.format(record))


def _stream_thread(target_fn, log_q: queue_module.Queue):
    """Run target_fn in a thread; put None sentinel when done."""
    try:
        target_fn()
    except Exception as e:
        log_q.put(f"[ERROR] {e}")
    finally:
        log_q.put(None)


def _attach_log_handler(log_q: queue_module.Queue):
    handler = _QueueHandler(log_q)
    handler.setFormatter(logging.Formatter("%(levelname)s | %(message)s"))
    handler.setLevel(logging.INFO)
    logging.getLogger().addHandler(handler)
    return handler


def _detach_log_handler(handler):
    logging.getLogger().removeHandler(handler)


# ─────────────────────────────────────────────────────────────────────────────
# Data helpers
# ─────────────────────────────────────────────────────────────────────────────

def _load_df() -> pd.DataFrame:
    leads = get_all_leads()
    if not leads:
        return pd.DataFrame(columns=DISPLAY_COLS)
    df = pd.DataFrame(leads)
    cols = [c for c in DISPLAY_COLS if c in df.columns]
    return df[cols]


def _get_stats() -> dict:
    leads = get_all_leads()
    return {
        "total":      len(leads),
        "with_email": sum(1 for l in leads if l.get("email")),
        "with_phone": sum(1 for l in leads if l.get("phone")),
        "ai_done":    sum(1 for l in leads if l.get("generated_email")),
        "contacted":  sum(1 for l in leads if l.get("contacted")),
        "ready":      sum(1 for l in leads
                         if l.get("generated_email") and l.get("email")
                         and not l.get("contacted")),
    }


def _make_bar_chart(s: dict):
    """Vertical bar chart of all lead pipeline metrics."""
    labels = [
        "Total Leads",
        "Have Email",
        "Have Phone",
        "AI Email Ready",
        "Campaign Ready",
        "Contacted",
    ]
    values = [
        s["total"],
        s["with_email"],
        s["with_phone"],
        s["ai_done"],
        s["ready"],
        s["contacted"],
    ]
    colors = [
        "#6366f1",  # indigo  — total
        "#22c55e",  # green   — email
        "#3b82f6",  # blue    — phone
        "#f59e0b",  # amber   — AI done
        "#ec4899",  # pink    — ready
        "#10b981",  # emerald — contacted
    ]
    fig = go.Figure(
        go.Bar(
            x=labels,
            y=values,
            marker_color=colors,
            text=values,
            textposition="outside",
            hovertemplate="%{x}: %{y}<extra></extra>",
        )
    )
    fig.update_layout(
        title=dict(text="Lead Pipeline Overview", font=dict(size=18, color="#f1f5f9")),
        plot_bgcolor="#0f172a",
        paper_bgcolor="#1e293b",
        font=dict(color="#f1f5f9", size=13),
        margin=dict(t=60, b=20, l=20, r=20),
        yaxis=dict(gridcolor="#334155", tickfont=dict(color="#f1f5f9")),
        xaxis=dict(tickfont=dict(size=12, color="#f1f5f9")),
        showlegend=False,
    )
    return fig


def _make_donut_chart(s: dict):
    """Donut chart: Contacted vs Ready vs Needs AI vs No Email."""
    no_email  = s["total"] - s["with_email"]
    needs_ai  = s["with_email"] - s["ai_done"] - s["contacted"]
    needs_ai  = max(needs_ai, 0)
    ready     = s["ready"]
    contacted = s["contacted"]

    labels = ["Contacted", "Ready to Send", "Needs AI Email", "No Email Found"]
    values = [contacted, ready, needs_ai, no_email]
    colors = ["#10b981", "#ec4899", "#f59e0b", "#94a3b8"]

    # Filter out zero slices
    filtered = [(l, v, c) for l, v, c in zip(labels, values, colors) if v > 0]
    if not filtered:
        filtered = [("No Data", 1, "#334155")]

    fig = go.Figure(
        go.Pie(
            labels=[f[0] for f in filtered],
            values=[f[1] for f in filtered],
            marker=dict(colors=[f[2] for f in filtered]),
            hole=0.55,
            textinfo="label+percent",
            hovertemplate="%{label}: %{value}<extra></extra>",
        )
    )
    fig.update_layout(
        title=dict(text="Lead Status Breakdown", font=dict(size=18, color="#f1f5f9")),
        plot_bgcolor="#0f172a",
        paper_bgcolor="#1e293b",
        font=dict(color="#f1f5f9", size=13),
        margin=dict(t=60, b=20, l=20, r=20),
        legend=dict(orientation="v", x=1.05, font=dict(color="#f1f5f9")),
        showlegend=True,
    )
    return fig


def _make_rating_hist():
    """Histogram of lead ratings."""
    leads = get_all_leads()
    ratings = [l["rating"] for l in leads if l.get("rating") and l["rating"] > 0]
    if not ratings:
        fig = go.Figure()
        fig.add_annotation(text="No data yet", x=0.5, y=0.5, showarrow=False, font=dict(color="#f1f5f9"))
        fig.update_layout(
            title="Rating Distribution",
            plot_bgcolor="#0f172a",
            paper_bgcolor="#1e293b",
            font=dict(color="#f1f5f9"),
        )
        return fig

    fig = go.Figure(
        go.Histogram(
            x=ratings,
            xbins=dict(start=1, end=5.5, size=0.5),
            marker_color="#6366f1",
            hovertemplate="Rating %{x}: %{y} leads<extra></extra>",
        )
    )
    fig.update_layout(
        title=dict(text="Rating Distribution", font=dict(size=18, color="#f1f5f9")),
        xaxis_title="Star Rating",
        yaxis_title="Number of Leads",
        plot_bgcolor="#0f172a",
        paper_bgcolor="#1e293b",
        font=dict(color="#f1f5f9", size=13),
        yaxis=dict(gridcolor="#334155", tickfont=dict(color="#f1f5f9")),
        xaxis=dict(tickfont=dict(color="#f1f5f9")),
        margin=dict(t=60, b=40, l=40, r=20),
    )
    return fig


def _make_socials_bar(s: dict):
    """Horizontal bar: how many leads have each social/contact channel."""
    leads = get_all_leads()
    channels = {
        "Facebook":  sum(1 for l in leads if l.get("facebook")),
        "Instagram": sum(1 for l in leads if l.get("instagram")),
        "Twitter":   sum(1 for l in leads if l.get("twitter")),
        "LinkedIn":  sum(1 for l in leads if l.get("linkedin")),
        "Phone":     sum(1 for l in leads if l.get("phone")),
        "Email":     sum(1 for l in leads if l.get("email")),
    }
    colors = ["#1877f2", "#e1306c", "#1da1f2", "#0077b5", "#22c55e", "#f59e0b"]
    fig = go.Figure(
        go.Bar(
            y=list(channels.keys()),
            x=list(channels.values()),
            orientation="h",
            marker_color=colors,
            text=list(channels.values()),
            textposition="outside",
            hovertemplate="%{y}: %{x} leads<extra></extra>",
        )
    )
    fig.update_layout(
        title=dict(text="Contact Channels Found", font=dict(size=18, color="#f1f5f9")),
        plot_bgcolor="#0f172a",
        paper_bgcolor="#1e293b",
        font=dict(color="#f1f5f9", size=13),
        xaxis=dict(gridcolor="#334155", tickfont=dict(color="#f1f5f9")),
        yaxis=dict(tickfont=dict(color="#f1f5f9")),
        margin=dict(t=60, b=20, l=20, r=60),
        showlegend=False,
    )
    return fig


def _refresh_all_charts():

    """Return all four charts + summary numbers for the Dashboard tab."""
    s = _get_stats()
    summary = (
        f"**{s['total']}** Total Leads &nbsp;|&nbsp; "
        f"**{s['with_email']}** Have Email &nbsp;|&nbsp; "
        f"**{s['ai_done']}** AI Emails Done &nbsp;|&nbsp; "
        f"**{s['ready']}** Ready to Send &nbsp;|&nbsp; "
        f"**{s['contacted']}** Contacted"
    )
    return (
        summary,
        _make_bar_chart(s),
        _make_donut_chart(s),
        _make_rating_hist(),
        _make_socials_bar(s),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Tab 1 — Scrape  (live streaming)
# ─────────────────────────────────────────────────────────────────────────────

def run_scrape(business_type: str, location: str, max_results: int):
    """
    Generator — streams live log output while scraping.
    Yields tuples: (log_text, new_lead_ids)
    new_lead_ids is populated only on the final yield so the caller
    can store the current-session IDs in gr.State.
    """
    if not business_type.strip() or not location.strip():
        yield "Please enter both a business type and a location.", []
        return

    log_q: queue_module.Queue = queue_module.Queue()
    # new_ids tracks every lead ID saved in THIS scrape session
    result_box = {"saved": 0, "skipped": 0, "failed": 0, "new_ids": []}

    def pipeline():
        log_q.put(
            f"Starting multi-query expansion for '{business_type.strip()}' "
            f"in '{location.strip()}' — target: {int(max_results)} leads..."
        )
        raw = scrape_with_expansion(
            business_type=business_type.strip(),
            location=location.strip(),
            max_results=int(max_results),
        )
        if not raw:
            log_q.put("No leads found on Google Maps.")
            return

        filtered = filter_leads(raw)
        log_q.put(
            f"Google Maps: {len(raw)} found → {len(filtered)} valid (have website)."
        )

        for lead in filtered:
            log_q.put(f"Crawling: {lead['name']}  ({lead['website']})")
            web = scrape_website(lead["website"])
            if web.get("success"):
                lead["email"]     = web.get("email")
                lead["phone"]     = web.get("phone") or lead.get("phone")
                socials           = web.get("socials", {})
                lead["linkedin"]  = socials.get("linkedin")
                lead["twitter"]   = socials.get("twitter")
                lead["instagram"] = socials.get("instagram")
                lead["facebook"]  = socials.get("facebook")
                lid = insert_lead(lead)
                if lid:
                    update_lead(lid, {"notes": web.get("text", "")})
                    result_box["saved"] += 1
                    result_box["new_ids"].append(lid)   # ← track session ID
                    log_q.put(
                        f"  ✓ Saved: {lead['name']} | "
                        f"Email: {lead.get('email')} | Phone: {lead.get('phone')}"
                    )
                else:
                    result_box["skipped"] += 1
                    log_q.put(f"  – Skipped (duplicate): {lead['name']}")
            else:
                result_box["failed"] += 1
                log_q.put(f"  ✗ Crawl failed: {lead['website']}")

            time.sleep(random.uniform(SCRAPE_DELAY_MIN, SCRAPE_DELAY_MAX))

        log_q.put(
            f"\n{'='*50}\n"
            f"✅ Scrape complete!\n"
            f"   Saved: {result_box['saved']}  |  "
            f"Skipped (duplicates): {result_box['skipped']}  |  "
            f"Crawl failed: {result_box['failed']}\n"
            f"   Session lead IDs: {result_box['new_ids']}\n\n"
            f"➡ Now go to the 'AI Process' tab to generate invitations for these leads."
        )

    handler = _attach_log_handler(log_q)
    t = threading.Thread(target=_stream_thread, args=(pipeline, log_q), daemon=True)
    t.start()

    lines = []
    while True:
        try:
            msg = log_q.get(timeout=2)
            if msg is None:
                break
            lines.append(msg)
            yield "\n".join(lines), []   # intermediate: IDs not ready yet
        except queue_module.Empty:
            if not t.is_alive():
                break

    _detach_log_handler(handler)
    # Final yield: pass real session IDs so gr.State gets updated
    yield "\n".join(lines), result_box["new_ids"]


# ─────────────────────────────────────────────────────────────────────────────
# Tab 2 — AI Process  (SESSION-ONLY — only processes current scrape's leads)
# ─────────────────────────────────────────────────────────────────────────────

def run_ai_process_for_session(session_ids: list):
    """
    Generator — streams live log while AI generates podcast invitations.
    ONLY processes leads whose IDs are in session_ids (current scrape session).
    Old leads already in the database are NOT touched.
    """
    log_q: queue_module.Queue = queue_module.Queue()

    def pipeline():
        # Guard: must have run a scrape first
        if not session_ids:
            log_q.put(
                "⚠️  No current session leads found.\n\n"
                "Please go to the 'Scrape Leads' tab, run a scrape, "
                "and then come back here to generate invitations."
            )
            return

        # Filter all DB leads to ONLY current session
        all_leads = get_all_leads()
        session_set = set(session_ids)

        # Leads in this session that still need AI processing
        to_process = [
            l for l in all_leads
            if l["id"] in session_set
            and not l.get("generated_email")
            and l.get("notes")
        ]

        # Leads already processed in this session
        already_done = [
            l for l in all_leads
            if l["id"] in session_set and l.get("generated_email")
        ]

        log_q.put(
            f"Current session: {len(session_ids)} leads scraped\n"
            f"  → {len(to_process)} need invitation generation\n"
            f"  → {len(already_done)} already processed\n"
        )

        if not to_process:
            log_q.put(
                "ℹ️  All current session leads already have invitations.\n"
                "Go to 'Email Review & Edit' tab to review and customise them."
            )
            return

        log_q.put(f"Generating invitations for {len(to_process)} leads via GPT-4o-mini...\n")

        for lead in to_process:
            log_q.put(f"Analyzing: {lead['name']}")
            analysis = analyze_website_content(lead["notes"])
            if not analysis:
                log_q.put(f"  ✗ Analysis failed — skipping.")
                continue

            result = generate_cold_email(lead["name"], analysis)
            if result:
                angles    = analysis.get("interesting_angles", [])
                expertise = analysis.get("expertise_area", "")
                why_guest = analysis.get("why_good_guest", "")
                update_lead(lead["id"], {
                    "business_type":   analysis.get("business_type"),
                    "pain_points":     ", ".join(angles),
                    "opportunities":   f"{expertise} | {why_guest}".strip(" |"),
                    "email_subject":   result["subject"],
                    "generated_email": result["body"],
                })
                log_q.put(f"  ✓ Subject: {result['subject']}")
                log_q.put(f"  ✓ Invitation ready for {lead['name']}")
            else:
                log_q.put(f"  ✗ Invitation generation failed for {lead['name']}")

            time.sleep(2)

        log_q.put(
            f"\n{'='*50}\n"
            f"✅ Done! Invitations generated for {len(to_process)} session leads.\n\n"
            f"➡ Go to 'Email Review & Edit' tab to review, edit, and customise "
            f"each invitation before sending."
        )

    handler = _attach_log_handler(log_q)
    t = threading.Thread(target=_stream_thread, args=(pipeline, log_q), daemon=True)
    t.start()

    lines = []
    while True:
        try:
            msg = log_q.get(timeout=2)
            if msg is None:
                break
            lines.append(msg)
            yield "\n".join(lines)
        except queue_module.Empty:
            if not t.is_alive():
                break

    _detach_log_handler(handler)
    yield "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# AI Process — Individual Lead Helper Functions
# ─────────────────────────────────────────────────────────────────────────────

def _get_notes_leads_choices(only_unprocessed=True):
    """Return dropdown choices for all leads that have website notes."""
    leads = get_all_leads()
    choices = []
    for l in leads:
        # Must have website notes to be processable by AI
        if not l.get("notes") or len(l.get("notes", "").strip()) < 50:
            continue
        # Optionally filter to only unprocessed ones
        if only_unprocessed and l.get("generated_email"):
            continue
        choices.append(f"{l['id']} — {l['name']}")
    return choices


def filter_single_choices(only_unprocessed: bool):
    """Gradio helper to filter dropdown choices for individual lead processing."""
    choices = _get_notes_leads_choices(only_unprocessed=only_unprocessed)
    return gr.Dropdown(choices=choices, value=choices[0] if choices else None)



def load_lead_info_for_ai(choice: str):
    """Load a lead's basic info and crawled notes preview."""
    if not choice:
        return "⚠️ No lead selected.", "", "", "", "", "", ""
    try:
        lead_id = int(choice.split("—")[0].strip())
    except (ValueError, IndexError):
        return "⚠️ Invalid lead selection.", "", "", "", "", "", ""
        
    leads = get_all_leads()
    lead = next((l for l in leads if l["id"] == lead_id), None)
    if not lead:
        return "⚠️ Lead not found.", "", "", "", "", "", ""
        
    # Create a nice markdown summary
    info_md = (
        f"### 📋 Selected Lead Details\n"
        f"**Business Name:** {lead['name']}\n"
        f"**Website URL:** [{lead.get('website')}]({lead.get('website')})\n"
        f"**Google Rating:** ⭐ {lead.get('rating') or 'N/A'} | **Phone:** {lead.get('phone') or 'N/A'}\n"
        f"**Address:** {lead.get('address') or 'N/A'}\n\n"
        f"**Crawled Website Notes Preview (First 400 chars):**\n"
        f"```text\n{lead.get('notes', '')[:400]}...\n```"
    )
    
    # Load any existing fields if previously generated
    angles_str = lead.get("pain_points") or ""
    # Map opportunities → expertise and why_good_guest
    opp_str = lead.get("opportunities") or ""
    expertise = ""
    why_good_guest = ""
    if " | " in opp_str:
        parts = opp_str.split(" | ", 1)
        expertise = parts[0]
        why_good_guest = parts[1]
    else:
        expertise = opp_str
        
    return (
        info_md,
        lead.get("business_type") or "",
        expertise,
        angles_str,
        why_good_guest,
        lead.get("email_subject") or "",
        lead.get("generated_email") or ""
    )


def run_ai_process_for_single_lead(choice: str):
    """Analyze website text with AI and generate email for a single selected lead."""
    if not choice:
        return "⚠️ No lead selected.", "", "", "", "", "", ""
    try:
        lead_id = int(choice.split("—")[0].strip())
    except (ValueError, IndexError):
        return "⚠️ Invalid lead selection.", "", "", "", "", "", ""
        
    leads = get_all_leads()
    lead = next((l for l in leads if l["id"] == lead_id), None)
    if not lead:
        return "⚠️ Lead not found in database.", "", "", "", "", "", ""
        
    if not lead.get("notes") or len(lead["notes"].strip()) < 50:
        return "⚠️ This lead does not have enough scraped website content to analyze.", "", "", "", "", "", ""
        
    # Run analysis
    analysis = analyze_website_content(lead["notes"])
    if not analysis:
        return "❌ AI analysis of website content failed. Please check your OpenAI API key or model settings.", "", "", "", "", "", ""
        
    # Generate email
    email_result = generate_cold_email(lead["name"], analysis)
    if not email_result:
        return "❌ Cold email generation failed. Please check your OpenAI API key or settings.", "", "", "", "", "", ""
        
    # Map and update in DB
    angles = analysis.get("interesting_angles", [])
    expertise = analysis.get("expertise_area", "")
    why_guest = analysis.get("why_good_guest", "")
    opp_str = f"{expertise} | {why_guest}".strip(" |")
    
    update_data = {
        "business_type":   analysis.get("business_type"),
        "pain_points":     ", ".join(angles),
        "opportunities":   opp_str,
        "email_subject":   email_result["subject"],
        "generated_email": email_result["body"],
    }
    update_lead(lead_id, update_data)
    
    status = f"✅ Successfully analyzed and generated invitation for **{lead['name']}**!"
    return (
        status,
        analysis.get("business_type") or "",
        expertise,
        ", ".join(angles),
        why_guest,
        email_result["subject"],
        email_result["body"]
    )


def save_single_lead_ai_edit(choice: str, business_type: str, expertise: str, angles: str, why_guest: str, subject: str, body: str):
    """Save manually customized AI analysis and email fields back to the DB."""
    if not choice:
        return "❌ No lead selected."
    try:
        lead_id = int(choice.split("—")[0].strip())
    except (ValueError, IndexError):
        return "❌ Invalid lead selection."
        
    opp_str = f"{expertise.strip()} | {why_guest.strip()}".strip(" |")
    update_data = {
        "business_type":   business_type.strip(),
        "pain_points":     angles.strip(),
        "opportunities":   opp_str,
        "email_subject":   subject.strip(),
        "generated_email": body.strip(),
    }
    
    update_lead(lead_id, update_data)
    return f"✅ Saved customization for Lead #{lead_id} successfully! Ready for campaign."


# ─────────────────────────────────────────────────────────────────────────────
# Tab 3 — Database

# ─────────────────────────────────────────────────────────────────────────────

def db_refresh():
    s = _get_stats()
    summary = (
        f"**{s['total']}** Total &nbsp;|&nbsp; "
        f"**{s['with_email']}** Have Email &nbsp;|&nbsp; "
        f"**{s['ai_done']}** AI Done &nbsp;|&nbsp; "
        f"**{s['ready']}** Ready &nbsp;|&nbsp; "
        f"**{s['contacted']}** Contacted"
    )
    return _load_df(), summary


def db_delete_one(lead_id_str: str):
    try:
        lid = int(str(lead_id_str).strip())
        delete_lead(lid)
        df, summary = db_refresh()
        return f"Deleted lead ID {lid}.", df, summary
    except (ValueError, TypeError):
        df, summary = db_refresh()
        return "Enter a valid numeric Lead ID.", df, summary


def db_delete_all():
    delete_all_leads()
    df, summary = db_refresh()
    return "All leads deleted.", df, summary


# ─────────────────────────────────────────────────────────────────────────────
# Tab 4 — Email Review & Edit
# ─────────────────────────────────────────────────────────────────────────────

def _email_choices():
    """Return dropdown choices for all leads in the database with status tags."""
    leads = get_all_leads()
    choices = []
    for l in leads:
        tag = ""
        if not l.get("email"):
            tag = " [No Email]"
        elif not l.get("generated_email"):
            tag = " [Needs AI]"
        choices.append(f"{l['id']} — {l['name']}{tag}")
    return choices


def _email_choices_for_session(session_ids: list):
    """Return dropdown choices restricted to current session leads with tags."""
    if not session_ids:
        return _email_choices()   # fallback: show all if no session
    session_set = set(session_ids)
    leads = get_all_leads()
    choices = []
    for l in leads:
        if l["id"] not in session_set:
            continue
        tag = ""
        if not l.get("email"):
            tag = " [No Email]"
        elif not l.get("generated_email"):
            tag = " [Needs AI]"
        choices.append(f"{l['id']} — {l['name']}{tag}")
    return choices



def load_email_for_edit(choice: str):
    """Load a lead's email into editable fields."""
    if not choice:
        return "No lead selected.", "", ""
    try:
        lead_id = int(choice.split("—")[0].strip())
    except (ValueError, IndexError):
        return "Invalid selection.", "", ""
    leads = get_all_leads()
    lead = next((l for l in leads if l["id"] == lead_id), None)
    if not lead:
        return "Lead not found.", "", ""
    info = (
        f"**{lead['name']}**  |  "
        f"📧 {lead.get('email') or '—'}  |  "
        f"📞 {lead.get('phone') or '—'}  |  "
        f"🌐 {lead.get('website') or '—'}  |  "
        f"⭐ {lead.get('rating') or '—'}  |  "
        f"📂 {lead.get('business_type') or '—'}"
    )
    subject = lead.get("email_subject") or ""
    body    = lead.get("generated_email") or ""
    return info, subject, body


def save_email_edit(choice: str, new_subject: str, new_body: str):
    """Persist user-edited subject and body back to the database."""
    if not choice:
        return "❌ No lead selected."
    try:
        lead_id = int(choice.split("—")[0].strip())
        update_lead(lead_id, {
            "email_subject":   new_subject.strip(),
            "generated_email": new_body.strip(),
        })
        return f"✅ Changes saved for Lead #{lead_id}. The campaign will use this updated version."
    except Exception as e:
        return f"❌ Error saving changes: {e}"


def refresh_email_choices():
    choices = _email_choices()
    return gr.Dropdown(choices=choices, value=choices[0] if choices else None)


def refresh_email_choices_session(session_ids: list):
    choices = _email_choices_for_session(session_ids)
    return gr.Dropdown(choices=choices, value=choices[0] if choices else None)


# ─────────────────────────────────────────────────────────────────────────────
# Tab 5 — Campaign  (live streaming)
# ─────────────────────────────────────────────────────────────────────────────

def run_campaign():
    """Generator — streams live log while sending emails."""
    log_q: queue_module.Queue = queue_module.Queue()

    def pipeline():
        leads = get_all_leads(uncontacted_only=True)
        to_contact = [
            l for l in leads
            if l.get("generated_email") and l.get("email")
        ]
        if not to_contact:
            log_q.put(
                "No leads ready to contact.\n"
                "Leads need both an email address AND a generated email.\n"
                "Run Scrape + AI Process first."
            )
            return

        log_q.put(f"Sending emails to {len(to_contact)} leads via {SMTP_USER}...")

        sent, failed = 0, 0
        for lead in to_contact:
            subject = lead.get("email_subject") or f"Quick idea for {lead['name']}"
            body    = lead["generated_email"]
            to_addr = lead["email"]

            log_q.put(f"\nSending to: {lead['name']} <{to_addr}>")
            log_q.put(f"  Subject: {subject}")

            ok = send_email(to_addr, subject, body)
            if ok:
                update_lead(lead["id"], {"contacted": True})
                log_q.put(f"  Sent successfully!")
                sent += 1
            else:
                update_lead(lead["id"], {"error_log": "Send failed"})
                log_q.put(f"  FAILED to send.")
                failed += 1

            time.sleep(random.uniform(EMAIL_DELAY_MIN, EMAIL_DELAY_MAX))

        log_q.put(f"\nCampaign done! Sent:{sent} | Failed:{failed}")

    handler = _attach_log_handler(log_q)
    t = threading.Thread(target=_stream_thread, args=(pipeline, log_q), daemon=True)
    t.start()

    lines = []
    while True:
        try:
            msg = log_q.get(timeout=2)
            if msg is None:
                break
            lines.append(msg)
            yield "\n".join(lines)
        except queue_module.Empty:
            if not t.is_alive():
                break

    _detach_log_handler(handler)
    yield "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Tab 6 — Export
# ─────────────────────────────────────────────────────────────────────────────

def export_csv():
    os.makedirs("data", exist_ok=True)
    path = os.path.abspath("data/leads_export.csv")
    leads = get_all_leads()
    if not leads:
        return None, "No leads to export."
    df = pd.DataFrame(leads)
    df.to_csv(path, index=False, encoding="utf-8")
    return path, f"Exported {len(leads)} leads to leads_export.csv"


# ─────────────────────────────────────────────────────────────────────────────
# Build the Gradio app
# ─────────────────────────────────────────────────────────────────────────────

def build_app():
    init_charts = _refresh_all_charts()
    initial_df  = _load_df()

    with gr.Blocks(title="AI Leads Generation System") as app:

        gr.Markdown(
            "# AI Leads Generation System\n"
            "Scrape Google Maps → Crawl Websites → Generate AI Emails → Send Campaign"
        )

        # ── Session state: IDs of leads saved in the most recent scrape ──────
        # This ensures AI Process only works on leads from THIS scrape session.
        session_lead_ids = gr.State([])

        # \u2500\u2500 TAB 1: DASHBOARD \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
        with gr.Tab("Dashboard"):
            dash_summary  = gr.Markdown(value=init_charts[0])

            with gr.Row():
                chart_bar    = gr.Plot(value=init_charts[1], label="Pipeline Overview")
                chart_donut  = gr.Plot(value=init_charts[2], label="Lead Status")

            with gr.Row():
                chart_rating  = gr.Plot(value=init_charts[3], label="Rating Distribution")
                chart_socials = gr.Plot(value=init_charts[4], label="Contact Channels")

            with gr.Row():
                refresh_dash_btn = gr.Button("\u21ba Refresh Charts", variant="secondary")

            refresh_dash_btn.click(
                fn=_refresh_all_charts,
                outputs=[dash_summary, chart_bar, chart_donut, chart_rating, chart_socials],
            )

            gr.Markdown("---")
            gr.Markdown(
                "### Quick Start Guide\n"
                "1. **Scrape Leads** \u2192 Enter business type + location \u2192 click Scrape\n"
                "2. **AI Process** \u2192 Click Generate Emails (needs OpenAI key in `.env`)\n"
                "3. **Email Preview** \u2192 Review each generated email\n"
                "4. **Campaign** \u2192 Send emails to leads that have email addresses\n"
                "5. **Database** \u2192 View / delete leads\n"
                "6. **Export** \u2192 Download leads as CSV\n\n"
                f"**Sender Identity:** {SENDER_TEAM} \u00b7 {SENDER_CONTACT} \u00b7 "
                f"{SENDER_COMPANY}, {SENDER_LOCATION}"
            )


        # ── TAB 2: SCRAPE ────────────────────────────────────────────────────
        with gr.Tab("Scrape Leads"):
            gr.Markdown(
                "### Scrape Google Maps\n"
                "Crawls up to 50+ results via multi-query geographic expansion, "
                "then visits each website to extract emails, phones & social links.\n\n"
                "**After scraping completes, go to the AI Process tab** to generate "
                "invitations for these leads."
            )
            with gr.Row():
                biz_type = gr.Textbox(
                    label="Business Type",
                    placeholder="e.g. Real Estate, Dentists, Architects, Law Firms",
                    scale=2,
                )
                location = gr.Textbox(
                    label="Location",
                    placeholder="e.g. London, Manchester, Dallas TX",
                    scale=2,
                )
                n_leads = gr.Slider(
                    label="Target Leads to Collect",
                    minimum=5, maximum=100, step=5, value=20,
                    scale=1,
                )
            scrape_btn = gr.Button("🔍 Start Scraping", variant="primary")
            scrape_log = gr.Textbox(
                label="Live Progress Log",
                lines=20, max_lines=40,
                interactive=False,
                placeholder="Scraping log will appear here...",
            )
            # Scrape outputs BOTH the log AND the session lead IDs
            scrape_btn.click(
                fn=run_scrape,
                inputs=[biz_type, location, n_leads],
                outputs=[scrape_log, session_lead_ids],
            )

        # ── TAB 3: AI PROCESS ────────────────────────────────────────────────
        with gr.Tab("AI Process"):
            gr.Markdown(
                "## 🤖 AI Podcast Invitation Generator\n"
                "Analyze lead business websites and generate personalized guest invitations.\n\n"
                f"**Sender Identity:** {SENDER_TEAM} · {SENDER_CONTACT} · "
                f"{SENDER_COMPANY}, {SENDER_LOCATION}"
            )

            with gr.Accordion("Option A: Bulk Process Current Scrape Session", open=False):
                gr.Markdown(
                    "This option will batch process **only the leads collected in your most recent scraping run** "
                    "in this browser session. Old leads already stored in your database will not be touched."
                )
                process_btn = gr.Button(
                    "🤖 Generate Invitations for Current Session Leads",
                    variant="primary",
                )
                process_log = gr.Textbox(
                    label="Live Processing Log",
                    lines=15, max_lines=30,
                    interactive=False,
                    placeholder="AI processing log will appear here...\n"
                                "(Run Scrape Leads first, then click the button above)",
                )
                process_btn.click(
                    fn=run_ai_process_for_session,
                    inputs=[session_lead_ids],
                    outputs=process_log,
                )

            with gr.Accordion("Option B: Deep Review & Process Individual Lead", open=True):
                gr.Markdown(
                    "Select a specific lead from your database, review its website crawled content, "
                    "generate its personalized email invitation with AI, and customize the output instantly."
                )
                
                # Fetch initial choices
                initial_notes_choices = _get_notes_leads_choices(only_unprocessed=True)
                
                with gr.Row():
                    single_lead_selector = gr.Dropdown(
                        label="Select Lead from Database (needs crawled website data)",
                        choices=initial_notes_choices,
                        value=initial_notes_choices[0] if initial_notes_choices else None,
                        scale=3,
                    )
                    only_unprocessed_chk = gr.Checkbox(
                        label="Only show leads needing AI email",
                        value=True,
                        scale=1,
                    )
                    refresh_single_btn = gr.Button("🔄 Refresh List", scale=1)
                
                # Dynamic Lead Summary Card
                single_lead_summary = gr.Markdown(
                    value="### 📋 Selected Lead Details\nSelect a lead from the dropdown to see details."
                )
                
                single_process_btn = gr.Button("🤖 Run AI Deep Review & Generate Email", variant="primary")
                single_process_status = gr.Markdown(value="")
                
                # Interactive AI Analysis & Customization Pane
                with gr.Group():
                    gr.Markdown("### 🛠️ AI Deep Review & Email Customization")
                    gr.Markdown("Review the AI analysis findings and edit the generated email body or subject line below. Click Save Changes when you're done.")
                    
                    with gr.Row():
                        single_biz_type = gr.Textbox(
                            label="Business Type (AI Analyzed)",
                            lines=1,
                            interactive=True,
                            placeholder="AI analyzed business description will load here",
                        )
                        single_expertise = gr.Textbox(
                            label="Main Expertise Area (AI Analyzed)",
                            lines=1,
                            interactive=True,
                            placeholder="AI analyzed expertise will load here",
                        )
                        
                    with gr.Row():
                        single_angles = gr.Textbox(
                            label="Interesting Podcast Angles (AI Analyzed)",
                            lines=2,
                            interactive=True,
                            placeholder="AI analyzed podcast angles (comma separated) will load here",
                        )
                        single_why_guest = gr.Textbox(
                            label="Why They'd Be a Great Guest (AI Analyzed)",
                            lines=2,
                            interactive=True,
                            placeholder="AI analyzed guest potential will load here",
                        )
                    
                    gr.Markdown("---")
                    single_subject = gr.Textbox(
                        label="Invitation Email Subject Line",
                        lines=1,
                        interactive=True,
                        placeholder="Generated subject line will load here — edit as needed",
                    )
                    
                    single_body = gr.Textbox(
                        label="Invitation Email Body",
                        lines=18,
                        interactive=True,
                        placeholder="Generated email body will load here — fully editable",
                    )
                    
                    with gr.Row():
                        single_save_btn = gr.Button("💾 Save Invitation & Customization", variant="primary", scale=2)
                        single_save_status = gr.Textbox(
                            label="Save Status",
                            interactive=False,
                            scale=3,
                        )

                # Wire event handlers
                single_lead_selector.change(
                    fn=load_lead_info_for_ai,
                    inputs=[single_lead_selector],
                    outputs=[
                        single_lead_summary,
                        single_biz_type,
                        single_expertise,
                        single_angles,
                        single_why_guest,
                        single_subject,
                        single_body,
                    ]
                )
                
                only_unprocessed_chk.change(
                    fn=filter_single_choices,
                    inputs=[only_unprocessed_chk],
                    outputs=[single_lead_selector]
                )
                
                refresh_single_btn.click(
                    fn=filter_single_choices,
                    inputs=[only_unprocessed_chk],
                    outputs=[single_lead_selector]
                )
                
                single_process_btn.click(
                    fn=run_ai_process_for_single_lead,
                    inputs=[single_lead_selector],
                    outputs=[
                        single_process_status,
                        single_biz_type,
                        single_expertise,
                        single_angles,
                        single_why_guest,
                        single_subject,
                        single_body,
                    ]
                )
                
                single_save_btn.click(
                    fn=save_single_lead_ai_edit,
                    inputs=[
                        single_lead_selector,
                        single_biz_type,
                        single_expertise,
                        single_angles,
                        single_why_guest,
                        single_subject,
                        single_body,
                    ],
                    outputs=[single_save_status]
                )


        # ── TAB 4: DATABASE ──────────────────────────────────────────────────
        with gr.Tab("Database"):
            gr.Markdown("### Leads Database")
            db_stats_md  = gr.Markdown(value=init_charts[0])
            db_table     = gr.Dataframe(
                value=initial_df,
                interactive=False,
                wrap=True,
                label="All Leads",
            )
            with gr.Row():
                db_refresh_btn = gr.Button("Refresh", variant="secondary")

            gr.Markdown("---")
            gr.Markdown("#### Delete Leads")
            with gr.Row():
                delete_id_box = gr.Textbox(
                    label="Lead ID to Delete",
                    placeholder="Enter numeric ID from table above",
                    scale=2,
                )
                delete_one_btn = gr.Button("Delete This Lead", variant="secondary", scale=1)
                delete_all_btn = gr.Button("Delete ALL Leads", variant="stop", scale=1)

            db_msg = gr.Textbox(label="Status", interactive=False)

            # Wire refresh
            db_refresh_btn.click(
                fn=db_refresh,
                outputs=[db_table, db_stats_md],
            )
            # Wire delete one
            delete_one_btn.click(
                fn=db_delete_one,
                inputs=[delete_id_box],
                outputs=[db_msg, db_table, db_stats_md],
            )
            # Wire delete all
            delete_all_btn.click(
                fn=db_delete_all,
                outputs=[db_msg, db_table, db_stats_md],
            )

        # ── TAB 5: EMAIL REVIEW & EDIT ────────────────────────────────────────
        with gr.Tab("Email Review & Edit"):
            gr.Markdown(
                "### ✏️ Review & Edit Generated Invitations\n"
                "Select a lead, review the AI-generated invitation, "
                "**edit the subject and body as needed**, then click **Save Changes**.\n\n"
                "The campaign will always use the latest saved version — "
                "so you can fully personalise every email before sending."
            )
            initial_choices = _email_choices()
            with gr.Row():
                email_selector = gr.Dropdown(
                    label="Select Lead",
                    choices=initial_choices,
                    value=initial_choices[0] if initial_choices else None,
                    scale=4,
                )
                refresh_emails_btn = gr.Button("🔄 Refresh List", scale=1)

            load_btn = gr.Button("📂 Load Email for Editing", variant="secondary")
            lead_info_md = gr.Markdown()

            gr.Markdown("#### Subject Line")
            edit_subject = gr.Textbox(
                label="Subject Line (editable)",
                lines=1,
                interactive=True,
                placeholder="Subject will load here — edit as needed",
            )

            gr.Markdown("#### Email Body")
            edit_body = gr.Textbox(
                label="Email Body (editable)",
                lines=22,
                interactive=True,
                placeholder="Email body will load here — edit as needed before sending",
            )

            with gr.Row():
                save_btn    = gr.Button("💾 Save Changes", variant="primary", scale=2)
                save_status = gr.Textbox(
                    label="Save Status", interactive=False, scale=3
                )

            # Load selected lead's email into editable fields
            load_btn.click(
                fn=load_email_for_edit,
                inputs=[email_selector],
                outputs=[lead_info_md, edit_subject, edit_body],
            )
            # Also load on dropdown change for convenience
            email_selector.change(
                fn=load_email_for_edit,
                inputs=[email_selector],
                outputs=[lead_info_md, edit_subject, edit_body],
            )
            # Save edited email back to DB
            save_btn.click(
                fn=save_email_edit,
                inputs=[email_selector, edit_subject, edit_body],
                outputs=save_status,
            )
            # Refresh dropdown list
            refresh_emails_btn.click(
                fn=refresh_email_choices,
                outputs=[email_selector],
            )

        # ── TAB 6: CAMPAIGN ──────────────────────────────────────────────────
        with gr.Tab("Email Campaign"):
            gr.Markdown(
                "### Send Cold Email Campaign\n"
                "Sends AI-generated emails to all leads that have:\n"
                "- An email address (found by website crawler)\n"
                "- A generated cold email (from AI Process tab)\n"
                "- Not yet contacted\n\n"
                f"Sending from: **{SMTP_USER}**"
            )
            campaign_btn = gr.Button("Send Campaign Now", variant="primary")
            campaign_log = gr.Textbox(
                label="Campaign Log",
                lines=20, max_lines=40,
                interactive=False,
                placeholder="Campaign log will appear here...",
            )
            campaign_btn.click(
                fn=run_campaign,
                outputs=campaign_log,
            )

        # ── TAB 7: EXPORT ────────────────────────────────────────────────────
        with gr.Tab("Export"):
            gr.Markdown(
                "### Export Leads to CSV\n"
                "Downloads all leads from the database as a UTF-8 CSV file."
            )
            export_btn    = gr.Button("Export to CSV", variant="primary")
            export_status = gr.Textbox(label="Status", interactive=False)
            export_file   = gr.File(label="Download CSV", visible=False)

            def do_export():
                path, msg = export_csv()
                if path:
                    return msg, gr.File(value=path, visible=True)
                return msg, gr.File(visible=False)

            export_btn.click(
                fn=do_export,
                outputs=[export_status, export_file],
            )

    return app


# ─────────────────────────────────────────────────────────────────────────────
# Launch
# ─────────────────────────────────────────────────────────────────────────────

def launch_dashboard():
    app = build_app()
    app.launch(
        server_name="127.0.0.1",
        server_port=7860,
        share=False,
        theme=gr.themes.Soft(),
    )


if __name__ == "__main__":
    launch_dashboard()
