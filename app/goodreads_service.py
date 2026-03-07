import httpx
from bs4 import BeautifulSoup
import urllib.parse
import re
import json
import logging

logger = logging.getLogger(__name__)

GOODREADS_BASE = "https://www.goodreads.com"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}


async def search_book(title: str, author: str = "") -> dict | None:
    """
    Search Goodreads for a book and return info from the best match.
    Returns dict with: url, title, author, rating, rating_count, review_count,
                       description, genres, reviews (top 5), cover_image
    """
    try:
        # Clean up the title — remove author if embedded in the title
        # Common audiobook formats: "Author - Title", "Title - Author", "Title by Author"
        clean_author = ""
        if author and author.lower() not in ('audiobook', 'audiobookbay', 'unknown', ''):
            clean_author = author.strip()
        
        clean_title = title.strip()
        
        # Strip author from title if it's embedded (e.g., "Project Hail Mary - Andy Weir")
        if clean_author:
            # Try "Title - Author" format
            clean_title = re.sub(
                r'\s*[-–—]\s*' + re.escape(clean_author) + r'\s*$', '', clean_title, flags=re.IGNORECASE
            ).strip()
            # Try "Author - Title" format
            clean_title = re.sub(
                r'^' + re.escape(clean_author) + r'\s*[-–—]\s*', '', clean_title, flags=re.IGNORECASE
            ).strip()
            # Try "Title by Author" format
            clean_title = re.sub(
                r'\s+by\s+' + re.escape(clean_author) + r'\s*$', '', clean_title, flags=re.IGNORECASE
            ).strip()
        
        # Also try splitting on " - " if no known author
        if not clean_author and ' - ' in clean_title:
            parts = clean_title.split(' - ')
            # Use the longest part as the title (heuristic)
            clean_title = max(parts, key=len).strip()
        
        # Remove common audiobook suffixes
        clean_title = re.sub(r'\s*\(unabridged\)', '', clean_title, flags=re.IGNORECASE)
        clean_title = re.sub(r'\s*\[audiobook\]', '', clean_title, flags=re.IGNORECASE)
        clean_title = re.sub(r'\s*-\s*audiobook.*$', '', clean_title, flags=re.IGNORECASE)
        clean_title = clean_title.strip()
        
        logger.info(f"Goodreads search: title='{clean_title}', author='{clean_author}'")
        
        async with httpx.AsyncClient(follow_redirects=True, timeout=15.0) as client:
            # Strategy: search with TITLE ONLY first (gives best results)
            # Adding author to query pollutes results with derivative books
            book_url = await _search_and_match(client, clean_title, clean_title)
            
            # Retry with "title author" if title-only didn't work
            if not book_url and clean_author:
                retry_query = f"{clean_title} {clean_author}"
                logger.info(f"Retrying Goodreads with author: '{retry_query}'")
                book_url = await _search_and_match(client, retry_query, clean_title)
            
            if not book_url:
                logger.warning(f"No Goodreads match found for: {clean_title}")
                return None
            
            logger.info(f"Goodreads best match URL: {book_url}")
            
            # Fetch the book page
            book_resp = await client.get(book_url, headers=HEADERS)
            
            if book_resp.status_code != 200:
                logger.warning(f"Goodreads book page returned {book_resp.status_code}")
                return None
            
            return _parse_book_page(book_resp.text, book_url)
    
    except Exception as e:
        logger.error(f"Goodreads scrape error: {e}")
        return None


async def _search_and_match(client, query: str, original_title: str) -> str | None:
    """Search Goodreads and find the best matching book URL."""
    encoded_query = urllib.parse.quote_plus(query.strip())
    search_url = f"{GOODREADS_BASE}/search?q={encoded_query}"
    
    resp = await client.get(search_url, headers=HEADERS)
    if resp.status_code != 200:
        return None
    
    soup = BeautifulSoup(resp.text, 'html.parser')
    book_url = _find_best_match(soup, original_title)
    
    if book_url:
        if book_url.startswith('/'):
            book_url = f"{GOODREADS_BASE}{book_url}"
        return book_url
    
    return None


