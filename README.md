# AI Leads Generation System

### Automated Podcast Guest Outreach — Built for NextMedia London

> **Purpose:** Automatically find professionals and business owners across any city, analyse their expertise, and send them a personalised invitation to be a podcast guest at **NextMedia London** — a professional podcast and video production studio in Bermondsey, London.

---

## 📸 Visual Walkthrough & Dashboard Gallery

Here is a step-by-step visual overview of the **AI Leads Generation System** dashboard, showing the entire pipeline from scraping to campaign dispatch:

### 1. Main Dashboard & Analytics
Interactive charts displaying real-time scraping stats, email outreach statuses, and database analytics.
![Dashboard Overview](Output%20images/1.%20Dashboard.jpeg)

### 2. Google Maps Lead Scraping
Target any city and niche. The scraper dynamically scrolls and utilizes multi-query expansion to discover high-quality leads.
![Scrape Leads](Output%20images/2.%20Scrape%20Leads.jpeg)

### 3. AI Processing & Personalization
Run bulk generation or use the interactive picker to inspect website crawls, run GPT-4o-mini deep analysis, and review personalized topic angles.
![AI Process](Output%20images/3.%20AI%20Process.jpeg)

### 4. SQLite Database Viewer
Browse all collected leads, contact details, and current pipeline states with options to prune/manage records.
![Database Viewer](Output%20images/4.%20Database.jpeg)

### 5. Email Review & Editing
Inspect every generated subject line and email body. Refine, customize, or save edits directly in the UI before sending.
![Email Review & Edit](Output%20images/5.%20Email%20Review%20&%20Edit.jpeg)

### 6. Email Campaign Sender
Send invitation batches via Gmail SMTP with built-in rate limits, monitoring progress and errors in real-time.
![Email Campaign](Output%20images/6.%20Email%20Compaign.jpeg)

### 7. Export Scraped Data
Download your entire leads database as a standard UTF-8 CSV file at any time.
![Export CSV](Output%20images/7.%20Export%20CSV.jpeg)

---

## What This System Does

At **NextMedia London**, the team manually searches for interesting professionals — business owners, entrepreneurs, industry experts — and invites them to appear as guests on podcast episodes recorded at the studio. This process was entirely manual: search Google, find websites, copy emails, write individual outreach emails one by one.

**This system fully automates that entire pipeline:**

1. You type a business category and city (e.g. `"Real Estate"` + `"London"`)
2. The system searches Google Maps, scrolls through results, and collects business listings
3. It visits every business website and extracts contact details (email, phone, social media)
4. **GPT-4o-mini** reads the website content and identifies the best podcast topic angles
5. A warm, personalised invitation email is generated — mentioning their specific work and a tailored episode topic
6. Invitations are sent via Gmail SMTP automatically
7. Everything is tracked in a local SQLite database with a live web dashboard

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        AI LEADS GENERATION SYSTEM                           │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────┐      ┌──────────────────────────────────────────────────┐
│   USER INPUT    │      │              GRADIO WEB DASHBOARD                │
│                 │      │         http://127.0.0.1:7860                    │
│ • Business Type │────▶│  7 Tabs: Dashboard │ Scrape │ AI Process │      │
│ • Location      │      │  Database │ Email Preview │ Campaign │ Export    │
│ • Target Count  │      └──────────────────┬───────────────────────────────┘
└─────────────────┘                         │
                                            ▼
┌───────────────────────────── STAGE 1: DISCOVERY ───────────────────────────┐
│                                                                            │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │              google_maps.py  — scrape_with_expansion()              │   │
│  │                                                                     │   │
│  │  Round 1: "Real Estate in London"          → ~12 results            │   │
│  │  Round 2: "Real Estate in East London"     → +10 results            │   │
│  │           "Real Estate in West London"     → +8  results            │   │
│  │           "Real Estate in Kensington"      → +9  results            │   │
│  │           ... (up to 17 London sub-areas)                           │   │
│  │  Round 3: "Estate Agents in London"        → +8  results  (syns)    │   │
│  │           "Property Agents in London"      → +5  results            │   │
│  │                                                                     │   │
│  │  Playwright (headless Chromium) ─ Deep sidebar scroll (80 rounds)   │   │
│  │  Extracts: name, rating, phone, address, website per business       │   │
│  │  Deduplication by website URL across all queries                    │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                              │ Raw leads list                              │
│                              ▼                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                    cleaner.py — filter_leads()                      │   │
│  │  • Must have a website  • Rating ≥ 3.5 (or unrated)                 │   │
│  │  • Deduplicate by website URL                                       │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────┬─────────────────────────────────────────┘
                                   │ Filtered leads
                                   ▼
