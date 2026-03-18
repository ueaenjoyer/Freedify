# Changelog

All notable changes to Freedify will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [Unreleased]

---

## [1.3.8] - 2026-03-18

### Added
- **Audiobook Direct URL Support**: Paste a full AudiobookBay URL into the search bar to jump directly to the book modal, bypassing keyword search limitations.
- **Audiobook Search Pagination**: Enabled "Load More Results" for audiobooks, wiring up AudiobookBay's pagination to browse deep into result pages.
- **Spotify Embed Pagination**: Added a lightweight API-based pagination fallback using embed tokens to discover and fetch 100+ track playlists without requiring the resource-heavy browser scraper in most cases.

### Fixed
- **Audiobook Chapter Progression**: Fixed an issue where audiobooks wouldn't auto-advance to the next chapter at the end of playback.
- **"Save to My Books" Sync**: Resolved a closure-related bug where toggling favorite status on a new book would sometimes remove the previously viewed book instead.
- **My Books "Play" Resume**: Clicking play on a book in "My Books" now correctly resumes the exact chapter and timestamp you left off at.

### Improved
- **High-Speed Audio Quality**: Added `preservesPitch` support to the audio engine, fixing metallic crackling and artifacts when listening to audiobooks or podcasts at 1.5x or 2x speed.

### Fixed
- **Audiobook Chapter Auto-Progression**: Fixed an issue where audiobooks would not automatically continue to the next chapter; `handleEnded` now correctly advances the queue.
- **Audiobook Info Resume**: The "Resume" button in the Book Info modal now correctly loads the entire book into the queue and starts exactly at the saved chapter and timestamp.
- **Audiobook "Save to My Books" Closure Bug**: Fixed a bug where clicking the save/favorite button in the Audiobook search modal would sometimes add or remove the wrong book due to a stale ID closure.
- **Spotify Scraper Memory Optimization**: Drastically reduced RAM usage for the headless Selenium scraper to prevent OOM crashes on Render. Offloaded track extraction to a single optimized JavaScript call to eliminate IPC bottlenecks and ReadTimeout errors.

---

## [1.3.7] - 2026-03-16

### Added
- **Playlist Management**: Added ♡ "Add All to Playlist" and per-track ♡ "Add to Playlist" buttons to the playlist detail view.
- **Render Keep-Alive**: Added an automatic background ping task to the FastAPI lifespan that pings the application's `RENDER_EXTERNAL_URL` every 13 minutes, preventing free-tier servers from spinning down due to inactivity.
- **Spotify Embed Scraping Fallback**: When the Spotify API returns a 403 Forbidden error for public playlists or albums, Freedify now seamlessly falls back to scraping track data directly from Spotify's embed pages.
- **Deezer Album Art Enrichment**: Songs imported via the Spotify embed fallback now use concurrent Deezer searches to automatically fetch and attach the correct high-quality album artwork for each individual track instead of reusing the playlist cover.
- **Premiumize CDN Auto-Refresh**: When a cached Premiumize audiobook/file CDN link expires (403 Forbidden), the server now automatically searches Premiumize cloud for the file by name, fetches a fresh download link, and retries the stream — completely transparent to the user.
- **Headless Browser Playlist Scraping**: For Spotify playlists with 100+ tracks, Freedify now automatically falls back to a headless Selenium browser that scrolls through the full playlist page to extract all tracks — bypassing Spotify's API/embed 100-track limit. Inspired by MusicGrabber's approach, reuses existing Selenium infrastructure.
- **Watched Spotify Playlists**: You can now "👁 Watch" Spotify playlists. Every time you open Freedify, it will check your watched playlists in the background and notify you if any new tracks have been added. Find your watched playlists and their sync status at the top of the Playlists tab.

### Fixed
- **Spotify Token Retrieval Dead Code**: Removed unreachable auth code in the Spotify integration service that prevented fallback token acquisition strategies.
- **Tidal 401 Token Expiry**: Tidal auth tokens are now automatically refreshed when they expire (401 Unauthorized), fixing playback failures on long-running Render deployments.
- **Spotify Audio Features 403 Spam**: Added a circuit breaker for the deprecated Spotify `/audio-features` endpoint — after the first 403, all subsequent DJ Mode calls skip the API entirely and fall back to AI estimation.
- **Dead Tidal API Discovery**: Removed the broken `status.monochrome.tf` API discovery call that logged errors on every startup.

