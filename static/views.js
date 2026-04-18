// views.js — ES module extracted from app.js
// Handles all view rendering, modals, and detail views.

import { state } from './state.js';
import { emit, on } from './event-bus.js';
import { showToast, escapeHtml, formatTime, getTimeSince, parseDuration } from './utils.js';
import { $, $$, resultsSection, resultsContainer, detailView, detailInfo, detailTracks, searchInput } from './dom.js';
import { showLoading, hideLoading, showError } from './ui.js';
import {
    createPlaylist,
    deletePlaylist,
    deleteFromPlaylist,
    saveWatchedPlaylists,
    watchPlaylist,
    unwatchPlaylist,
    isWatchedPlaylist,
    syncAllWatchedPlaylists,
    isInLibrary,
    toggleLibrary,
    addAllToLibrary,
    removePodcastFavorite,
    isPodcastFavorited,
    togglePodcastFavorite,
    saveAudiobookFavorites,
    addAudiobookFavorite,
    removeAudiobookFavorite,
    isAudiobookFavorited,
    toggleAudiobookFavorite,
    isEpisodePlayed,
    toggleEpisodePlayed,
    getEpisodePosition,
    getAllUsedTags,
    getPodcastTags,
    setPodcastTags,
    syncOneWatchedPlaylist,
} from './data.js';

// ========== PLAYLISTS VIEW ==========
function renderPlaylistsView() {
    hideLoading();

    if (state.playlists.length === 0) {
        resultsContainer.innerHTML = `
            <div class="empty-state">
                <span class="empty-icon">❤️</span>
                <p>No saved playlists yet</p>
                <p style="font-size: 0.9em; opacity: 0.7;">Import a Spotify playlist and click "Save to Playlist"</p>
            </div>
        `;
        return;
    }

    const grid = document.createElement('div');
    grid.className = 'results-grid';

    state.playlists.forEach(playlist => {
        const trackCount = playlist.tracks.length;
        const coverArt = playlist.tracks[0]?.album_art || '/static/icon.svg';
        grid.innerHTML += `
            <div class="album-item playlist-item" data-playlist-id="${playlist.id}">
                <div class="album-art-container">
                    <img src="${coverArt}" alt="${playlist.name}" class="album-art" loading="lazy">
                    <div class="album-overlay">
                        <button class="play-album-btn">▶</button>
                    </div>
                </div>
                <div class="album-info">
                    <div class="album-name">${playlist.name}</div>
                    <div class="album-artist">${trackCount} track${trackCount !== 1 ? 's' : ''}</div>
                </div>
                <button class="delete-playlist-btn" title="Delete playlist">🗑️</button>
            </div>
        `;
    });

    // Build watched playlists section
    let watchedHtml = '';
    if (state.watchedPlaylists.length > 0) {
        watchedHtml = `
            <div class="playlists-header" style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px;">
                <h2>👁 Watched Playlists</h2>
                <button id="sync-all-watched-btn" class="btn-secondary" style="padding: 6px 14px; font-size: 0.85em;">🔄 Sync All</button>
            </div>
            <div class="results-grid watched-grid" style="margin-bottom: 32px;">
                ${state.watchedPlaylists.map(w => {
                    const timeSince = w.lastSynced ? getTimeSince(w.lastSynced) : 'never';
                    return `
                    <div class="album-item watched-item" data-spotify-id="${w.spotifyId}">
                        <div class="album-art-container">
                            <img src="${w.coverArt || '/static/icon.svg'}" alt="${escapeHtml(w.name)}" class="album-art" loading="lazy">
                            <div class="album-overlay">
                                <button class="play-album-btn">▶</button>
                            </div>
                            ${w.newTracks > 0 ? `<span class="watched-badge">${w.newTracks} new</span>` : ''}
                        </div>
                        <div class="album-info">
                            <div class="album-name">${escapeHtml(w.name)}</div>
                            <div class="album-artist">${w.trackCount} tracks · synced ${timeSince}</div>
                        </div>
                        <div class="watched-actions">
                            <button class="sync-watched-btn" title="Sync now">🔄</button>
                            <button class="unwatch-btn" title="Stop watching">✕</button>
                        </div>
                    </div>`;
                }).join('')}
            </div>
        `;
    }

    const headerHtml = `
        <div class="playlists-header" style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px;">
            <h2>Your Playlists</h2>
            <div class="playlists-actions">
                <button id="import-playlist-btn" class="btn-secondary" style="padding: 8px 16px;">📥 Import Playlist</button>
                <input type="file" id="playlist-import-input" accept=".m3u,.m3u8,.csv,.json" class="hidden">
            </div>
        </div>
    `;

    resultsContainer.innerHTML = watchedHtml + headerHtml;
    resultsContainer.appendChild(grid);

    // Bind Sync All button
    const syncAllBtn = document.getElementById('sync-all-watched-btn');
    if (syncAllBtn) {
        syncAllBtn.addEventListener('click', async () => {
            syncAllBtn.disabled = true;
            syncAllBtn.textContent = '⏳ Syncing...';
            await syncAllWatchedPlaylists(true);
            syncAllBtn.disabled = false;
            syncAllBtn.textContent = '🔄 Sync All';
        });
    }

    // Bind watched playlist click handlers
    resultsContainer.querySelectorAll('.watched-item').forEach(el => {
        el.addEventListener('click', async (e) => {
            if (e.target.closest('.unwatch-btn')) {
                e.stopPropagation();
                unwatchPlaylist(el.dataset.spotifyId);
                return;
            }
            if (e.target.closest('.sync-watched-btn')) {
                e.stopPropagation();
                const watched = state.watchedPlaylists.find(w => w.spotifyId === el.dataset.spotifyId);
                if (watched) {
                    showToast(`🔄 Syncing "${watched.name}"...`);
                    await syncOneWatchedPlaylist(watched);
                    saveWatchedPlaylists();
                    renderPlaylistsView();
                    showToast(`✓ "${watched.name}" synced (${watched.trackCount} tracks)`);
                }
                return;
            }
            // Click on the card itself — open from locally stored tracks (instant, no API call)
            const watched = state.watchedPlaylists.find(w => w.spotifyId === el.dataset.spotifyId);
            if (watched && watched.tracks && watched.tracks.length > 0) {
                // Open instantly from cached data — same as a regular playlist
                const playlistItem = {
                    id: watched.spotifyId,
                    name: watched.name,
                    type: 'playlist',
                    source: 'spotify',
                    album_art: watched.coverArt,
                    artists: `${watched.trackCount} tracks · synced ${watched.lastSynced ? getTimeSince(watched.lastSynced) : 'never'}`,
                    total_tracks: watched.trackCount
                };
                showDetailView(playlistItem, watched.tracks);
            } else {
                // Legacy fallback: no stored tracks yet, fetch from API
                showLoading('Loading watched playlist...');
                try {
                    const spotifyUrl = `https://open.spotify.com/playlist/${el.dataset.spotifyId}`;
                    const response = await fetch(`/api/search?q=${encodeURIComponent(spotifyUrl)}&type=playlist`);
                    const data = await response.json();
                    hideLoading();
                    if (data.tracks && data.results && data.results[0]) {
                        // Store tracks for next time
                        if (watched) {
                            watched.tracks = data.tracks.map(t => ({
                                id: t.id, name: t.name, artists: t.artists,
                                album: t.album || '', album_art: t.album_art || t.image || '/static/icon.svg',
                                album_id: t.album_id || '', isrc: t.isrc || t.id,
                                duration: t.duration || '0:00', source: t.source || 'spotify'
                            }));
                            saveWatchedPlaylists();
                        }
                        showDetailView(data.results[0], data.tracks);
                    }
                } catch (err) {
                    hideLoading();
                    showToast('Failed to load playlist');
                }
            }
        });
    });

    // Bind import button
    const importBtn = document.getElementById('import-playlist-btn');
    const importInput = document.getElementById('playlist-import-input');

    if (importBtn && importInput) {
        importBtn.addEventListener('click', () => importInput.click());
        importInput.addEventListener('change', (e) => {
            const file = e.target.files[0];
            if (file) handlePlaylistImport(file);
            e.target.value = ''; // Reset input
        });
    }

    // Click handlers
    grid.querySelectorAll('.playlist-item').forEach(el => {
        el.addEventListener('click', (e) => {
            if (e.target.closest('.delete-playlist-btn')) {
                e.stopPropagation();
                const id = el.dataset.playlistId;
                if (confirm('Delete this playlist?')) {
                    deletePlaylist(id);
                }
                return;
            }
            const playlist = state.playlists.find(p => p.id === el.dataset.playlistId);
            if (playlist) {
                showPlaylistDetail(playlist);
            }
        });
    });
}