┌───────────────────────────── STAGE 2: CRAWLING ────────────────────────────┐
│                                                                            │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │              website_scraper.py — scrape_website()                  │   │
│  │                                                                     │   │
│  │  BFS crawler: up to 12 pages per domain                             │   │
│  │  Prioritises: /contact  /about  /team  /reach  /info pages          │   │
│  │  Rotates 3 User-Agent strings to avoid bot detection                │   │
│  │  Extracts:                                                          │   │
│  │    • Email addresses   (regex)                                      │   │
│  │    • Phone numbers     (regex, word-boundary anchored)              │   │
│  │    • Facebook URL      (link pattern matching)                      │   │
│  │    • Instagram URL     (link pattern matching)                      │   │
│  │    • Twitter / X URL   (link pattern matching)                      │   │
│  │    • LinkedIn URL      (link pattern matching)                      │   │
│  │    • Full page text    (up to 6,000 chars for AI analysis)          │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                              │ Enriched leads                              │
│                              ▼                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                    db.py — insert_lead()                            │   │
│  │  Saves to SQLite: data/leads.db                                     │   │
│  │  UNIQUE(email) constraint prevents duplicates                       │   │
│  │  Stores all contact fields + website text (notes column)            │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────┬─────────────────────────────────────────┘
                                   │ Stored leads (with notes)
                                   ▼
┌───────────────────────────── STAGE 3: AI ANALYSIS ─────────────────────────┐
│                                                                            │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │           processor.py — analyze_website_content()                  │   │
│  │                                                                     │   │
│  │  Sends website text → GPT-4o-mini                                   │   │
│  │  Returns JSON:                                                      │   │
│  │    • business_type      — what they do                              │   │
│  │    • expertise_area     — what knowledge they can share             │   │
│  │    • interesting_angles — 3 specific podcast episode topics         │   │
│  │    • why_good_guest     — why they'd be compelling on air           │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                              │ Analysis dict                               │
│                              ▼                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │           processor.py — generate_cold_email()                      │   │
│  │                                                                     │   │
│  │  Sends analysis → GPT-4o-mini (temperature=0.75 for variety)        │   │
│  │  Generates personalised podcast invitation:                         │   │
│  │    • Dynamic subject line (about them, not us)                      │   │
│  │    • Specific compliment referencing their actual work              │   │
│  │    • Tailored episode topic from interesting_angles                 │   │
│  │    • Studio facilities mention (4K, Engineer, social clips)         │   │
│  │    • Warm CTA + real NextMedia London signature                     │   │
│  │  Returns: { "subject": "...", "body": "..." }                       │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────┬─────────────────────────────────────────┘
                                   │ Generated invitation
                                   ▼
┌───────────────────────────── STAGE 4: CAMPAIGN ────────────────────────────┐
│                                                                            │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │               sender.py — send_email()                              │   │
│  │                                                                     │   │
│  │  Gmail SMTP (port 587, STARTTLS)                                    │   │
│  │  Rate-limited: 5–10 second delay between sends                      │   │
│  │  On success: marks lead as contacted=True in database               │   │
│  │  On failure: logs error to error_log column                         │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                            │
│               ✉ Invitation delivered to business email inbox              │
└────────────────────────────────────────────────────────────────────────────┘
```

---

## System Workflow

```
You enter:  "Real Estate"  +  "London"  +  50 leads target
                │
                ▼
        ┌──────────────┐
        │  Google Maps │  Rounds 1→3: original + sub-areas + synonyms
        │   Scraper    │  Until 50 unique businesses collected
        └──────┬───────┘
               │ 50 raw business listings (name, rating, phone, website)
               ▼
        ┌──────────────┐
        │   Filter &   │  Remove: no website, rating < 3.5, duplicates
        │  Deduplicate │
        └──────┬───────┘
               │ ~45 valid leads
               ▼
        ┌──────────────┐
        │   Website    │  Crawl each site (up to 12 pages)
        │   Crawler    │  Extract: email, phone, Facebook, Instagram,
        └──────┬───────┘  Twitter, LinkedIn, page text
               │ 45 enriched leads saved to SQLite
               ▼
        ┌──────────────┐
        │  GPT-4o-mini │  Analyse website text
        │  Analysis    │  → expertise area + 3 podcast angles
        └──────┬───────┘
               ▼
        ┌──────────────┐
        │  GPT-4o-mini │  Write personalised podcast invitation
        │  Email Gen   │  → unique subject + warm body + NM signature
        └──────┬───────┘
               │ ~20 invitations (leads that have email addresses)
               ▼
        ┌──────────────┐
        │ Gmail SMTP   │  Send each invitation
        │  Campaign    │  Rate-limited, tracked in DB
        └──────────────┘
