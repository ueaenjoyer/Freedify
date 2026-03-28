import httpx
import logging
import base64
import json
import xml.etree.ElementTree as ET
import random
import io
from typing import Optional, List, Dict, Any, Tuple
from fastapi import HTTPException

logger = logging.getLogger(__name__)

# Import the canonical proxy list from audio_service (single source of truth)
from app.audio_service import TIDAL_APIS as _TIDAL_APIS

# Randomize a copy for load balancing (don't mutate the original)
PROXY_TARGETS = list(_TIDAL_APIS)
random.shuffle(PROXY_TARGETS)

# Persistent HTTP client — reuses TCP connections across requests
_client = httpx.AsyncClient(
    timeout=10.0,
    limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
    headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "X-Client": "BiniLossless/1.0"
    }
)

async def close():
    """Close the persistent HTTP client (called on server shutdown)."""
    await _client.aclose()

async def _fetch_from_proxy(endpoint: str) -> Optional[Dict[Any, Any]]:
    """
    Attempt to fetch data from the proxy cluster, trying fallback URLs if one fails.
    """
    for target in PROXY_TARGETS:
        url = f"{target.rstrip('/')}/{endpoint.lstrip('/')}"
        try:
            response = await _client.get(url)
            if response.status_code == 200:
                return response.json()
            elif response.status_code == 429:
                logger.warning(f"Tidal proxy {target} rate-limited. Trying next...")
                continue
            else:
                logger.warning(f"Tidal proxy {target} returned {response.status_code}")
        except Exception as e:
            logger.debug(f"Tidal proxy {target} failed: {str(e)}")
            continue

    logger.error("All Tidal API proxies failed.")
    return None

async def search_tracks(query: str, limit: int = 20, offset: int = 0) -> List[Dict[str, Any]]:
    """
    Search Tidal for tracks and normalize them into Freedify's structure.
    """
    data = await _fetch_from_proxy(f"/search/?s={query}&limit={limit}&offset={offset}")
    if not data:
        return []

    # Handle standard nested response vs V2 API {version: ..., data: ...} response
    items_list = []
    if isinstance(data, dict):
        if "items" in data:
            items_list = data["items"]
        elif "data" in data and isinstance(data["data"], dict) and "items" in data["data"]:
            items_list = data["data"]["items"]
    elif isinstance(data, list):
        items_list = data

    results = []
    for item in items_list[:limit]:
        # Sometimes items are wrapped in an `item` key
        track = item.get("item", item) if isinstance(item, dict) else item
        
        if not isinstance(track, dict) or "id" not in track or "title" not in track:
            continue

        # Extract artist name
        artist_name = "Unknown Artist"
        if "artist" in track and isinstance(track["artist"], dict) and "name" in track["artist"]:
            artist_name = track["artist"]["name"]
        elif "artists" in track and isinstance(track["artists"], list) and len(track["artists"]) > 0:
            artist_name = track["artists"][0].get("name", "Unknown Artist")

        # Extract album and cover
        album_name = "Unknown Album"
        cover_url = None
        if "album" in track and isinstance(track["album"], dict):
            album_name = track["album"].get("title", "Unknown Album")
            cover_id = track["album"].get("cover")
            if cover_id:
                # Tidal uses UUIDs for cover images, transform UUID dashes to slashes
                # e.g. b1234567-890a-bcde-f123-4567890abcde -> b1234567/890a/bcde/f123/4567890abcde
                cover_path = str(cover_id).replace("-", "/")
                cover_url = f"https://resources.tidal.com/images/{cover_path}/320x320.jpg"

        duration_s = track.get("duration", 0)
        duration_str = f"{duration_s//60}:{duration_s%60:02d}"
        
        # Audio Quality hinting
        # Options from the API are usually: LOSSLESS, HI_RES, HI_RES_LOSSLESS
        api_quality = track.get("audioQuality", "LOSSLESS")
        is_hires = "HI_RES" in str(api_quality).upper()

        tidal_album_id = ""
        if "album" in track and isinstance(track["album"], dict) and "id" in track["album"]:
            tidal_album_id = f"td_{track['album']['id']}"

        results.append({
            "id": str(track["id"]),
            "name": track["title"],
            "title": track["title"], # Keep title for safety
            "artists": artist_name,
            "artist": artist_name,
            "album": album_name,
            "album_id": tidal_album_id,
            "duration": duration_str,
            "duration_ms": duration_s * 1000,
            "album_art": cover_url,
            "cover": cover_url,
            "source": "tidal",
            "is_hires": is_hires,
        })

    return results

