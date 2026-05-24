"""
NextMedia London Podcast Guest Invitation System.

Analyzes scraped business websites to understand who they are,
then generates a personalized podcast guest invitation email on behalf of
NextMedia London — a professional podcast & video studio in Bermondsey, London.

Compatible with openai SDK v2.x.
"""

import json
import logging
from openai import OpenAI
from config import (
    OPENAI_API_KEY, OPENAI_MODEL,
    SENDER_TEAM, SENDER_COMPANY, SENDER_LOCATION, SENDER_CONTACT,
)

logger = logging.getLogger(__name__)

_client = None

def _get_client() -> OpenAI:
    global _client
    if _client is None:
        if not OPENAI_API_KEY:
            raise RuntimeError("OPENAI_API_KEY is not set. Add it to your .env file.")
        _client = OpenAI(api_key=OPENAI_API_KEY)
    return _client


# ─────────────────────────────────────────────────────────────────────────────
# NextMedia London — Studio Profile (used in every email prompt)
# ─────────────────────────────────────────────────────────────────────────────

STUDIO_PROFILE = """
NextMedia London is a professional podcast and video production studio located at:
  Studio 214, Cocoa Studios, The Biscuit Factory, 100 Drummond Rd, Bermondsey, London SE16 4DG

What we offer to podcast guests:
- Fully soundproofed, acoustically treated recording studio
- 4K multi-camera Sony Cinema Line video recording system
- Broadcast-quality microphones (Rode PodMic, Shure) and RodeCaster Pro audio mixer
- Professional lighting optimised for on-camera interviews
- Dedicated on-site Studio Engineer for every session — guests just talk, we handle everything
- Teleprompter system and customisable TV branding displays
- Comfortable guest seating area and fast Wi-Fi
- Remote guest support (can join from anywhere)
- Full post-production: audio/video editing, colour correction, content distribution
- Social media content repurposing from each episode (clips, audiograms, thumbnails)
- Flexible bookings: hourly or daily

Website: https://nextmedia.london
Email: info@nextmedia.london
Phone: +44 7717 666929
""".strip()


# ─────────────────────────────────────────────────────────────────────────────
# Prompt 1: Business Analysis for Podcast Guest Targeting
# ─────────────────────────────────────────────────────────────────────────────

ANALYSIS_PROMPT = """
You are a podcast booking researcher at NextMedia London, a professional podcast studio in London.

Analyze the following business website content. Your goal is to identify whether this person/business
would make an interesting podcast guest — someone who can share expertise, insights, or an inspiring
story with our audience.

Return ONLY valid JSON — no markdown, no explanation — with exactly these keys:
{{
  "business_type": "one sentence describing exactly what the business does and who runs it",
  "expertise_area": "the main area of expertise or knowledge this person/business could share on a podcast",
  "target_audience": "who their customers/clients are",
  "interesting_angles": [
    "compelling podcast topic or story angle 1",
    "compelling podcast topic or story angle 2",
    "compelling podcast topic or story angle 3"
  ],
  "why_good_guest": "one sentence explaining why this person/business would be a valuable podcast guest"
}}

Website Content:
{content}
""".strip()


# ─────────────────────────────────────────────────────────────────────────────
# Prompt 2: Podcast Guest Invitation Email
# ─────────────────────────────────────────────────────────────────────────────

EMAIL_PROMPT = """
You are writing a highly personalized podcast guest invitation email on behalf of {sender_company}, a professional
podcast and video production studio in London.

Your goal is to invite {lead_name} to be a guest on a podcast episode recorded at NextMedia London's
state-of-the-art studio in Bermondsey, London.

About NextMedia London Studio:
{studio_profile}

Rules for the email:
- Subject line: Warm, personal, engaging, and under 65 characters. It must be highly relevant to their specific business niche, area of expertise, or one of the proposed podcast angles.
  CRITICAL: Do NOT reuse generic templates like "Your expertise deserves to be heard", "We'd love to have you on our podcast", or "An invitation to share your story". Create a unique subject line tailored specifically for {lead_name} based on the guest details below.
- Greeting: "Hi {lead_name} Team," — use the EXACT business name, do not change it.
- Paragraph 1: Open with a genuine, specific compliment about their work or a project they did. Reference something highly detailed and unique about {lead_name} based on the guest info and website description. Avoid generic praise like "impressed by your commitment to excellence". Make them feel truly recognized as an individual business.
- Paragraph 2: Warmly invite them as a guest on our podcast. Introduce one of the highly interesting podcast angles ({interesting_angles}) and explain why their unique voice and perspective would resonate deeply with our audience. Keep this paragraph focused entirely on the value and insights they can share.
- Paragraph 3: Briefly explain that we make the experience completely effortless: we provide a professional soundproofed 4K studio, a dedicated on-site Studio Engineer who handles all setup and editing, and we supply short, polished social media video clips/audiograms for them to share on their channels. Do not use identical boilerplate sentences across different emails; phrase this in a fresh, natural way that fits the conversation.
- Paragraph 4: Soft call-to-action. Ask if they'd be open to a quick, no-pressure chat or reply to discuss details.
- Signature (exactly as shown, no changes):
  Warm regards,
  {sender_team}
  {sender_contact}
  {sender_company}, {sender_location}
  https://nextmedia.london

Tone: warm, genuine, flattering but authentic, professional. Max 200 words for the body.
CRITICAL: Every email must read as if it was individually hand-crafted by a human producer who spent time researching their website. Never repeat generic, boilerplate sentences or subject templates between different leads.

Guest info:
- Business / Person Name: {lead_name}
- What they do: {business_type}
- Their expertise area: {expertise_area}
- Interesting podcast angles: {interesting_angles}
- Why they'd be a great guest: {why_good_guest}

Return ONLY valid JSON with exactly these two keys:
{{
  "subject": "the email subject line here",
  "body": "the full email body here — greeting through signature — as a single string with newlines"
}}
""".strip()