---

## [1.3.6] - 2026-03-09

### Added
- **Tidal Hi-Res FLAC APIs**: Added multiple new upstream proxy APIs capable of resolving and streaming true 24-bit Hi-Res LOSSLESS FLAC tracks directly from Tidal.
- **Stream URL Cache**: Seeking around a track now instantly reuses the existing upstream stream URL without re-triggering the full API search chain, saving significant battery and bandwidth.
- **Dynamic Quality Badging**: The "Now Playing" UI now extracts `X-Audio-Quality` and `Content-Type` directly from stream headers via an instantaneous pre-flight `HEAD` request. Badges proudly display **HI-RES** (24-bit), **HIFI** (16-bit), **M4B**, or **MP3** dynamically.

### Improved
- **API Search Pipeline Redesign**: Audio routing logic is now separated into two explicitly distinct paths based on the Hi-Res toggle state, prioritizing the fastest possible Time-To-First-Byte for 16-bit audio, and maximum quality for 24-bit audio. 
- **Parallel Proxy Racing**: Greatly reduced latency when fetching Tidal Hi-Res streams by racing the top 3 proxies in parallel (first one to answer wins), abandoning the old sequential 1-by-1 cascade check.
- **Tidal API Pre-Warming**: The API fallback list is now synced immediately during app startup, rather than blocking the very first song play request of the session.
- **Album Art Deferral**: Album art fetching is now fully deferred in the proxy streaming path, shaving ~300ms off track load times (downloads continue to receive fully embedded FLAC cover art).

### Fixed
- **Hi-Res Fallback Breakage**: Fixed a critical bug where the app failed to play anything if a requested Hi-Res track only existed in 16-bit. It now seamlessly falls back to 16-bit LOSSLESS and updates the UI badge accordingly.
- **Manifest Decode Error Noise**: Fixed proxy error log pollution caused by Tidal APIs returning empty manifests for tracks unavailable in 24-bit; these are now gracefully handled as deliberate HTTP 200 "not available" responses.

---

## [1.3.5] - 2026-03-07

### Added
- **Audiobook Playback Speed**: Added adjustable playback speed controls (1x, 1.25x, 1.5x, 2x) to the player bar when listening to audiobooks.

### Fixed
- **Premiumize Root File Detection**: Fixed an issue where single-file audiobooks downloaded to the root directory were not detected, enabling seamless mapping and playback.
- **Audiobook Metadata Mismatch**: Resolved a bug where saving a direct-file audiobook resulted in incorrect metadata (e.g., retrieving "The Shining" instead of the actual book) by standardizing the `showDetailView` object structure.
- **Audiobook Streaming Links**: Corrected the internal ISRC Base64 formatting for direct Premiumize file streams so the audio engine can actually play them.

---

## [1.3.4] - 2026-03-07

### Fixed
- **Audiobook History Playback**: Recently played audiobook chapters now play from Premiumize cache instead of falling back to YouTube. Stream URLs are stored in history entries with a fallback resolver for older entries.
- **Search Type Navigation**: Clicking Song, Artist, or Album search tabs now shows the Jump Back In dashboard when the search bar is empty, instead of staying stuck on the Podcasts/Audiobooks view.
- **Audiobook History Separation**: Audiobook chapters no longer appear in the Podcast "Recently Played" section. Added a separate `audiobookHistory` with automatic migration of existing entries.

### Added
- **Recently Played Chapters**: New section on the My Books page showing last 10 played audiobook chapters with resume position indicators.
- **Docker Chromium Support**: Dockerfile now installs Chromium and chromedriver for AudiobookBay's Selenium-based Cloudflare bypass.
- **`PREMIUMIZE_API_KEY`**: Added to `docker-compose.yml` and README environment variable docs for audiobook streaming.

### Improved
- **Docker Build**: Suppressed pip root user warning with `PIP_ROOT_USER_ACTION=ignore`.
- **Selenium Fallback**: AudiobookBay scraper uses system Chromium in Docker, falls back to webdriver-manager for local development.
- **Google Drive Sync**: Audiobook history now syncs alongside podcast history and other data.

---

## [1.3.3] - 2026-03-07

