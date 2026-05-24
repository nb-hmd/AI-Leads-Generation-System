import os
from dotenv import load_dotenv

# Load .env file from the project root and override cached/shell environment variables
load_dotenv(override=True)

# ── OpenAI ────────────────────────────────────────────────────
OPENAI_API_KEY: str  = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL:   str  = os.getenv("OPENAI_MODEL",   "gpt-4o-mini")


# ── SMTP / Email ──────────────────────────────────────────────
SMTP_HOST:     str  = os.getenv("SMTP_HOST",     "smtp.gmail.com")
SMTP_PORT:     int  = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER:     str  = os.getenv("SMTP_USER",     "")
SMTP_PASSWORD: str  = os.getenv("SMTP_PASSWORD", "")
SENDER_NAME:   str  = os.getenv("SENDER_NAME",   "AI Leads Bot")

# ── Sender Identity (used in cold email signature) ────────────
SENDER_TEAM:     str = os.getenv("SENDER_TEAM",     "")
SENDER_COMPANY:  str = os.getenv("SENDER_COMPANY",  "")
SENDER_LOCATION: str = os.getenv("SENDER_LOCATION", "")
SENDER_CONTACT:  str = os.getenv("SENDER_CONTACT",  "")

# ── Lead Filtering ────────────────────────────────────────────
MIN_RATING:         float = float(os.getenv("MIN_RATING",         "3.5"))
MAX_LEADS_PER_RUN:  int   = int(os.getenv("MAX_LEADS_PER_RUN",   "50"))

# ── Scraping Rate Limits (seconds) ───────────────────────────
SCRAPE_DELAY_MIN: float = float(os.getenv("SCRAPE_DELAY_MIN", "2"))
SCRAPE_DELAY_MAX: float = float(os.getenv("SCRAPE_DELAY_MAX", "5"))
EMAIL_DELAY_MIN:  float = float(os.getenv("EMAIL_DELAY_MIN",  "5"))
EMAIL_DELAY_MAX:  float = float(os.getenv("EMAIL_DELAY_MAX",  "10"))

# ── Database ──────────────────────────────────────────────────
DB_PATH: str = os.getenv("DB_PATH", "data/leads.db")

# ── Logging ───────────────────────────────────────────────────
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
LOG_FILE:  str = os.getenv("LOG_FILE",  "logs/system.log")

# ── Validation helper ─────────────────────────────────────────
def validate_config() -> list[str]:
    """Return a list of missing critical configuration keys."""
    missing = []
    if not OPENAI_API_KEY:
        missing.append("OPENAI_API_KEY")
    if not SMTP_USER:
        missing.append("SMTP_USER")
    if not SMTP_PASSWORD:
        missing.append("SMTP_PASSWORD")
    return missing
