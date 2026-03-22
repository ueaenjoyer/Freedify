"""
Freedify Streaming Server
A FastAPI server for streaming music with FFmpeg transcoding.
"""
import os
import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Optional

# Load .env file for local development (Docker uses docker-compose env_file instead)
from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, HTTPException, Query, Response, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import zipfile
import io
from typing import List
import httpx


from app.deezer_service import deezer_service
from app.live_show_service import live_show_service
from app.spotify_service import spotify_service
from app.audio_service import audio_service
from app.podcast_service import podcast_service
from app.dj_service import dj_service
from app.ai_radio_service import ai_radio_service
from app.ytmusic_service import ytmusic_service
from app.setlist_service import setlist_service
from app.lastfm_service import lastfm_service
from app.artist_service import artist_service
from app.listenbrainz_service import listenbrainz_service
from app.jamendo_service import jamendo_service
from app.genius_service import genius_service
from app.concert_service import concert_service
from app.audiobookbay_service import search_audiobooks, get_audiobook_details, is_audiobookbay_url, extract_slug_from_url
from app.premiumize_service import create_transfer, check_transfer_status, list_folder_contents, search_my_files, delete_item

from app.cache import cleanup_cache, periodic_cleanup, is_cached, get_cache_path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ============================================================
# Stream URL Cache — avoids re-running the full API chain on seek/range requests
# Key: isrc, Value: (stream_url, metadata, timestamp)
# Entries expire after STREAM_CACHE_TTL seconds (CDN tokens typically live ~1 hour)
# ============================================================
import time
_stream_url_cache: dict = {}
STREAM_CACHE_TTL = 1800  # 30 minutes

async def keep_awake_ping():
    """Background task to ping the server and prevent Render spin-down."""
    import httpx
    # Render sets RENDER_EXTERNAL_URL automatically, so we can use it to ping ourselves
    target_url = os.environ.get("RENDER_EXTERNAL_URL", "http://localhost:8000")
    ping_url = f"{target_url}/api/health"
    
    # 13 minutes = 780 seconds
    interval = 13 * 60
    
    async with httpx.AsyncClient() as client:
        while True:
            await asyncio.sleep(interval)
            try:
                response = await client.get(ping_url)
                logger.debug(f"Auto-ping {ping_url}: {response.status_code}")
            except Exception as e:
                logger.warning(f"Auto-ping failed: {e}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    logger.info("Starting Freedify Streaming Server...")
    
    # Initial cache cleanup
    await cleanup_cache()
    
    # Pre-warm Tidal API list at startup (so first play isn't slow)
    try:
        await audio_service.update_tidal_apis()
    except Exception as e:
        logger.warning(f"Failed to pre-warm Tidal APIs at startup: {e}")
    
    # Start periodic cleanup task
    cleanup_task = asyncio.create_task(periodic_cleanup(30))
    
    # Start auto-ping task to prevent Render spin-down
    ping_task = asyncio.create_task(keep_awake_ping())
    
    yield
    
    # Cleanup on shutdown
    cleanup_task.cancel()
    ping_task.cancel()
    await deezer_service.close()
    await live_show_service.close()
    await spotify_service.close()
    await audio_service.close()
    await podcast_service.close()
    logger.info("Server shutdown complete.")


app = FastAPI(
    title="Freedify Streaming",
    description="Stream music from Deezer, Spotify URLs, and Live Archives",
    lifespan=lifespan
)

# CORS for mobile access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Middleware to set COOP header for Google OAuth popups
@app.middleware("http")
async def add_security_headers(request, call_next):
    response = await call_next(request)
    # Allow popups (like Google Sign-In) to communicate with window
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin-allow-popups"
    return response


# ========== MODELS ==========

class ParseUrlRequest(BaseModel):
    url: str

class ImportRequest(BaseModel):
    url: str


# ========== API ENDPOINTS ==========

@app.get("/api/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok", "service": "freedify-streaming"}


@app.get("/api/config")
async def get_config():
    """Get public configuration for the frontend (like Google Client ID)."""
    return {
        "google_client_id": os.environ.get("GOOGLE_CLIENT_ID", ""),
    }

# ========== SPOTIFY OAUTH ENDPOINTS ==========

@app.get("/api/spotify/login")
async def spotify_login(request: Request):
    """Redirect user to Spotify OAuth login."""
    # Build redirect URI based on the incoming request host
    scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get("x-forwarded-host", request.url.netloc)
    
    # Spotify strictly blocks 'localhost' over HTTP, but allows '127.0.0.1'
    if host.startswith("localhost"):
        host = host.replace("localhost", "127.0.0.1")
        
    redirect_uri = f"{scheme}://{host}/api/spotify/callback"
    
    url = spotify_service.get_oauth_url(redirect_uri)
    if not url:
        raise HTTPException(status_code=500, detail="Spotify Client ID missing in .env")
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url)

@app.get("/api/spotify/callback")
async def spotify_callback(request: Request, code: str = None, error: str = None):
    """Handle the Spotify OAuth callback and exchange code for tokens."""
    if error:
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url="/?spotify_error=" + error)
        
    if not code:
        raise HTTPException(status_code=400, detail="Missing authorization code")
        
    scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get("x-forwarded-host", request.url.netloc)
    
    if host.startswith("localhost"):
        host = host.replace("localhost", "127.0.0.1")
        
    redirect_uri = f"{scheme}://{host}/api/spotify/callback"
    
    success = await spotify_service.exchange_oauth_code(code, redirect_uri)
    from fastapi.responses import RedirectResponse
    # Redirect user back to wherever they were, or root
    if success:
        return RedirectResponse(url="/?spotify_connected=true")
    else:
        return RedirectResponse(url="/?spotify_error=exchange_failed")

@app.get("/api/spotify/status")
async def spotify_status():
    """Check if the user has connected their Spotify account."""
    is_connected = spotify_service.has_user_token()
    return {"connected": is_connected}

@app.post("/api/spotify/disconnect")
async def spotify_disconnect():
    """Disconnect the user's Spotify account by clearing tokens."""
    spotify_service.clear_user_token()
    return {"status": "disconnected"}