### Added
- **My Podcasts Favorites Page**: Save and manage favorite podcasts with ❤️ toggle on search cards and a dedicated grid view. Click the Podcasts tab to see your saved shows.
- **Episode Resume Position**: Automatically saves playback position for podcast episodes and resumes where you left off.
- **Mark as Played**: Toggle episodes as played/unplayed with ✅ buttons — automatically marks episodes as played when they finish.
- **Podcast Episode History**: Recently played episodes section on the My Podcasts page with resume indicators.
- **Podcast Categories/Tags**: Tag podcasts with custom categories (e.g., Tech, Comedy) and filter your favorites by tag.
- **Episode Download**: Download podcast episodes via the existing download infrastructure from the episode detail view.
- **Podcast Queue Integration**: Podcast episodes seamlessly integrate with the existing queue system with source-aware tracking.
- **Unplayed Episode Indicators**: Resume position indicators appear on episode rows showing where you stopped listening.
- **My Books (Audiobooks)**: Dedicated audiobook bookshelf in the Audiobooks tab. Favorite audiobooks from AudiobookBay search, cache Premiumize downloads, and resume playback across sessions.
- **Book Info Modal**: Click any book in My Books to view a rich detail modal with cover art, chapter count, and play/resume controls.
- **Goodreads Integration**: Book Info modal fetches Goodreads ratings, descriptions, genres, and top 5 community reviews via a score-based search that filters out derivative "summary" books.
- **Audiobook Resume from My Books**: Cached audiobook tracks are stored locally so subsequent plays from My Books resume correctly without re-fetching from Premiumize.
- **Google Drive Sync**: All podcast and audiobook data (favorites, played status, resume positions, history, tags, cached tracks) syncs to Google Drive alongside existing data.

### New Backend Services
- **`goodreads_service.py`**: Goodreads web scraper using httpx + BeautifulSoup — searches books, parses ratings/reviews/descriptions, filters derivative books via scoring.
- **`audiobookbay_service.py`**: AudiobookBay search and detail scraper for audiobook discovery.
- **`premiumize_service.py`**: Premiumize.me integration for audiobook torrent caching and streaming.

---

## [1.3.2] - 2026-03-02

### Added
- **Podcast Playback Speed Control**: Listeners can now toggle podcast playback speed between 0.8x, 1.0x, 1.25x, 1.5x, and 2.0x via the player bar.
- **Dynamic Fullscreen Theming**: The fullscreen view now features a gorgeous blurred and tinted background effect dynamically derived from the current track's album art.
- **Premium Color Themes**: Added 4 new curated developer themes ported directly from Aonsoku: Dracula, Catppuccin, Night Owl, and Nuclear.

---

## [1.3.1] - 2026-03-02

### Fixed
- **Android Background Playback**: Resolved multiple issues causing playback pauses and queue stalls when the browser is backgrounded or screen is locked on Android.
- **Lock Screen Controls**: Fully implemented MediaSession API to enable OS-level next, previous, play, and pause buttons on the Android lock screen and notification panel.
- **Headphone Controls**: Fixed an issue where unpausing via headphone buttons failed on mobile, and enabled headphone track skipping.
- **Background Stream Recovery**: Added automatic stream reconnection and queue progression if the network momentarily drops while the app is in the background.

---

## [1.3.0] - 2026-03-01

### Added
- **Last.fm Scrobbling** — Connect your Last.fm account to automatically scrobble tracks. Includes Now Playing updates, configurable scrobble threshold (50% or 4 minutes), and session persistence across page reloads.
- **Artist Bio Modal** — Click the artist name in the player bar to view biography (Wikipedia), genres, social links, country, active years, and artist image (fanart.tv / Wikipedia).
- **Similar Artists** — Artist Bio modal now shows a horizontally scrollable list of similar artists (powered by Last.fm). Click any chip to load that artist's bio.
- **Playlist Export** — Export any playlist or queue as M3U, CSV, or JSON via the 📤 button in detail view and queue panel.
- **Playlist Import** — Import playlists from M3U, CSV, or JSON files via **More → Import Playlist**. Tracks are automatically resolved against Deezer.
- **Hi-Res Quality Selector** — HiFi button now cycles through 3 modes: HiFi (16-bit FLAC), Hi-Res (24-bit), and Hi-Res+ (highest available). Quality preference persists across sessions.
- **💖 Donate** — Added donate link (Pally.gg) to the More dropdown menu and README header.