// ========== MY PODCASTS PAGE ==========
function renderMyPodcastsView() {
    hideLoading();
    detailView.classList.add('hidden');
    resultsSection.classList.remove('hidden');

    if (state.podcastFavorites.length === 0) {
        resultsContainer.innerHTML = `
            <div class="empty-state">
                <span class="empty-icon">🎙️</span>
                <p>No saved podcasts yet</p>
                <p style="font-size: 0.9em; opacity: 0.7;">Search for podcasts and tap ❤️ to save them here</p>
                <button onclick="document.getElementById('search-input').focus(); document.getElementById('search-input').placeholder='Search podcasts...';" class="btn-secondary" style="margin-top: 12px; padding: 8px 20px;">🔍 Search Podcasts</button>
            </div>
        `;
        return;
    }

    // Build tag filter bar
    const allTags = getAllUsedTags();
    let tagFilterHtml = '';
    if (allTags.length > 0) {
        tagFilterHtml = `
            <div class="podcast-tag-filter" style="display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 16px;">
                <button class="podcast-tag-btn active" data-tag="all">All</button>
                ${allTags.map(tag => `<button class="podcast-tag-btn" data-tag="${escapeHtml(tag)}">${escapeHtml(tag)}</button>`).join('')}
            </div>
        `;
    }

    const headerHtml = `
        <div class="playlists-header" style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px;">
            <h2>🎙️ My Podcasts</h2>
        </div>
        ${tagFilterHtml}
    `;

    const grid = document.createElement('div');
    grid.className = 'results-grid';
    grid.id = 'my-podcasts-grid';

    state.podcastFavorites.forEach(podcast => {
        const tags = getPodcastTags(podcast.id);
        const tagStr = tags.length > 0 ? tags.join(', ') : '';
        grid.innerHTML += `
            <div class="album-item podcast-fav-item" data-podcast-id="${podcast.id}" data-tags="${escapeHtml(tags.join(','))}">
                <div class="album-art-container">
                    <img src="${podcast.artwork || '/static/icon.svg'}" alt="${escapeHtml(podcast.name)}" class="album-art" loading="lazy">
                </div>
                <div class="album-info">
                    <div class="album-name">${escapeHtml(podcast.name)}</div>
                    <div class="album-artist">${escapeHtml(podcast.artist || '')}</div>
                    ${tagStr ? `<div class="podcast-tag-display" style="font-size: 0.7rem; opacity: 0.6; margin-top: 2px;">${escapeHtml(tagStr)}</div>` : ''}
                </div>
                <button class="podcast-fav-btn favorited" title="Remove from My Podcasts" data-podcast-id="${podcast.id}">❤️</button>
                <button class="podcast-tag-edit-btn" title="Edit Tags" data-podcast-id="${podcast.id}">🏷️</button>
            </div>
        `;
    });

    resultsContainer.innerHTML = headerHtml;
    resultsContainer.appendChild(grid);

    // Render recent podcast history section if available
    if (state.podcastHistory.length > 0) {
        const historySection = document.createElement('div');
        historySection.style.marginTop = '32px';
        historySection.innerHTML = `
            <h3 style="margin-bottom: 12px; color: var(--text-primary);">🕐 Recently Played Episodes</h3>
            <div class="results-list" id="podcast-history-list">
                ${state.podcastHistory.slice(0, 10).map(ep => {
                    const resumePos = getEpisodePosition(ep.id);
                    const resumeText = resumePos > 0 ? ` • Resume at ${formatTime(resumePos)}` : '';
                    const played = isEpisodePlayed(ep.id);
                    return `
                        <div class="track-item ${played ? 'episode-played' : ''}" data-id="${ep.id}" style="cursor: pointer;">
                            <img class="track-album-art" src="${ep.album_art || '/static/icon.svg'}" alt="Art" loading="lazy">
                            <div class="track-info">
                                <p class="track-name">${escapeHtml(ep.name)}</p>
                                <p class="track-artist">${escapeHtml(ep.artists)}${resumeText}</p>
                            </div>
                            <div class="track-actions">
                                <span class="track-duration">${ep.duration || ''}</span>
                                <button class="episode-played-btn ${played ? 'played' : ''}" data-episode-id="${ep.id}" title="${played ? 'Mark as unplayed' : 'Mark as played'}">
                                    ${played ? '✅' : '⬜'}
                                </button>
                            </div>
                        </div>
                    `;
                }).join('')}
            </div>
        `;
        resultsContainer.appendChild(historySection);

        // Click handlers for history items
        historySection.querySelectorAll('.track-item').forEach(el => {
            el.addEventListener('click', (e) => {
                if (e.target.closest('.episode-played-btn')) return;
                const epId = el.dataset.id;
                const episode = state.podcastHistory.find(ep => ep.id === epId);
                if (episode) {
                    emit('playTrack', episode);
                }
            });
        });

        // Played toggle handlers
        historySection.querySelectorAll('.episode-played-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                const epId = btn.dataset.episodeId;
                const nowPlayed = toggleEpisodePlayed(epId);
                btn.textContent = nowPlayed ? '✅' : '⬜';
                btn.classList.toggle('played', nowPlayed);
                btn.title = nowPlayed ? 'Mark as unplayed' : 'Mark as played';
                btn.closest('.track-item').classList.toggle('episode-played', nowPlayed);
                showToast(nowPlayed ? 'Marked as played' : 'Marked as unplayed');
            });
        });
    }

    // Tag filter click handlers
    resultsContainer.querySelectorAll('.podcast-tag-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            resultsContainer.querySelectorAll('.podcast-tag-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            const tag = btn.dataset.tag;
            const items = grid.querySelectorAll('.podcast-fav-item');
            items.forEach(item => {
                if (tag === 'all') {
                    item.style.display = '';
                } else {
                    const itemTags = (item.dataset.tags || '').split(',');
                    item.style.display = itemTags.includes(tag) ? '' : 'none';
                }
            });
        });
    });

    // Click handlers for podcast cards
    grid.querySelectorAll('.podcast-fav-item').forEach(el => {
        el.addEventListener('click', (e) => {
            // Handle unfavorite button
            if (e.target.closest('.podcast-fav-btn')) {
                e.stopPropagation();
                const id = e.target.closest('.podcast-fav-btn').dataset.podcastId;
                if (confirm('Remove this podcast from favorites?')) {
                    removePodcastFavorite(id);
                    renderMyPodcastsView();
                }
                return;
            }
            // Handle tag edit button
            if (e.target.closest('.podcast-tag-edit-btn')) {
                e.stopPropagation();
                const podcastId = e.target.closest('.podcast-tag-edit-btn').dataset.podcastId;
                openPodcastTagEditor(podcastId);
                return;
            }
            // Open episode list
            const podcastId = el.dataset.podcastId;
            if (podcastId) openPodcastEpisodes(podcastId);
        });
    });
} // end renderMyPodcastsView

// ========== MY BOOKS PAGE ==========
function renderMyBooksView() {
    const resultsContainer = document.getElementById('results-container');

    // Header
    let html = `
        <div class="search-header">
            <h2>📚 My Books</h2>
            <div>You have ${state.audiobookFavorites.length} saved books</div>
        </div>
    `;

    if (state.audiobookFavorites.length === 0) {
        html += `
            <div style="text-align: center; padding: 40px 20px;">
                <p>No saved books yet</p>
                <p style="font-size: 0.9em; opacity: 0.7;">Search for audiobooks and tap ❤️ to save them here</p>
                <button onclick="document.getElementById('search-input').focus(); document.getElementById('search-input').placeholder='Search audiobooks...';" class="btn-secondary" style="margin-top: 12px; padding: 8px 20px;">🔍 Search Books</button>
            </div>
        `;
        resultsContainer.innerHTML = html;
        return;
    }

    // Grid
    html += `<div class="dashboard-grid dashboard-grid-albums" id="my-books-grid">`;

    state.audiobookFavorites.forEach(book => {
        const hasCachedTracks = book.cachedTracks && book.cachedTracks.length > 0;
        const badgeText = hasCachedTracks ? '▶ Ready' : '⏳ Not cached';
        const badgeStyle = hasCachedTracks
            ? 'background: rgba(29,185,84,0.85); color: #fff;'
            : 'background: rgba(255,255,255,0.15); color: rgba(255,255,255,0.6);';

        // Check if there's a resume position for any track in this book
        let resumeInfo = '';
        if (hasCachedTracks) {
            for (const t of book.cachedTracks) {
                const pos = getEpisodePosition(t.id);
                if (pos > 10) {
                    const mins = Math.floor(pos / 60);
                    const secs = Math.floor(pos % 60);
                    resumeInfo = `<p class="dashboard-card-subtitle" style="color: var(--accent-color); font-size: 0.75em;">⏱ Resume Ch.${t.track_number} @ ${mins}:${String(secs).padStart(2,'0')}</p>`;
                    break; // Show only the first chapter with a resume point
                }
            }
        }

        html += `
            <div class="dashboard-card album-card book-fav-item" data-id="${book.id}">
                <button class="podcast-fav-btn favorited" title="Remove from My Books" data-book-id="${book.id}" style="position: absolute; top: 10px; right: 10px; z-index: 5;">❤️</button>
                <span style="position: absolute; top: 10px; left: 10px; z-index: 5; padding: 2px 8px; border-radius: 4px; font-size: 0.7em; ${badgeStyle}">${badgeText}</span>
                <img src="${book.artwork}" alt="${escapeHtml(book.name)}" loading="lazy">
                <div class="dashboard-card-info">
                    <p class="dashboard-card-title">${escapeHtml(book.name)}</p>
                    <p class="dashboard-card-subtitle">${escapeHtml(book.artist)}</p>
                    ${resumeInfo}
                </div>
            </div>
        `;
    });

    html += `</div>`;
    resultsContainer.innerHTML = html;

    // Render recently played audiobook chapters
    if (state.audiobookHistory.length > 0) {
        const historySection = document.createElement('div');
        historySection.style.marginTop = '32px';
        historySection.innerHTML = `
            <h3 style="margin-bottom: 12px; color: var(--text-primary);">🕐 Recently Played Chapters</h3>
            <div class="results-list" id="audiobook-history-list">
                ${state.audiobookHistory.slice(0, 10).map(ep => {
                    const resumePos = getEpisodePosition(ep.id);
                    const resumeText = resumePos > 0 ? ` • Resume at ${formatTime(resumePos)}` : '';
                    return `
                        <div class="track-item" data-id="${ep.id}" style="cursor: pointer;">
                            <img class="track-album-art" src="${ep.album_art || '/static/icon.svg'}" alt="Art" loading="lazy">
                            <div class="track-info">
                                <p class="track-name">${escapeHtml(ep.name)}</p>
                                <p class="track-artist">${escapeHtml(ep.artists)}${resumeText}</p>
                            </div>
                            <div class="track-actions">
                                <span class="track-duration">${ep.duration || ''}</span>
                            </div>
                        </div>
                    `;
                }).join('')}
            </div>
        `;
        resultsContainer.appendChild(historySection);

        // Click handlers for audiobook history items
        historySection.querySelectorAll('.track-item').forEach(el => {
            el.addEventListener('click', () => {
                const epId = el.dataset.id;
                let episode = state.audiobookHistory.find(ep => ep.id === epId);
                if (episode) {
                    // If history entry has no stream URL, try to resolve from cached tracks
                    if (!episode.src && !episode.url) {
                        for (const book of state.audiobookFavorites) {
                            if (book.cachedTracks) {
                                const cached = book.cachedTracks.find(t => t.id === epId);
                                if (cached) {
                                    episode = { ...episode, ...cached };
                                    break;
                                }
                            }
                        }
                    }
                    emit('playTrack', episode);
                }
            });
        });
    }

    // Click handlers
    const grid = document.getElementById('my-books-grid');
    grid.querySelectorAll('.book-fav-item').forEach(el => {
        el.addEventListener('click', (e) => {
            // Unfavorite
            if (e.target.closest('.podcast-fav-btn')) {
                e.stopPropagation();
                const id = e.target.closest('.podcast-fav-btn').dataset.bookId;
                if (confirm('Remove this book from favorites?')) {
                    removeAudiobookFavorite(id);
                    renderMyBooksView();
                }
                return;
            }
            // Open book info modal
            const bookId = el.dataset.id;
            const book = state.audiobookFavorites.find(b => b.id === bookId);
            if (book) {
                openBookInfoModal(book);
            } else if (bookId) {
                openAudiobook(bookId);
            }
        });
    });
}
window.renderMyBooksView = renderMyBooksView;