```

---

## Project Structure

```
AI Leads Generation System/
│
├── .env                        ← API keys, SMTP credentials, sender identity
├── config.py                   ← Loads all settings from .env
├── main.py                     ← CLI entry point
├── requirements.txt            ← Python dependencies
├── README.md                   ← Project Detail
│
├── scrapers/
│   ├── google_maps.py          ← Playwright deep-scroll + multi-query expansion
│   └── website_scraper.py      ← BFS crawler (12 pages/domain, 3 User-Agents)
│
├── data_cleaner/
│   └── cleaner.py              ← Filters: needs website, rating ≥ 3.5, dedup
│
├── database/
│   └── db.py                   ← SQLite CRUD + automatic schema migration
│
├── ai/
│   └── processor.py            ← GPT-4o-mini: guest analysis + invitation writer
│                                  Contains full NextMedia London studio profile
│
├── email_sender/
│   └── sender.py               ← Gmail SMTP dispatcher (STARTTLS, port 587)
│
├── dashboard/
│   └── app.py                  ← 7-tab Gradio web dashboard
│                                  Live charts (Plotly) + live log streaming
│
├── utils/                      ← Utility helpers
│
└── data/
    ├── leads.db                ← SQLite database (auto-created on first run)
    └── leads_export.csv        ← CSV export output
```

---

## Module Details

### `scrapers/google_maps.py`

- Uses **Playwright** (bundled Chromium — no system browser needed)
- Runs headless (invisible browser window)
- Opens Google Maps, searches the query, scrolls the results sidebar up to **80 times** to load all available results
- Detects "end of list" markers and stale scrolls to stop early
- Extracts per business: name, rating, phone, address, website URL
- **`scrape_with_expansion()`** — the core function that runs multiple queries to break the ~20-result-per-query limit (see [Multi-Query Expansion](#multi-query-expansion))

### `scrapers/website_scraper.py`

- Python BFS (Breadth-First Search) crawler using `requests` + `BeautifulSoup`
- Stays within the same domain (no following external links)
- Crawls up to **12 pages** per site
- Prioritises pages with keywords: `contact`, `about`, `team`, `reach`, `info`, `office`
- Rotates through 3 real User-Agent strings to reduce 403 errors
- Extracts: email, phone, Facebook, Instagram, Twitter/X, LinkedIn
- Captures up to **6,000 characters** of page text for AI analysis
- `CRAWL_DELAY = 0.8s` between requests to be polite

### `ai/processor.py`

- Connects to **OpenAI GPT-4o-mini** API
- **Two-step process:**
  1. `analyze_website_content()` — sends website text, returns structured JSON (expertise, podcast angles, why a good guest)
  2. `generate_cold_email()` — sends analysis, generates warm invitation with real name, specific topic, studio details
- Contains embedded **NextMedia London Studio Profile** used in every email prompt
- Temperature 0.3 for analysis (consistent), 0.75 for email (varied and natural)
- Returns `None` gracefully on API failure — never crashes the pipeline

### `database/db.py`

- SQLite database at `data/leads.db`
- `init_db()` — creates table if not exists
- `migrate_db()` — safely adds new columns to existing tables (no data loss on upgrades)
- `insert_lead()` — silently skips duplicates (UNIQUE on email)
- `get_all_leads()` — returns all or only uncontacted leads
- `delete_lead(id)` — delete one lead by ID
- `delete_all_leads()` — wipe entire table

### `email_sender/sender.py`

- Gmail SMTP via Python's built-in `smtplib`
- STARTTLS encryption on port 587
- Requires Gmail **App Password** (not your Google login password)
- Returns `True`/`False` — errors are caught and logged, never raise

### `data_cleaner/cleaner.py`

- Filters out leads with no website (can't crawl or find contact details)
- Filters out leads with a Google rating below `MIN_RATING` (default 3.5)
- Leads with **no rating at all** are kept (new businesses with no reviews)
- Deduplicates by website URL

### `config.py`

- Single source of all settings — loads from `.env` via `python-dotenv`
- Provides typed constants with safe defaults for every value

### `dashboard/app.py`

- **Gradio** web interface
- Live log streaming: uses Python `threading` + `queue.Queue` as a bridge between background pipeline threads and Gradio's generator-based UI updates
- **Plotly** for live interactive charts on the Dashboard tab

---

## Dashboard — 7 Tabs

Open: **`http://127.0.0.1:7860`** after running `python main.py dashboard`