def _decode_manifest(manifest_str: str) -> str:
    """Decode URL-safe base64 manifest strictly to string."""
    try:
        # Pad if necessary
        padded = manifest_str + '=' * (4 - len(manifest_str) % 4)
        return base64.urlsafe_b64decode(padded).decode('utf-8')
    except Exception as e:
        logger.error(f"Failed to decode Tidal manifest: {e}")
        return manifest_str

def _extract_flac_url(decoded_manifest: str) -> Optional[str]:
    """Parse the JSON or XML (Dash MPD) manifest to find the direct FLAC url."""
    # Attempt JSON parse first
    try:
        parsed = json.loads(decoded_manifest)
        if "urls" in parsed and isinstance(parsed["urls"], list) and len(parsed["urls"]) > 0:
            return parsed["urls"][0]
    except json.JSONDecodeError:
        pass

    # Attempt proper XML parse (Tidal DASH MPD)
    try:
        # Strip namespaces to make searching easier
        it = ET.iterparse(io.StringIO(decoded_manifest))
        for _, el in it:
            if '}' in el.tag:
                el.tag = el.tag.split('}', 1)[1]  # strip all namespaces
        root = it.root

        # Find all BaseURLs
        base_urls = []
        for rep in root.findall('.//Representation'):
            codecs = rep.attrib.get('codecs', '').lower()
            if 'flac' in codecs or 'alac' in codecs:
                # 1. Look for BaseURL (old style)
                for base in rep.findall('.//BaseURL'):
                    if base.text:
                        base_urls.append(base.text.strip())
                # 2. Look for SegmentTemplate (new segmented style)
                for seg in rep.findall('.//SegmentTemplate'):
                    init_url = seg.attrib.get('initialization')
                    if init_url:
                        base_urls.append(init_url)
        
        # If no specific Representation BaseURL/SegmentTemplate, grab any top level
        if not base_urls:
            for base in root.findall('.//BaseURL'):
                if base.text:
                    base_urls.append(base.text.strip())
            for seg in root.findall('.//SegmentTemplate'):
                init_url = seg.attrib.get('initialization')
                if init_url:
                    base_urls.append(init_url)

        # Give it a quick score just like the JS code to pick the Best FLAC url
        def score_url(url: str) -> int:
            normalized = url.lower()
            score = 0
            if 'flac' in normalized: score += 3
            if 'hires' in normalized: score += 1
            if normalized.endswith('.flac'): score += 4
            if 'token=' in normalized: score += 1
            return score

        valid_urls = [u for u in base_urls if u and ("token=" in u or "flac" in u or "?" in u)]
        if valid_urls:
            valid_urls.sort(key=score_url, reverse=True)
            return valid_urls[0]

    except Exception as e:
        logger.error(f"XML parse error for MPD manifest: {e}")
            
    return None

async def get_stream_url(track_id: str, quality: str = "LOSSLESS") -> str:
    """
    Fetch the playback manifest for a track and extract the direct stream URL.
    quality should be 'LOSSLESS' (16-bit 44.1kHz) or 'HI_RES_LOSSLESS' (24-bit 96/192kHz).
    """
    data = await _fetch_from_proxy(f"/track/?id={track_id}&quality={quality}")
    
    if not data:
        raise HTTPException(status_code=502, detail="Tidal proxy cluster completely unresponsive")

    # The payload structure is often nested under 'data' or returned directly
    payload = data.get("data", data) if isinstance(data, dict) else data
    
    # Locate the manifest
    if not isinstance(payload, dict):
        raise HTTPException(status_code=500, detail="Unexpected payload from Tidal proxy.")
        
    manifest_b64 = payload.get("manifest")
    if not manifest_b64:
        raise HTTPException(status_code=404, detail="No playback manifest found for this track. Could be region restricted.")

    decoded_manifest = _decode_manifest(manifest_b64)
    stream_url = _extract_flac_url(decoded_manifest)

    if not stream_url:
        logger.error(f"Failed to extract URL from manifest: {decoded_manifest[:200]}...")
        raise HTTPException(status_code=500, detail="Could not parse FLAC url from Tidal manifest. Might be an unsupported DRM stream.")

    return stream_url