@app.get("/api/search")
async def search(
    q: str = Query(..., min_length=1, description="Search query"),
    type: str = Query("track", description="Search type: track, album, artist, or podcast"),
    offset: int = Query(0, description="Offset for pagination")
):
    """Search for tracks, albums, artists, or podcasts."""
    try:
        # Check for Spotify URL (uses Spotify API - may be rate limited)
        if spotify_service.is_spotify_url(q):
            parsed = spotify_service.parse_spotify_url(q)
            if parsed:
                url_type, item_id = parsed
                logger.info(f"Detected Spotify URL: {url_type}/{item_id}")
                try:
                    return await get_spotify_content(url_type, item_id)
                except HTTPException as e:
                    # If Spotify fails (rate limited), return error with info
                    raise HTTPException(
                        status_code=503,
                        detail=str(e.detail)
                    )
        
        # Check for other URLs (Bandcamp, Soundcloud, Phish.in, Archive.org, etc.)
        if q.startswith("http://") or q.startswith("https://"):
            logger.info(f"Detected URL: {q}")
            item = await audio_service.import_url(q)
            if item:
                # Check if it's an album/playlist
                if item.get('type') == 'album':
                    return {
                        "results": [item],
                        "type": "album",
                        "is_url": True, 
                        "source": "import",
                        "tracks": item.get('tracks', [])
                    }
                # Single track
                return {"results": [item], "type": "track", "is_url": True, "source": "import"}
        # Podcast Search
        if type == "podcast":
            results = await podcast_service.search_podcasts(q)
            return {"results": results, "query": q, "type": "podcast", "source": "podcast", "offset": offset}
            
        # Audiobook Search
        if type == "audiobook":
            # Check if the query is a direct AudiobookBay URL
            if is_audiobookbay_url(q):
                slug = extract_slug_from_url(q)
                if slug:
                    details = await get_audiobook_details(slug)
                    # Return as a single result with is_url flag so the frontend auto-opens it
                    return {
                        "results": [{
                            "id": details["id"],
                            "title": details["title"],
                            "cover_image": details.get("cover_image"),
                            "description": details.get("description", ""),
                            "source": "audiobookbay"
                        }],
                        "query": q,
                        "type": "audiobook",
                        "source": "audiobookbay",
                        "is_url": True,
                        "offset": 0
                    }
            # Normal keyword search with pagination
            page = (offset // 15) + 1 if offset > 0 else 1
            results = await search_audiobooks(q, page=page)
            return {"results": results, "query": q, "type": "audiobook", "source": "audiobookbay", "offset": offset}
        
        # YouTube Music Search
        if type == "ytmusic":
            results = await ytmusic_service.search_tracks(q, limit=20, offset=offset)
            return {"results": results, "query": q, "type": "track", "source": "ytmusic", "offset": offset}
        
        # Setlist.fm Search
        if type == "setlist":
            results = await setlist_service.search_setlists(q)
            return {"results": results, "query": q, "type": "album", "source": "setlist.fm", "offset": offset}
            
        # Check for live show searches FIRST if no type specified or type is album
        # But only if NOT one of the special types above (which returned already)
        live_results = await live_show_service.search_live_shows(q)
        if live_results is not None:
            return {"results": live_results, "query": q, "type": "album", "source": "live_shows"}
        
        # Regular search - Use Tidal (Priority), then Qobuz, then Dab, then Deezer
        logger.info(f"Searching: {q} (type: {type}, offset: {offset})")
        
        results = []
        source = "deezer"
        
        # 0. Try Tidal FIRST
        if type in ["album", "track"]:
            try:
                import app.tidal_service as tidal_service
                if type == "album":
                    tidal_results = await tidal_service.search_albums(q, limit=20, offset=offset)
                else:
                    tidal_results = await tidal_service.search_tracks(q, limit=20, offset=offset)
                
                if tidal_results:
                    logger.info(f"Found {len(tidal_results)} results on Tidal")
                    results = tidal_results
                    source = "tidal"
            except Exception as e:
                logger.error(f"Tidal search error: {e}")
        
        # 1. Try Qobuz (Squid.wtf) if Tidal found no results [BYPASSED — currently broken]
        from app.audio_service import ENABLE_QOBUZ, ENABLE_DAB
        if ENABLE_QOBUZ and not results and type in ["album", "track"] and offset == 0:
            try:
                from app.qobuz_service import qobuz_service
                if type == "album":
                    qobuz_results = await qobuz_service.search_albums(q, limit=10)
                else:
                    qobuz_results = await qobuz_service.search_tracks(q, limit=10)
                
                if qobuz_results:
                    logger.info(f"Found {len(qobuz_results)} results on Qobuz")
                    results = qobuz_results
                    source = "qobuz"
            except Exception as e:
                logger.error(f"Qobuz search error: {e}")

        # 1b. Try Dab Music (fallback/alternative Hi-Res) [BYPASSED — currently broken]
        if ENABLE_DAB and not results and type in ["album", "track"] and offset == 0:
            try:
                from app.dab_service import dab_service
                if type == "album":
                    dab_results = await dab_service.search_albums(q, limit=10)
                else:
                    dab_results = await dab_service.search_tracks(q, limit=10)
                
                if dab_results:
                    logger.info(f"Found {len(dab_results)} results on Dab Music")
                    results = dab_results
                    source = "dab"
            except Exception as e:
                logger.error(f"Dab search error: {e}")

        # 2. Fallback to Deezer if no Dab results
        if not results:
            logger.info(f"Falling back to Deezer search...")
            if type == "album":
                results = await deezer_service.search_albums(q, limit=20, offset=offset)
            elif type == "artist":
                results = await deezer_service.search_artists(q, limit=20, offset=offset)
            else:
                results = await deezer_service.search_tracks(q, limit=20, offset=offset)
            if results:
                source = "deezer"
        
        # 3. Final fallback to Jamendo (independent/CC music) if still no results
        if not results and type in ["track", "album", "artist"]:
            logger.info(f"Falling back to Jamendo search...")
            try:
                if type == "album":
                    results = await jamendo_service.search_albums(q, limit=20, offset=offset)
                elif type == "artist":
                    results = await jamendo_service.search_artists(q, limit=20, offset=offset)
                else:
                    results = await jamendo_service.search_tracks(q, limit=20, offset=offset)
                if results:
                    source = "jamendo"
                    logger.info(f"Found {len(results)} results on Jamendo")
            except Exception as e:
                logger.error(f"Jamendo search error: {e}")
        
        return {"results": results, "query": q, "type": type, "source": source, "offset": offset}
    except Exception as e:
        logger.error(f"Search error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


async def get_content_by_type(content_type: str, item_id: str):
    """Helper to get content by type and ID (uses Deezer, Dab, or Jamendo)."""
    
    # Handle Dab Music IDs
    if item_id.startswith("dab_"):
        from app.dab_service import dab_service
        if content_type == "album":
            album = await dab_service.get_album(item_id)
            if album:
                return {"results": [album], "type": "album", "is_url": True, "tracks": album.get("tracks", [])}
        # Dab doesn't really have "get_track" singular metadata endpoint exposed yet, but we can search or use stream.
        # But for UI "open track", usually it plays directly.
        pass
    
    # Handle Jamendo IDs (jm_ prefix)
    if item_id.startswith("jm_"):
        if content_type == "album":
            album = await jamendo_service.get_album(item_id)
            if album:
                return {"results": [album], "type": "album", "is_url": True, "tracks": album.get("tracks", []), "source": "jamendo"}
        elif content_type == "artist" or item_id.startswith("jm_artist_"):
            artist = await jamendo_service.get_artist(item_id)
            if artist:
                return {"results": [artist], "type": "artist", "is_url": True, "tracks": artist.get("tracks", []), "source": "jamendo"}
        elif content_type == "track":
            track = await jamendo_service.get_track(item_id)
            if track:
                return {"results": [track], "type": "track", "is_url": True, "source": "jamendo"}
        raise HTTPException(status_code=404, detail=f"Jamendo {content_type} not found")

    if content_type == "track":
        results = await deezer_service.search_tracks(item_id, limit=1)
        if results:
            return {"results": results, "type": "track", "is_url": True}
    elif content_type == "album":
        album = await deezer_service.get_album(item_id)
        if album:
            return {"results": [album], "type": "album", "is_url": True, "tracks": album.get("tracks", [])}
    elif content_type == "artist":
        artist = await deezer_service.get_artist(item_id)
        if artist:
            return {"results": [artist], "type": "artist", "is_url": True, "tracks": artist.get("tracks", [])}
    
    raise HTTPException(status_code=404, detail=f"{content_type.title()} not found")


async def get_spotify_content(content_type: str, item_id: str):
    """Helper to get content from Spotify by type and ID."""
    if content_type == "track":
        track = await spotify_service.get_track_by_id(item_id)
        if track:
            return {"results": [track], "type": "track", "is_url": True, "source": "spotify"}
    elif content_type == "album":
        album = await spotify_service.get_album(item_id)
        if album:
            return {"results": [album], "type": "album", "is_url": True, "tracks": album.get("tracks", []), "source": "spotify"}
    elif content_type == "playlist":
        playlist = await spotify_service.get_playlist(item_id)
        if playlist:
            return {"results": [playlist], "type": "playlist", "is_url": True, "tracks": playlist.get("tracks", []), "source": "spotify"}
    elif content_type == "artist":
        artist = await spotify_service.get_artist(item_id)
        if artist:
            return {"results": [artist], "type": "artist", "is_url": True, "tracks": artist.get("tracks", []), "source": "spotify"}
    
    raise HTTPException(status_code=404, detail=f"Spotify {content_type.title()} not found")


@app.post("/api/import")
async def import_url_endpoint(request: ImportRequest):
    """Import a track from a URL (Bandcamp, Soundcloud, etc.)."""
    try:
        track = await audio_service.import_url(request.url)
        if not track:
            raise HTTPException(status_code=400, detail="Could not import URL")
        return track
    except Exception as e:
        logger.error(f"Import endpoint error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/track/{track_id}")
async def get_track(track_id: str):
    """Get track details by Spotify ID."""
    try:
        track = await spotify_service.get_track_by_id(track_id)
        if not track:
            raise HTTPException(status_code=404, detail="Track not found")
        return track
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Track fetch error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/album/{album_id}")
async def get_album(album_id: str):
    # Support Dab Albums
    if album_id.startswith("dab_"):
        from app.dab_service import dab_service
        album = await dab_service.get_album(album_id)
        if album: return album
        raise HTTPException(status_code=404, detail="Dab album not found")
        
    # Support Deezer Albums (fallback logic handled in dedicated service or here)
    if album_id.startswith("dz_"):
        album = await deezer_service.get_album(album_id)
        if album: return album
        raise HTTPException(status_code=404, detail="Deezer album not found")

    try:
        # Handle different sources based on ID prefix
        if album_id.startswith("dz_"):
            # Deezer album
            album = await deezer_service.get_album(album_id)
        elif album_id.startswith("td_"):
            # Tidal album
            from app.tidal_service import get_album as get_tidal_album
            album = await get_tidal_album(album_id)
        elif album_id.startswith("archive_"):
            # Archive.org show - import via URL
            identifier = album_id.replace("archive_", "")
            url = f"https://archive.org/details/{identifier}"
            logger.info(f"Importing Archive.org show: {url}")
            album = await audio_service.import_url(url)
        elif album_id.startswith("phish_"):
            # Phish.in show - import via URL 
            date = album_id.replace("phish_", "")
            url = f"https://phish.in/{date}"
            logger.info(f"Importing Phish.in show: {url}")
            album = await audio_service.import_url(url)
        elif album_id.startswith("pod_"):
            # Podcast Import (PodcastIndex)
            feed_id = album_id.replace("pod_", "")
            album = await podcast_service.get_podcast_episodes(feed_id)
        elif album_id.startswith("itunes_"):
            # iTunes Podcast - fetch episodes via RSS
            album = await podcast_service.get_podcast_episodes(album_id)
        elif album_id.startswith("setlist_"):
            # Setlist.fm - get full setlist with tracks
            setlist_id = album_id.replace("setlist_", "")
            album = await setlist_service.get_setlist(setlist_id)
            if album and album.get("audio_source") == "phish.in":
                # Phish show - fetch audio from phish.in
                album["audio_available"] = True
            elif album and album.get("audio_source") == "archive.org":
                # Other artist - find best Archive.org version
                archive_url = await setlist_service.find_best_archive_show(
                    album.get("artists", ""),
                    album.get("iso_date", "")
                )
                if archive_url:
                    album["audio_url"] = archive_url
                    album["audio_available"] = True
                else:
                    # Fallback to search if no direct match
                    album["audio_available"] = True
        else:
            # Unknown source - try Deezer
            album = await deezer_service.get_album(album_id)
        
        if not album:
            raise HTTPException(status_code=404, detail="Album not found")
        return album
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Album fetch error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/playlist/{playlist_id}")
async def get_playlist(playlist_id: str):
    """Get playlist details with all tracks."""
    try:
        playlist = await spotify_service.get_playlist(playlist_id)
        if not playlist:
            raise HTTPException(status_code=404, detail="Playlist not found")
        return playlist
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Playlist fetch error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/artist/{artist_id}")
async def get_artist(artist_id: str):
    """Get artist details with top tracks."""
    try:
        # Use Deezer for dz_ prefixed IDs
        if artist_id.startswith("dz_"):
            artist = await deezer_service.get_artist(artist_id)
        else:
            artist = await spotify_service.get_artist(artist_id)
        if not artist:
            raise HTTPException(status_code=404, detail="Artist not found")
        return artist
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Artist fetch error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.api_route("/api/stream/{isrc}", methods=["GET", "HEAD"])
async def stream_audio(
    request: Request,
    isrc: str,
    q: Optional[str] = Query(None, description="Search query hint"),
    hires: bool = Query(True, description="Prefer Hi-Res 24-bit audio"),
    hires_quality: str = Query("6", description="Hi-Res quality: 5=192kHz/24bit, 6=96kHz/24bit"),
    source: Optional[str] = Query(None, description="Source of the track")
):
    """Stream audio for a track by ISRC."""
    try:
        logger.info(f"Stream request for ISRC: {isrc} (hires={hires})")
        
        target_stream_url = None
        
        # 1. Resolve Target Stream URL (Direct or via yt-dlp)
        
        # Handle Imported Links (LINK:)
        if isrc.startswith("LINK:"):
            import base64
            from urllib.parse import urlparse
            try:
                encoded_url = isrc.replace("LINK:", "")
                # Add strict URL-safe base64 padding
                encoded_url += "=" * ((4 - len(encoded_url) % 4) % 4)
                original_url = base64.urlsafe_b64decode(encoded_url).decode()
                
                # Check for direct file extension first (fast path)
                parsed = urlparse(original_url)
                audio_exts = ('.mp3', '.m4a', '.ogg', '.wav', '.aac', '.opus', '.flac', '.m4b', '.mp4')
                if any(parsed.path.lower().endswith(ext) for ext in audio_exts):
                     target_stream_url = original_url
                else:
                    # Try to extract stream via yt-dlp (for YouTube/SoundCloud links)
                    # Run in executor to avoid blocking
                    loop = asyncio.get_event_loop()
                    target_stream_url = await loop.run_in_executor(None, audio_service._get_stream_url, original_url)
                    
            except Exception as e:
                logger.warning(f"Failed to parse/extract LINK: {e}")

        # Handle YouTube Music (ytm_)
        elif isrc.startswith("ytm_"):
             video_id = isrc.replace("ytm_", "")
             youtube_url = f"https://music.youtube.com/watch?v={video_id}"
             loop = asyncio.get_event_loop()
             target_stream_url = await loop.run_in_executor(None, audio_service._get_stream_url, youtube_url)

        # Handle Jamendo (jm_) - Direct stream/download URLs
        elif isrc.startswith("jm_"):
            track_id = isrc.replace("jm_", "")
            target_stream_url = await jamendo_service.get_stream_url(track_id, prefer_flac=hires)

        # 2. Proxy the Target Stream (if found)
        if target_stream_url:
            logger.info(f"Proxying direct stream: {target_stream_url[:60]}...")
            
            # Forward Range header to support seeking
            req_headers = {}
            if request.headers.get("Range"):
                req_headers["Range"] = request.headers.get("Range")
                logger.info(f"Forwarding Range header: {req_headers['Range']}")



            try:
                # Create a local client instance (not shared).
                # Use long read timeout (300s) so slow upstream CDNs don't kill active streams
                stream_timeout = httpx.Timeout(connect=10.0, read=300.0, write=10.0, pool=10.0)
                client = httpx.AsyncClient(follow_redirects=True, timeout=stream_timeout)
                req = client.build_request("GET", target_stream_url, headers=req_headers)
                r = await client.send(req, stream=True)
                
                # Auto-refresh expired Premiumize CDN links
                if r.status_code == 403 and "energycdn.com" in target_stream_url:
                    await r.aclose()
                    await client.aclose()
                    
                    # Extract filename from the expired URL path
                    from urllib.parse import urlparse, unquote
                    expired_path = urlparse(target_stream_url).path
                    filename = unquote(expired_path.split("/")[-1])
                    logger.info(f"Premiumize CDN link expired (403). Refreshing link for: {filename}")
                    
                    from app.premiumize_service import refresh_link_by_filename
                    fresh_url = await refresh_link_by_filename(filename)
                    
                    if fresh_url:
                        logger.info(f"Got fresh Premiumize link, retrying stream...")
                        target_stream_url = fresh_url
                        client = httpx.AsyncClient(follow_redirects=True, timeout=stream_timeout)
                        req = client.build_request("GET", target_stream_url, headers=req_headers)
                        r = await client.send(req, stream=True)
                    else:
                        logger.warning(f"Could not refresh Premiumize link for: {filename}")
                        raise HTTPException(status_code=403, detail="Premiumize CDN link expired and could not be refreshed. Try re-adding the file from your cloud.")
                
                # Prepare headers
                resp_headers = {
                    "Accept-Ranges": "bytes",
                    "Cache-Control": "public, max-age=3600",
                    "Access-Control-Allow-Origin": "*",
                    "X-Accel-Buffering": "no"
                }
                for key in ["Content-Range", "Content-Length", "Content-Type", "Last-Modified", "ETag"]:
                    if r.headers.get(key):
                        resp_headers[key] = r.headers[key]
                
                # Custom iterator that closes the LOCAL client
                async def response_iterator():
                    try:
                        async for chunk in r.aiter_bytes(chunk_size=65536):
                            yield chunk
                    except Exception as e:
                        logger.error(f"Stream iteration error: {e}")
                    finally:
                        # Close the response AND the client
                        await r.aclose()
                        await client.aclose()
                
                return StreamingResponse(
                    response_iterator(),
                    status_code=r.status_code,
                    media_type=r.headers.get("Content-Type", "audio/mpeg"),
                    headers=resp_headers
                )
            except Exception as e:
                logger.error(f"Proxying stream failed: {e}")
                # Fall through to standard playback if proxy fails
        
        # 3. Standard / HiFi Playback (Fallback or standard sources)
        
        # Force FLAC/Hi-Res path (MP3 option removed)
        cache_ext = "flac"
        mime_type = "audio/flac"
        
        # Check file cache
        if is_cached(isrc, cache_ext):
            cache_path = get_cache_path(isrc, cache_ext)
            logger.info(f"Serving from cache ({cache_ext}): {cache_path}")
            return FileResponse(
                cache_path,
                media_type=mime_type,
                headers={"Accept-Ranges": "bytes", "Cache-Control": "public, max-age=86400"}
            )
        
        # Check stream URL cache (for seek/range requests on the same track)
        cached = _stream_url_cache.get(isrc)
        if cached:
            cached_url, cached_meta, cached_time = cached
            if time.time() - cached_time < STREAM_CACHE_TTL:
                logger.info(f"Stream URL cache HIT for {isrc} — skipping API chain")
                target_stream_url = cached_url
                metadata = cached_meta
            else:
                # Expired
                del _stream_url_cache[isrc]
                cached = None
        
        if not cached:
            # 4. Full fetch_flac pipeline (only on first play, not on seeks)
            result = await audio_service.fetch_flac(isrc, q or "", hires=hires, hires_quality=hires_quality, source=source)
            
            if not result:
                raise HTTPException(status_code=404, detail="Could not fetch audio")
            
            if isinstance(result[0], str):
                # It's a URL — cache it for future seek requests
                target_stream_url = result[0]
                metadata = result[1]
                _stream_url_cache[isrc] = (target_stream_url, metadata, time.time())
                logger.info(f"Stream URL cached for {isrc} (TTL={STREAM_CACHE_TTL}s) - is_hi_res={metadata.get('is_hi_res')}")
            else:
                # It's bytes! Serve directly (no caching needed).
                flac_data, metadata = result
                
                headers = {
                    "Accept-Ranges": "bytes",
                    "Content-Length": str(len(flac_data)),
                    "Cache-Control": "public, max-age=86400",
                    "Access-Control-Expose-Headers": "X-Audio-Quality, X-Audio-Format, Content-Type, Content-Length",
                    "X-Audio-Format": "FLAC"
                }
                
                if metadata and metadata.get("is_hi_res"):
                    headers["X-Audio-Quality"] = "Hi-Res"
                    
                return Response(
                    content=flac_data,
                    media_type="audio/flac",
                    headers=headers
                )
        
        # 5. Proxy the resolved stream URL (handles both cached and freshly-resolved URLs)
        logger.info(f"Proxying stream: {target_stream_url[:60]}...")
        
        req_headers = {}
        if request.headers.get("Range"):
            req_headers["Range"] = request.headers.get("Range")
            logger.info(f"Forwarding Range header: {req_headers['Range']}")

        if request.method == "HEAD":
            head_headers = {
                "Accept-Ranges": "bytes",
                "Cache-Control": "public, max-age=3600",
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Expose-Headers": "X-Audio-Quality, X-Audio-Format, Content-Type, Content-Length",
                "Content-Type": "audio/flac",
                "X-Audio-Format": "FLAC"
            }
            if metadata and metadata.get("is_hi_res"):
                head_headers["X-Audio-Quality"] = "Hi-Res"
            else:
                # Explicitly remove it or set it to standard so browser sees it change
                head_headers["X-Audio-Quality"] = "Standard"
                
            return Response(status_code=200, headers=head_headers)

        stream_timeout = httpx.Timeout(connect=10.0, read=300.0, write=10.0, pool=10.0)
        client = httpx.AsyncClient(timeout=stream_timeout, follow_redirects=True)
        try:
            upstream_req = client.build_request("GET", target_stream_url, headers=req_headers)
            upstream_resp = await client.send(upstream_req, stream=True)
            
            # Build response headers
            resp_headers = {
                "Accept-Ranges": "bytes",
                "Cache-Control": "public, max-age=3600",
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Expose-Headers": "X-Audio-Quality, X-Audio-Format, Content-Type, Content-Length",
                "X-Accel-Buffering": "no"
            }
            
            # Forward important headers from upstream
            for key in ["Content-Range", "Content-Length", "Content-Type"]:
                if upstream_resp.headers.get(key):
                    resp_headers[key] = upstream_resp.headers[key]
            
            resp_headers["X-Audio-Format"] = "FLAC"
            if metadata and metadata.get("is_hi_res"):
                resp_headers["X-Audio-Quality"] = "Hi-Res"
            else:
                resp_headers["X-Audio-Quality"] = "Standard"

            # Iterator that closes client when done
            async def response_iterator():
                try:
                    async for chunk in upstream_resp.aiter_bytes(chunk_size=65536):
                        yield chunk
                except Exception as e:
                    logger.error(f"Stream iteration error: {e}")
                finally:
                    await upstream_resp.aclose()
                    await client.aclose()
            
            return StreamingResponse(
                response_iterator(),
                status_code=upstream_resp.status_code,  # 200 or 206
                media_type=upstream_resp.headers.get("Content-Type", "audio/flac"), 
                headers=resp_headers
            )
        except Exception as e:
            await client.aclose()
            raise
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Stream error for {isrc}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/download/{isrc}")
async def download_audio(
    isrc: str,
    q: Optional[str] = Query(None, description="Search query hint"),
    format: str = Query("mp3", description="Audio format: mp3, flac, aiff, wav, alac"),
    filename: Optional[str] = Query(None, description="Filename"),
    hires: bool = Query(False, description="Enable Hi-Res mode"),
    hires_quality: str = Query("6", description="Hi-Res quality: 6=96kHz/24bit, 5=192kHz/24bit")
):
    """Download audio in specified format."""
    try:
        logger.info(f"Download request for {isrc} in {format} (hires={hires}, quality={hires_quality})")
        
        result = await audio_service.get_download_audio(isrc, q or "", format, hires=hires, hires_quality=hires_quality)
        
        if not result:
            raise HTTPException(status_code=404, detail="Could not fetch audio for download")
        
        data, ext, mime = result
        download_name = filename if filename else f"{isrc}{ext}"
        if not download_name.endswith(ext):
            download_name += ext
            
        return Response(
            content=data,
            media_type=mime,
            headers={
                "Content-Disposition": f'attachment; filename="{download_name}"',
                "Content-Length": str(len(data))
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Download error for {isrc}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ========== DJ MODE ENDPOINTS ==========

class TrackForFeatures(BaseModel):
    id: str
    isrc: Optional[str] = None
    name: Optional[str] = None
    artists: Optional[str] = None


class AudioFeaturesBatchRequest(BaseModel):
    tracks: List[TrackForFeatures]


class TrackForSetlist(BaseModel):
    id: str
    name: str
    artists: str
    bpm: int
    camelot: str
    energy: float


class SetlistRequest(BaseModel):
    tracks: List[TrackForSetlist]
    style: str = "progressive"  # progressive, peak-time, chill, journey


@app.get("/api/audio-features/{track_id}")
async def get_audio_features(
    track_id: str,
    isrc: Optional[str] = Query(None),
    name: Optional[str] = Query(None),
    artist: Optional[str] = Query(None)
):
    """Get audio features (BPM, key, energy) for a track."""
    try:
        features = await spotify_service.get_audio_features(track_id, isrc, name, artist)
        if not features:
            raise HTTPException(status_code=404, detail="Audio features not found")
        return features
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Audio features error for {track_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/audio-features/batch")
async def get_audio_features_batch(request: AudioFeaturesBatchRequest):
    """Get audio features for multiple tracks."""
    try:
        if not request.tracks:
            return {"features": []}
        
        # Process each track, handling Deezer tracks with ISRC/name lookup
        features = []
        for track in request.tracks:
            feat = await spotify_service.get_audio_features(
                track.id, 
                track.isrc, 
                track.name, 
                track.artists
            )
            
            # Fallback to AI estimation if Spotify fails
            if not feat and track.name and track.artists:
                feat = await dj_service.get_audio_features_ai(track.name, track.artists)
                if feat:
                    feat['track_id'] = track.id  # Match requested ID for frontend cache
            
            features.append(feat)
        
        return {"features": features}
    except Exception as e:
        logger.error(f"Batch audio features error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.error(f"Batch audio features error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/dj/generate-setlist")
async def generate_setlist(request: SetlistRequest):
    """Generate AI-optimized DJ setlist ordering."""
    try:
        tracks = [t.model_dump() for t in request.tracks]
        result = await dj_service.generate_setlist(tracks, request.style)
        return result
    except Exception as e:
        logger.error(f"Setlist generation error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class MoodSearchRequest(BaseModel):
    query: str


@app.post("/api/search/mood")
async def search_by_mood(request: MoodSearchRequest):
    """Interpret a natural language mood query using AI and return search terms."""
    try:
        result = await dj_service.interpret_mood_query(request.query)
        if not result:
            # Fallback: just return the query as a search term
            return {
                "search_terms": [request.query],
                "moods": [],
                "bpm_range": None,
                "energy": "medium",
                "description": f"Searching for: {request.query}"
            }
        return result
    except Exception as e:
        logger.error(f"Mood search error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class SeedTrack(BaseModel):
    name: str
    artists: str
    bpm: Optional[int] = None
    camelot: Optional[str] = None


class QueueTrack(BaseModel):
    name: str
    artists: str


class AIRadioRequest(BaseModel):
    seed_track: Optional[SeedTrack] = None
    mood: Optional[str] = None
    current_queue: Optional[List[QueueTrack]] = None
    count: int = 5


@app.post("/api/ai-radio/generate")
async def generate_ai_radio_recommendations(request: AIRadioRequest):
    """Generate AI Radio recommendations based on seed track or mood."""
    try:
        seed = request.seed_track.model_dump() if request.seed_track else None
        queue = [t.model_dump() for t in request.current_queue] if request.current_queue else []
        
        result = await ai_radio_service.generate_recommendations(
            seed_track=seed,
            mood=request.mood,
            current_queue=queue,
            count=request.count
        )
        return result
    except Exception as e:
        logger.error(f"AI Radio error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== AI ASSISTANT ENDPOINTS ====================

class GeneratePlaylistRequest(BaseModel):
    description: str
    duration_mins: int = 60

@app.post("/api/ai/generate-playlist")
async def ai_generate_playlist(request: GeneratePlaylistRequest):
    """Generate a playlist from a natural language description."""
    try:
        result = await ai_radio_service.generate_playlist(
            description=request.description,
            duration_mins=request.duration_mins
        )
        return result
    except Exception as e:
        logger.error(f"Playlist generation error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Global progress store
# Format: { "download_id": { "current": 0, "total": 0, "status": "processing" } }
download_progress = {}

class BatchDownloadRequest(BaseModel):
    tracks: List[str]  # List of ISRCs or IDs
    names: List[str]   # List of track names for filenames
    artists: List[str] # List of artist names
    album_name: Optional[str] = None
    zip_name: Optional[str] = None
    format: str = "mp3"
    part: int = 1          # Part number for multi-part downloads
    total_parts: int = 1   # Total number of parts
    download_id: Optional[str] = None # Unique ID for progress tracking
    # Optional metadata for embedding (from frontend)
    album_art_urls: Optional[List[str]] = None  # Cover art URLs per track
    release_year: Optional[str] = None  # Album release year
    is_playlist: bool = False


@app.get("/api/progress/{download_id}")
async def get_progress(download_id: str):
    """Get status of a background download"""
    return download_progress.get(download_id, {"current": 0, "total": 0, "status": "unknown"})


@app.post("/api/download-batch")
async def download_batch(request: BatchDownloadRequest):
    """Download multiple tracks as a ZIP file with parallel processing."""
    try:
        final_name = request.zip_name or request.album_name or "download"
        logger.info(f"Batch download request: {len(request.tracks)} tracks from {final_name}")
        
        # In-memory ZIP buffer
        zip_buffer = io.BytesIO()
        
        # Initialize progress tracking
        if request.download_id:
            download_progress[request.download_id] = {
                "current": 0, 
                "total": len(request.tracks),
                "status": "processing"
            }
        
        # Concurrency control (3 concurrent downloads)
        semaphore = asyncio.Semaphore(3)
        zip_lock = asyncio.Lock()
        used_names = set()
        
        async def process_track(i: int, isrc: str):
            async with semaphore:
                try:
                    logger.info(f"Starting track {i+1}/{len(request.tracks)}: {request.names[i]}")
                    
                    query = f"{request.names[i]} {request.artists[i]}"
                    
                    # Build metadata
                    provided_metadata = {
                        "title": request.names[i],
                        "artists": request.artists[i],
                        "album": request.album_name,
                        "year": request.release_year or "",
                        "album_art_url": request.album_art_urls[i] if request.album_art_urls and i < len(request.album_art_urls) else None,
                        "total_tracks": len(request.tracks) * request.total_parts if request.album_name else None
                    }
                    
                    # Download
                    result = await audio_service.get_download_audio(
                        isrc, 
                        query, 
                        request.format,
                        track_number=i+1,
                        provided_metadata=provided_metadata
                    )
                    
                    if result:
                        data, ext, _ = result
                        
                        # Calculate filename
                        safe_name = f"{request.artists[i]} - {request.names[i]}".replace("/", "_").replace("\\", "_").replace(":", "_").replace("*", "").replace("?", "").replace('"', "").replace("<", "").replace(">", "").replace("|", "")
                        filename = f"{safe_name}{ext}"
                        
                        # Write to ZIP (atomic operation via lock)
                        async with zip_lock:
                            # Handle duplicates
                            count = 1
                            base_filename = filename
                            while filename in used_names:
                                filename = f"{safe_name} ({count}){ext}"
                                count += 1
                            used_names.add(filename)
                            
                            zip_file.writestr(filename, data)
                            logger.info(f"Added to ZIP: {filename}")
                            
                            # Update progress
                            if request.download_id:
                                download_progress[request.download_id]["current"] += 1
                                
                except Exception as e:
                    logger.error(f"Failed to download track {isrc}: {e}")
                    # Don't raise, just continue (partial success)
        
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
            # Create tasks
            tasks = [process_track(i, isrc) for i, isrc in enumerate(request.tracks)]
            await asyncio.gather(*tasks)

        # Cleanup progress
        if request.download_id and request.download_id in download_progress:
            del download_progress[request.download_id]
        
        zip_buffer.seek(0)
        final_name = request.zip_name or request.album_name or "download"
        safe_album = final_name.replace("/", "_").replace("\\", "_").replace(":", "_")
        
        # Name ZIP with part number
        if request.total_parts > 1:
            filename = f"{safe_album} (Part {request.part} of {request.total_parts}).zip"
        else:
            filename = f"{safe_album}.zip"
        
        logger.info(f"ZIP complete: {filename} ({len(zip_buffer.getvalue())} bytes)")
        
        return Response(
            content=zip_buffer.getvalue(),
            media_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"'
            }
        )
        
    except Exception as e:
        logger.error(f"Batch download error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ========== GOOGLE DRIVE ==========

class UploadToDriveRequest(BaseModel):
    isrc: str
    access_token: str
    format: str = "aiff"
    folder_id: Optional[str] = None
    filename: Optional[str] = None
    q: Optional[str] = None


@app.post("/api/drive/upload")
async def upload_to_drive(request: UploadToDriveRequest):
    """Download audio, transcode, and upload to Google Drive."""
    try:
        logger.info(f"Drive upload request for {request.isrc} in {request.format}")
        
        # 1. Get Audio Data (reuse existing logic)
        result = await audio_service.get_download_audio(request.isrc, request.q or "", request.format)
        
        if not result:
            raise HTTPException(status_code=404, detail="Could not fetch audio")
        
        data, ext, mime = result
        filename = request.filename if request.filename else f"{request.isrc}{ext}"
        if not filename.endswith(ext):
            filename += ext
            
        # 2. Upload to Drive (Multipart upload for metadata + media)
        metadata = {
            'name': filename,
            'mimeType': mime
        }
        if request.folder_id:
            metadata['parents'] = [request.folder_id]
        
        import httpx
        import json
        
        async with httpx.AsyncClient() as client:
            # Multipart upload
            files_param = {
                'metadata': (None, json.dumps(metadata), 'application/json; charset=UTF-8'),
                'file': (filename, data, mime)
            }
            
            drive_response = await client.post(
                'https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart',
                headers={'Authorization': f'Bearer {request.access_token}'},
                files=files_param,
                timeout=300.0 # 5 minutes for upload
            )
            
            if drive_response.status_code != 200:
                logger.error(f"Drive upload failed: {drive_response.text}")
                raise HTTPException(status_code=500, detail=f"Drive upload failed: {drive_response.text}")
                
            file_data = drive_response.json()
            return {"file_id": file_data.get('id'), "name": file_data.get('name')}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Drive upload error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ========== STATIC FILES ==========

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC_DIR = os.path.join(BASE_DIR, "static")

if os.path.exists(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
async def index():
    """Serve the main page."""
    index_path = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "Freedify Streaming Server", "docs": "/docs"}


@app.get("/manifest.json")
async def manifest():
    """Serve PWA manifest."""
    manifest_path = os.path.join(STATIC_DIR, "manifest.json")
    if os.path.exists(manifest_path):
        return FileResponse(manifest_path, media_type="application/json")
    raise HTTPException(status_code=404)


@app.get("/sw.js")
async def service_worker():
    """Serve service worker."""
    sw_path = os.path.join(STATIC_DIR, "sw.js")
    if os.path.exists(sw_path):
        return FileResponse(sw_path, media_type="application/javascript")
    raise HTTPException(status_code=404)


# ==================== LAST.FM ENDPOINTS ====================

class LastFMScrobbleRequest(BaseModel):
    session_key: str
    artist: str
    track: str
    album: str = ""
    timestamp: Optional[int] = None

class LastFMNowPlayingRequest(BaseModel):
    session_key: str
    artist: str
    track: str
    album: str = ""

@app.get("/api/lastfm/auth-url")
async def lastfm_auth_url(callback: str = Query(..., description="Callback URL after authorization")):
    """Get Last.fm authorization URL for the user to click."""
    url = lastfm_service.get_auth_url(callback)
    return {"url": url}

@app.post("/api/lastfm/callback")
async def lastfm_callback(data: dict):
    """Exchange authorization token for session key."""
    token = data.get("token")
    if not token:
        raise HTTPException(status_code=400, detail="Token required")
    result = await lastfm_service.get_session(token)
    if not result:
        raise HTTPException(status_code=401, detail="Last.fm authorization failed")
    return result

@app.post("/api/lastfm/scrobble")
async def lastfm_scrobble(request: LastFMScrobbleRequest):
    """Scrobble a track to Last.fm."""
    success = await lastfm_service.scrobble(
        request.session_key, request.artist, request.track,
        request.album, request.timestamp
    )
    return {"success": success}

@app.post("/api/lastfm/nowplaying")
async def lastfm_nowplaying(request: LastFMNowPlayingRequest):
    """Update Now Playing on Last.fm."""
    success = await lastfm_service.update_now_playing(
        request.session_key, request.artist, request.track, request.album
    )
    return {"success": success}

@app.get("/lastfm-callback")
async def lastfm_callback_page():
    """Serve the Last.fm callback page that captures the token."""
    html = """
    <!DOCTYPE html>
    <html><head><title>Last.fm Authorization</title>
    <style>body{background:#121212;color:#fff;font-family:Inter,sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;margin:0}</style>
    </head><body>
    <div style="text-align:center">
        <h2>✅ Last.fm Connected!</h2>
        <p>This window will close automatically...</p>
    </div>
    <script>
        const params = new URLSearchParams(window.location.search);
        const token = params.get('token');
        if (token) {
            // Store token for the main window to pick up
            localStorage.setItem('lastfm_pending_token', token);
            
            // Try postMessage to opener
            if (window.opener) {
                window.opener.postMessage({type: 'lastfm-auth', token: token}, '*');
            }
            
            // Try BroadcastChannel (works even without window.opener)
            try {
                const bc = new BroadcastChannel('freedify_lastfm');
                bc.postMessage({type: 'lastfm-auth', token: token});
                bc.close();
            } catch(e) {}
            
            // Always close — never redirect to /
            setTimeout(() => window.close(), 1500);
        }
    </script>
    </body></html>
    """
    return Response(content=html, media_type="text/html")

@app.get("/api/lastfm/artist/{artist}/similar")
async def lastfm_similar_artists(artist: str):
    """Get similar artists from Last.fm."""
    artists = await lastfm_service.get_similar_artists(artist)
    return {"artists": artists or []}


# ==================== ARTIST BIO ENDPOINT ====================

@app.get("/api/artist/{name}/bio")
async def get_artist_bio(name: str):
    """Get artist biography, social links, and image."""
    result = await artist_service.get_artist_bio(name)
    if not result:
        raise HTTPException(status_code=404, detail="Artist not found")
    return result


# ==================== LISTENBRAINZ ENDPOINTS ====================

@app.post("/api/listenbrainz/now-playing")
async def listenbrainz_now_playing(track: dict):
    """Submit 'now playing' status to ListenBrainz."""
    success = await listenbrainz_service.submit_now_playing(track)
    return {"success": success}


@app.post("/api/listenbrainz/scrobble")
async def listenbrainz_scrobble(track: dict, listened_at: Optional[int] = None):
    """Submit a completed listen to ListenBrainz."""
    success = await listenbrainz_service.submit_listen(track, listened_at)
    return {"success": success}


@app.get("/api/listenbrainz/validate")
async def listenbrainz_validate():
    """Validate ListenBrainz token and return username."""
    username = await listenbrainz_service.validate_token()
    return {"valid": username is not None, "username": username}


@app.get("/api/listenbrainz/recommendations/{username}")
async def listenbrainz_recommendations(username: str, count: int = 25):
    """Get personalized recommendations for a user."""
    recommendations = await listenbrainz_service.get_recommendations(username, count)
    return {"recommendations": recommendations, "count": len(recommendations)}


@app.get("/api/listenbrainz/listens/{username}")
async def listenbrainz_listens(username: str, count: int = 25):
    """Get recent listens for a user."""
    listens = await listenbrainz_service.get_user_listens(username, count)
    return {"listens": listens, "count": len(listens)}


@app.post("/api/listenbrainz/set-token")
async def listenbrainz_set_token(token: str):
    """Set ListenBrainz user token (from settings UI)."""
    listenbrainz_service.set_token(token)
    username = await listenbrainz_service.validate_token()
    return {"valid": username is not None, "username": username}

@app.get("/api/listenbrainz/playlists/{username}")
async def listenbrainz_playlists(username: str, count: int = 25):
    """Get user's ListenBrainz playlists (includes Weekly Exploration)."""
    playlists = await listenbrainz_service.get_user_playlists(username, count)
    return {"playlists": playlists, "count": len(playlists)}

@app.get("/api/listenbrainz/playlist/{playlist_id}")
async def listenbrainz_playlist_tracks(playlist_id: str):
    """Get tracks from a ListenBrainz playlist."""
    playlist = await listenbrainz_service.get_playlist_tracks(playlist_id)
    if not playlist:
        raise HTTPException(status_code=404, detail="Playlist not found")
    return playlist

@app.get("/api/listenbrainz/stats/{username}")
async def listenbrainz_stats(username: str):
    """Get user's ListenBrainz listening statistics."""
    stats = await listenbrainz_service.get_user_stats(username)
    return stats


# ========== GENIUS LYRICS ==========

@app.get("/api/lyrics")
async def get_lyrics(artist: str, title: str):
    """Get lyrics and song info from Genius."""
    result = await genius_service.get_lyrics_and_info(artist, title)
    return result


@app.get("/api/proxy_image")
async def proxy_image(url: str):
    """Proxy image requests to avoid 429 errors/CORS issues."""
    if not url:
        raise HTTPException(status_code=400, detail="No URL provided")
    
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, follow_redirects=True)
            if resp.status_code != 200:
                raise HTTPException(status_code=resp.status_code, detail="Failed to fetch image")
            
            return Response(
                content=resp.content,
                media_type=resp.headers.get("Content-Type", "image/jpeg"),
                headers={
                    "Cache-Control": "public, max-age=86400"
                }
            )
    except Exception as e:
        logger.error(f"Image proxy error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ========== CONCERT ALERTS ENDPOINTS ==========

@app.get("/api/concerts/search")
async def search_concerts(
    artist: str = Query(..., description="Artist name to search"),
    city: Optional[str] = Query(None, description="City to filter events")
):
    """
    Search for upcoming concerts by artist name.
    Uses Ticketmaster with SeatGeek fallback.
    """
    try:
        logger.info(f"Concert search for: {artist} (city: {city})")
        events = await concert_service.search_events(artist, city, limit=20)
        return {"events": events, "artist": artist, "city": city}
    except Exception as e:
        logger.error(f"Concert search error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/concerts/for-artists")
async def get_concerts_for_artists(
    artists: str = Query(..., description="Comma-separated list of artist names"),
    cities: Optional[str] = Query(None, description="Comma-separated list of cities")
):
    """
    Get upcoming concerts for multiple artists.
    Useful for showing concerts from recently listened artists.
    """
    try:
        artist_list = [a.strip() for a in artists.split(",") if a.strip()]
        city_list = [c.strip() for c in cities.split(",")] if cities else None
        
        if not artist_list:
            return {"events": [], "artists": [], "cities": city_list}
        
        logger.info(f"Concert search for {len(artist_list)} artists, cities: {city_list}")
        events = await concert_service.get_events_for_artists(artist_list, city_list)
        
        return {"events": events, "artists": artist_list, "cities": city_list}
    except Exception as e:
        logger.error(f"Concerts for artists error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ========== GOODREADS ENDPOINTS ==========

@app.get("/api/goodreads/book")
async def get_goodreads_book_info(
    title: str = Query(..., description="Book title"),
    author: str = Query("", description="Book author (optional)")
):
    """Search Goodreads for a book and return rating, reviews, and description."""
    try:
        from app.goodreads_service import search_book
        result = await search_book(title, author)
        if not result:
            return {"found": False, "message": "No Goodreads match found"}
        return {"found": True, **result}
    except Exception as e:
        logger.error(f"Goodreads lookup error: {e}")
        return {"found": False, "message": str(e)}

# ========== AUDIOBOOKS & PREMIUMIZE ENDPOINTS ==========

@app.get("/api/audiobooks/details")
async def get_audiobook_details_endpoint(id: str = Query(..., description="Audiobook slug")):
    """Get details and magnet link for an audiobook from AudiobookBay."""
    try:
        details = await get_audiobook_details(id)
        return details
    except Exception as e:
        logger.error(f"Audiobook details error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/premiumize/transfer")
async def start_premiumize_transfer(request: Request):
    """Start a Premiumize transfer using a magnet link."""
    try:
        data = await request.json()
        magnet_link = data.get("magnet_link")
        if not magnet_link:
            raise HTTPException(status_code=400, detail="magnet_link is required")
        result = await create_transfer(magnet_link)
        return result
    except Exception as e:
        logger.error(f"Premiumize transfer error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/premiumize/transfer/{transfer_id}")
async def get_premiumize_transfer_status(transfer_id: str):
    """Check status of a specific Premiumize transfer."""
    try:
        status = await check_transfer_status(transfer_id)
        return {"transfer": status}
    except Exception as e:
        logger.error(f"Premiumize status error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/premiumize/folder/{folder_id}")
async def get_premiumize_folder_contents(folder_id: str):
    """List audio files in a Premiumize folder."""
    try:
        contents = await list_folder_contents(folder_id)
        return contents
    except Exception as e:
        logger.error(f"Premiumize folder error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/premiumize/search")
async def search_premiumize_files(q: str = Query(..., description="Query to search your files")):
    """Search for files already downloaded to Premiumize."""
    try:
        results = await search_my_files(q)
        return {"results": results}
    except Exception as e:
        logger.error(f"Premiumize search error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/premiumize/delete")
async def delete_premiumize_item(request: Request):
    """Delete a transfer, folder, or file from Premiumize."""
    try:
        data = await request.json()
        item_id = data.get("id")
        is_transfer = data.get("is_transfer", False)
        if not item_id:
            raise HTTPException(status_code=400, detail="ID is required")
        result = await delete_item(item_id, is_transfer)
        return {"status": "success", "result": result}
    except Exception as e:
        logger.error(f"Premiumize delete error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 8000)),
        reload=True
    )