// ========== BOOK INFO MODAL ==========
function openBookInfoModal(book) {
    const modal = document.getElementById('book-info-modal');
    const overlay = modal.querySelector('.book-info-overlay');
    const closeBtn = document.getElementById('book-info-close');

    // Populate header
    document.getElementById('book-info-art').src = book.artwork || '/static/icon.svg';
    document.getElementById('book-info-title').textContent = book.name;
    document.getElementById('book-info-author').textContent = book.artist || 'Unknown Author';

    // Badges
    const badgesEl = document.getElementById('book-info-badges');
    let badgeHtml = '';
    if (book.cachedTracks && book.cachedTracks.length > 0) {
        badgeHtml += `<span class="book-info-badge">📖 ${book.cachedTracks.length} chapters</span>`;
        badgeHtml += `<span class="book-info-badge" style="color: #1db954;">▶ Ready to play</span>`;
    } else {
        badgeHtml += `<span class="book-info-badge">⏳ Not yet downloaded</span>`;
    }
    badgesEl.innerHTML = badgeHtml;

    // Description
    const descEl = document.getElementById('book-info-description');
    descEl.textContent = book.description || 'No description available. Click "Goodreads Reviews" tab for book info.';

    // Reset tabs
    modal.querySelectorAll('.book-info-tab').forEach(t => t.classList.remove('active'));
    modal.querySelector('.book-info-tab[data-tab="description"]').classList.add('active');
    document.getElementById('book-info-desc-tab').classList.add('active');
    document.getElementById('book-info-reviews-tab').classList.remove('active');

    // Reset Goodreads section
    document.getElementById('book-info-goodreads').innerHTML = `
        <div class="book-info-loading">
            <div class="spinner"></div>
            <p>Fetching Goodreads data...</p>
        </div>
    `;

    // Tab switching
    modal.querySelectorAll('.book-info-tab').forEach(tab => {
        tab.onclick = () => {
            modal.querySelectorAll('.book-info-tab').forEach(t => t.classList.remove('active'));
            tab.classList.add('active');
            const target = tab.dataset.tab;
            document.getElementById('book-info-desc-tab').classList.toggle('active', target === 'description');
            document.getElementById('book-info-reviews-tab').classList.toggle('active', target === 'reviews');

            // Lazy-load Goodreads data on first tab click
            if (target === 'reviews' && !modal._goodreadsLoaded) {
                modal._goodreadsLoaded = true;
                fetchGoodreadsData(book.name, book.artist);
            }
        };
    });
    modal._goodreadsLoaded = false;

    // Play button
    const playBtn = document.getElementById('book-info-play-btn');
    // Check for resume position — find the chapter with a saved position
    let resumeText = '▶ Play';
    let resumeChapterIndex = -1;
    if (book.cachedTracks && book.cachedTracks.length > 0) {
        for (let i = 0; i < book.cachedTracks.length; i++) {
            const pos = getEpisodePosition(book.cachedTracks[i].id);
            if (pos > 10) {
                const mins = Math.floor(pos / 60);
                const secs = Math.floor(pos % 60);
                resumeText = `▶ Resume Ch.${book.cachedTracks[i].track_number} @ ${mins}:${String(secs).padStart(2, '0')}`;
                resumeChapterIndex = i;
                break;
            }
        }
    }
    playBtn.textContent = resumeText;

    playBtn.onclick = () => {
        modal.classList.add('hidden');
        if (book.cachedTracks && book.cachedTracks.length > 0) {
            // Load all chapters into the queue
            state.queue = book.cachedTracks.map(t => ({...t}));
            // Jump to the resume chapter, or start from the beginning
            const startIdx = resumeChapterIndex >= 0 ? resumeChapterIndex : 0;
            state.currentIndex = startIdx;
            emit('updateQueueUI');
            emit('loadTrack', state.queue[startIdx]);
        } else {
            openAudiobook(book.id);
        }
    };

    // Chapters button
    const chaptersBtn = document.getElementById('book-info-chapters-btn');
    if (book.cachedTracks && book.cachedTracks.length > 0) {
        chaptersBtn.style.display = '';
        chaptersBtn.onclick = () => {
            modal.classList.add('hidden');
            const albumData = {
                id: `ab_cached_${book.id}`,
                name: book.name,
                artists: 'Audiobook',
                image: book.artwork || '/static/icon.svg',
                is_playlist: false
            };
            showDetailView(albumData, book.cachedTracks);
        };
    } else {
        chaptersBtn.style.display = 'none';
    }

    // Delete from Cloud button
    const deleteBtn = document.getElementById('book-info-delete-btn');
    // Show if we have IDs OR if we have cached tracks (we can pull IDs from them)
    if (book.folder_id || book.premiumize_id || (book.cachedTracks && book.cachedTracks.length > 0)) {
        deleteBtn.classList.remove('hidden');
        deleteBtn.onclick = async () => {
            if (!confirm(`Are you sure you want to delete "${book.name}" from your Premiumize cloud? This cannot be undone.`)) return;

            // Try to get ID from various places
            let itemId = book.folder_id || book.premiumize_id;
            let isTransfer = !!book.premiumize_id && !book.folder_id;

            if (!itemId && book.cachedTracks && book.cachedTracks.length > 0) {
                // Try to extract folder/file ID from the first track's URL
                const track = book.cachedTracks[0];
                const streamUrl = track.src || (track.isrc && track.isrc.startsWith('LINK:') ? atob(track.isrc.replace('LINK:', '').replace(/-/g, '+').replace(/_/g, '/')) : '');

                if (streamUrl.includes('premiumize.me')) {
                    const urlObj = new URL(streamUrl);
                    itemId = urlObj.searchParams.get('id'); // Common in direct links
                }
            }

            if (!itemId) {
                showToast('Could not find Cloud ID for this book. Try re-searching it.');
                return;
            }

            deleteBtn.disabled = true;
            deleteBtn.textContent = '⏳ Deleting...';

            try {
                const response = await fetch('/api/premiumize/delete', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ id: itemId, is_transfer: isTransfer })
                });
                const data = await response.json();

                if (response.ok && data.status === 'success') {
                    showToast(`Deleted "${book.name}" from cloud`);
                    // Remove from favorites/cached tracks since it's gone from source
                    removeAudiobookFavorite(book.id);
                    modal.classList.add('hidden');
                    renderMyBooksView();
                } else {
                    throw new Error(data.detail || 'Delete failed');
                }
            } catch (err) {
                console.error('Delete error:', err);
                showToast(`Failed to delete: ${err.message}`);
                deleteBtn.disabled = false;
                deleteBtn.textContent = '🗑 Delete from Cloud';
            }
        };
    } else {
        deleteBtn.classList.add('hidden');
    }

    // Close handlers
    const closeModal = () => modal.classList.add('hidden');
    closeBtn.onclick = closeModal;
    overlay.onclick = closeModal;

    // Show modal
    modal.classList.remove('hidden');
}

async function fetchGoodreadsData(title, author) {
    const container = document.getElementById('book-info-goodreads');
    const badgesEl = document.getElementById('book-info-badges');

    try {
        const params = new URLSearchParams({ title });
        if (author && author.toLowerCase() !== 'audiobookbay') params.set('author', author);

        const resp = await fetch(`/api/goodreads/book?${params}`);
        const data = await resp.json();

        if (!data.found) {
            container.innerHTML = `
                <div class="book-info-no-reviews">
                    <p>📚 No Goodreads data found for this book</p>
                    <a href="https://www.goodreads.com/search?q=${encodeURIComponent(title)}" target="_blank" rel="noopener" class="book-info-gr-link" style="margin-top: 10px;">🔍 Search on Goodreads</a>
                </div>
            `;
            return;
        }

        // Update badges with Goodreads rating
        if (data.rating) {
            const starCount = Math.round(parseFloat(data.rating));
            const stars = '★'.repeat(starCount) + '☆'.repeat(5 - starCount);
            badgesEl.innerHTML += `<span class="book-info-badge rating">⭐ ${data.rating}</span>`;
            if (data.rating_count) {
                badgesEl.innerHTML += `<span class="book-info-badge">${data.rating_count}</span>`;
            }
        }

        // Add genres
        if (data.genres && data.genres.length > 0) {
            data.genres.slice(0, 4).forEach(g => {
                badgesEl.innerHTML += `<span class="book-info-badge genres">${g}</span>`;
            });
        }

        // Update description if Goodreads has a better one
        const descEl = document.getElementById('book-info-description');
        if (data.description && data.description.length > (descEl.textContent || '').length) {
            descEl.textContent = data.description;
        }

        // Build reviews section
        let html = '';

        // Rating header
        if (data.rating) {
            const starCount = Math.round(parseFloat(data.rating));
            const starsDisplay = '★'.repeat(starCount) + '☆'.repeat(5 - starCount);
            html += `
                <div class="book-info-gr-header">
                    <div class="book-info-gr-rating">
                        <span class="book-info-gr-stars">${starsDisplay}</span>
                        <span class="book-info-gr-score">${data.rating}</span>
                        <span class="book-info-gr-count">${data.rating_count || ''} · ${data.review_count || ''}</span>
                    </div>
                    <a href="${data.url}" target="_blank" rel="noopener" class="book-info-gr-link">📖 Goodreads</a>
                </div>
            `;
        }

        // Reviews
        if (data.reviews && data.reviews.length > 0) {
            data.reviews.forEach(review => {
                const reviewStars = review.rating ? '★'.repeat(review.rating) + '☆'.repeat(5 - review.rating) : '';
                html += `
                    <div class="book-info-review">
                        <div class="book-info-review-header">
                            <span class="book-info-reviewer">${escapeHtml(review.reviewer || 'Anonymous')}</span>
                            ${reviewStars ? `<span class="book-info-review-stars">${reviewStars}</span>` : ''}
                        </div>
                        ${review.date ? `<div class="book-info-review-date">${escapeHtml(review.date)}</div>` : ''}
                        <div class="book-info-review-text">${escapeHtml(review.text || 'No text')}</div>
                    </div>
                `;
            });
        } else {
            html += `<div class="book-info-no-reviews"><p>No reviews available</p></div>`;
        }

        // View all on Goodreads link
        if (data.url) {
            html += `
                <div style="text-align: center; margin-top: 16px;">
                    <a href="${data.url}" target="_blank" rel="noopener" class="book-info-gr-link">📖 View all reviews on Goodreads</a>
                </div>
            `;
        }

        container.innerHTML = html;

    } catch (err) {
        console.error('Goodreads fetch error:', err);
        container.innerHTML = `
            <div class="book-info-no-reviews">
                <p>⚠️ Failed to load Goodreads data</p>
                <a href="https://www.goodreads.com/search?q=${encodeURIComponent(title)}" target="_blank" rel="noopener" class="book-info-gr-link" style="margin-top: 10px;">🔍 Search on Goodreads manually</a>
            </div>
        `;
    }
}

// Tag editor modal
function savePodcastFavorites() {
    // Use the same key as state.js (freedify_podcasts) so saves persist across reloads
    localStorage.setItem('freedify_podcasts', JSON.stringify(state.podcastFavorites));
}

function openPodcastTagEditor(podcastId) {
    const podcast = state.podcastFavorites.find(p => p.id === podcastId);
    if (!podcast) return;

    const currentTags = getPodcastTags(podcastId);
    const allTags = getAllUsedTags();

    const tagInput = prompt(
        `Edit tags for "${podcast.name}"\n\nCurrent tags: ${currentTags.join(', ') || '(none)'}\n\nEnter tags separated by commas (e.g. Tech, Science, Comedy):`,
        currentTags.join(', ')
    );

    if (tagInput !== null) {
        const newTags = tagInput.split(',').map(t => t.trim()).filter(t => t.length > 0);
        setPodcastTags(podcastId, newTags);
        showToast(`Tags updated for "${podcast.name}"`);
        renderMyPodcastsView();
    }
}