### Fixed
- **Artist Bio Auto-Popup** — Fixed bug where clicking any track in an album/playlist would trigger the Artist Bio modal (click handler was too broad, now restricted to player bar only).
- **Artist Bio Caching** — Fixed empty biographies being permanently cached when Wikipedia extraction failed. Cache now only stores successful results.
- **Stale Browser Cache** — Updated app.js cache buster to force browsers to load latest code after updates.

### Improved
- **XSS Hardening** — Fixed potential XSS vulnerability in Similar Artists chips where artist names with apostrophes could break inline JavaScript handlers. Now uses `data-artist` attributes.
- **Code Cleanup** — Full audit: removed debug traceback from `artist_service.py`, dead `get_similar_tracks()` from `lastfm_service.py`, orphaned API endpoint, and stale SpotiFLAC branding in service worker.
- **Service Worker** — Renamed from "SpotiFLAC" to "Freedify" and bumped cache version to `freedify-v7`.

---

## [1.2.0] - 2026-03-01

### Improved
- **Streaming Resilience**: Increased upstream proxy read timeout from 60s to 300s to prevent random mid-song pauses caused by slow CDN delivery from Tidal/Deezer.
- **Faster Playback Start**: Switched audio load trigger from `canplaythrough` to `canplay` — playback begins as soon as the first few seconds are buffered instead of waiting for the browser's full-track estimate.
- **Load Timeout**: Reduced track load timeout from 120s to 20s — failed tracks are detected and handled much faster.
- **Uvicorn Keepalive**: Increased from default 5s to 120s in Dockerfile to prevent premature TCP connection closures on long streams.

### Added
- **Auto-Skip on Failure**: If a track fails to load, the player automatically skips to the next track in the queue with a toast notification. Cascades up to 5 consecutive failures before stopping.
- **Stall Recovery**: New `stalled` event handler with a 10-second recovery timer — attempts a seek-to-resume (forces browser reconnect). If unrecoverable after 20s, auto-skips to the next track.
- **Waiting Watchdog**: 15-second watchdog on the `waiting` event triggers a seek-recovery if the browser's audio buffer runs dry mid-song.
- **Proxy Unbuffering**: Added `X-Accel-Buffering: no` header to all streaming responses so reverse proxies (Render, Tailscale, nginx) flush audio chunks immediately.
- **Docker `.env` Security**: Refactored `docker-compose.yml` to pull all API keys from a local `.env` file. Added `.env.example` template for safe public sharing.
- **Environment Variables**: Added support for Ticketmaster, SeatGeek, Setlist.fm, Spotify, Google, and Jamendo API keys in `.env` and `docker-compose.yml`.

### Fixed
- **Podcast Episode Modal**: Fixed `SyntaxError` from unescaped apostrophes in podcast descriptions breaking inline JSON handlers. Fixed `showPodcastModal` parsing a URL-encoded string instead of a JSON object. Restored missing `podcast-modal` HTML structure.

---

## [1.1.9] - 2026-02-26

### Added
- **Docker `.env` Security**: Complete refactor of `docker-compose.yml` to securely pull all API keys from a private `.env` file instead of hardcoding them. Added `.env.example` template for public repo sharing.
- **Git Ignore**: Strictly ignored `.env` files in `.gitignore` to prevent API keys (Gemini, Ticketmaster, Setlist.fm, Spotify, etc.) from being accidentally committed to public repositories.

### Fixed
- **Podcast Episode Modal Not Opening**: Fixed a critical `SyntaxError` caused by unescaped single quotes (apostrophes) in podcast descriptions breaking the inline JSON `onclick` handler.
- **Podcast Modal Type Error**: Fixed `showPodcastModal` attempting to access properties on a URL-encoded JSON string instead of a parsed javascript Object, restoring the ability to read episode notes and play individual podcasts.
- **Podcast Modal HTML Missing**: Restored the missing `podcast-modal` DOM layout to `index.html` which previously prevented the modal from rendering.

---

## [1.1.8] - 2026-02-24

### Added
- **Add Album to Library**: New "★ Add to Library" button on album detail modal — adds all tracks at once, skips duplicates, shows gold ★ saved state when complete.
- **Add Playlist to Library**: New "★ Add All to Library" button on playlist/artist detail view header — same batch-add behavior with dedup and instant UI feedback.
- **Delete Songs from Playlist**: Per-track ✕ remove buttons now visible on user-created playlists in the detail view. Playlist refreshes immediately after removal.