def _find_best_match(soup: BeautifulSoup, original_title: str) -> str | None:
    """
    Find the best matching book URL from Goodreads search results.
    Uses a scoring system to prefer exact title matches and penalize derivative books
    (summaries, study guides, "after reading", "lessons learned", etc.)
    """
    # Patterns that indicate a derivative/knockoff book — these get heavy penalties
    derivative_patterns = re.compile(
        r'\bsummary\b|\bstudy guide\b|\banalysis\b|\bworkbook\b'
        r'|\bcliff.?s?\s*notes\b|\breading guide\b'
        r'|\bafter reading\b|\blessons?\s*(i\s*)?learned\b'
        r'|\bpersonal reflection\b|\bquick read\b'
        r'|\bbook review\b|\breview of\b|\bguide to\b'
        r'|\bcompanion\b|\bdigest\b|\boverview\b'
        r'|\bbookclub\b|\bbook club\b|\bdiscussion\b|\binsight\b',
        re.IGNORECASE
    )
    
    # Normalize the original title for comparison
    clean_title = re.sub(r'[^\w\s]', '', original_title.lower()).strip()
    title_words = set(clean_title.split())
    
    candidates = []
    
    # Look for table-based search results (Goodreads uses <table class="tableList">)
    table = soup.find('table', class_='tableList')
    if table:
        rows = table.find_all('tr')
        for row in rows:
            title_link = row.find('a', class_='bookTitle')
            if not title_link:
                continue
            
            result_title = title_link.get_text(strip=True)
            href = title_link.get('href', '')
            
            if not href or '/book/show/' not in href:
                continue
            
            # Score this result
            score = _score_result(result_title, clean_title, title_words, derivative_patterns)
            
            # Bonus: check for edition count (more editions = more likely the real book)
            editions_elem = row.find('a', href=re.compile(r'/work/editions/'))
            if editions_elem:
                editions_text = editions_elem.get_text(strip=True)
                edition_match = re.search(r'(\d+)', editions_text)
                if edition_match:
                    edition_count = int(edition_match.group(1))
                    if edition_count > 5:
                        score += 20  # Many editions = real book
                    elif edition_count > 2:
                        score += 10
            
            candidates.append((score, href, result_title))
    
    # If no table results, try any book links on the page
    if not candidates:
        all_links = soup.find_all('a', href=True)
        for link in all_links:
            href = link.get('href', '')
            text = link.get_text(strip=True)
            
            if '/book/show/' in href and text and len(text) > 3:
                score = _score_result(text, clean_title, title_words, derivative_patterns)
                candidates.append((score, href, text))
    
    if not candidates:
        return None
    
    # Sort by score (highest first) and return the best match
    candidates.sort(key=lambda x: x[0], reverse=True)
    
    best_score, best_href, best_title = candidates[0]
    logger.info(f"Goodreads best match: '{best_title}' (score: {best_score})")
    
    # Log top 3 for debugging
    for i, (s, h, t) in enumerate(candidates[:3]):
        logger.debug(f"  #{i+1}: score={s} title='{t}'")
    
    return best_href


def _score_result(result_title: str, clean_title: str, title_words: set, derivative_patterns) -> int:
    """Score a search result based on how well it matches the original title."""
    score = 0
    clean_result = re.sub(r'[^\w\s]', '', result_title.lower()).strip()
    result_words = set(clean_result.split())
    
    # Exact or near-exact title match gets big bonus
    if clean_result == clean_title:
        score += 100
    elif clean_title in clean_result or clean_result in clean_title:
        score += 60
    
    # Word overlap score
    if title_words:
        overlap = len(title_words & result_words)
        overlap_ratio = overlap / len(title_words)
        score += int(overlap_ratio * 40)
    
    # Heavy penalty for derivative books
    if derivative_patterns.search(result_title):
        score -= 80
    
    # Penalty if result title is much longer than original (likely has extra words like "Summary of...")
    len_ratio = len(clean_result) / max(len(clean_title), 1)
    if len_ratio > 2.0:
        score -= 30
    elif len_ratio > 1.5:
        score -= 15
    
    # Bonus for title starting with the same words
    if clean_result.startswith(clean_title[:min(20, len(clean_title))]):
        score += 25
    
    return score