function showPlaylistDetail(playlist) {
    // Track which playlist is being viewed
    state.currentPlaylistView = playlist.id;

    // Reuse the existing detail view
    const albumData = {
        id: playlist.id,
        name: playlist.name,
        artists: `${playlist.tracks.length} tracks`,
        image: playlist.tracks[0]?.album_art || '/static/icon.svg',
        is_playlist: true,
        is_user_playlist: true  // Flag to indicate this is a user-created playlist (for delete buttons)
    };
    showDetailView(albumData, playlist.tracks);
}

// ========== OPEN ALBUM ==========
async function openAlbum(albumId) {
    // Intercept setlists to open special modal
    if (albumId.startsWith('setlist_')) {
        openSetlistModal(albumId);
        return;
    }

    showLoading('Loading album...');
    try {
        const response = await fetch(`/api/album/${albumId}`);
        const album = await response.json();
        if (!response.ok) throw new Error(album.detail);

        hideLoading();

        // Store album info in state for batch downloads
        state.detailName = album.name || '';
        state.detailArtist = album.artists || '';

        showAlbumModal(album);
    } catch (error) {
        console.error('Failed to load album:', error);
        showError('Failed to load album');
    }
}

// Open podcast episodes in detail view (not album modal)
async function openPodcastEpisodes(podcastId) {
    showLoading('Loading podcast episodes...');
    try {
        const response = await fetch(`/api/album/${podcastId}`);
        const podcast = await response.json();
        if (!response.ok) throw new Error(podcast.detail);

        hideLoading();

        // Use detail view for podcasts (allows clicking episodes for info modal)
        showDetailView(podcast, podcast.tracks || []);

        // After detail view renders, inject podcast-specific controls
        setTimeout(() => {
        // Add favorite toggle button to detail header
        // Always remove old button first so we get a fresh handler bound to this podcast
        const detailActions = document.querySelector('.detail-actions');
        if (detailActions) {
            detailActions.querySelector('.podcast-detail-fav-btn')?.remove();
            const isFav = isPodcastFavorited(podcastId);
            const favBtn = document.createElement('button');
            favBtn.className = `detail-add-library-btn podcast-detail-fav-btn ${isFav ? 'saved' : ''}`;
            favBtn.innerHTML = isFav ? '❤️ In My Podcasts' : '🤍 Save to My Podcasts';
            favBtn.addEventListener('click', () => {
                const nowFav = togglePodcastFavorite(podcast);
                favBtn.innerHTML = nowFav ? '❤️ In My Podcasts' : '🤍 Save to My Podcasts';
                favBtn.classList.toggle('saved', nowFav);
            });
            detailActions.appendChild(favBtn);
        }

            // Add played/download buttons to each episode row
            const trackItems = document.querySelectorAll('#detail-tracks .track-item');
            const tracks = podcast.tracks || [];
            trackItems.forEach((el, i) => {
                const track = tracks[i];
                if (!track || track.source !== 'podcast') return;

                const actionsDiv = el.querySelector('.track-actions');
                if (!actionsDiv || actionsDiv.querySelector('.episode-played-btn')) return;

                // Mark as played button
                const played = isEpisodePlayed(track.id);
                const playedBtn = document.createElement('button');
                playedBtn.className = `episode-played-btn ${played ? 'played' : ''}`;
                playedBtn.textContent = played ? '✅' : '⬜';
                playedBtn.title = played ? 'Mark as unplayed' : 'Mark as played';
                playedBtn.dataset.episodeId = track.id;
                playedBtn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    const nowPlayed = toggleEpisodePlayed(track.id);
                    playedBtn.textContent = nowPlayed ? '✅' : '⬜';
                    playedBtn.classList.toggle('played', nowPlayed);
                    playedBtn.title = nowPlayed ? 'Mark as unplayed' : 'Mark as played';
                    el.classList.toggle('episode-played', nowPlayed);
                });
                actionsDiv.insertBefore(playedBtn, actionsDiv.firstChild);

                // Add played visual
                if (played) el.classList.add('episode-played');

                // Resume position indicator
                const resumePos = getEpisodePosition(track.id);
                if (resumePos > 10) {
                    const infoDiv = el.querySelector('.track-artist');
                    if (infoDiv && !infoDiv.textContent.includes('Resume')) {
                        infoDiv.textContent += ` • Resume at ${formatTime(resumePos)}`;
                    }
                }
            });
        }, 100);
    } catch (error) {
        console.error('Failed to load podcast:', error);
        showError('Failed to load podcast');
    }
}

// ========== SETLIST MODAL ==========
const setlistModal = $('#setlist-modal');
const setlistCloseBtn = $('#setlist-close-btn');
const setlistInfo = $('#setlist-info');
const setlistTracks = $('#setlist-tracks');
const setlistPlayBtn = $('#setlist-play-btn');
let currentSetlist = null;

if (setlistCloseBtn) {
    setlistCloseBtn.addEventListener('click', () => {
        setlistModal.classList.add('hidden');
    });
}

if (setlistPlayBtn) {
    setlistPlayBtn.addEventListener('click', () => {
        if (currentSetlist) {
            setlistModal.classList.add('hidden');
            // Check if we have a direct audio source URL or need to search
            if (currentSetlist.audio_url) {
                // Direct import (Phish.in) - use performSearch which handles URLs
                emit('performSearch', currentSetlist.audio_url);
            } else if (currentSetlist.audio_search) {
                // Search Archive.org (Artist Date)
                emit('performSearch', currentSetlist.audio_search);
            } else {
                showError("No audio source found for this setlist.");
            }
        }
    });
}

async function openSetlistModal(setlistId) {
    // Get modal elements fresh each time
    const modal = document.getElementById('setlist-modal');
    const infoEl = document.getElementById('setlist-info');
    const tracksEl = document.getElementById('setlist-tracks');
    const playBtn = document.getElementById('setlist-play-btn');

    if (!modal) {
        showError("Setlist modal not available");
        return;
    }

    showLoading('Fetching setlist...');
    try {
        // Use existing endpoint which returns formatted setlist
        const response = await fetch(`/api/album/${setlistId}`);
        const setlist = await response.json();

        if (!response.ok) throw new Error(setlist.detail);

        currentSetlist = setlist;
        hideLoading();

        // Render Modal Content
        infoEl.innerHTML = `
            <div style="text-align: center; margin-bottom: 20px;">
                <h2 style="font-size: 1.5rem; margin-bottom: 4px;">${escapeHtml(setlist.artists)}</h2>
                <p style="font-size: 1.1rem; color: var(--text-secondary); margin-bottom: 4px;">${escapeHtml(setlist.venue)}</p>
                <p style="font-size: 1rem; color: var(--accent-color);">${setlist.date || setlist.release_date}</p>
                <p style="font-size: 0.9rem; color: var(--text-tertiary); margin-top: 8px;">
                    ${setlist.city}
                </p>
            </div>
        `;

        tracksEl.innerHTML = setlist.tracks.map((track, i) => `
            <div class="setlist-track-item" style="display: flex; padding: 8px 0; border-bottom: 1px solid var(--border-color);">
                <span style="color: var(--text-tertiary); width: 30px; text-align: right; margin-right: 12px; font-variant-numeric: tabular-nums;">${i + 1}</span>
                <div style="flex: 1;">
                    <div style="display: flex; justify-content: space-between; align-items: baseline;">
                        <span style="font-weight: 500;">${escapeHtml(track.name)}</span>
                        ${track.set_name ? `<span style="font-size: 0.75rem; color: var(--text-tertiary); background: var(--bg-secondary); padding: 2px 6px; border-radius: 4px;">${track.set_name}</span>` : ''}
                    </div>
                    ${track.info ? `<p style="font-size: 0.8rem; color: var(--text-tertiary); margin: 2px 0 0;">${escapeHtml(track.info)}</p>` : ''}
                    ${track.cover_info ? `<p style="font-size: 0.8rem; color: var(--text-tertiary); margin: 2px 0 0;">(Cover of ${escapeHtml(track.cover_info)})</p>` : ''}
                </div>
            </div>
        `).join('');

        // Show audio source button label
        if (setlist.audio_source === 'phish.in') {
            playBtn.textContent = "🎧 Listen on Phish.in";
        } else {
            playBtn.textContent = "🎧 Search on Archive.org";
        }

        modal.classList.remove('hidden');

    } catch (error) {
        console.error(error);
        showError('Failed to load setlist');
    }
}

// ========== ALBUM DETAILS MODAL ==========
const albumModal = $('#album-modal');
const albumModalClose = $('#album-modal-close');
const albumModalOverlay = albumModal?.querySelector('.album-modal-overlay');
let currentAlbumData = null;

// Close modal
if (albumModalClose) {
    albumModalClose.addEventListener('click', () => {
        albumModal.classList.add('hidden');
    });
}

// Close on overlay click
if (albumModalOverlay) {
    albumModalOverlay.addEventListener('click', () => {
        albumModal.classList.add('hidden');
    });
}

// Tab switching
const albumTabs = albumModal?.querySelectorAll('.album-tab');
albumTabs?.forEach(tab => {
    tab.addEventListener('click', () => {
        albumTabs.forEach(t => t.classList.remove('active'));
        tab.classList.add('active');

        const tabName = tab.dataset.tab;
        if (tabName === 'tracks') {
            $('#album-modal-tracks')?.classList.remove('hidden');
            $('#album-modal-info-tab')?.classList.add('hidden');
        } else {
            $('#album-modal-tracks')?.classList.add('hidden');
            $('#album-modal-info-tab')?.classList.remove('hidden');
        }
    });
});

// Action buttons
$('#album-play-btn')?.addEventListener('click', () => {
    if (currentAlbumData?.tracks?.length) {
        state.queue = [...currentAlbumData.tracks];
        state.currentIndex = 0;
        emit('updateQueueUI');
        emit('loadTrack', state.queue[0]);
        albumModal.classList.add('hidden');
        showToast(`Playing "${currentAlbumData.name}"`);
    }
});

$('#album-queue-btn')?.addEventListener('click', () => {
    if (currentAlbumData?.tracks?.length) {
        state.queue.push(...currentAlbumData.tracks);
        emit('updateQueueUI');
        albumModal.classList.add('hidden');
        showToast(`Added ${currentAlbumData.tracks.length} tracks to queue`);
    }
});

$('#album-download-btn')?.addEventListener('click', () => {
    if (currentAlbumData) {
        // Get only selected tracks based on checked checkboxes
        const checkedIndices = new Set();
        document.querySelectorAll('#album-modal-tracks .track-select-cb:checked').forEach(cb => {
            checkedIndices.add(parseInt(cb.dataset.index));
        });

        const selectedTracks = currentAlbumData.tracks.filter((_, i) => checkedIndices.has(i));

        if (selectedTracks.length === 0) {
            showToast('Please select at least one track to download');
            return;
        }

        isBatchDownload = true;
        trackToDownload = null;
        state.detailTracks = selectedTracks;
        downloadTrackName.textContent = `${currentAlbumData.name} (${selectedTracks.length} of ${currentAlbumData.tracks.length} tracks)`;
        downloadModal.classList.remove('hidden');
        albumModal.classList.add('hidden');
    }
});

