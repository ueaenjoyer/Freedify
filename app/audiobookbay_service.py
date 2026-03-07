import httpx
from bs4 import BeautifulSoup
import urllib.parse
from fastapi import HTTPException
import re
import asyncio
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

ABB_BASE_URL = "https://audiobookbay.lu"

async def search_audiobooks(query: str, page: int = 1):
    """
    Search AudiobookBay for audiobooks.
    """
    # ABB requires &tt=1 for author/title search to return actual results
    # ABB blocks direct URL query strings. We must load the homepage, type the query, and hit enter.
    loop = asyncio.get_event_loop()
    
    def fetch_with_selenium(search_query: str):
        options = Options()
        options.add_argument('--headless=new')
        options.add_argument('--window-size=1920,1080')
        options.add_argument('--disable-gpu')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-blink-features=AutomationControlled')
        options.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option('useAutomationExtension', False)
        
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)
        try:
            from selenium.webdriver.common.by import By
            from selenium.webdriver.common.keys import Keys
            driver.set_page_load_timeout(30)
            
            # 1. Load Homepage
            driver.get(ABB_BASE_URL)
            import time
            time.sleep(2)
            
            # 2. Find Search Box, Type, Submit
            search_box = driver.find_element(By.NAME, 's')
            search_box.send_keys(search_query)
            # If checking author/title only, there's no easy UI toggle, but typically default search is enough.
            search_box.send_keys(Keys.RETURN)
            
            # 3. Wait for results page
            time.sleep(3)
            
            return driver.page_source
        finally:
            driver.quit()

    try:
        html_content = await loop.run_in_executor(None, fetch_with_selenium, query)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch from AudiobookBay via Selenium: {str(e)}")

    soup = BeautifulSoup(html_content, 'html.parser')
    results = []

    # Typical structure: <div class="post"> with h2>a for title and img for cover
    posts = soup.find_all('div', class_='post')
    
    for post in posts:
        title_elem = post.find('div', class_='postTitle').find('h2').find('a') if post.find('div', class_='postTitle') else None
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
        cover_image = img_elem['src'] if img_elem else None
        
        # Get details (Category, Language, Size, etc.) inside the postContent
        # Usually it's in a <p> or mixed text
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
    
    def fetch_with_selenium(target_url):
        options = Options()
        options.add_argument('--headless=new')
        options.add_argument('--window-size=1920,1080')
        options.add_argument('--disable-gpu')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-blink-features=AutomationControlled')
        options.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option('useAutomationExtension', False)
        
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)
        try:
            driver.set_page_load_timeout(45)
            driver.get(target_url)
            import time
            time.sleep(3)
            return driver.page_source
        finally:
            driver.quit()

    try:
        html_content = await loop.run_in_executor(None, fetch_with_selenium, url)
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
