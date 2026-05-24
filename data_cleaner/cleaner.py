import logging
from config import MIN_RATING

logger = logging.getLogger(__name__)

def filter_leads(leads):
    """
    Filter out leads that don't meet the criteria:
    - Must have a website
    - Rating above MIN_RATING
    - Remove duplicates based on email (or website if email is None but we'll try to find email later)
    """
    filtered = []
    seen_websites = set()
    
    for lead in leads:
        website = lead.get('website')
        rating = lead.get('rating', 0.0)
        
        if not website:
            logger.debug(f"Filtering out lead '{lead.get('name')}': No website.")
            continue
            
        # Only reject if a rating exists AND it is below the threshold.
        # rating == 0.0 means the business has no reviews yet — still valid.
        if rating > 0.0 and rating < MIN_RATING:
            logger.debug(f"Filtering out lead '{lead.get('name')}': Rating {rating} is below {MIN_RATING}.")
            continue
            
        # Deduplicate based on website initially, because emails are usually found after scraping the website
        # The database handles email uniqueness later
        if website in seen_websites:
            continue
            
        seen_websites.add(website)
        filtered.append(lead)
        
    logger.info(f"Filtered {len(leads)} raw leads down to {len(filtered)} valid leads.")
    return filtered