$('#album-playlist-btn')?.addEventListener('click', () => {
    if (currentAlbumData?.tracks?.length) {
        // Open add to playlist modal with all album tracks
        if (typeof openAddToPlaylistModal === 'function') {
            openAddToPlaylistModal(currentAlbumData.tracks, currentAlbumData.name);
        } else {
            showToast('Playlist feature coming soon');
        }
    }
});

function showAlbumModal(album) {
    if (!albumModal) return;

    currentAlbumData = album;
    const tracks = album.tracks || [];

    // Populate modal data
    $('#album-modal-art').src = album.album_art || album.image || '/static/icon.svg';
    $('#album-modal-title').textContent = album.name || 'Unknown Album';
    $('#album-modal-artist').textContent = album.artists || 'Unknown Artist';

    // Metadata pills
    const date = album.release_date || '';
    const genre = album.genres?.[0] || album.genre || '';
    const trackCount = tracks.length || album.total_tracks || 0;
    const totalDuration = tracks.reduce((sum, t) => sum + (parseDuration(t.duration) || 0), 0);
    const durationMins = Math.round(totalDuration / 60);

    $('#album-modal-date').textContent = `📅 ${date || 'Unknown'}`;
    $('#album-modal-trackcount').textContent = `🎵 ${trackCount} tracks`;
    $('#album-modal-duration').textContent = `⏱️ ${durationMins || '??'} min`;

    // Add All to Library button
    const allInLibrary = tracks.length > 0 && tracks.every(t => isInLibrary(t.id));
    const addToLibBtn = $('#album-add-to-library-btn');
    if (addToLibBtn) {
        addToLibBtn.textContent = allInLibrary ? '✓ In Library' : '★ Add to Library';
        addToLibBtn.disabled = allInLibrary;
        addToLibBtn.classList.toggle('saved', allInLibrary);
        addToLibBtn.onclick = () => {
            addAllToLibrary(tracks);
            // Update button state
            addToLibBtn.textContent = '★ In Library';
            addToLibBtn.disabled = true;
            addToLibBtn.classList.add('saved');
            // Update star buttons in track list
            tracksContainer.querySelectorAll('.star-btn').forEach(btn => {
                btn.textContent = '★';
                btn.classList.add('starred');
                btn.title = 'Remove from Library';
            });
        };
    }

    // Quality badge removed — showed inaccurate static defaults

    // Render track list with selection checkboxes for batch download
    const tracksContainer = $('#album-modal-tracks');
    tracksContainer.innerHTML = tracks.map((track, i) => {
        const isStarred = isInLibrary(track.id);
        return `
        <div class="album-modal-track" data-index="${i}">
            <div class="track-row-top">
                <input type="checkbox" class="track-select-cb" data-index="${i}" checked title="Select for download">
                <span class="album-track-num">${i + 1}.</span>
                <button class="album-track-play" title="Play" data-index="${i}">▶</button>
                <div class="album-track-info">
                    <p class="album-track-name">${escapeHtml(track.name)}</p>
                </div>
            </div>
            <div class="track-row-actions">
                <button class="star-btn ${isStarred ? 'starred' : ''}" data-track-id="${track.id}" data-index="${i}" title="${isStarred ? 'Remove from Library' : 'Add to Library'}">${isStarred ? '★' : '☆'}</button>
                <button class="album-track-playlist" title="Add to Playlist" data-index="${i}">♡</button>
                <span class="album-track-duration">${typeof track.duration === 'number' ? formatTime(track.duration) : (track.duration || '--:--')}</span>
                <button title="Add to Queue" data-action="queue" data-index="${i}">+</button>
                <button title="Download" data-action="download" data-index="${i}">⬇</button>
            </div>
        </div>
    `}).join('');

    // Track click handlers
    tracksContainer.querySelectorAll('.album-track-play').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            const idx = parseInt(btn.dataset.index);
            state.queue = [...tracks];
            state.currentIndex = idx;
            emit('updateQueueUI');
            emit('loadTrack', tracks[idx]);
            albumModal.classList.add('hidden');
        });
    });

    tracksContainer.querySelectorAll('[data-action="queue"]').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            const idx = parseInt(btn.dataset.index);
            state.queue.push(tracks[idx]);
            emit('updateQueueUI');
            showToast(`Added "${tracks[idx].name}" to queue`);
        });
    });

    // Playlist button handler
    tracksContainer.querySelectorAll('.album-track-playlist').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            const idx = parseInt(btn.dataset.index);
            const track = tracks[idx];
            // Open add to playlist modal
            if (typeof openAddToPlaylistModal === 'function') {
                openAddToPlaylistModal(track);
            } else {
                showToast('Playlist feature coming soon');
            }
        });
    });

    tracksContainer.querySelectorAll('[data-action="download"]').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            const idx = parseInt(btn.dataset.index);
            // Hide album modal first so download modal appears on top
            albumModal.classList.add('hidden');
            // Store album data so we can reopen after download closes
            state.pendingAlbumReopen = { album, tracks };
            openDownloadModal(encodeURIComponent(JSON.stringify(tracks[idx])));
        });
    });

    // Star button handler for album modal
    tracksContainer.querySelectorAll('.star-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            const idx = parseInt(btn.dataset.index);
            const track = tracks[idx];
            if (track) {
                const nowStarred = toggleLibrary(track);
                btn.textContent = nowStarred ? '★' : '☆';
                btn.classList.toggle('starred', nowStarred);
                btn.title = nowStarred ? 'Remove from Library' : 'Add to Library';
            }
        });
    });

    // Track selection handlers
    const selectAllCb = $('#select-all-tracks');
    const selectionCount = $('#track-selection-count');

    function updateSelectionCount() {
        const checked = tracksContainer.querySelectorAll('.track-select-cb:checked').length;
        const total = tracks.length;
        selectionCount.textContent = `${checked} of ${total} selected`;

        // Update Select All checkbox state
        if (selectAllCb) {
            selectAllCb.checked = checked === total;
            selectAllCb.indeterminate = checked > 0 && checked < total;
        }
    }

    // Select All toggle
    if (selectAllCb) {
        selectAllCb.addEventListener('change', () => {
            const isChecked = selectAllCb.checked;
            tracksContainer.querySelectorAll('.track-select-cb').forEach(cb => {
                cb.checked = isChecked;
            });
            updateSelectionCount();
        });
    }

    // Individual checkbox changes
    tracksContainer.querySelectorAll('.track-select-cb').forEach(cb => {
        cb.addEventListener('change', updateSelectionCount);
    });

    // Initial count
    updateSelectionCount();

    // Album Info tab
    $('#album-modal-description').textContent = album.description ||
        `${album.name} by ${album.artists}. Released ${date}. ${trackCount} tracks.`;

    // Reset to tracks tab
    albumTabs?.forEach(t => t.classList.remove('active'));
    albumModal.querySelector('[data-tab="tracks"]')?.classList.add('active');
    $('#album-modal-tracks')?.classList.remove('hidden');
    $('#album-modal-info-tab')?.classList.add('hidden');

    // Show modal
    albumModal.classList.remove('hidden');
}

async function openArtist(artistId) {
    showLoading('Loading artist...');
    try {
        const response = await fetch(`/api/artist/${artistId}`);
        const artist = await response.json();
        if (!response.ok) throw new Error(artist.detail);

        hideLoading();
        showDetailView(artist, artist.tracks);
    } catch (error) {
        showError('Failed to load artist');
    }
}

// Updated showDetailView to handle downloads
function showDetailView(item, tracks) {
    state.detailTracks = tracks || [];

    // Store name and artist for batch downloads
    state.detailName = item.name || 'Playlist';
    // Determine type: Only force album tagging if explicitly an album AND has a release date.
    // Playlists, Artists, and Custom Lists should preserve original track album tags.
    state.detailType = (item.type === 'album' && item.release_date) ? 'album' : 'playlist';

    // Handle owner if it's an object (Spotify playlist) or string
    let artistName = item.artists || '';
    if (!artistName && item.owner) {
        artistName = typeof item.owner === 'object' ? item.owner.display_name : item.owner;
    }
    state.detailArtist = artistName || '';

    // Store release year for metadata embedding
    state.detailReleaseYear = item.release_date?.substring(0, 4) || '';
    // Store cover art for metadata embedding (fallback for tracks)
    state.detailCover = item.album_art || item.image || null;

    // Render info section
    const isArtist = item.type === 'artist';
    const isUserPlaylist = item.is_user_playlist || false;
    const image = item.album_art || item.image || '/static/icon.svg';
    const subtitle = item.artists || item.owner || (item.genres?.slice(0, 2).join(', ')) || '';
    const stats = item.total_tracks ? `${item.total_tracks} tracks` :
                  item.followers ? `${(item.followers / 1000).toFixed(0)}K followers` : '';

    // Check if all tracks already in library
    const allInLibrary = tracks.length > 0 && tracks.every(t => isInLibrary(t.id));

    detailInfo.innerHTML = `
        <img class="detail-art${isArtist ? ' artist-art' : ''}" src="${image}" alt="Cover">
        <div class="detail-meta">
            <p class="detail-name">${escapeHtml(item.name)}</p>
            <p class="detail-artist">${escapeHtml(subtitle)}</p>
            <p class="detail-stats">${stats}</p>
            <div class="detail-actions">
                <button class="detail-add-library-btn ${allInLibrary ? 'saved' : ''}" ${allInLibrary ? 'disabled' : ''}>
                    ${allInLibrary ? '★ In Library' : '★ Add All to Library'}
                </button>
                <button class="detail-add-playlist-btn" title="Add all to playlist">
                    ♡ Add All to Playlist
                </button>
                ${(item.type === 'playlist' && item.source === 'spotify' && item.id && !item.is_user_playlist) ? `
                <button class="detail-watch-btn ${isWatchedPlaylist(item.id) ? 'watched' : ''}" title="${isWatchedPlaylist(item.id) ? 'Stop watching this playlist' : 'Watch for new tracks'}">
                    ${isWatchedPlaylist(item.id) ? '👁 Watching ✓' : '👁 Watch Playlist'}
                </button>
                ` : ''}
            </div>
        </div>
    `;

    // Wire up Add All to Library button
    const addLibBtn = detailInfo.querySelector('.detail-add-library-btn');
    if (addLibBtn && !allInLibrary) {
        addLibBtn.addEventListener('click', () => {
            addAllToLibrary(tracks);
            addLibBtn.textContent = '★ In Library';
            addLibBtn.disabled = true;
            addLibBtn.classList.add('saved');
            // Update star buttons
            detailTracks.querySelectorAll('.star-btn').forEach(btn => {
                btn.textContent = '★';
                btn.classList.add('starred');
                btn.title = 'Remove from Library';
            });
        });
    }

    // Wire up Add All to Playlist button
    const addPlaylistBtn = detailInfo.querySelector('.detail-add-playlist-btn');
    if (addPlaylistBtn && tracks.length > 0) {
        addPlaylistBtn.addEventListener('click', () => {
            if (typeof openAddToPlaylistModal === 'function') {
                openAddToPlaylistModal(tracks);
            }
        });
    }

    // Wire up Watch Playlist button
    const watchBtn = detailInfo.querySelector('.detail-watch-btn');
    if (watchBtn && item.id) {
        watchBtn.addEventListener('click', () => {
            if (isWatchedPlaylist(item.id)) {
                unwatchPlaylist(item.id);
                watchBtn.textContent = '👁 Watch Playlist';
                watchBtn.classList.remove('watched');
                watchBtn.title = 'Watch for new tracks';
            } else {
                watchPlaylist(item.id, item.name, image, tracks);
                watchBtn.textContent = '👁 Watching ✓';
                watchBtn.classList.add('watched');
                watchBtn.title = 'Stop watching this playlist';
            }
        });
    }

    // Render tracks with download button (and delete for user playlists)
    detailTracks.innerHTML = tracks.map((t, i) => {
        const isStarred = isInLibrary(t.id);
        return `
        <div class="track-item" data-index="${i}" data-track-id="${t.id}">
            <img class="track-album-art" src="${t.album_art || image}" alt="Art" loading="lazy">
            <div class="track-info">
                <p class="track-name">${escapeHtml(t.name)}</p>
                <p class="track-artist">${escapeHtml(t.artists)}</p>
            </div>

            <div class="track-actions">
                ${renderDJBadgeForTrack(t)}
                <span class="track-duration">${t.duration}</span>
                <button class="star-btn ${isStarred ? 'starred' : ''}" data-track-id="${t.id}" title="${isStarred ? 'Remove from Library' : 'Add to Library'}">${isStarred ? '★' : '☆'}</button>
                <button class="playlist-btn" title="Add to Playlist" onclick="event.stopPropagation(); if(typeof window.openAddToPlaylistModal === 'function') window.openAddToPlaylistModal(JSON.parse(decodeURIComponent('${encodeURIComponent(JSON.stringify(t)).replace(/'/g, "%27")}')))">♡</button>
                <button class="download-btn" title="Download" onclick="event.stopPropagation(); openDownloadModal('${encodeURIComponent(JSON.stringify(t)).replace(/'/g, "%27")}')">
                    ⬇
                </button>
                ${isUserPlaylist ? `
                <button class="delete-track-btn" title="Remove from playlist" onclick="event.stopPropagation(); deleteFromPlaylist('${item.id}', '${t.id}')">
                    ✕
                </button>
                ` : ''}
            </div>
        </div>
    `}).join('');

    // Show detail view
    detailView.classList.remove('hidden');
    resultsSection.classList.add('hidden');

    if (state.djMode && tracks.length > 0) {
        fetchAudioFeaturesForTracks(tracks);
    }
}