| Tab                              | What It Does                                                                                                                                                                                                                                                    |
| -------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **📊 Dashboard**           | 4 live Plotly charts, elegantly custom-themed in deep slate for absolute legibility in both light and dark browser modes. Click ↺ to refresh after any operation                                                                                               |
| **🔍 Scrape Leads**        | Enter business type + location + target count → watch multi-query expansion live                                                                                                                                                                               |
| **🤖 AI Process**          | **Interactive & Bulk Gen Hub**: Contains *Option A* (batch-process recent scrape session leads) and *Option B* (interactive single-lead picker with website crawled content preview, selective AI deep review, and inline real-time editing & saving) |
| **🗄️ Database**          | Full leads table, delete by ID, delete all, live stats summary                                                                                                                                                                                                  |
| **✉ Email Review & Edit** | **Interactive Customization Hub**: Lists all leads with status tags (`[Needs AI]`, `[No Email]`). Select any lead to review, manually write, edit, and save customized subjects/bodies directly                                                       |
| **📨 Campaign**            | Send all ready invitations via Gmail SMTP → live log per send                                                                                                                                                                                                  |
| **📥 Export**              | Download all leads as UTF-8 CSV file                                                                                                                                                                                                                            |

---

## Setup & Installation

### Prerequisites

- Python 3.10 or newer
- A Gmail account with **2-Step Verification** enabled
- An **OpenAI API key**

### Step 1 — Install Dependencies

```powershell
pip install -r requirements.txt
```

### Step 2 — Install Playwright Browser (one-time only)

```powershell
playwright install chromium
```

> This downloads a bundled Chromium browser (~200MB). No system Chrome installation needed.

### Step 3 — Configure `.env`

