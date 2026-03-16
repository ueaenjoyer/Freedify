"""
Spotify service for Freedify.
Provides playlist/album fetching and URL parsing.
ONLY used when a Spotify URL is pasted - not for search (to avoid rate limits).
"""
import httpx
import re
from typing import Optional, Dict, List, Any, Tuple
import logging
from random import randrange

logger = logging.getLogger(__name__)


def get_random_user_agent():
    return f"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_{randrange(11, 15)}_{randrange(4, 9)}) AppleWebKit/{randrange(530, 537)}.{randrange(30, 37)} (KHTML, like Gecko) Chrome/{randrange(80, 105)}.0.{randrange(3000, 4500)}.{randrange(60, 125)} Safari/{randrange(530, 537)}.{randrange(30, 36)}"


class SpotifyService:
    """Service for fetching metadata from Spotify URLs (not for search)."""
    
    TOKEN_URL = "https://open.spotify.com/get_access_token?reason=transport&productType=web_player"
    AUTH_URL = "https://accounts.spotify.com/api/token"
    API_BASE = "https://api.spotify.com/v1"
    
    # Regex patterns for Spotify URLs
    URL_PATTERNS = {
        'track': re.compile(r'(?:spotify\.com/track/|spotify:track:)([a-zA-Z0-9]+)'),
        'album': re.compile(r'(?:spotify\.com/album/|spotify:album:)([a-zA-Z0-9]+)'),
        'playlist': re.compile(r'(?:spotify\.com/playlist/|spotify:playlist:)([a-zA-Z0-9]+)'),
        'artist': re.compile(r'(?:spotify\.com/artist/|spotify:artist:)([a-zA-Z0-9]+)'),
    }
    
    def __init__(self):
        import os
        import json
        self.access_token: Optional[str] = None
        self.user_access_token: Optional[str] = None
        self.user_token_expires: float = 0
        
        self.client_id = os.environ.get("SPOTIFY_CLIENT_ID")
        self.client_secret = os.environ.get("SPOTIFY_CLIENT_SECRET")
        self.sp_dc = os.environ.get("SPOTIFY_SP_DC")
        self.client = httpx.AsyncClient(timeout=30.0)
        
        # Load user token from local settings file if available
        self.settings_file = os.path.join(os.path.dirname(__file__), "..", "freedify_settings.json")
        self._load_settings()

    def _load_settings(self):
        import json
        import os
        if os.path.exists(self.settings_file):
            try:
                with open(self.settings_file, "r") as f:
                    data = json.load(f)
                    self.spotify_refresh_token = data.get("spotify_refresh_token")
            except:
                self.spotify_refresh_token = None
        else:
            self.spotify_refresh_token = None

    def _save_settings(self):
        import json
        try:
            data = {"spotify_refresh_token": self.spotify_refresh_token}
            with open(self.settings_file, "w") as f:
                json.dump(data, f)
        except Exception as e:
            logger.error(f"Failed to save settings: {e}")
    
    # ========== OAUTH METHODS ==========

    def get_oauth_url(self, redirect_uri: str) -> Optional[str]:
        """Generate Spotify OAuth URL for user login."""
        if not self.client_id:
            return None
        import urllib.parse
        scope = "playlist-read-private playlist-read-collaborative"
        params = {
            "client_id": self.client_id,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "scope": "playlist-read-private playlist-read-collaborative user-read-private",
            "show_dialog": "true"
        }
        return f"https://accounts.spotify.com/authorize?{urllib.parse.urlencode(params)}"

    async def exchange_oauth_code(self, code: str, redirect_uri: str) -> bool:
        """Exchange OAuth code for tokens and save refresh token."""
        if not self.client_id or not self.client_secret:
            return False
            
        import base64
        import time
        auth_str = f"{self.client_id}:{self.client_secret}"
        b64_auth = base64.b64encode(auth_str.encode()).decode()
        
        headers = {
            "Authorization": f"Basic {b64_auth}",
            "Content-Type": "application/x-www-form-urlencoded"
        }
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri
        }
        
        try:
            response = await self.client.post(self.AUTH_URL, headers=headers, data=data)
            if response.status_code == 200:
                token_data = response.json()
                self.user_access_token = token_data.get("access_token")
                self.user_token_expires = time.time() + token_data.get("expires_in", 3600) - 60
                
                refresh_token = token_data.get("refresh_token")
                if refresh_token:
                    self.spotify_refresh_token = refresh_token
                    self._save_settings()
                
                logger.info("Successfully exchanged Spotify OAuth code for user token")
                return True
            else:
                logger.error(f"OAuth code exchange failed: {response.text}")
                return False
        except Exception as e:
            logger.error(f"OAuth code exchange error: {e}")
            return False

    def has_user_token(self) -> bool:
        """Check if user has linked their Spotify account."""
        return self.spotify_refresh_token is not None

    def clear_user_token(self):
        """Disconnect user Spotify account."""
        self.spotify_refresh_token = None
        self.user_access_token = None
        self.user_token_expires = 0
        self._save_settings()

    async def _refresh_user_token(self) -> bool:
        """Refresh the user's OAuth access token."""
        if not self.spotify_refresh_token or not self.client_id or not self.client_secret:
            return False
            
        import base64
        import time
        auth_str = f"{self.client_id}:{self.client_secret}"
        b64_auth = base64.b64encode(auth_str.encode()).decode()
        
        headers = {
            "Authorization": f"Basic {b64_auth}",
            "Content-Type": "application/x-www-form-urlencoded"
        }
        data = {
            "grant_type": "refresh_token",
            "refresh_token": self.spotify_refresh_token
        }
        
        try:
            response = await self.client.post(self.AUTH_URL, headers=headers, data=data)
            if response.status_code == 200:
                token_data = response.json()
                self.user_access_token = token_data.get("access_token")
                self.user_token_expires = time.time() + token_data.get("expires_in", 3600) - 60
                
                # Sometimes a new refresh token is returned
                new_refresh = token_data.get("refresh_token")
                if new_refresh:
                    self.spotify_refresh_token = new_refresh
                    self._save_settings()
                    
                logger.info("Successfully refreshed Spotify user token")
                return True
            else:
                logger.error(f"Failed to refresh user token: {response.text}")
                # If refresh token is revoked/invalid, clear it
                if response.status_code in [400, 401]:
                    self.clear_user_token()
                return False
        except Exception as e:
            logger.error(f"User token refresh error: {e}")
            return False

    async def _get_access_token(self, force_client_credentials: bool = False) -> str:
        """Get access token (OAuth User > Client Creds > Cookie > Web Player > Embed)."""
        import time
        
        # 0. Try User OAuth Token First
        if self.spotify_refresh_token and not force_client_credentials:
            if not self.user_access_token or time.time() > self.user_token_expires:
                await self._refresh_user_token()
            if self.user_access_token and time.time() < self.user_token_expires:
                return self.user_access_token
                
        if self.access_token:
            return self.access_token
            
        # 1. Try Client Credentials Flow
        if self.client_id and self.client_secret:
            try:
                import base64
                auth_str = f"{self.client_id}:{self.client_secret}"
                b64_auth = base64.b64encode(auth_str.encode()).decode()
                
                headers = {
                    "Authorization": f"Basic {b64_auth}",
                    "Content-Type": "application/x-www-form-urlencoded"
                }
                data = {"grant_type": "client_credentials"}
                
                response = await self.client.post(self.AUTH_URL, headers=headers, data=data)
                if response.status_code == 200:
                    token_data = response.json()
                    self.access_token = token_data.get("access_token")
                    logger.info("Got Spotify token via Client Credentials")
                    return self.access_token
            except Exception as e:
                logger.error(f"Client Credentials auth failed: {e}")

        # 2. Try Cookie Auth (sp_dc) - Mimics logged-in Web Player
        cookies = None
        if self.sp_dc:
            cookies = {"sp_dc": self.sp_dc}
            logger.info("Using provided sp_dc cookie for authentication")

        # 3. Web Player Token (Anonymous or Authenticated via Cookie)
        headers = {
            "User-Agent": get_random_user_agent(),
            "Accept": "application/json",
            "Referer": "https://open.spotify.com/",
        }
        
        try:
            response = await self.client.get(self.TOKEN_URL, headers=headers, cookies=cookies)
            if response.status_code == 200:
                data = response.json()
                self.access_token = data.get("accessToken")
                if self.access_token:
                    logger.info(f"Got Spotify token via Web Player ({'Authenticated' if cookies else 'Anonymous'})")
                    return self.access_token
        except Exception as e:
            logger.warning(f"Web Player token fetch failed: {e}")
        
        # 4. Fallback: Embed Page token
        try:
            embed_url = "https://open.spotify.com/embed/track/4cOdK2wGLETKBW3PvgPWqT"
            response = await self.client.get(embed_url, headers={"User-Agent": get_random_user_agent()})
            if response.status_code == 200:
                token_match = re.search(r'"accessToken":"([^"]+)"', response.text)
                if token_match:
                    self.access_token = token_match.group(1)
                    logger.info("Got Spotify token via embed page")
                    return self.access_token
        except Exception as e:
            logger.warning(f"Embed token fetch failed: {e}")
        
        raise Exception("Failed to get Spotify access token")
    
    async def _get_web_player_token(self) -> Optional[str]:
        """Get an anonymous Web Player token (separate from self.access_token).
        
        Used as fallback when Client Credentials token is blocked on certain endpoints.
        """
        headers = {
            "User-Agent": get_random_user_agent(),
            "Accept": "application/json",
            "Referer": "https://open.spotify.com/",
        }
        
        # Try cookie-authenticated token first, then anonymous
        cookies = {"sp_dc": self.sp_dc} if self.sp_dc else None
        
        try:
            response = await self.client.get(self.TOKEN_URL, headers=headers, cookies=cookies)
            if response.status_code == 200:
                data = response.json()
                token = data.get("accessToken")
                if token:
                    logger.info(f"Got Web Player token for fallback ({'Authenticated' if cookies else 'Anonymous'})")
                    return token
        except Exception as e:
            logger.warning(f"Web Player fallback token fetch failed: {e}")
        
        # Try embed page token as last resort
        try:
            embed_url = "https://open.spotify.com/embed/track/4cOdK2wGLETKBW3PvgPWqT"
            response = await self.client.get(embed_url, headers={"User-Agent": get_random_user_agent()})
            if response.status_code == 200:
                token_match = re.search(r'"accessToken":"([^"]+)"', response.text)
                if token_match:
                    logger.info("Got embed page token for fallback")
                    return token_match.group(1)
        except Exception as e:
            logger.warning(f"Embed fallback token fetch failed: {e}")
        
        return None
    
    async def _api_request(self, endpoint: str, params: dict = None, force_client_credentials: bool = False) -> dict:
        """Make authenticated API request with rate limit handling."""
        import asyncio
        
        max_retries = 3
        retry_delay = 2
        
        for attempt in range(max_retries):
            token = await self._get_access_token(force_client_credentials=force_client_credentials)
            headers = {
                "Authorization": f"Bearer {token}",
                "User-Agent": get_random_user_agent(),
                "Accept": "application/json",
            }
            response = await self.client.get(f"{self.API_BASE}{endpoint}", headers=headers, params=params)
            
            if response.status_code in (401, 403):
                if attempt < max_retries - 1:
                    logger.warning(f"Got {response.status_code}, refreshing Spotify token (attempt {attempt + 1}/{max_retries})...")
                    if response.status_code == 403 and token == self.user_access_token and not force_client_credentials:
                        logger.warning("User token got 403 Forbidden. Forcing Client Credentials fallback for retry.")
                        force_client_credentials = True
                        continue
                        
                    if token == self.user_access_token:
                        # Clear user token to force refresh
                        self.user_access_token = None
                    else:
                        # Clear client token to force refresh
                        self.access_token = None
                    continue
                else:
                    # Final attempt failed — raise so caller can try embed fallback
                    response.raise_for_status()
            
            if response.status_code == 429:
                retry_after = min(int(response.headers.get("Retry-After", retry_delay)), 10)
                logger.warning(f"Rate limited (429). Waiting {retry_after}s before retry {attempt + 1}/{max_retries}")
                await asyncio.sleep(retry_after)
                retry_delay *= 2
                continue
            
            response.raise_for_status()
            return response.json()
        
        response.raise_for_status()
        return response.json()
    
    def parse_spotify_url(self, url: str) -> Optional[Tuple[str, str]]:
        """Parse Spotify URL and return (type, id) or None."""
        for url_type, pattern in self.URL_PATTERNS.items():
            match = pattern.search(url)
            if match:
                return (url_type, match.group(1))
        return None
    
    def is_spotify_url(self, url: str) -> bool:
        """Check if a URL is a Spotify URL."""
        return 'spotify.com/' in url or 'spotify:' in url
    
    # ========== TRACK METHODS ==========
    
    async def get_track_by_id(self, track_id: str) -> Optional[Dict[str, Any]]:
        """Get a single track by ID."""
        try:
            data = await self._api_request(f"/tracks/{track_id}", {"market": "US"})
            return self._format_track(data)
        except:
            return None
    
    def _format_track(self, item: dict) -> dict:
        """Format track data for frontend."""
        return {
            "id": item["id"],
            "type": "track",
            "name": item["name"],
            "artists": ", ".join(a["name"] for a in item["artists"]),
            "artist_names": [a["name"] for a in item["artists"]],
            "album": item["album"]["name"],
            "album_id": item["album"]["id"],
            "album_art": self._get_best_image(item["album"]["images"]),
            "duration_ms": item["duration_ms"],
            "duration": self._format_duration(item["duration_ms"]),
            "isrc": item.get("external_ids", {}).get("isrc"),
            "source": "spotify",
        }
    
    # ========== ALBUM METHODS ==========
    
    async def get_album(self, album_id: str) -> Optional[Dict[str, Any]]:
        """Get album with all tracks. Falls back to embed scraping on 403."""
        try:
            data = await self._api_request(f"/albums/{album_id}", {"market": "US"})
            album = self._format_album(data)
            
            tracks = []
            for item in data.get("tracks", {}).get("items", []):
                track = {
                    "id": item["id"],
                    "type": "track",
                    "name": item["name"],
                    "artists": ", ".join(a["name"] for a in item["artists"]),
                    "artist_names": [a["name"] for a in item["artists"]],
                    "album": data["name"],
                    "album_id": album_id,
                    "album_art": album["album_art"],
                    "duration_ms": item["duration_ms"],
                    "duration": self._format_duration(item["duration_ms"]),
                    "isrc": None,
                    "source": "spotify",
                }
                tracks.append(track)
            
            album["tracks"] = tracks
            return album
        except Exception as e:
            if "403" in str(e):
                logger.warning(f"Spotify API returned 403 for album {album_id}, trying embed scrape...")
                return await self._scrape_embed_album(album_id)
            logger.error(f"Error fetching Spotify album {album_id}: {e}")
            return None
    
    async def _scrape_embed_album(self, album_id: str) -> Optional[Dict[str, Any]]:
        """Scrape album data from Spotify embed page as fallback when API returns 403."""
        import json
        try:
            embed_url = f"https://open.spotify.com/embed/album/{album_id}"
            headers = {"User-Agent": get_random_user_agent()}
            response = await self.client.get(embed_url, headers=headers)
            if response.status_code != 200:
                logger.error(f"Embed page returned {response.status_code} for album {album_id}")
                return None
            
            # Extract __NEXT_DATA__ JSON from the HTML
            match = re.search(r'<script\s+id="__NEXT_DATA__"\s+type="application/json">([^<]+)</script>', response.text)
            if not match:
                logger.error(f"Could not find __NEXT_DATA__ in embed page for album {album_id}")
                return None
            
            next_data = json.loads(match.group(1))
            entity = next_data.get("props", {}).get("pageProps", {}).get("state", {}).get("data", {}).get("entity", {})
            
            if not entity:
                logger.error(f"No entity found in embed data for album {album_id}")
                return None
            
            # Extract cover art
            cover_art = None
            cover_data = entity.get("coverArt", {})
            if cover_data:
                sources = cover_data.get("sources", [])
                if sources:
                    cover_art = sorted(sources, key=lambda x: x.get("width", 0), reverse=True)[0].get("url")
            
            # Build album object
            album = {
                "id": album_id,
                "type": "album",
                "name": entity.get("name", "Unknown Album"),
                "artists": entity.get("subtitle", "Unknown Artist"),
                "album_art": cover_art,
                "release_date": "",
                "total_tracks": len(entity.get("trackList", [])),
                "source": "spotify",
            }
            
            tracks = []
            for item in entity.get("trackList", []):
                uri = item.get("uri", "")
                track_id = uri.split(":")[-1] if "spotify:track:" in uri else None
                if not track_id:
                    continue
                
                tracks.append({
                    "id": track_id,
                    "type": "track",
                    "name": item.get("title", "Unknown"),
                    "artists": item.get("subtitle", "Unknown Artist"),
                    "artist_names": [a.strip() for a in item.get("subtitle", "Unknown Artist").split(",")],
                    "album": album["name"],
                    "album_id": album_id,
                    "album_art": cover_art,
                    "duration_ms": item.get("duration", 0),
                    "duration": self._format_duration(item.get("duration", 0)),
                    "isrc": None,
                    "source": "spotify",
                })
            
            album["tracks"] = tracks
            logger.info(f"Scraped {len(tracks)} tracks from embed page for album '{album['name']}'")
            
            # Enrich tracks with real album art from Deezer
            await self._enrich_tracks_with_deezer_art(tracks)
            
            return album
        except Exception as e:
            logger.error(f"Embed scrape failed for album {album_id}: {e}")
            return None
    
    async def _enrich_tracks_with_deezer_art(self, tracks: List[Dict]) -> None:
        """Enrich scraped tracks with real album art from Deezer search API (no rate limits)."""
        import asyncio
        
        async def fetch_art(track):
            try:
                query = f"{track['artists']} {track['name']}".replace('&', '')
                response = await self.client.get(
                    "https://api.deezer.com/search",
                    params={"q": query, "limit": 1},
                    headers={"User-Agent": get_random_user_agent()}
                )
                if response.status_code == 200:
                    data = response.json()
                    results = data.get("data", [])
                    if results:
                        album_data = results[0].get("album", {})
                        cover = album_data.get("cover_big") or album_data.get("cover_medium") or album_data.get("cover")
                        if cover:
                            track["album_art"] = cover
                            track["album"] = album_data.get("title", track.get("album", ""))
            except Exception as e:
                logger.debug(f"Deezer art lookup failed for '{track.get('name')}': {e}")
        
        # Run all lookups concurrently (Deezer has no rate limits)
        tasks = [fetch_art(t) for t in tracks]
        await asyncio.gather(*tasks)
        
        enriched = sum(1 for t in tracks if t.get("album_art") and "deezer" in t["album_art"])
        logger.info(f"Enriched {enriched}/{len(tracks)} tracks with Deezer album art")
    
    def _format_album(self, item: dict) -> dict:
        return {
            "id": item["id"],
            "type": "album",
            "name": item["name"],
            "artists": ", ".join(a["name"] for a in item.get("artists", [])),
            "album_art": self._get_best_image(item.get("images", [])),
            "release_date": item.get("release_date", ""),
            "total_tracks": item.get("total_tracks", 0),
            "source": "spotify",
        }
    
    # ========== PLAYLIST METHODS ==========
    
    async def get_playlist(self, playlist_id: str) -> Optional[Dict[str, Any]]:
        """Get playlist with all tracks. Uses API for metadata, embed scraping for tracks."""
        import json
        
        playlist = None
        tracks = []
        
        try:
            # Step 1: Get playlist metadata from API (works with Client Credentials)
            try:
                data = await self._api_request(f"/playlists/{playlist_id}")
                playlist = {
                    "id": data["id"],
                    "type": "playlist",
                    "name": data["name"],
                    "description": data.get("description", ""),
                    "album_art": self._get_best_image(data.get("images", [])),
                    "owner": data.get("owner", {}).get("display_name", ""),
                    "total_tracks": data.get("tracks", {}).get("total", 0),
                    "source": "spotify",
                }
                
                # Check if tracks are included inline
                tracks_data = data.get("tracks", {})
                items = tracks_data.get("items", [])
                if items:
                    for item in items:
                        track_data = item.get("track")
                        if track_data and track_data.get("id"):
                            tracks.append(self._format_track(track_data))
                    
                    if len(tracks) >= playlist["total_tracks"]:
                        logger.info(f"Loaded all {len(tracks)} tracks inline from playlist '{playlist['name']}'")
                        playlist["tracks"] = tracks
                        return playlist
                    # Have some inline tracks but not all
                    logger.info(f"Got {len(tracks)} inline tracks, need {playlist['total_tracks']} total")
                else:
                    logger.info(f"Got 0 inline tracks, need {playlist['total_tracks']} total. Proceeding to pagination.")
            except Exception as e:
                logger.warning(f"API metadata fetch encountered an issue (mostly likely missing inline tracks): {e}")
            
            # Step 2: Use regular API pagination if we have a real user token
            # Note: Spotify API sometimes reports total_tracks=0 on the initial metadata request
            # for Premium accounts without 'market' parameter.
            total = playlist["total_tracks"]
            
            if playlist and self.has_user_token() and (len(tracks) < total or total == 0):
                logger.info(f"User is authenticated, paginating remaining tracks via Spotify API...")
                offset = len(tracks)
                page_data = {}
                
                # If total was 0, pretend it's at least 1 so we enter the loop and fetch
                if total == 0:
                    total = 1
                
                while offset < total:
                    try:
                        logger.info(f"Fetching API page (offset {offset}/{total})...")
                        page_data = await self._api_request(f"/playlists/{playlist_id}/tracks", {
                            "limit": 100,
                            "offset": offset,
                            "additional_types": "track",
                            "fields": "items(track(id,name,artists(name),album(name,id,images),duration_ms,external_ids)),total,next"
                        })
                        
                        if total == 1 and page_data.get("total"):
                            total = page_data.get("total")
                        
                        items = page_data.get("items", [])
                        if not items:
                            break
                            
                        for item in items:
                            track_data = item.get("track")
                            if track_data and track_data.get("id"):
                                tracks.append(self._format_track(track_data))
                        
                        offset += len(items)
                        
                        if not page_data.get("next"):
                            break
                    except Exception as e:
                        logger.warning(f"Failed to paginate API with user token: {e}")
                        break
                
                # If we achieved our goal, we can just skip the embed scrape entirely!
                if len(tracks) >= total:
                    playlist["tracks"] = tracks
                    playlist["total_tracks"] = len(tracks)
                    for track in tracks:
                        track["source"] = "spotify"
                    logger.info(f"Loaded {len(tracks)} tracks via API pagination")
                    return playlist
                else:
                    logger.warning(f"API pagination gave up at {len(tracks)}/{total} tracks. Falling back to embed scrape.")
                    
            # Step 3: Fallback - Scrape embed page for tracks
            # If we reach here, we either don't have a token, or the API pagination failed/returned 403.
            # But we might already have the basic playlist metadata from Step 1!
            embed_tracks = []

            embed_url = f"https://open.spotify.com/embed/playlist/{playlist_id}"
            headers = {"User-Agent": get_random_user_agent()}
            response = await self.client.get(embed_url, headers=headers)
            
            if response.status_code != 200:
                logger.error(f"Embed page returned {response.status_code}")
                # We return whatever we have so far
                if playlist:
                    playlist["tracks"] = tracks
                    for t in playlist["tracks"]: t["source"] = "spotify"
                return playlist
            
            # Extract __NEXT_DATA__
            match = re.search(r'<script\s+id="__NEXT_DATA__"\s+type="application/json">([^<]+)</script>', response.text)
            if not match:
                logger.error("Could not find __NEXT_DATA__ in embed page")
                if playlist:
                    playlist["tracks"] = tracks
                return playlist
            
            next_data = json.loads(match.group(1))
            entity = next_data.get("props", {}).get("pageProps", {}).get("state", {}).get("data", {}).get("entity", {})
            
            # Extract embed access token
            embed_token = None
            token_match = re.search(r'"accessToken":"([^"]+)"', response.text)
            if token_match:
                embed_token = token_match.group(1)
            
            if not entity:
                logger.error("No entity found in embed data")
                if playlist:
                    playlist["tracks"] = tracks
                return playlist
            
            # Build playlist metadata if missing
            if not playlist:
                cover_art = None
                cover_data = entity.get("coverArt", {})
                if cover_data:
                    sources = cover_data.get("sources", [])
                    if sources:
                        cover_art = sorted(sources, key=lambda x: x.get("width", 0), reverse=True)[0].get("url")
                
                playlist = {
                    "id": playlist_id,
                    "type": "playlist",
                    "name": entity.get("name", "Unknown Playlist"),
                    "description": entity.get("description", ""),
                    "album_art": cover_art,
                    "owner": entity.get("subtitle", ""),
                    "total_tracks": 0,
                    "source": "spotify",
                }
            
            # Process tracks from embed page
            track_list = entity.get("trackList", [])
            cover_art = playlist.get("album_art")
            
            for item in track_list:
                uri = item.get("uri", "")
                track_id = uri.split(":")[-1] if "spotify:track:" in uri else None
                if not track_id:
                    continue
                
                # Make sure we don't duplicate tracks already loaded from API inline items
                if any(t["id"] == track_id for t in tracks):
                    continue
                
                track_art = cover_art
                item_cover_data = item.get("coverArt", {})
                if item_cover_data:
                    sources = item_cover_data.get("sources", [])
                    if sources:
                        track_art = sorted(sources, key=lambda x: x.get("width", 0), reverse=True)[0].get("url")
                    
                embed_tracks.append({
                    "id": track_id,
                    "type": "track",
                    "name": item.get("title", "Unknown"),
                    "artists": item.get("subtitle", "Unknown Artist"),
                    "artist_names": [a.strip() for a in item.get("subtitle", "Unknown Artist").split(",")],
                    "album": "",
                    "album_id": "",
                    "album_art": track_art,
                    "duration_ms": item.get("duration", 0),
                    "duration": self._format_duration(item.get("duration", 0)),
                    "isrc": None,
                    "source": "spotify",
                })
            
            # Combine the tracks
            tracks.extend(embed_tracks)
            logger.info(f"Scraped {len(embed_tracks)} new tracks from embed page for '{playlist['name']}'")
            
            # Step 4: If embed didn't get all tracks, use embed token to fetch remaining via batch lookup
            total_expected = playlist.get("total_tracks", 0) or len(tracks)
            
            if embed_token and len(tracks) < total_expected and len(tracks) > 0:
                logger.info(f"Have {len(tracks)}/{total_expected} tracks, fetching remaining via batch track lookup...")
                
                try:
                    all_track_ids = set(t["id"] for t in tracks)
                    offset = len(tracks)
                    
                    while offset < total_expected:
                        logger.info(f"Fetching track IDs via embed token... ({offset}/{total_expected})")
                        try:
                            resp = await self.client.get(
                                f"{self.API_BASE}/playlists/{playlist_id}/tracks",
                                params={
                                    "market": "US",
                                    "limit": 50,
                                    "offset": offset,
                                    "fields": "items(track(id,name,artists(name),album(name,id,images),duration_ms,external_ids)),total,next"
                                },
                                headers={
                                    "Authorization": f"Bearer {embed_token}",
                                    "User-Agent": get_random_user_agent(),
                                    "Accept": "application/json",
                                }
                            )
                            
                            if resp.status_code != 200:
                                logger.warning(f"Embed token tracks fetch returned {resp.status_code}, stopping pagination")
                                break
                            
                            page_data = resp.json()
                            page_items = page_data.get("items", [])
                            if not page_items:
                                break
                            
                            for item in page_items:
                                track_data = item.get("track")
                                if track_data and track_data.get("id") and track_data["id"] not in all_track_ids:
                                    tracks.append(self._format_track(track_data))
                                    all_track_ids.add(track_data["id"])
                            
                            offset += len(page_items)
                            
                            if not page_data.get("next"):
                                break
                        except Exception as e:
                            logger.warning(f"Embed token pagination error at offset {offset}: {e}")
                            break
                    
                    logger.info(f"After pagination: {len(tracks)} total tracks")
                except Exception as e:
                    logger.warning(f"Batch track lookup failed: {e}")
            
            # Step 5: Browser scrape fallback for large playlists (100+ tracks)
            # If we still don't have all the tracks, or if exactly 100 tracks were found
            # (hitting the initial Spotify pagination limit), use headless Selenium to scroll
            # through the full Spotify playlist page and extract all track data.
            total_expected = playlist.get("total_tracks", 0) or len(tracks)
            if len(tracks) < total_expected or len(tracks) == 100:
                logger.info(f"Have {len(tracks)}/{total_expected} tracks (or exactly 100). Launching browser scrape fallback...")
                try:
                    browser_tracks = await self._scrape_playlist_via_browser(playlist_id)
                    if browser_tracks:
                        # Build a set of existing track names for dedup
                        existing_keys = set()
                        for t in tracks:
                            key = f"{t.get('artists', '')}|||{t.get('name', '')}".lower()
                            existing_keys.add(key)
                        
                        new_count = 0
                        for bt in browser_tracks:
                            key = f"{bt['artists']}|||{bt['name']}".lower()
                            if key not in existing_keys:
                                # Create a track entry from browser data
                                import hashlib
                                track_hash = hashlib.md5(f"{bt['artists']}-{bt['name']}".encode()).hexdigest()[:12]
                                tracks.append({
                                    "id": f"browser_{track_hash}",
                                    "type": "track",
                                    "name": bt["name"],
                                    "artists": bt["artists"],
                                    "artist_names": [a.strip() for a in bt["artists"].split(",")],
                                    "album": "",
                                    "album_id": "",
                                    "album_art": playlist.get("album_art", ""),
                                    "duration_ms": 0,
                                    "duration": "0:00",
                                    "isrc": None,
                                    "source": "spotify",
                                })
                                existing_keys.add(key)
                                new_count += 1
                        
                        logger.info(f"Browser scrape added {new_count} new tracks (total: {len(tracks)})")
                        # Mark all browser-scraped tracks for art enrichment
                        if new_count > 0:
                            embed_tracks.extend(tracks[-new_count:])
                except Exception as e:
                    logger.warning(f"Browser scrape fallback failed: {e}")
            
            # Step 6: Add source attribution
            for track in tracks:
                track["source"] = "spotify"
            
            # Enrich tracks with real album art from Deezer since Spotify embed omits them now
            if len(embed_tracks) > 0:
                logger.info(f"Enriching {len(embed_tracks)} scraped tracks with Deezer album art...")
                await self._enrich_tracks_with_deezer_art(tracks)
                
            playlist["tracks"] = tracks
            playlist["total_tracks"] = len(tracks)
            logger.info(f"Loaded {len(tracks)} tracks from playlist '{playlist['name']}'")
            return playlist
            
        except Exception as e:
            logger.error(f"Error fetching Spotify playlist {playlist_id}: {e}")
            return None
    
    async def _scrape_playlist_via_browser(self, playlist_id: str) -> list:
        """Scrape ALL tracks from a Spotify playlist using headless Selenium.
        
        Spotify's web UI uses virtualised scrolling — tracks are lazy-loaded as 
        you scroll. This method launches a headless Chrome, navigates to the 
        playlist, and scrolls through the entire tracklist, extracting track 
        data incrementally from [data-testid="tracklist-row"] elements.
        
        Adapted from MusicGrabber's Playwright approach, using our existing 
        Selenium infrastructure (same as AudiobookBay).
        
        Returns list of {"name": ..., "artists": ...} dicts.
        """
        import asyncio
        import time
        
        def _browser_scrape(playlist_id: str) -> list:
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options
            from selenium.webdriver.chrome.service import Service
            from selenium.webdriver.common.by import By
            import shutil
            
            options = Options()
            options.add_argument('--headless=new')
            options.add_argument('--window-size=1280,800')
            options.add_argument('--disable-gpu')
            options.add_argument('--no-sandbox')
            options.add_argument('--disable-dev-shm-usage')
            options.add_argument('--disable-blink-features=AutomationControlled')
            
            # AGGRESSIVE MEMORY SAVING FLAGS FOR RENDER 512MB RAM LIMIT
            options.add_argument('--disable-extensions')
            options.add_argument('--disable-logging')
            options.add_argument('--disable-background-networking')
            options.add_argument('--disable-default-apps')
            options.add_argument('--disable-sync')
            options.add_argument('--disable-translate')
            options.add_argument('--hide-scrollbars')
            options.add_argument('--metrics-recording-only')
            options.add_argument('--mute-audio')
            options.add_argument('--no-first-run')
            options.add_argument('--safebrowsing-disable-auto-update')
            options.add_argument('--js-flags="--max-old-space-size=256"')
            
            # Disable images, CSS, and fonts to save massive amounts of RAM
            prefs = {
                "profile.managed_default_content_settings.images": 2,
                "profile.managed_default_content_settings.stylesheet": 2,
                "profile.managed_default_content_settings.fonts": 2,
            }
            options.add_experimental_option("prefs", prefs)
            
            options.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
            options.add_experimental_option("excludeSwitches", ["enable-automation"])
            options.add_experimental_option('useAutomationExtension', False)
            
            # Try system Chromium first (Docker/Render), fall back to webdriver-manager
            chromium_path = shutil.which('chromium') or shutil.which('chromium-browser')
            chromedriver_path = shutil.which('chromedriver')
            
            if chromium_path and chromedriver_path:
                options.binary_location = chromium_path
                service = Service(chromedriver_path)
            else:
                from webdriver_manager.chrome import ChromeDriverManager
                service = Service(ChromeDriverManager().install())
            
            driver = webdriver.Chrome(service=service, options=options)
            try:
                url = f"https://open.spotify.com/playlist/{playlist_id}"
                logger.info(f"Browser scrape: navigating to {url}")
                driver.set_page_load_timeout(60)
                driver.get(url)
                time.sleep(3)
                
                # Dismiss cookie consent if present
                cookie_selectors = [
                    "[data-testid='cookie-policy-manage-dialog-accept-button']",
                    "button.onetrust-close-btn-handler",
                ]
                for sel in cookie_selectors:
                    try:
                        btns = driver.find_elements(By.CSS_SELECTOR, sel)
                        if btns:
                            btns[0].click()
                            logger.info(f"Browser scrape: dismissed cookie dialog")
                            time.sleep(2)
                            break
                    except Exception:
                        pass
                
                # Wait for tracklist rows to appear
                SELECTOR = '[data-testid="tracklist-row"]'
                for _ in range(30):  # Wait up to 30 seconds
                    rows = driver.find_elements(By.CSS_SELECTOR, SELECTOR)
                    if rows:
                        break
                    time.sleep(1)
                
                if not rows:
                    logger.warning("Browser scrape: no tracklist rows found")
                    return []
                
                # Scroll through the virtualised tracklist, extracting tracks incrementally
                seen_tracks = {}  # Use dict to preserve order and deduplicate
                stale_count = 0
                last_seen_count = 0
                
                def extract_visible_tracks():
                    # Massively optimized JS extraction to prevent Selenium IPC timeouts and OOM
                    js_code = """
                    let rows = document.querySelectorAll('[data-testid="tracklist-row"]');
                    let results = [];
                    for (let r of rows) {
                        let lines = r.innerText.split('\\n').map(l => l.trim()).filter(l => l);
                        if (!lines || !lines[0].match(/^\\d+$/)) continue; // skip if not numbered
                        
                        lines.shift(); // remove number
                        if (lines.length > 0 && lines[0] === 'E') lines.shift(); // remove explicit tag
                        
                        if (lines.length >= 2) {
                            let trackName = lines[0];
                            let artist = lines[1];
                            if (artist === 'E' && lines.length >= 3) artist = lines[2];
                            
                            if (trackName && artist && artist !== 'E') {
                                results.push(artist + "|||" + trackName);
                            }
                        }
                    }
                    return results;
                    """
                    try:
                        extracted = driver.execute_script(js_code)
                        for item in extracted:
                            parts = item.split("|||")
                            if len(parts) == 2:
                                artist, track_name = parts
                                key = f"{artist}|||{track_name}".lower()
                                if key not in seen_tracks:
                                    seen_tracks[key] = {
                                        "name": track_name,
                                        "artists": artist
                                    }
                    except Exception as e:
                        logger.warning(f"JS extraction error: {e}")
                
                # First extraction before scrolling
                extract_visible_tracks()
                logger.info(f"Browser scrape: initial extraction found {len(seen_tracks)} tracks")
                
                # Scroll to load all tracks. Stop when we reach 10 consecutive stale scrolls
                stale_limit = 10
                while stale_count < stale_limit:
                    try:
                        rows = driver.find_elements(By.CSS_SELECTOR, SELECTOR)
                        if rows:
                            # Scroll the last row into view
                            driver.execute_script("arguments[0].scrollIntoView({block: 'end'});", rows[-1])
                    except Exception:
                        pass
                    
                    # Wait for network/DOM to catch up
                    time.sleep(1.0)
                    
                    extract_visible_tracks()
                    
                    if len(seen_tracks) == last_seen_count:
                        stale_count += 1
                        if stale_count % 3 == 0:
                            # Try scrolling up a bit and back down if stuck
                            try:
                                driver.execute_script("window.scrollBy(0, -300);")
                                time.sleep(0.5)
                                rows = driver.find_elements(By.CSS_SELECTOR, SELECTOR)
                                if rows:
                                    driver.execute_script("arguments[0].scrollIntoView({block: 'end'});", rows[-1])
                                    time.sleep(0.5)
                            except Exception:
                                pass
                    else:
                        stale_count = 0
                        
                        # Only log occasionally so we don't spam Render logs
                        if len(seen_tracks) - last_seen_count >= 50 or last_seen_count == 0:
                            logger.info(f"Browser scrape progress: {len(seen_tracks)} tracks loaded so far...")
                            
                        last_seen_count = len(seen_tracks)
                
                logger.info(f"Browser scrape: finished with {len(seen_tracks)} tracks")
                return list(seen_tracks.values())
            
            finally:
                driver.quit()
        
        # Run the blocking Selenium work in a thread executor
        loop = asyncio.get_event_loop()
        try:
            result = await loop.run_in_executor(None, _browser_scrape, playlist_id)
            return result
        except Exception as e:
            logger.error(f"Browser scrape failed: {e}")
            return []
    
    async def _scrape_embed_playlist(self, playlist_id: str) -> Optional[Dict[str, Any]]:
        """Scrape playlist data from Spotify embed page as fallback when API returns 403."""
        import json
        try:
            embed_url = f"https://open.spotify.com/embed/playlist/{playlist_id}"
            headers = {"User-Agent": get_random_user_agent()}
            response = await self.client.get(embed_url, headers=headers)
            if response.status_code != 200:
                logger.error(f"Embed page returned {response.status_code} for playlist {playlist_id}")
                return None
            
            # Extract __NEXT_DATA__ JSON from the HTML
            match = re.search(r'<script\s+id="__NEXT_DATA__"\s+type="application/json">([^<]+)</script>', response.text)
            if not match:
                logger.error(f"Could not find __NEXT_DATA__ in embed page for playlist {playlist_id}")
                return None
            
            next_data = json.loads(match.group(1))
            entity = next_data.get("props", {}).get("pageProps", {}).get("state", {}).get("data", {}).get("entity", {})
            
            if not entity:
                logger.error(f"No entity found in embed data for playlist {playlist_id}")
                return None
            
            # Extract cover art
            cover_art = None
            cover_data = entity.get("coverArt", {})
            if cover_data:
                sources = cover_data.get("sources", [])
                if sources:
                    cover_art = sorted(sources, key=lambda x: x.get("width", 0), reverse=True)[0].get("url")
            
            # Build playlist object
            track_list = entity.get("trackList", [])
            playlist = {
                "id": playlist_id,
                "type": "playlist",
                "name": entity.get("name", "Unknown Playlist"),
                "description": entity.get("description", ""),
                "album_art": cover_art,
                "owner": entity.get("subtitle", ""),
                "total_tracks": len(track_list),
                "source": "spotify",
            }
            
            tracks = []
            for item in track_list:
                uri = item.get("uri", "")
                track_id = uri.split(":")[-1] if "spotify:track:" in uri else None
                if not track_id:
                    continue
                
                tracks.append({
                    "id": track_id,
                    "type": "track",
                    "name": item.get("title", "Unknown"),
                    "artists": item.get("subtitle", "Unknown Artist"),
                    "artist_names": [a.strip() for a in item.get("subtitle", "Unknown Artist").split(",")],
                    "album": "",
                    "album_id": "",
                    "album_art": cover_art,
                    "duration_ms": item.get("duration", 0),
                    "duration": self._format_duration(item.get("duration", 0)),
                    "isrc": None,
                    "source": "spotify",
                })
            
            playlist["tracks"] = tracks
            logger.info(f"Scraped {len(tracks)} tracks from embed page for playlist '{playlist['name']}'")
            
            # Enrich tracks with real album art from Deezer
            await self._enrich_tracks_with_deezer_art(tracks)
            
            return playlist
        except Exception as e:
            logger.error(f"Embed scrape failed for playlist {playlist_id}: {e}")
            return None
    
    # ========== ARTIST METHODS ==========
    
    async def get_artist(self, artist_id: str) -> Optional[Dict[str, Any]]:
        """Get artist info with top tracks."""
        try:
            artist_data = await self._api_request(f"/artists/{artist_id}")
            artist = {
                "id": artist_data["id"],
                "type": "artist",
                "name": artist_data["name"],
                "image": self._get_best_image(artist_data.get("images", [])),
                "genres": artist_data.get("genres", []),
                "followers": artist_data.get("followers", {}).get("total", 0),
                "source": "spotify",
            }
            
            top_tracks = await self._api_request(f"/artists/{artist_id}/top-tracks", {"market": "US"})
            artist["tracks"] = [self._format_track(t) for t in top_tracks.get("tracks", [])]
            
            return artist
        except Exception as e:
            logger.error(f"Error fetching Spotify artist {artist_id}: {e}")
            return None
    
    # ========== AUDIO FEATURES & CAMELOT ==========
    
    # Camelot Wheel: Maps (pitch_class, mode) to Camelot notation
    # pitch_class: 0=C, 1=C#, 2=D, ..., 11=B
    # mode: 1=Major (B), 0=Minor (A)
    CAMELOT_MAP = {
        (0, 1): "8B",   (0, 0): "5A",   # C Major / C Minor
        (1, 1): "3B",   (1, 0): "12A",  # C# Major / C# Minor
        (2, 1): "10B",  (2, 0): "7A",   # D Major / D Minor
        (3, 1): "5B",   (3, 0): "2A",   # D# Major / D# Minor
        (4, 1): "12B",  (4, 0): "9A",   # E Major / E Minor
        (5, 1): "7B",   (5, 0): "4A",   # F Major / F Minor
        (6, 1): "2B",   (6, 0): "11A",  # F# Major / F# Minor
        (7, 1): "9B",   (7, 0): "6A",   # G Major / G Minor
        (8, 1): "4B",   (8, 0): "1A",   # G# Major / G# Minor
        (9, 1): "11B",  (9, 0): "8A",   # A Major / A Minor
        (10, 1): "6B",  (10, 0): "3A",  # A# Major / A# Minor
        (11, 1): "1B",  (11, 0): "10A", # B Major / B Minor
    }
    
    def _to_camelot(self, key: int, mode: int) -> str:
        """Convert Spotify key/mode to Camelot notation."""
        return self.CAMELOT_MAP.get((key, mode), "?")
    
    async def search_track_by_isrc(self, isrc: str) -> Optional[str]:
        """Search for a track by ISRC and return Spotify track ID."""
        try:
            data = await self._api_request("/search", {"q": f"isrc:{isrc}", "type": "track", "limit": 1})
            tracks = data.get("tracks", {}).get("items", [])
            if tracks:
                return tracks[0].get("id")
        except Exception as e:
            logger.warning(f"ISRC search failed for {isrc}: {e}")
        return None
    
    async def search_track_by_name(self, name: str, artist: str) -> Optional[str]:
        """Search for a track by name and artist, return Spotify track ID."""
        try:
            # 1. Try strict search first
            query = f"track:{name} artist:{artist}"
            data = await self._api_request("/search", {"q": query, "type": "track", "limit": 1, "market": "US"})
            tracks = data.get("tracks", {}).get("items", [])
            if tracks:
                return tracks[0].get("id")
            
            # 2. Fallback to loose search (just string matching)
            # Remove special chars and extra artists for better matching
            clean_name = name.split('(')[0].split('-')[0].strip()
            clean_artist = artist.split(',')[0].strip() 
            query = f"{clean_name} {clean_artist}"
            data = await self._api_request("/search", {"q": query, "type": "track", "limit": 1, "market": "US"})
            tracks = data.get("tracks", {}).get("items", [])
            if tracks:
                return tracks[0].get("id")
                
        except Exception as e:
            logger.warning(f"Name search failed for {name} by {artist}: {e}")
        return None

    async def get_audio_features(self, track_id: str, isrc: str = None, name: str = None, artist: str = None) -> Optional[Dict[str, Any]]:
        """Get audio features (BPM, key, energy) for a single track.
        
        If track_id starts with 'dz_' (Deezer), will try ISRC or name/artist lookup first.
        NOTE: Spotify deprecated /audio-features for non-partner apps in late 2024.
        A circuit breaker disables further calls after the first 403.
        """
        # Circuit breaker: if Spotify has already rejected us once, skip entirely
        if getattr(self, '_audio_features_disabled', False):
            return None
        
        spotify_id = track_id
        
        # Handle Deezer tracks - need to find Spotify equivalent
        if track_id.startswith("dz_"):
            spotify_id = None
            # Try ISRC first
            if isrc:
                spotify_id = await self.search_track_by_isrc(isrc)
            # Fallback to name/artist search
            if not spotify_id and name and artist:
                spotify_id = await self.search_track_by_name(name, artist)
            
            if not spotify_id:
                logger.warning(f"Could not find Spotify ID for Deezer track {track_id}")
                return None
        
        try:
            data = await self._api_request(f"/audio-features/{spotify_id}")
            return self._format_audio_features(data)
        except Exception as e:
            # 403 Forbidden = endpoint deprecated for non-partner apps
            if "403" in str(e):
                logger.warning(f"Spotify /audio-features returned 403 — endpoint deprecated. Disabling further calls.")
                self._audio_features_disabled = True
            else:
                logger.error(f"Error fetching audio features for {spotify_id}: {e}")
            return None

    
    async def get_audio_features_batch(self, track_ids: List[str]) -> List[Optional[Dict[str, Any]]]:
        """Get audio features for multiple tracks (max 100 per request)."""
        if not track_ids:
            return []
        
        # Spotify API limit is 100 tracks per request
        results = []
        for i in range(0, len(track_ids), 100):
            batch = track_ids[i:i+100]
            try:
                data = await self._api_request("/audio-features", {"ids": ",".join(batch)})
                for features in data.get("audio_features", []):
                    if features:
                        results.append(self._format_audio_features(features))
                    else:
                        results.append(None)
            except Exception as e:
                logger.error(f"Error fetching batch audio features: {e}")
                results.extend([None] * len(batch))
        
        return results
    
    def _format_audio_features(self, data: dict) -> dict:
        """Format audio features for frontend."""
        key = data.get("key", -1)
        mode = data.get("mode", 0)
        return {
            "track_id": data.get("id"),
            "bpm": round(data.get("tempo", 0)),
            "key": key,
            "mode": mode,
            "camelot": self._to_camelot(key, mode) if key >= 0 else "?",
            "energy": round(data.get("energy", 0), 2),
            "danceability": round(data.get("danceability", 0), 2),
            "valence": round(data.get("valence", 0), 2),  # "happiness"
        }
    
    # ========== UTILITIES ==========
    
    def _get_best_image(self, images: List[Dict]) -> Optional[str]:
        if not images:
            return None
        sorted_images = sorted(images, key=lambda x: x.get("width", 0), reverse=True)
        return sorted_images[0]["url"] if sorted_images else None
    
    def _format_duration(self, ms: int) -> str:
        seconds = ms // 1000
        minutes = seconds // 60
        secs = seconds % 60
        return f"{minutes}:{secs:02d}"
    
    async def get_made_for_you_playlists(self) -> List[Dict[str, Any]]:
        """
        Get 'Made For You' playlists (Daily Mix, Discover Weekly, etc.).
        Uses search API with strict filtering for Spotify-owned playlists.
        Requires authenticated token (sp_dc cookie).
        """
        try:
            # Check if we have a valid token (will try cookie auth)
            token = await self._get_access_token()
            if not token:
                logger.warning("No Spotify token available for Made For You")
                return []
            
            mixes = []
            queries = ["Daily Mix", "Discover Weekly", "Release Radar", "On Repeat", "Repeat Rewind"]
            
            for q in queries:
                try:
                    data = await self._api_request("/search", {"q": q, "type": "playlist", "limit": 10})
                    if not data:
                        continue
                    
                    items = data.get("playlists", {}).get("items", [])
                    for item in items:
                        if not item:
                            continue
                        
                        owner_id = item.get("owner", {}).get("id", "")
                        name = item.get("name", "")
                        
                        # Filter: owned by "spotify" OR name starts with one of our keywords
                        # (Daily Mix 1, Daily Mix 2, etc. are personalized)
                        is_spotify_owned = owner_id == "spotify"
                        name_matches = any(name.startswith(kw) or name == kw for kw in queries)
                        
                        if is_spotify_owned or name_matches:
                            mixes.append({
                                "id": item["id"],
                                "name": name,
                                "description": item.get("description", ""),
                                "image": self._get_best_image(item.get("images", [])),
                                "owner": "Spotify",
                                "type": "playlist",
                                "source": "spotify"
                            })
                except Exception as e:
                    logger.warning(f"Failed to fetch mix '{q}': {e}")
            
            # Deduplicate by ID
            unique_mixes = {m['id']: m for m in mixes}.values()
            logger.info(f"Found {len(list(unique_mixes))} Made For You playlists")
            return list(unique_mixes)

        except Exception as e:
            logger.error(f"Error fetching Made For You playlists: {e}")
            return []

    async def close(self):
        await self.client.aclose()


# Singleton instance
spotify_service = SpotifyService()