// ========== PODCAST EPISODE DETAILS MODAL ==========
const podcastModal = $('#podcast-modal');
const podcastModalClose = $('#podcast-modal-close');
const podcastModalArt = $('#podcast-modal-art');
const podcastModalTitle = $('#podcast-modal-title');
const podcastModalDate = $('#podcast-modal-date');
const podcastModalDuration = $('#podcast-modal-duration');
const podcastModalDescription = $('#podcast-modal-description');
const podcastModalPlay = $('#podcast-modal-play');

let currentPodcastEpisode = null;

function showPodcastModal(trackJson) {
    if (!trackJson) return;

    try {
        const track = typeof trackJson === 'string'
            ? JSON.parse(decodeURIComponent(trackJson))
            : trackJson;

        if (track.source !== 'podcast') return;

        currentPodcastEpisode = track;

        podcastModalArt.src = track.album_art || '/static/icon.svg';
        podcastModalTitle.textContent = track.name;
        podcastModalDate.textContent = track.datePublished || '';
        podcastModalDuration.textContent = `Duration: ${track.duration}`;

        // Strip HTML tags from description and decode entities
        const tempDiv = document.createElement('div');
        tempDiv.innerHTML = track.description || 'No description available.';
        podcastModalDescription.textContent = tempDiv.textContent || tempDiv.innerText;

        podcastModal.classList.remove('hidden');
    } catch (e) {
        console.error('Error opening podcast modal:', e);
    }
}
window.showPodcastModal = showPodcastModal;

function hidePodcastModal() {
    podcastModal.classList.add('hidden');
    currentPodcastEpisode = null;
}

// Close modal
podcastModalClose?.addEventListener('click', hidePodcastModal);

// Close on backdrop click
podcastModal?.addEventListener('click', (e) => {
    if (e.target === podcastModal) hidePodcastModal();
});

// Play button
podcastModalPlay?.addEventListener('click', () => {
    if (currentPodcastEpisode) {
        emit('playTrack', currentPodcastEpisode);
        hidePodcastModal();
    }
});

// Close on Escape key
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && !podcastModal.classList.contains('hidden')) {
        hidePodcastModal();
    }
});

// ========== LYRICS MODAL ==========
const lyricsBtn = $('#lyrics-btn');
const fsLyricsBtn = $('#fs-lyrics-btn');
const lyricsModal = $('#lyrics-modal');
const lyricsModalClose = $('#lyrics-modal-close');
const lyricsModalArt = $('#lyrics-modal-art');
const lyricsModalTitle = $('#lyrics-modal-title');
const lyricsModalArtist = $('#lyrics-modal-artist');
const lyricsModalAlbum = $('#lyrics-modal-album');
const lyricsLoading = $('#lyrics-loading');
const lyricsText = $('#lyrics-text');
const lyricsNotFound = $('#lyrics-not-found');
const lyricsSearchLink = $('#lyrics-search-link');
const aboutDescription = $('#about-description');
const aboutRelease = $('#about-release');
const aboutWriters = $('#about-writers');
const aboutProducers = $('#about-producers');
const geniusLink = $('#genius-link');
const annotationsList = $('#annotations-list');
const annotationsEmpty = $('#annotations-empty');
const lyricsTabs = document.querySelectorAll('.lyrics-tab');
const lyricsPanels = document.querySelectorAll('.lyrics-panel');

let currentLyricsData = null;

async function openLyricsModal() {
    const track = state.queue[state.currentIndex];
    if (!track) {
        showToast('No track playing');
        return;
    }

    // Show modal and loading state
    lyricsModal.classList.remove('hidden');
    lyricsLoading.classList.remove('hidden');
    lyricsText.textContent = '';
    lyricsNotFound.classList.add('hidden');
    aboutDescription.textContent = '';
    aboutRelease.textContent = '';
    aboutWriters.textContent = '';
    aboutProducers.textContent = '';

    // Set header info
    lyricsModalArt.src = track.album_art || '/static/icon.svg';
    lyricsModalTitle.textContent = track.name || 'Unknown';
    lyricsModalArtist.textContent = track.artists || 'Unknown Artist';
    lyricsModalAlbum.textContent = track.album || '';

    // Reset to lyrics tab
    lyricsTabs.forEach(t => t.classList.remove('active'));
    lyricsPanels.forEach(p => p.classList.remove('active'));
    document.querySelector('[data-tab="lyrics"]')?.classList.add('active');
    document.getElementById('lyrics-panel')?.classList.add('active');

    // Fetch lyrics
    try {
        const artist = track.artists || '';
        const title = track.name || '';
        const response = await fetch(`/api/lyrics?artist=${encodeURIComponent(artist)}&title=${encodeURIComponent(title)}`);
        const data = await response.json();

        currentLyricsData = data;
        lyricsLoading.classList.add('hidden');

        if (data.found && data.lyrics) {
            lyricsText.textContent = data.lyrics;
            lyricsNotFound.classList.add('hidden');
        } else {
            lyricsText.textContent = '';
            lyricsNotFound.classList.remove('hidden');
            lyricsSearchLink.href = `https://genius.com/search?q=${encodeURIComponent(artist + ' ' + title)}`;
        }

        // Populate About tab
        if (data.about) {
            aboutDescription.textContent = data.about;
        } else {
            aboutDescription.textContent = 'No description available for this track.';
        }

        if (data.release_date) {
            aboutRelease.innerHTML = `<strong>Released:</strong> ${data.release_date}`;
        }
        if (data.writers && data.writers.length > 0) {
            aboutWriters.innerHTML = `<strong>Written by:</strong> ${data.writers.join(', ')}`;
        }
        if (data.producers && data.producers.length > 0) {
            aboutProducers.innerHTML = `<strong>Produced by:</strong> ${data.producers.join(', ')}`;
        }
        if (data.genius_url) {
            geniusLink.href = data.genius_url;
            geniusLink.classList.remove('hidden');
        } else {
            geniusLink.classList.add('hidden');
        }

        // Populate Annotations tab
        if (data.annotations && data.annotations.length > 0) {
            annotationsList.innerHTML = data.annotations.map(ann => `
                <div class="annotation-item">
                    <div class="annotation-fragment">"${ann.fragment}"</div>
                    <div class="annotation-text">${ann.text}</div>
                </div>
            `).join('');
            annotationsEmpty.classList.add('hidden');
        } else {
            annotationsList.innerHTML = '';
            annotationsEmpty.classList.remove('hidden');
        }

    } catch (error) {
        console.error('Lyrics fetch error:', error);
        lyricsLoading.classList.add('hidden');
        lyricsText.textContent = '';
        lyricsNotFound.classList.remove('hidden');
        const artist = track.artists || '';
        const title = track.name || '';
        lyricsSearchLink.href = `https://genius.com/search?q=${encodeURIComponent(artist + ' ' + title)}`;
    }
}

function closeLyricsModal() {
    lyricsModal.classList.add('hidden');
    currentLyricsData = null;
}

// Button handlers
if (lyricsBtn) {
    lyricsBtn.addEventListener('click', openLyricsModal);
}
if (fsLyricsBtn) {
    fsLyricsBtn.addEventListener('click', openLyricsModal);
}
if (lyricsModalClose) {
    lyricsModalClose.addEventListener('click', closeLyricsModal);
}

// Close on backdrop click
lyricsModal?.addEventListener('click', (e) => {
    if (e.target === lyricsModal) {
        closeLyricsModal();
    }
});

// Tab switching
lyricsTabs.forEach(tab => {
    tab.addEventListener('click', () => {
        const tabName = tab.dataset.tab;

        lyricsTabs.forEach(t => t.classList.remove('active'));
        lyricsPanels.forEach(p => p.classList.remove('active'));

        tab.classList.add('active');
        document.getElementById(`${tabName}-panel`)?.classList.add('active');
    });
});

// Add L keyboard shortcut for lyrics
document.addEventListener('keydown', (e) => {
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
    if (e.key.toLowerCase() === 'l' && !e.ctrlKey && !e.metaKey) {
        openLyricsModal();
    }
});

// Expose as showLyricsModal
function showLyricsModal() {
    openLyricsModal();
}

// ========== MUSIC VIDEO ==========
const fsVideoBtn = $('#fs-video-btn');