# ─────────────────────────────────────────────────────────────────────────────
# Public Functions
# ─────────────────────────────────────────────────────────────────────────────

def analyze_website_content(content: str) -> dict | None:
    """
    Analyze scraped website text to identify podcast guest potential.
    Returns dict: business_type, expertise_area, target_audience,
                  interesting_angles, why_good_guest.
    """
    if not content or len(content.strip()) < 50:
        logger.warning("Website content too short for analysis.")
        return None

    try:
        client = _get_client()
        resp = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a podcast booking researcher at NextMedia London. "
                        "Your job is to analyse business websites and identify podcast guest potential. "
                        "Respond ONLY with valid JSON."
                    ),
                },
                {
                    "role": "user",
                    "content": ANALYSIS_PROMPT.format(content=content[:5000]),
                },
            ],
            response_format={"type": "json_object"},
            temperature=0.3,
            max_tokens=600,
        )

        result = json.loads(resp.choices[0].message.content)
        required = {"business_type", "expertise_area", "interesting_angles", "why_good_guest"}
        if not required.issubset(result.keys()):
            logger.warning(f"AI analysis missing keys: {result.keys()}")
            return None
        return result

    except json.JSONDecodeError as e:
        logger.error(f"AI returned invalid JSON during analysis: {e}")
        return None
    except Exception as e:
        logger.error(f"OpenAI error during analysis: {e}")
        return None


def generate_cold_email(lead_name: str, analysis: dict) -> dict | None:
    """
    Generate a personalized podcast guest invitation email for NextMedia London.

    Returns a dict with keys:
        'subject'  — the email subject line
        'body'     — the full invitation email body (greeting through signature)

    Returns None on failure.
    """
    if not analysis:
        logger.warning("No analysis provided for email generation.")
        return None

    interesting_angles = "; ".join(analysis.get("interesting_angles", []))
    business_type      = analysis.get("business_type", "business")
    expertise_area     = analysis.get("expertise_area", "their field")
    why_good_guest     = analysis.get("why_good_guest", "")

    if not interesting_angles:
        logger.warning(f"No podcast angles identified for {lead_name} — skipping.")
        return None

    # Sender identity from .env
    sender_company  = SENDER_COMPANY  or "NextMedia London"
    sender_team     = SENDER_TEAM     or "The NextMedia Team"
    sender_contact  = SENDER_CONTACT  or "info@nextmedia.london"
    sender_location = SENDER_LOCATION or "London"

    prompt = EMAIL_PROMPT.format(
        lead_name=lead_name,
        business_type=business_type,
        expertise_area=expertise_area,
        interesting_angles=interesting_angles,
        why_good_guest=why_good_guest,
        sender_company=sender_company,
        sender_team=sender_team,
        sender_contact=sender_contact,
        sender_location=sender_location,
        studio_profile=STUDIO_PROFILE,
    )

    try:
        client = _get_client()
        resp = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a warm, professional podcast producer at NextMedia London. "
                        "You write genuine, personalised guest invitation emails. "
                        "You NEVER use placeholder text. Respond ONLY with valid JSON."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.75,
            max_tokens=600,
        )

        result = json.loads(resp.choices[0].message.content)

        subject = result.get("subject", "").strip()
        body    = result.get("body", "").strip()

        if not subject or not body or len(body) < 80:
            logger.warning(f"Generated invitation too short for {lead_name}.")
            return None

        logger.info(f"Invitation generated for {lead_name} | Subject: {subject}")
        return {"subject": subject, "body": body}

    except json.JSONDecodeError as e:
        logger.error(f"AI returned invalid JSON for email: {e}")
        return None
    except Exception as e:
        logger.error(f"OpenAI error during email generation for {lead_name}: {e}")
        return None