async def search_albums(query: str, limit: int = 20, offset: int = 0) -> List[Dict[str, Any]]:
    """
    Search Tidal specifically for albums.
    """
    data = await _fetch_from_proxy(f"/search/?al={query}&limit={limit}&offset={offset}")
    if not data:
        return []

    items_list = []
    items_list = []
    if isinstance(data, dict):
        if "data" in data and "albums" in data["data"]:
            items_list = data["data"]["albums"].get("items", [])
        elif "albums" in data:
            items_list = data["albums"].get("items", [])
        elif "items" in data:
            items_list = data["items"]
        elif "data" in data and isinstance(data["data"], dict) and "items" in data["data"]:
            items_list = data["data"]["items"]
    elif isinstance(data, list):
        items_list = data

    results = []
    for item in items_list[:limit]:
        album = item.get("item", item) if isinstance(item, dict) else item
        
        if not isinstance(album, dict) or "id" not in album or "title" not in album:
            continue

        # Extract artist name
        artist_name = "Unknown Artist"
        if "artist" in album and isinstance(album["artist"], dict) and "name" in album["artist"]:
            artist_name = album["artist"]["name"]
        elif "artists" in album and isinstance(album["artists"], list) and len(album["artists"]) > 0:
            artist_name = album["artists"][0].get("name", "Unknown Artist")

        # Extract cover
        cover_url = None
        cover_id = album.get("cover")
        if cover_id:
            cover_path = str(cover_id).replace("-", "/")
            cover_url = f"https://resources.tidal.com/images/{cover_path}/320x320.jpg"

        api_quality = album.get("audioQuality", "LOSSLESS")
        is_hires = "HI_RES" in str(api_quality).upper()
        if not is_hires and "mediaMetadata" in album:
            tags = album.get("mediaMetadata", {}).get("tags", [])
            is_hires = any("HIRES" in str(tag).upper() or "HI_RES" in str(tag).upper() for tag in tags)

        results.append({
            "id": f"td_{album['id']}",
            "name": album["title"],
            "title": album["title"],
            "artists": artist_name,
            "artist": artist_name,
            "album_art": cover_url,
            "cover": cover_url,
            "type": "album",
            "source": "tidal",
            "is_hires": is_hires,
            "tracks": []  # Tracks aren't loaded in search, they load when clicked
        })

    return results

async def get_album(album_id: str) -> Optional[Dict[str, Any]]:
    """
    Fetch album details, including all tracks for displaying inside the UI.
    """
    # Remove the td_ prefix if it exists
    real_id = album_id.replace("td_", "")
    data = await _fetch_from_proxy(f"/album/?id={real_id}")
    
    if not data:
        return None

    album = data.get("data", data) if isinstance(data, dict) else data
    if not isinstance(album, dict) or "id" not in album or "title" not in album:
        return None

    # Artist
    artist_name = "Unknown Artist"
    if "artist" in album and isinstance(album["artist"], dict) and "name" in album["artist"]:
        artist_name = album["artist"]["name"]

    # Cover
    cover_url = None
    cover_id = album.get("cover")
    if cover_id:
        cover_path = str(cover_id).replace("-", "/")
        cover_url = f"https://resources.tidal.com/images/{cover_path}/320x320.jpg"

    # Tracks
    tracks = []
    items_list = album.get("items", [])
    for list_item in items_list:
        track = list_item.get("item", list_item) if isinstance(list_item, dict) else list_item
        if not isinstance(track, dict) or "id" not in track:
            continue
            
        duration_s = track.get("duration", 0)
        duration_str = f"{duration_s//60}:{duration_s%60:02d}"
        
        api_quality = track.get("audioQuality", "LOSSLESS")
        is_hires = "HI_RES" in str(api_quality).upper()
        
        # Track artists can sometimes differ from album artists (compilations)
        track_artist = artist_name
        if "artists" in track and isinstance(track["artists"], list) and len(track["artists"]) > 0:
            track_artist = track["artists"][0].get("name", artist_name)

        tracks.append({
            "id": str(track["id"]),
            "name": track.get("title", "Unknown Track"),
            "title": track.get("title", "Unknown Track"),
            "artists": track_artist,
            "artist": track_artist,
            "album": album["title"],
            "duration": duration_str,
            "duration_ms": duration_s * 1000,
            "album_art": cover_url,
            "cover": cover_url,
            "source": "tidal",
            "is_hires": is_hires,
        })

    return {
        "id": f"td_{album['id']}",
        "name": album["title"],
        "title": album["title"],
        "artists": artist_name,
        "artist": artist_name,
        "album_art": cover_url,
        "cover": cover_url,
        "type": "album",
        "source": "tidal",
        "tracks": tracks
    }