def _parse_book_page(html: str, book_url: str) -> dict:
    """Parse a Goodreads book page for rating, description, and reviews."""
    soup = BeautifulSoup(html, 'html.parser')
    result = {
        "url": book_url,
        "title": "",
        "author": "",
        "rating": None,
        "rating_count": "",
        "review_count": "",
        "description": "",
        "genres": [],
        "reviews": [],
        "cover_image": None
    }
    
    # Title
    title_elem = soup.find('h1', {'data-testid': 'bookTitle'})
    if not title_elem:
        title_elem = soup.find('h1', class_='Text__title1')
    if title_elem:
        result["title"] = title_elem.get_text(strip=True)
    
    # Author
    author_elem = soup.find('span', {'data-testid': 'name'})
    if not author_elem:
        # Fallback
        author_container = soup.find('div', class_='ContributorLinksList')
        if author_container:
            author_elem = author_container.find('a')
    if author_elem:
        result["author"] = author_elem.get_text(strip=True)
    
    # Rating
    rating_elem = soup.find('div', class_='RatingStatistics__rating')
    if rating_elem:
        result["rating"] = rating_elem.get_text(strip=True)
    
    # Rating count and review count
    rating_count_elems = soup.find_all('span', {'data-testid': True})
    for elem in rating_count_elems:
        test_id = elem.get('data-testid', '')
        if 'ratingsCount' in test_id:
            result["rating_count"] = elem.get_text(strip=True)
        elif 'reviewsCount' in test_id:
            result["review_count"] = elem.get_text(strip=True)
    
    # If we didn't find via data-testid, try a broader approach
    if not result["rating_count"]:
        stats_text = ""
        stats_container = soup.find('div', class_='RatingStatistics__meta')
        if stats_container:
            stats_text = stats_container.get_text()
        
        rating_match = re.search(r'([\d,]+)\s*ratings?', stats_text)
        review_match = re.search(r'([\d,]+)\s*reviews?', stats_text)
        
        if rating_match:
            result["rating_count"] = rating_match.group(1) + " ratings"
        if review_match:
            result["review_count"] = review_match.group(1) + " reviews"
    
    # Description
    desc_elem = soup.find('div', {'data-testid': 'description'})
    if not desc_elem:
        desc_elem = soup.find('div', class_='DetailsLayoutRightParagraph__widthConstrained')
    if desc_elem:
        # Get the full text, handling "show more" buttons
        desc_spans = desc_elem.find_all('span', class_='Formatted')
        if desc_spans:
            # Use the longest span (usually the full description)
            result["description"] = max(
                [s.get_text(strip=True) for s in desc_spans],
                key=len,
                default=""
            )
        else:
            result["description"] = desc_elem.get_text(strip=True)
    
    # Genres
    genre_elems = soup.find_all('span', class_='BookPageMetadataSection__genreButton')
    if not genre_elems:
        genre_elems = soup.find_all('a', href=re.compile(r'/genres/'))
    
    seen_genres = set()
    for g in genre_elems[:8]:
        genre_text = g.get_text(strip=True)
        if genre_text and genre_text.lower() not in seen_genres:
            seen_genres.add(genre_text.lower())
            result["genres"].append(genre_text)
    
    # Cover image
    cover_img = soup.find('img', class_='ResponsiveImage')
    if cover_img:
        result["cover_image"] = cover_img.get('src', '')
    
    # Reviews — parse community reviews section
    result["reviews"] = _parse_reviews(soup)
    
    # Try to extract from JSON-LD as fallback for missing fields
    _enrich_from_json_ld(soup, result)
    
    return result