Edit the `.env` file with your real credentials (see [Configuration](#configuration-env) below).

### Step 4 — Initialize Database

```powershell
python main.py setup
```

### Step 5 — Launch Dashboard

```powershell
python main.py dashboard
```

Open your browser → `http://127.0.0.1:7860`

---

## Configuration (.env)

```env
# ── OpenAI ────────────────────────────────────────────────────────────
OPENAI_API_KEY=sk-proj-...            # Your OpenAI API key
OPENAI_MODEL=gpt-4o-mini            # Model to use (gpt-4o-mini)

# ── Gmail SMTP ────────────────────────────────────────────────────────
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your-gmail@gmail.com        # Your Gmail address
SMTP_PASSWORD=xxxx xxxx xxxx xxxx    # Gmail App Password (16 chars with spaces)
SENDER_NAME=Your Name                 # Displayed in From: field

# ── NextMedia London Sender Identity ─────────────────────────────────
# These fill the email signature automatically
SENDER_TEAM=The NextMedia Team
SENDER_COMPANY=NextMedia London
SENDER_LOCATION=Bermondsey, London
SENDER_CONTACT=info@nextmedia.london

# ── Lead Filtering ────────────────────────────────────────────────────
MIN_RATING=3.5           # Minimum Google star rating (0 = unrated, always kept)
MAX_LEADS_PER_RUN=50     # Max leads processed by AI per run

# ── Scraping Rate Limits ──────────────────────────────────────────────
SCRAPE_DELAY_MIN=2       # Min seconds between website crawls
SCRAPE_DELAY_MAX=5       # Max seconds between website crawls
EMAIL_DELAY_MIN=5        # Min seconds between email sends
EMAIL_DELAY_MAX=10       # Max seconds between email sends
```

> **How to get a Gmail App Password:**
> Google Account → Security → 2-Step Verification → App Passwords → Select "Mail" → Generate
> Copy the 16-character password (format: `xxxx xxxx xxxx xxxx`)

---

## Usage — Dashboard (Recommended)

```powershell
python main.py dashboard
```

Open → `http://127.0.0.1:7860`

**Typical workflow in the dashboard:**

1. Go to **Scrape Leads** tab → Enter `Real Estate` + `London` + slider to `50` → Click **Start Scraping**
2. Watch the live log as expansion queries run and websites are crawled
3. Go to **AI Process** tab:
   * Open **Option A** to batch-process all session leads at once, or
   * Open **Option B** to select a specific lead, run deep AI analysis for it, and tweak/edit the resulting email directly.
4. Go to **Email Review & Edit** tab → Select leads (clearly tagged with `[Needs AI]` or `[No Email]`) to review, manually draft, or personalize.
5. Go to **Campaign** tab → Click **Send Campaign** to dispatch all invitations
6. Go to **Dashboard** tab → Click **↺ Refresh Charts** to see updated stats
7. Go to **Export** tab → Download CSV if needed

---

### All Available Commands

```powershell
# 1. Manually Run each process
# 1.1. Initialize database (first time only)
python main.py setup

# 1.2. Scrape leads — uses multi-query expansion automatically
python main.py scrape "BUSINESS TYPE in CITY" --max-results N

# 1.3. Generate AI podcast invitations
python main.py process

# 1.4. Check current stats
python main.py stats

# 1.5. Send email campaign
python main.py campaign

# 1.6. Export all leads to CSV
python main.py export

# 2. Launch web dashboard and process all steps through UI
python main.py dashboard
```

### Scrape Examples

```powershell
python main.py scrape "Real Estate in London" --max-results 50
python main.py scrape "Architects in Manchester" --max-results 30
python main.py scrape "Fitness Trainers in Birmingham" --max-results 40
python main.py scrape "Dentists in Glasgow" --max-results 25
python main.py scrape "Tech Startups in London" --max-results 60
python main.py scrape "Interior Designers in Leeds" --max-results 30
python main.py scrape "Lawyers in New York" --max-results 50
python main.py scrape "Digital Marketing in Dallas, TX" --max-results 40
```

### Complete Pipeline (copy-paste ready)

```powershell
python main.py setup
python main.py scrape "Real Estate in London" --max-results 50
python main.py process
python main.py stats
python main.py campaign
python main.py export
```

---

## Multi-Query Expansion

### The Problem

Google Maps returns a maximum of **~20 results per search query**. If you search `"Real Estate in London"`, you'll only get 12–20 businesses — not 50 or 100.

### The Solution — 3-Round Automatic Expansion

The `scrape_with_expansion()` function runs multiple searches and merges all results:

```
EXAMPLE: "Real Estate" in "London", target = 50

Round 1 — Original query:
  "Real Estate in London"             → 12 unique results

Round 2 — Geographic sub-areas (stops when target reached):
  "Real Estate in Central London"     → +9  results  (total: 21)
  "Real Estate in East London"        → +8  results  (total: 29)
  "Real Estate in West London"        → +7  results  (total: 36)
  "Real Estate in North London"       → +8  results  (total: 44)
  "Real Estate in South London"       → +6  results  (total: 50) ✓ DONE

Round 3 — Business synonyms (only if still short):
  "estate agents in London"
  "property agents in London"
  "realtors in London"
  "property consultants in London"
```

All results across all queries are **deduplicated by normalised website URL** — no business appears twice.

### Supported Cities (Pre-defined Sub-areas)

| Region              | Cities                                                                                           |
| ------------------- | ------------------------------------------------------------------------------------------------ |
| **UK**        | London (17 areas), Manchester, Birmingham, Leeds, Glasgow, Edinburgh                             |
| **USA**       | New York, Los Angeles, Dallas, Houston, Chicago, Miami, Phoenix, San Francisco, Seattle, Atlanta |
| **Canada**    | Toronto, Vancouver                                                                               |
| **Australia** | Sydney, Melbourne                                                                                |

> **Any other city** — Falls back to generic directional split: Central, East, West, North, South + city name.

### Business Type Synonyms (Built-in)

| You type          | Synonyms tried                                                 |
| ----------------- | -------------------------------------------------------------- |
| Real Estate       | estate agents, property agents, realtors, property consultants |
| Roofers           | roofing contractors, roofing company, roof repair              |
| Lawyers           | law firms, solicitors, legal services                          |
| Dentists          | dental clinics, dental practice                                |
| Accountants       | accounting firms, chartered accountants, bookkeepers           |
| Digital Marketing | marketing agencies, seo agencies, advertising agencies         |
| Builders          | construction companies, building contractors                   |

---

## Generated Invitation Example

**Subject:** `An invitation to share your expertise — Arrington Roofing`

```
Hi Arrington Roofing Team,

I've been truly impressed by your commitment to excellence in both residential
and commercial roofing across the Dallas market. Your 4.9-star reputation built
on quality craftsmanship and customer trust is exactly the kind of story our
listeners love to hear.

We'd love to invite you as a guest on our podcast to discuss how independent
roofing contractors can compete and thrive against larger corporations —
a topic that resonates deeply with small business owners in our audience.

At NextMedia London, we make the whole process completely effortless. Our
professional 4K studio in Bermondsey comes with a dedicated Studio Engineer
who handles everything — recording, audio levels, lighting — so you simply
turn up and talk. We also create short clips and audiograms from every episode
to help amplify your message across your own social media channels.

Would you be open to a quick call this week to discuss the details? We'd love
to make this happen.

Warm regards,
The NextMedia Team
info@nextmedia.london
NextMedia London, Bermondsey, London
https://nextmedia.london
```

---

## Database Schema

**Table: `leads`** — stored in `data/leads.db`

| Column              | Type        | Description                        |
| ------------------- | ----------- | ---------------------------------- |
| `id`              | INTEGER PK  | Auto-increment unique ID           |
| `name`            | TEXT        | Business name from Google Maps     |
| `email`           | TEXT UNIQUE | Email found by website crawler     |
| `website`         | TEXT        | Business website URL               |
| `phone`           | TEXT        | Phone (Maps or website)            |
| `address`         | TEXT        | Address from Google Maps           |
| `rating`          | REAL        | Google star rating (0.0 if none)   |
| `linkedin`        | TEXT        | LinkedIn URL                       |
| `twitter`         | TEXT        | Twitter/X URL                      |
| `instagram`       | TEXT        | Instagram URL                      |
| `facebook`        | TEXT        | Facebook URL                       |
| `business_type`   | TEXT        | AI-identified business description |
| `pain_points`     | TEXT        | Podcast topic angles (3 ideas)     |
| `opportunities`   | TEXT        | Expertise area + why great guest   |
| `generated_email` | TEXT        | Full invitation email body         |
| `email_subject`   | TEXT        | Generated subject line             |
| `contacted`       | BOOLEAN     | True after invitation sent         |
| `error_log`       | TEXT        | SMTP error message if send failed  |
| `notes`           | TEXT        | Raw website text (for AI input)    |
| `created_at`      | TIMESTAMP   | When the lead was scraped          |

---

## Troubleshooting

| Problem                           | Cause                              | Solution                                                                                    |
| --------------------------------- | ---------------------------------- | ------------------------------------------------------------------------------------------- |
| Port 7860 already in use          | Old dashboard still running        | Run:`netstat -ano \| findstr :7860` then `taskkill /PID <id> /F`                         |
| Only 12 results found             | Google Maps per-query limit        | System uses expansion automatically — make sure you passed `--max-results 50` not `10` |
| `playwright install` error      | Chromium not downloaded            | Run:`playwright install chromium` (one-time, ~200MB)                                      |
| SMTP Authentication Error         | Wrong password type                | Use Gmail**App Password**, not your Google login password                             |
| `No unprocessed leads found`    | All leads already have invitations | Clear `generated_email` in DB or scrape fresh leads                                       |
| `No ready-to-contact leads`     | Leads missing email address        | Website crawler couldn't find email on those sites; nothing to send                         |
| Website returns 403               | Bot detection                      | Crawler automatically retries with 3 different User-Agent strings                           |
| `UnicodeEncodeError` on Windows | Windows cp1252 encoding            | Fixed — UTF-8 forced via `sys.stdout.reconfigure()` at startup                           |
| Dashboard shows old data          | Charts not refreshed               | Click**↺ Refresh Charts** on the Dashboard tab                                             |
| AI generates placeholder text     | Wrong processor version            | All placeholder text removed — real sender info always comes from `.env`                 |
| `OPENAI_API_KEY not set`        | Missing .env configuration         | Add your key to `.env` file                                                               |

---

## About NextMedia London

**NextMedia London** is a full-service podcast and video production studio.

---

## Requirements

```
requests
beautifulsoup4
playwright
openai
pandas
python-dotenv
click
rich
gradio
plotly>=5.0
```

Install everything:

```powershell
pip install -r requirements.txt
playwright install chromium
```

---

## License

MIT License — Free to use and modify.