### Fixed
- **Playlists Not Opening**: Fixed critical `ReferenceError` — `isUserPlaylist` was used in `showDetailView` but never declared, crashing the entire function silently.
- **Back Button Not Working**: The ← Back button on the detail view was declared but never had a click handler attached. Now correctly exits detail view and returns to results.
- **Download Filename for 24-bit**: `aiff_24` and `wav_24` formats produced invalid `.aiff_24` / `.wav_24` file extensions. Now correctly strips the `_24` suffix from the extension.
- **Genius Lyrics Not Loading**: Lyrics scraper was sending requests without a browser User-Agent, causing Genius to block from cloud IPs. Added Chrome-like headers, multiple CSS selector fallbacks, JSON extraction fallback, and detailed logging.

### Changed
- **Library Button Consistency**: All "Add to Library" buttons now use the ★ gold star icon to match existing per-track star buttons throughout the app.

---

## [1.1.7] - 2026-02-24

### Fixed
- **Random Mid-Playback Pauses**: Fixed `performGaplessSwitch` and `performCrossfade` order-of-operations bug where `activePlayer` was switched AFTER pausing the old player, causing `handlePause` to falsely set `isPlaying = false` during transitions.
- **Half-Second Play Then Reload**: Fixed `togglePlay` catch handler that called `loadTrack()` on play failure instead of resuming AudioContext — now tries `audioContext.resume()` first (common issue on mobile after screen lock).
- **Gapless Reliability**: Eliminated parallel track-advance code path in `handleTimeUpdate` that bypassed `playNext()` — all track transitions now flow through a single `playNext()` function.
- **Queue Progression**: Fixed self-blocking bug where `handleTimeUpdate` set `transitionInProgress` before calling `playNext()`, causing it to immediately return and stop the queue.
- **EQ Audio Dropout**: EQ initialization `play` handler was only on `audioPlayer`, not `audioPlayer2` — if player 2 started first, AudioContext would remain suspended. Now handles both players symmetrically.
- **Mute Button**: Fixed mute toggle only setting `audioPlayer.volume` — now sets both `audioPlayer` and `audioPlayer2` volume for correct behavior regardless of which player is active.
- **Preload Consistency**: Changed preload ready detection from `canplay` to `canplaythrough` to match `loadTrack` behavior, preventing premature transition attempts.

### Changed
- **Stream-Through Proxy**: Tidal and Deezer audio now streams directly from source to browser via chunk-by-chunk proxy instead of downloading the entire file (38+ MB) to the server first. Cuts initial load time from ~5s to under 1s.
- **Crossfade Support in Queue**: `playNext` and `playTrack` now correctly choose between crossfade and gapless switch based on user preference (previously always used gapless).
- **Code Quality**: Collapsed ~100 lines of double-line-spacing artifact from previous fix, removed duplicate `state.crossfadeEnabled` declaration.

---


## [1.1.6] - 2026-02-24

### Fixed
- **Gapless Playback**: Fixed double-firing `ended` event handler that caused skipped tracks, broken gapless transitions, and silent queue failures. Root cause: `removeEventListener` on anonymous function silently failed, leaving two competing handlers on the same player.
- **Song Stuttering**: Changed audio ready detection from `canplay` to `canplaythrough` so the browser buffers sufficient data before starting playback, eliminating the half-second stutter/rebuffer at track start.
- **Queue Progression**: `playNext` now properly handles Repeat All (loops back to start) and Repeat One (restarts current track) — previously only worked on player 1 due to handler mismatch.
- **Mid-Playback Stops**: `transitionInProgress` flag now resets on every fresh `loadTrack` call, preventing stuck state that suppressed all track advancement.
- **Pause State Bug**: Fixed `handlePause` using incorrect `this` context in event listener — now uses `e.target` for reliable active player detection.
- **FLAC Download Speed**: FLAC-to-FLAC downloads now bypass FFmpeg entirely when source is already FLAC (detects `fLaC` magic bytes), saving 5-15 seconds per track.

### Removed
- ~430 lines of zombie/duplicate code from frontend including: duplicate `showDetailView`, `openArtist`, `openDownloadModal`, `closeDownloadModal`, `downloadConfirmBtn` handler, `updateMediaSession`, keyboard shortcut handlers (×3), service worker registration, `addToQueue`, and `fsNextBtn` handler.
- Dead `stream_generator` function (42 lines) from backend `main.py`.

---


## [1.1.5] - 2026-01-26

