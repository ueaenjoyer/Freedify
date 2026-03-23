import httpx
from bs4 import BeautifulSoup
import urllib.parse
from fastapi import HTTPException
import re
import asyncio
import logging
import shutil
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

logger = logging.getLogger(__name__)

ABB_BASE_URL = "https://audiobookbay.lu"

MAX_RETRIES = 2


def _create_driver():
    """Create a memory-optimized headless Chrome driver for constrained environments (Render, Docker)."""
    options = Options()
    options.add_argument('--headless=new')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-gpu')
    options.add_argument('--disable-extensions')
    options.add_argument('--disable-plugins-discovery')
    options.add_argument('--disable-software-rasterizer')
    options.add_argument('--disable-background-networking')
    options.add_argument('--disable-default-apps')
    options.add_argument('--disable-sync')
    options.add_argument('--disable-translate')
    options.add_argument('--disable-logging')
    options.add_argument('--single-process')
    options.add_argument('--no-zygote')
    options.add_argument('--no-first-run')
    options.add_argument('--window-size=1280,720')
    options.add_argument('--js-flags=--max-old-space-size=256')
    options.add_argument('--blink-settings=imagesEnabled=false')
    options.add_argument('--disable-blink-features=AutomationControlled')
    options.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option('useAutomationExtension', False)

    # Disable images/CSS to speed up loading
    prefs = {
        'profile.managed_default_content_settings.images': 2,
        'profile.managed_default_content_settings.stylesheets': 2,
    }
    options.add_experimental_option('prefs', prefs)

    # Try system-installed Chromium first (Docker/Linux), fall back to webdriver-manager (local dev)
    chromium_path = shutil.which('chromium') or shutil.which('chromium-browser')
    chromedriver_path = shutil.which('chromedriver')

    if chromium_path and chromedriver_path:
        options.binary_location = chromium_path
        service = Service(chromedriver_path)
    else:
        service = Service(ChromeDriverManager().install())

    driver = webdriver.Chrome(service=service, options=options)
    driver.set_page_load_timeout(60)
    return driver


def _fetch_page_with_retry(url: str, wait_selector: str = None) -> str:
    """Fetch a page with Selenium, retrying on timeout. Returns page source HTML."""
    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        driver = None
        try:
            logger.info(f"Selenium fetch attempt {attempt}/{MAX_RETRIES}: {url}")
            driver = _create_driver()
            driver.get(url)

            # Wait for actual content instead of fixed sleep
            if wait_selector:
                try:
                    WebDriverWait(driver, 15).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, wait_selector))
                    )
                except Exception:
                    # Content might still be there, just not matching selector — continue
                    pass

            return driver.page_source
        except Exception as e:
            last_error = e
            logger.warning(f"Selenium attempt {attempt} failed: {e}")
        finally:
            if driver:
                try:
                    driver.quit()
                except Exception:
                    pass

    raise last_error


def extract_slug_from_url(url: str):
    """
    Extract the audiobook slug from a full AudiobookBay URL.
    e.g. 'https://audiobookbay.lu/audio-books/it-a-novel-4/' -> 'audio-books/it-a-novel-4'
    """
    from urllib.parse import urlparse
    parsed = urlparse(url)
    path = parsed.path.strip('/')
    return path if path else None


def is_audiobookbay_url(text: str) -> bool:
    """Check if a string is an AudiobookBay URL."""
    return bool(re.match(r'https?://(www\.)?audiobookbay\.[a-z]+/', text))