function openMusicVideo() {
    const track = state.queue[state.currentIndex];
    if (!track) {
        showToast('No track playing');
        return;
    }

    const artist = track.artists || '';
    const title = track.name || '';
    const query = `${artist} ${title} official music video`;

    // Open YouTube search in new tab
    const youtubeUrl = `https://www.youtube.com/results?search_query=${encodeURIComponent(query)}`;
    window.open(youtubeUrl, '_blank');

    showToast('🎬 Opening YouTube...');
}

// Button handlers
if (fsVideoBtn) {
    fsVideoBtn.addEventListener('click', openMusicVideo);
}

// Also add to more menu video button
const videoBtn = $('#video-btn');
if (videoBtn) {
    videoBtn.addEventListener('click', openMusicVideo);
}

// V keyboard shortcut for video
document.addEventListener('keydown', (e) => {
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
    if (e.key.toLowerCase() === 'v' && !e.ctrlKey && !e.metaKey && !e.altKey) {
        if (e.shiftKey) {
            e.preventDefault();
            openVisualizer();
        } else {
            openMusicVideo();
        }
    }
});

// Expose as showMusicVideo
function showMusicVideo() {
    openMusicVideo();
}

// ==================== PLAYLIST EXPORT ====================
function initPlaylistExportImport() {
    const detailExportBtn = $('#detail-export-btn');
    const detailExportMenu = $('#detail-export-menu');
    const queueExportBtn = $('#queue-export-btn');
    const queueExportMenu = $('#queue-export-menu');

    // Toggle dropdowns
    detailExportBtn?.addEventListener('click', (e) => {
        e.stopPropagation();
        detailExportMenu.classList.toggle('hidden');
        if (queueExportMenu) queueExportMenu.classList.add('hidden');
    });

    queueExportBtn?.addEventListener('click', (e) => {
        e.stopPropagation();
        queueExportMenu.classList.toggle('hidden');
        if (detailExportMenu) detailExportMenu.classList.add('hidden');
    });

    // Close dropdowns when clicking outside
    document.addEventListener('click', (e) => {
        if (!e.target.closest('.export-dropdown-container')) {
            detailExportMenu?.classList.add('hidden');
            queueExportMenu?.classList.add('hidden');
        }
    });

    // Handle export option click
    document.addEventListener('click', (e) => {
        const option = e.target.closest('.export-option');
        if (!option) return;

        e.preventDefault();
        const target = option.dataset.target; // 'detail' or 'queue'
        const format = option.dataset.format; // 'm3u', 'csv', 'json'

        let tracks = [];
        let title = 'Playlist';

        if (target === 'detail') {
            tracks = state.detailTracks || [];
            title = state.detailName || 'Exported_Playlist';
        } else if (target === 'queue') {
            tracks = state.queue || [];
            title = 'Freedify_Queue';
        }

        if (tracks.length === 0) {
            showToast('No tracks to export');
            return;
        }

        exportPlaylist(tracks, format, title.replace(/[^a-z0-9]/gi, '_'));

        // Hide menus
        detailExportMenu?.classList.add('hidden');
        queueExportMenu?.classList.add('hidden');
    });
}

function exportPlaylist(tracks, format, filename) {
    let content = '';
    let type = 'text/plain;charset=utf-8';

    switch (format) {
        case 'm3u':
            content = generateM3U(tracks);
            type = 'audio/x-mpegurl;charset=utf-8';
            filename += '.m3u';
            break;
        case 'csv':
            content = generateCSV(tracks);
            type = 'text/csv;charset=utf-8';
            filename += '.csv';
            break;
        case 'json':
            content = JSON.stringify(tracks, null, 2);
            type = 'application/json;charset=utf-8';
            filename += '.json';
            break;
        default:
            return;
    }

    triggerDownload(content, filename, type);
    showToast(`Exported ${tracks.length} tracks to ${format.toUpperCase()}`);
}

function generateM3U(tracks) {
    let m3u = '#EXTM3U\n';
    tracks.forEach(track => {
        const durationSeconds = track.duration ? Math.round(track.duration) : -1;
        m3u += `#EXTINF:${durationSeconds},${track.artists} - ${track.name}\n`;
        // We use ISRC as the URI if streamUrl is not immediately available
        m3u += `freedify://track/${track.isrc || track.id}\n`;
    });
    return m3u;
}