def _parse_reviews(soup: BeautifulSoup, max_reviews: int = 5) -> list:
    """Extract top reviews from the Goodreads book page."""
    reviews = []
    
    # Look for review cards
    review_cards = soup.find_all('article', class_='ReviewCard')
    if not review_cards:
        # Fallback: look for review sections
        review_cards = soup.find_all('div', class_='ReviewCard')
    
    if not review_cards:
        # Another fallback: look for review text sections
        review_sections = soup.find_all('section', class_='ReviewCard__content')
        if review_sections:
            review_cards = [s.parent for s in review_sections if s.parent]
    
    for card in review_cards[:max_reviews]:
        review = {
            "reviewer": "",
            "rating": None,
            "date": "",
            "text": "",
            "url": ""
        }
        
        # Reviewer name
        name_elem = card.find('div', {'data-testid': 'name'})
        if not name_elem:
            name_elem = card.find('a', class_='ReviewerProfile__name')
        if not name_elem:
            # Try finding any link that looks like a user profile
            profile_link = card.find('a', href=re.compile(r'/user/show/'))
            if profile_link:
                name_elem = profile_link
        if name_elem:
            review["reviewer"] = name_elem.get_text(strip=True)
        
        # Rating (star count)
        stars_elem = card.find('span', class_='RatingStars')
        if stars_elem:
            aria_label = stars_elem.get('aria-label', '')
            star_match = re.search(r'(\d)', aria_label)
            if star_match:
                review["rating"] = int(star_match.group(1))
        
        if not review["rating"]:
            # Try another star pattern
            star_spans = card.find_all('span', class_=re.compile(r'ratingstar|RatingStar'))
            review["rating"] = len(star_spans) if star_spans else None
        
        # Date
        date_elem = card.find('span', class_='Text__body3')
        if not date_elem:
            date_elem = card.find('a', href=re.compile(r'/review/show/'))
        if date_elem:
            date_text = date_elem.get_text(strip=True)
            # Only use if it looks like a date
            if re.search(r'\d{4}|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec', date_text, re.IGNORECASE):
                review["date"] = date_text
        
        # Review URL
        review_link = card.find('a', href=re.compile(r'/review/show/'))
        if review_link:
            href = review_link.get('href', '')
            review["url"] = f"{GOODREADS_BASE}{href}" if href.startswith('/') else href
        
        # Review text
        text_container = card.find('section', class_='ReviewCard__content')
        if not text_container:
            text_container = card.find('div', class_='ReviewText')
        if not text_container:
            text_container = card.find('span', class_='Formatted')
        
        if text_container:
            # Get formatted text spans
            formatted = text_container.find_all('span', class_='Formatted')
            if formatted:
                review["text"] = max(
                    [s.get_text(strip=True) for s in formatted],
                    key=len,
                    default=""
                )
            else:
                review["text"] = text_container.get_text(strip=True)
            
            # Truncate very long reviews
            if len(review["text"]) > 600:
                review["text"] = review["text"][:597] + "..."
        
        # Only add if we got some meaningful content
        if review["reviewer"] or review["text"]:
            reviews.append(review)
    
    return reviews


def _enrich_from_json_ld(soup: BeautifulSoup, result: dict):
    """Try to fill in missing fields from JSON-LD structured data on the page."""
    try:
        scripts = soup.find_all('script', type='application/ld+json')
        for script in scripts:
            data = json.loads(script.string)
            if isinstance(data, dict) and data.get('@type') == 'Book':
                if not result["title"]:
                    result["title"] = data.get('name', '')
                if not result["author"]:
                    author_data = data.get('author', {})
                    if isinstance(author_data, list):
                        result["author"] = author_data[0].get('name', '') if author_data else ''
                    elif isinstance(author_data, dict):
                        result["author"] = author_data.get('name', '')
                if not result["rating"]:
                    agg_rating = data.get('aggregateRating', {})
                    result["rating"] = str(agg_rating.get('ratingValue', ''))
                    if not result["rating_count"]:
                        rc = agg_rating.get('ratingCount', '')
                        result["rating_count"] = f"{rc:,} ratings" if isinstance(rc, int) else str(rc)
                    if not result["review_count"]:
                        rvc = agg_rating.get('reviewCount', '')
                        result["review_count"] = f"{rvc:,} reviews" if isinstance(rvc, int) else str(rvc)
                if not result["cover_image"]:
                    result["cover_image"] = data.get('image', '')
                if not result["description"]:
                    result["description"] = data.get('description', '')
                break
    except Exception as e:
        logger.debug(f"JSON-LD parse error (non-critical): {e}")
