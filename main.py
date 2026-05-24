import sys

# ── Force UTF-8 output on Windows (in-place, safe for all libraries) ─────────
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import click
import time
import random
import logging
import csv
from rich.console import Console
from rich.logging import RichHandler

from config import SCRAPE_DELAY_MIN, SCRAPE_DELAY_MAX, EMAIL_DELAY_MIN, EMAIL_DELAY_MAX, MAX_LEADS_PER_RUN
from database.db import init_db, insert_lead, get_all_leads, update_lead
from scrapers.google_maps import scrape_with_expansion
from scrapers.website_scraper import scrape_website
from data_cleaner.cleaner import filter_leads
from ai.processor import analyze_website_content, generate_cold_email
from email_sender.sender import send_email

# Setup logging — safe for Windows terminals
logging.basicConfig(
    level="INFO",
    format="%(message)s",
    datefmt="[%X]",
    handlers=[RichHandler(rich_tracebacks=True, show_path=False)]
)

logger = logging.getLogger("rich")
# Console with UTF-8 safe output
console = Console(highlight=False)


@click.group()
def cli():
    """AI-Powered Lead Generation & Outreach System"""
    pass

@cli.command()
def setup():
    """Initialize the database schema."""
    init_db()
    console.print("[bold green]Database initialized successfully![/bold green]")

@cli.command()
@click.argument('query')
@click.option('--max-results', default=20, help='Total unique leads to collect (uses multi-query expansion).')
def scrape(query, max_results):
    """
    Scrape leads from Google Maps using multi-query geographic expansion.

    QUERY format: "<business type> in <location>"
    Examples:
      python main.py scrape "Real Estate in London" --max-results 50
      python main.py scrape "Dentists in Manchester" --max-results 30
    """
    # Parse "<business_type> in <location>" format
    if " in " in query:
        parts = query.split(" in ", 1)
        business_type = parts[0].strip()
        location      = parts[1].strip()
    else:
        # Fallback: treat entire string as business type, location unknown
        business_type = query.strip()
        location      = ""
        console.print(
            "[yellow]Tip: Use format 'Business Type in Location' for best results.[/yellow]\n"
            "Example: python main.py scrape \"Real Estate in London\" --max-results 50"
        )

    console.print(
        f"[bold blue]Starting multi-query expansion:[/bold blue]\n"
        f"  Business type : {business_type}\n"
        f"  Location      : {location or '(not specified)'}\n"
        f"  Target leads  : {max_results}"
    )

    # 1. Scrape Google Maps with automatic sub-area expansion
    raw_leads = scrape_with_expansion(
        business_type=business_type,
        location=location,
        max_results=max_results,
    )
    if not raw_leads:
        console.print("[bold red]No leads found. Try a different query or location.[/bold red]")
        return

    console.print(f"[bold cyan]Google Maps expansion complete: {len(raw_leads)} unique businesses found.[/bold cyan]")

    # 2. Filter Leads (Require Website & Rating)
    filtered_leads = filter_leads(raw_leads)
    console.print(f"[bold green]After filtering: {len(filtered_leads)} valid leads with websites.[/bold green]")

    # 3. Process Websites & Store
    saved = skipped = failed = 0
    for lead in filtered_leads:
        console.print(f"Crawling: [bold]{lead['name']}[/bold] ({lead['website']})")        
        web_data = scrape_website(lead['website'])
        
        if web_data.get('success'):
            lead['email']     = web_data.get('email')
            lead['phone']     = web_data.get('phone') or lead.get('phone')
            socials           = web_data.get('socials', {})
            lead['linkedin']  = socials.get('linkedin')
            lead['twitter']   = socials.get('twitter')
            lead['instagram'] = socials.get('instagram')
            lead['facebook']  = socials.get('facebook')

            lead_id = insert_lead(lead)
            if lead_id:
                update_lead(lead_id, {'notes': web_data.get('text', '')})
                console.print(f"  [green]Saved[/green] | Email: {lead.get('email')} | Phone: {lead.get('phone')}")
                saved += 1
            else:
                console.print(f"  [yellow]Skipped (duplicate)[/yellow]")
                skipped += 1
        else:
            console.print(f"  [red]Crawl failed[/red]")
            failed += 1
            
        delay = random.uniform(SCRAPE_DELAY_MIN, SCRAPE_DELAY_MAX)
        time.sleep(delay)

    console.print(
        f"\n[bold green]Done![/bold green] "
        f"Saved: {saved} | Skipped: {skipped} | Failed: {failed}"
    )