function generateCSV(tracks) {
    const escapeCSV = (str) => {
        if (!str) return '""';
        const cleaned = String(str).replace(/"/g, '""');
        return `"${cleaned}"`;
    };

    let csv = 'Name,Artist,Album,Duration(s),ISRC,Source\n';
    tracks.forEach(track => {
        const row = [
            escapeCSV(track.name),
            escapeCSV(track.artists),
            escapeCSV(track.album),
            track.duration || '',
            escapeCSV(track.isrc),
            escapeCSV(track.source)
        ].join(',');
        csv += row + '\n';
    });
    return csv;
}

function triggerDownload(content, filename, type) {
    const blob = new Blob([content], { type: type });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    setTimeout(() => {
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    }, 100);
}

// ==================== PLAYLIST IMPORT ====================
async function handlePlaylistImport(file) {
    const ext = file.name.split('.').pop().toLowerCase();
    const text = await file.text();
    let importedTracks = [];

    try {
        if (ext === 'json') {
            const data = JSON.parse(text);
            importedTracks = Array.isArray(data) ? data : (data.tracks || []);
        } else if (ext === 'm3u' || ext === 'm3u8') {
            const lines = text.split('\n');
            let currentTrack = {};
            for (const line of lines) {
                const l = line.trim();
                if (l.startsWith('#EXTINF:')) {
                    // Extract duration and name (format: #EXTINF:duration,Artist - Title)
                    const parsed = l.match(/#EXTINF:(-?\d+),(.*)/);
                    if (parsed) {
                        currentTrack.duration = Math.max(0, parseInt(parsed[1], 10));
                        const parts = parsed[2].split(' - ');
                        if (parts.length >= 2) {
                            currentTrack.artists = parts[0].trim();
                            currentTrack.name = parts.slice(1).join(' - ').trim();
                        } else {
                            currentTrack.name = parsed[2].trim();
                            currentTrack.artists = 'Unknown Artist';
                        }
                    }
                } else if (l && !l.startsWith('#')) {
                    // URI or path
                    currentTrack.id = l.replace('freedify://track/', '') || `import_${Date.now()}_${Math.random()}`;
                    currentTrack.isrc = currentTrack.id;
                    if (!currentTrack.name) currentTrack.name = l.split('/').pop();
                    importedTracks.push({...currentTrack, source: 'import'});
                    currentTrack = {};
                }
            }
        } else if (ext === 'csv') {
            const lines = text.split('\n').filter(l => l.trim().length > 0);
            if (lines.length > 1) { // Skip header
                for (let i = 1; i < lines.length; i++) {
                    const l = lines[i];
                    // Very simple CSV parse (doesn't handle commas inside quotes well, but enough for basic use)
                    const parts = l.split(',');
                    if (parts.length >= 2) {
                        importedTracks.push({
                            id: `import_${Date.now()}_${i}`,
                            name: parts[0].replace(/"/g, '').trim(),
                            artists: parts[1].replace(/"/g, '').trim(),
                            album: parts[2] ? parts[2].replace(/"/g, '').trim() : '',
                            duration: parts[3] ? parseInt(parts[3]) : 0,
                            isrc: parts[4] ? parts[4].replace(/"/g, '').trim() : '',
                            source: 'import'
                        });
                    }
                }
            }
        }

        if (importedTracks.length > 0) {
            const baseName = file.name.replace(/\.[^/.]+$/, "");
            createPlaylist(`Imported: ${baseName}`, importedTracks);
            showToast(`Imported "${baseName}" with ${importedTracks.length} tracks!`);
        } else {
            showToast('Could not parse any tracks from this file');
        }
    } catch (e) {
        console.error('Import error:', e);
        showToast('Error parsing playlist file. Invalid format.');
    }
}

// ========== AUDIOBOOK LOGIC ==========

const audiobookModal = $('#audiobook-modal');
const audiobookCloseBtn = $('#audiobook-modal-close');
let currentAudiobookDetails = null;
let audiobookPollInterval = null;

function initAudiobooks() {
    if (audiobookCloseBtn) {
        audiobookCloseBtn.addEventListener('click', () => {
            audiobookModal.classList.add('hidden');
            if (audiobookPollInterval) {
                clearInterval(audiobookPollInterval);
                audiobookPollInterval = null;
            }
        });
    }
}

async function openAudiobook(id) {
    showLoading('Fetching audiobook details...');
    try {
        const response = await fetch(`/api/audiobooks/details?id=${encodeURIComponent(id)}`);
        if (!response.ok) throw new Error('Failed to fetch audiobook details');
        const details = await response.json();
        hideLoading();

        currentAudiobookDetails = details;

        // Populate Modal
        $('#audiobook-modal-title').textContent = details.title;
        $('#audiobook-modal-art').src = details.cover_image || '/static/icon.svg';
        $('#audiobook-modal-description').textContent = details.description || 'No description available.';

        // Reset UI
        const btn = $('#audiobook-download-btn');
        btn.textContent = '☁️ Download to Premiumize';
        btn.disabled = false;

        let favBtn = $('#audiobook-fav-btn');
        if (!favBtn) {
            favBtn = document.createElement('button');
            favBtn.id = 'audiobook-fav-btn';
            btn.parentNode.insertBefore(favBtn, btn.nextSibling);
            favBtn.style.marginTop = '10px';
        }

        // Replace click handler every time so it always references the CURRENT book
        favBtn.onclick = () => {
            if (!currentAudiobookDetails) return;
            const bookInfo = {
                id: currentAudiobookDetails.id || id,
                name: currentAudiobookDetails.title,
                artist: 'AudiobookBay',
                artwork: currentAudiobookDetails.cover_image || '/static/icon.svg'
            };
            const nowFav = toggleAudiobookFavorite(bookInfo);
            favBtn.textContent = nowFav ? '❤️ In My Books' : '🤍 Save to My Books';
            favBtn.className = nowFav ? 'btn-secondary saved' : 'btn-secondary';
        };

        const isFav = isAudiobookFavorited(id);
        favBtn.textContent = isFav ? '❤️ In My Books' : '🤍 Save to My Books';
        favBtn.className = isFav ? 'btn-secondary saved' : 'btn-secondary';
        btn.disabled = false;
        $('#audiobook-progress-container').classList.add('hidden');
        $('#audiobook-progress-status').textContent = 'Starting...';
        $('#audiobook-progress-percent').textContent = '0%';
        $('#audiobook-progress-fill').style.width = '0%';

        // Check if it's already in Premiumize by searching the title (optimistic check)
        checkExistingAudiobook(details.title);

        btn.onclick = () => startAudiobookDownload(details.magnet_link);

        audiobookModal.classList.remove('hidden');
    } catch (e) {
        hideLoading();
        console.error(e);
        showError(e.message);
    }
}

async function checkExistingAudiobook(title) {
    try {
        // Search Premiumize for the exact title
        // Torrents often have weird names, so we might not find it, which is fine
        const { folder, audioFiles } = await searchPremiumizeForAudiobook(title);

        if (folder || audioFiles.length > 0) {
            if (folder) {
                const btn = $('#audiobook-download-btn');
                btn.textContent = '▶ Play from Premiumize Cache';
                btn.onclick = () => loadAudiobookFolder(folder.id, currentAudiobookDetails);
                showToast('Found in Premiumize cache!');
            } else if (audioFiles.length > 0) {
                const btn = $('#audiobook-download-btn');
                btn.textContent = '▶ Play from Premiumize Cache';
                btn.onclick = () => processDirectAudioFiles(audioFiles, currentAudiobookDetails);
                showToast('Found in Premiumize cache!');
            }
        }
    } catch (e) {
        console.error("Cache check failed", e);
    }
}

async function searchPremiumizeForAudiobook(title) {
    try {
        // Extract the two longest unique significant words from the title for a more specific query
        const getLongestWords = (str) => {
            const words = str.split(/[^a-zA-Z0-9]/).filter(w => w.length > 3).sort((a, b) => b.length - a.length);
            return [...new Set(words)].slice(0, 2).join(' ');
        };
        const searchWord = getLongestWords(title) || title.split(' ')[0];
        const response = await fetch(`/api/premiumize/search?q=${encodeURIComponent(searchWord)}`);
        const data = await response.json();

        if (!data || !data.results || data.results.length === 0) {
            return { folder: null, audioFiles: [] };
        }

        const sanitize = str => str.toLowerCase().replace(/[^a-z0-9]/g, ' ').replace(/\s+/g, ' ').trim();
        const targetWords = sanitize(title).split(' ').filter(w => w.length > 2 && w !== 'audiobook');
        const wordsToMatch = targetWords.length > 0 ? targetWords : sanitize(title).split(' ');

        const isMatch = (name) => {
            const n = sanitize(name);
            const matchCount = wordsToMatch.filter(w => n.includes(w)).length;
            // Require at least 50% of significant words to match
            const required = Math.max(1, Math.ceil(wordsToMatch.length / 2));
            return matchCount >= required;
        };

        const matchingResults = data.results.filter(i => isMatch(i.name));
        const folder = matchingResults.find(i => i.type === 'folder');
        const audioExtensions = ['.mp3', '.m4b', '.m4a', '.flac', '.wav', '.ogg'];
        const audioFiles = matchingResults.filter(i =>
            i.type === 'file' && audioExtensions.some(ext => i.name.toLowerCase().endsWith(ext))
        );

        return { folder, audioFiles };
    } catch (e) {
        console.error("Premiumize search failed", e);
        return { folder: null, audioFiles: [] };
    }
}

function processDirectAudioFiles(audioFiles, details) {
    audioFiles.sort((a, b) => a.name.localeCompare(b.name));
    audiobookModal.classList.add('hidden');

    const mappedTracks = audioFiles.map((file, index) => {
        const streamUrl = file.stream_link || file.directlink || file.link;
        const stableId = `ab_${details.title}_${file.name}`.replace(/[^a-zA-Z0-9_]/g, '_');

        return {
            id: stableId,
            isrc: `LINK:${btoa(streamUrl).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')}`,
            name: file.name.replace(/\.[^/.]+$/, ""),
            artists: details.author || 'Unknown Author',
            album: details.title,
            album_art: details.cover_image || '/static/icon.svg',
            duration: '0:00',
            source: 'audiobook',
            track_number: index + 1
        };
    });

    const albumData = {
        id: `ab_${details.id}_direct`,
        name: details.title,
        artists: details.author || 'Audiobook',
        image: details.cover_image || '/static/icon.svg',
        is_playlist: false
    };

    // Auto-save to My Books and cache the tracks
    addAudiobookFavorite(details);
    const favIdx = state.audiobookFavorites.findIndex(b =>
        b.name === details.title || b.id === details.id
    );
    if (favIdx !== -1) {
        state.audiobookFavorites[favIdx].cachedTracks = mappedTracks;
        state.audiobookFavorites[favIdx].cachedAt = Date.now();
        if (details.description) {
            state.audiobookFavorites[favIdx].description = details.description;
        }
        saveAudiobookFavorites();
    }

    showDetailView(albumData, mappedTracks);
}

async function startAudiobookDownload(magnetLink) {
    const btn = $('#audiobook-download-btn');
    btn.disabled = true;
    btn.textContent = 'Starting Transfer...';
    $('#audiobook-progress-container').classList.remove('hidden');

    try {
        const response = await fetch('/api/premiumize/transfer', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ magnet_link: magnetLink })
        });
        const data = await response.json();

        if (data.status === 'success') {
            pollAudiobookTransfer(data.id || data.transfer_id); // The id depends on the exact API response
        } else {
            throw new Error(data.message || 'Failed to start transfer');
        }
    } catch (e) {
        btn.disabled = false;
        btn.textContent = '☁️ Download to Premiumize';
        showError(e.message);
    }
}

async function pollAudiobookTransfer(transferId) {
    if (audiobookPollInterval) clearInterval(audiobookPollInterval);

    // Fallback if transferId is missing from create transfer response
    const fetchStatus = async () => {
        try {
            const res = await fetch(`/api/premiumize/transfer/${transferId || ''}`);
            const data = await res.json();

            let transfer = null;
            if (transferId && data.transfer && !Array.isArray(data.transfer)) {
                transfer = data.transfer;
            } else if (data.transfer && Array.isArray(data.transfer)) {
                // Find highest progress if we don't know the ID
                transfer = data.transfer.filter(t => t.name && (t.name.includes(currentAudiobookDetails.title.split(' ')[0]) || t.message !== 'finished')).pop();
            }

            if (!transfer) {
                // If transfer disappeared, it might be finished
                clearInterval(audiobookPollInterval);
                audiobookPollInterval = null;
                // Now try to find the folder it created
                autoFindFinishedFolder();
                return;
            }

            const progress = (transfer.progress || 0) * 100;
            const statusStr = transfer.message || transfer.status || 'Downloading';

            $('#audiobook-progress-percent').textContent = `${progress.toFixed(1)}%`;
            $('#audiobook-progress-fill').style.width = `${progress}%`;
            $('#audiobook-progress-status').textContent = statusStr;

            if (transfer.status === 'finished' || progress >= 100) {
                clearInterval(audiobookPollInterval);
                audiobookPollInterval = null;
                $('#audiobook-progress-status').textContent = 'Complete! Loading tracks...';
                $('#audiobook-download-btn').textContent = '▶ Play';

                // If we get the folder ID directly from the transfer object
                if (transfer.folder_id) {
                    loadAudiobookFolder(transfer.folder_id, currentAudiobookDetails);
                } else {
                    autoFindFinishedFolder();
                }
            }

        } catch (e) {
            console.error('Polling error', e);
        }
    };

    audiobookPollInterval = setInterval(fetchStatus, 3000);
    fetchStatus(); // immediate run
}

async function autoFindFinishedFolder() {
    try {
        const { folder, audioFiles } = await searchPremiumizeForAudiobook(currentAudiobookDetails.title);

        if (folder) {
            loadAudiobookFolder(folder.id, currentAudiobookDetails);
        } else if (audioFiles.length > 0) {
            processDirectAudioFiles(audioFiles, currentAudiobookDetails);
        } else {
            $('#audiobook-progress-status').textContent = 'Completed, but could not locate folder. Check your Premiumize web interface.';
            $('#audiobook-progress-percent').textContent = '';
            $('#audiobook-download-btn').disabled = false;
            $('#audiobook-download-btn').textContent = 'Open Premiumize';
            $('#audiobook-download-btn').onclick = () => window.open('https://www.premiumize.me/files', '_blank');
        }
    } catch (e) {
        console.error(e);
        showError('Could not locate downloaded folder');
    }
}

async function loadAudiobookFolder(folderId, audiobookDetails) {
    showLoading('Loading audiobook tracks from Premiumize...');
    try {
        const response = await fetch(`/api/premiumize/folder/${folderId}`);
        const data = await response.json();
        hideLoading();

        let audioFiles = data.audio_files || [];

        // If empty, maybe it's nested in a subfolder. Let's recursively check (max 1 deep for simplicity)
        if (audioFiles.length === 0 && data.folders && data.folders.length > 0) {
            const subFolderId = data.folders[0].id;
            const subRes = await fetch(`/api/premiumize/folder/${subFolderId}`);
            const subData = await subRes.json();
            audioFiles = subData.audio_files || [];
        }

        if (audioFiles.length === 0) {
            showError('No audio files found in the downloaded folder.');
            return;
        }

        // Close modal and map tracks for showDetailView
        audiobookModal.classList.add('hidden');

        const mappedTracks = audioFiles.map((file, index) => {
            // Use stream_link if available, fallback to directlink for actual media access
            const streamUrl = file.stream_link || file.directlink || file.link;
            // Use a STABLE ID based on filename + audiobook title (stream URLs expire and change)
            const stableId = `ab_${audiobookDetails.title}_${file.name}`.replace(/[^a-zA-Z0-9_]/g, '_');
            return {
                id: stableId,
                isrc: `LINK:${btoa(streamUrl).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')}`,
                name: file.name.replace(/\.[^/.]+$/, ""), // Remove extension
                artists: audiobookDetails.title,
            album: audiobookDetails.title,
            album_art: audiobookDetails.cover_image || '/static/icon.svg',
            duration: '0:00', // We don't have duration upfront
            source: 'audiobook', // Mark as audiobook so it uses the podcast resume logic!
            track_number: index + 1
        };
    });

        const albumData = {
            id: `ab_${folderId}`,
            name: audiobookDetails.title,
            artists: 'Audiobook',
            image: audiobookDetails.cover_image || '/static/icon.svg',
            is_playlist: false
        };

        showDetailView(albumData, mappedTracks);

        // Cache the mapped tracks into the audiobookFavorites entry
        // so subsequent plays from My Books don't need to re-fetch from Premiumize
        const favIdx = state.audiobookFavorites.findIndex(b =>
            b.name === audiobookDetails.title || b.id === audiobookDetails.id
        );
        if (favIdx !== -1) {
            state.audiobookFavorites[favIdx].cachedTracks = mappedTracks;
            state.audiobookFavorites[favIdx].cachedAt = Date.now();
            // Cache the description from AudiobookBay for the book info modal
            if (audiobookDetails.description) {
                state.audiobookFavorites[favIdx].description = audiobookDetails.description;
            }
            saveAudiobookFavorites();
        }

    } catch (e) {
        hideLoading();
        console.error(e);
        showError('Failed to load audiobook folder');
    }
}

// ========== EXPORTS ==========
export {
    renderPlaylistsView,
    showPlaylistDetail,
    openAlbum,
    openArtist,
    showDetailView,
    openPodcastEpisodes,
    showPodcastModal,
    renderMyPodcastsView,
    renderMyBooksView,
    showLyricsModal,
    showMusicVideo,
    initPlaylistExportImport,
    initAudiobooks,
    openAudiobook,
};