async def search_audiobooks(query: str, page: int = 1):
    """
    Search AudiobookBay for audiobooks.
    Uses direct URL search (single page load) instead of form submission.
    Supports pagination via the `page` parameter (1-indexed).
    """
    loop = asyncio.get_event_loop()

    def do_search(search_query: str, target_page: int):
        encoded_query = urllib.parse.quote_plus(search_query)
        # Direct URL search — single page load, no homepage visit needed
        if target_page > 1:
            url = f"{ABB_BASE_URL}/page/{target_page}/?s={encoded_query}"
        else:
            url = f"{ABB_BASE_URL}/?s={encoded_query}"

        return _fetch_page_with_retry(url, wait_selector='div.post')

    try:
        html_content = await loop.run_in_executor(None, do_search, query, page)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch from AudiobookBay via Selenium: {str(e)}")

    soup = BeautifulSoup(html_content, 'html.parser')
    results = []

    # Typical structure: <div class="post"> with h2>a for title and img for cover
    posts = soup.find_all('div', class_='post')

    for post in posts:
        title_div = post.find('div', class_='postTitle')
        title_h2 = title_div.find('h2') if title_div else None
        title_elem = title_h2.find('a') if title_h2 else None

        if not title_elem:
            continue

        title = title_elem.text.strip()
        link = title_elem['href']

        # Extract ID or slug from link (e.g. /audio-books/some-book-name/)
        slug = link.replace(ABB_BASE_URL, '').strip('/')
        if link.startswith('/'):
            slug = link.strip('/')
            link = f"{ABB_BASE_URL}{link}"

        # Get cover image
        img_elem = post.find('img')
        cover_image = img_elem.get('src') if img_elem else None

        # Get details (Category, Language, Size, etc.) inside the postContent
        post_content = post.find('div', class_='postContent')
        desc_text = post_content.text.strip() if post_content else ""

        results.append({
            "id": slug,
            "title": title,
            "url": link,
            "cover_image": cover_image,
            "description": desc_text[:200] + "..." if len(desc_text) > 200 else desc_text,
            "source": "audiobookbay"
        })

    return results

async def get_audiobook_details(slug: str):
    """
    Fetch details of a specific audiobook and extract the Info Hash to build a magnet link.
    """
    url = f"{ABB_BASE_URL}/{slug}/"
    if not url.endswith('/'):
         url += '/'

    loop = asyncio.get_event_loop()

    def do_fetch(target_url):
        return _fetch_page_with_retry(target_url, wait_selector='div.postContent')

    try:
        html_content = await loop.run_in_executor(None, do_fetch, url)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch details from AudiobookBay via Selenium: {str(e)}")

    soup = BeautifulSoup(html_content, 'html.parser')

    # Title
    title_elem = soup.find('div', class_='postTitle')
    title = title_elem.find('h1').text.strip() if title_elem and title_elem.find('h1') else "Unknown Title"

    # Cover
    cover_elem = soup.find('div', class_='postContent')
    cover_image = None
    if cover_elem:
        img = cover_elem.find('img')
        if img:
            cover_image = img['src']

    # Extract info hash
    # It's usually in a table row: <tr><td class="statusInfo">Info Hash:</td><td>[HASH]</td></tr>
    info_hash = None

    # Look for the tracker table
    tables = soup.find_all('table')
    for table in tables:
        rows = table.find_all('tr')
        for row in rows:
            cols = row.find_all('td')
            if len(cols) == 2 and "Info Hash:" in cols[0].text:
                info_hash = cols[1].text.strip()
                break
        if info_hash:
            break

    if not info_hash:
        raise HTTPException(status_code=404, detail="Info hash not found on the page. Cannot generate magnet link.")

    encoded_title = urllib.parse.quote_plus(title)
    # List of common trackers used by ABB to improve DHT discovery
    trackers = [
        "udp://tracker.opentrackr.org:1337/announce",
        "udp://tracker.openbittorrent.com:6969/announce",
        "udp://tracker.internetwarriors.net:1337/announce",
        "udp://exodus.desync.com:6969/announce",
        "udp://open.demonii.com:1337/announce"
    ]
    tracker_suffix = "".join([f"&tr={urllib.parse.quote_plus(tr)}" for tr in trackers])
    magnet_link = f"magnet:?xt=urn:btih:{info_hash}&dn={encoded_title}{tracker_suffix}"

    # Get description text
    desc_div = soup.find('div', class_='desc')
    description = desc_div.text.strip() if desc_div else ""

    return {
        "id": slug,
        "title": title,
        "cover_image": cover_image,
        "description": description,
        "info_hash": info_hash,
        "magnet_link": magnet_link,
        "source": "audiobook"
    }