@cli.command()
def process():
    """Analyze website text with AI and generate emails."""
    leads = get_all_leads(uncontacted_only=True)
    
    # Filter to leads that haven't been processed yet (no generated email)
    to_process = [l for l in leads if not l.get('generated_email') and l.get('notes')]
    
    if not to_process:
        console.print("[bold yellow]No unprocessed leads found.[/bold yellow]")
        return
        
    console.print(f"[bold blue]Processing {len(to_process)} leads with AI...[/bold blue]")
    
    for lead in to_process[:MAX_LEADS_PER_RUN]:
        console.print(f"Analyzing [bold]{lead['name']}[/bold]...")

        # 1. Analyze website content
        analysis = analyze_website_content(lead['notes'])

        if analysis:
            # 2. Generate email (returns dict with 'subject' and 'body')
            email_result = generate_cold_email(lead['name'], analysis)

            if email_result:
                # Map new podcast-analysis fields to existing DB columns:
                # pain_points  → podcast topic angles
                # opportunities → why they'd be a great guest + expertise area
                angles    = analysis.get('interesting_angles', [])
                expertise = analysis.get('expertise_area', '')
                why_guest = analysis.get('why_good_guest', '')
                update_data = {
                    'business_type':   analysis.get('business_type'),
                    'pain_points':     ", ".join(angles),
                    'opportunities':   f"{expertise} | {why_guest}".strip(" |"),
                    'email_subject':   email_result['subject'],
                    'generated_email': email_result['body'],
                }
                update_lead(lead['id'], update_data)
                console.print(f"[green]Invitation ready for {lead['name']}[/green]")
                console.print(f"  Subject: {email_result['subject']}")
            else:
                console.print(f"[red]Failed to generate email for {lead['name']}[/red]")
        else:
            console.print(f"[red]Failed to analyze {lead['name']}[/red]")

        time.sleep(2)

@cli.command()
def campaign():
    """Send generated emails to leads."""
    leads = get_all_leads(uncontacted_only=True)
    
    # Filter to leads that have emails generated but not contacted
    to_contact = [l for l in leads if l.get('generated_email') and l.get('email')]
    
    if not to_contact:
        console.print("[bold yellow]No ready-to-contact leads found (missing email address or generated text).[/bold yellow]")
        return
        
    console.print(f"[bold blue]Starting email campaign for {len(to_contact)} leads...[/bold blue]")
    
    for lead in to_contact:
        name    = lead['name']
        to_addr = lead['email']
        subject = lead.get('email_subject') or f"Growing {name} — a quick idea"
        body    = lead['generated_email']

        console.print(f"Sending to [bold]{name}[/bold] ({to_addr})...")
        console.print(f"  Subject: {subject}")

        success = send_email(to_addr, subject, body)

        if success:
            update_lead(lead['id'], {'contacted': True})
            console.print(f"[green]Sent to {to_addr}[/green]")
        else:
            update_lead(lead['id'], {'error_log': 'Failed to send email'})
            console.print(f"[red]Failed to send to {to_addr}[/red]")
            
        # Rate limiting
        delay = random.uniform(EMAIL_DELAY_MIN, EMAIL_DELAY_MAX)
        logger.info(f"Sleeping for {delay:.2f} seconds...")
        time.sleep(delay)

@cli.command()
def stats():
    """View system statistics."""
    leads = get_all_leads()
    total = len(leads)
    contacted = sum(1 for l in leads if l.get('contacted'))
    with_email = sum(1 for l in leads if l.get('email'))
    ready_to_send = sum(1 for l in leads if l.get('generated_email') and l.get('email') and not l.get('contacted'))
    
    console.print("\n[bold cyan]===== Lead Generation System Stats =====[/bold cyan]")
    console.print(f"[white]Total Leads in DB       :[/white] [bold]{total}[/bold]")
    console.print(f"[white]Leads with Email Addr   :[/white] [bold]{with_email}[/bold]")
    console.print(f"[white]Leads Ready for Campaign:[/white] [bold]{ready_to_send}[/bold]")
    console.print(f"[white]Successfully Contacted  :[/white] [bold green]{contacted}[/bold green]\n")

@cli.command()
def dashboard():
    """Launch the Gradio UI dashboard."""
    from dashboard.app import launch_dashboard
    console.print("[bold green]Starting Dashboard...[/bold green]")
    launch_dashboard()

@cli.command()
def export():
    """Export all leads to CSV."""
    leads = get_all_leads()
    if not leads:
        console.print("[yellow]No leads to export.[/yellow]")
        return
        
    keys = leads[0].keys()
    with open('data/leads_export.csv', 'w', newline='', encoding='utf-8') as f:
        dict_writer = csv.DictWriter(f, keys)
        dict_writer.writeheader()
        dict_writer.writerows(leads)
    console.print("[green]Exported leads to data/leads_export.csv[/green]")

if __name__ == '__main__':
    cli()