### Added
- **Background Downloading**: Downloads now run in the background with a non-intrusive status indicator, allowing you to browse and stream music while downloading.
- **Download Status Pill**: Floating progress indicator shows download status and can be minimized.
- **Parallel Processing**: Streaming and downloading can now be performed simultaneously without blocking the UI.
- **Concurrent Batch Downloads**: Batch downloads now process 3 tracks in parallel for significantly faster speeds, with automatic API fallback.

### Fixed
- **Metadata Embedding**: Fixed issue where metadata (Cover Art, Artist, Album) was missing for 24-bit FLAC and ALAC downloads.
- **Format Support**: Extended tagging support to include ALAC (.m4a) and ensured all FLAC bit-depths are handled correctly.

---

## [1.1.4] - 2026-01-23

### Added
- **Selective Track Download**: Checkboxes on each track in album/playlist/queue modals to select specific songs to download
- **Select All Toggle**: Quick select/deselect all tracks with selection count display
- **Queue Download**: Added "Download Selected" button to queue controls

---

## [1.1.3] - 2026-01-23

### Fixed
- **Mobile Gapless Playback**: Fixed "false start" bug where tracks would play briefly, pause for 20 seconds, then restart from beginning when screen is off
- **Track Transition Race Condition**: Added `transitionInProgress` lock to prevent double-trigger between gapless switch and ended event handlers

### Changed
- **Mobile Album Modal**: Two-row track layout on mobile - track name on top row, action buttons (star, heart, duration, queue, download) on second row for better readability
- **Star Icon Visibility**: Star button now uses white outline and gold fill when starred, with glow effect
- **Preload Timing**: Replaced setTimeout with requestAnimationFrame for mobile-friendly track preloading

---

## [1.1.2] - 2026-01-22

### Added
- **Jump Back In Dashboard**: Home screen now shows personalized sections for recent albums, artists, library, and playlists
- **My Library (⭐)**: Save tracks with star icon - separate from playlists, syncs with Google Drive
- **Listening History**: Tracks your last 50 played songs, persists across sessions
- **Library View**: Click "See All" on the dashboard to browse your full starred collection

### Changed
- **Google Drive Sync**: Now syncs Library and History alongside playlists
- **Search Cards**: Added star (☆/★) button to quickly save tracks

---

## [1.1.1] - 2026-01-21

### Fixed
- **Download Metadata**: Fixed "Album: test" overwriting actual album tags in playlist downloads via new Strict Mode logic
- **Album Art**: Fixed missing art/metadata by adding automatic MusicBrainz fallback when primary source fails
- **FLAC Duration**: Fixed 00:00 duration/seeking issues in VLC (corrected ffmpeg pipe handling)
- **Stability**: Hardened backend against 404s and empty metadata fields

---

## [1.1.0] - 2026-01-21

### Added
- **Multi-arch Docker**: ARM64 support for Raspberry Pi, Apple Silicon (M1/M2/M3), and ARM servers
- **Termux/Android support**: Run Freedify directly on Android via Termux
- **Termux documentation**: New section in README and deployment guide
- **Cross-platform cache**: Cache now defaults to `~/.freedify_cache` (works on Termux)
- **Apple Music workaround**: Documentation for importing Apple Music playlists via Spotify

### Changed
- **Docker workflow**: Added QEMU emulation for ARM64 builds
- **Cache filenames**: MD5 hash long `LINK:` IDs to prevent filename errors
- **API reliability**: Updated Tidal fallback servers (squid, spotisaver, kinoplus, binimum, qqdl)
- **User-Agent header**: Added custom `Freedify/1.0` User-Agent for API requests

### Fixed
- **iOS audio**: Added silent audio keepalive to prevent screen lock suspension
- **Keyboard shortcuts**: Play/pause now correctly uses Enter key (not Space)
- **Docker Compose**: Updated to use Docker Hub image by default with NAS-friendly options

---

## [1.0.0] - 2026-01-18

### Added
- Initial public release
- Lossless FLAC streaming (16-bit & 24-bit Hi-Res)
- AI Smart Playlists with Gemini
- Multi-source search (Deezer, YouTube Music, Jamendo, Phish.in)
- Google Drive sync for playlists
- ListenBrainz scrobbling
- Docker support with auto-publish to Docker Hub
- Visual deployment guide for Localhost, Railway, and Render

---

*For changes before v1.0, see [commit history](https://github.com/BioHapHazard/Freedify/commits/main).*
