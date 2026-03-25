/**
 * Freedify UI Module
 * Loading/error overlays, empty state/dashboard, theme picker, HiFi mode
 */

import { state } from './state.js';
import { escapeHtml, showToast } from './utils.js';
import { emit } from './event-bus.js';
import { getMoodStatsForWeek } from './data.js';
import {
    $, $$, loadingOverlay, loadingText, errorMessage, errorText,
    errorRetry, resultsContainer, searchInput,
} from './dom.js';

// ========== LOADING / ERROR ==========
export function showLoading(text) {
    loadingText.textContent = text || 'Loading...';
    loadingOverlay.classList.remove('hidden');
    errorMessage.classList.add('hidden');
}

export function hideLoading() {
    loadingOverlay.classList.add('hidden');
}

export function showError(message) {
    hideLoading();
    errorText.textContent = message;
    errorMessage.classList.remove('hidden');
}

errorRetry.addEventListener('click', () => {
    errorMessage.classList.add('hidden');
    const query = searchInput.value.trim();
    if (query) emit('performSearch', query);
});

// ========== DASHBOARD / EMPTY STATE ==========
export function showEmptyState() {
    const hasHistory = state.history && state.history.length > 0;
    const hasPlaylists = state.playlists && state.playlists.length > 0;
    const hasLibrary = state.library && state.library.length > 0;

    if (!hasHistory && !hasPlaylists && !hasLibrary) {
        resultsContainer.innerHTML = `
            <div class="empty-state">
                <span class="empty-icon">🔍</span>
                <p>Search for your favorite music</p>
                <p class="hint">Or paste a Spotify link to an album or playlist</p>
            </div>
        `;
        return;
    }

    let html = '<div class="dashboard">';

    // Jump Back In
    if (hasHistory) {
        const seenAlbums = new Set();
        const recentAlbums = [];
        for (const track of state.history) {
            const albumKey = track.album || track.artists;
            if (!seenAlbums.has(albumKey) && recentAlbums.length < 8) {
                seenAlbums.add(albumKey);
                recentAlbums.push(track);
            }
        }

        if (recentAlbums.length > 0) {
            html += `
                <section class="dashboard-section">
                    <h3 class="dashboard-title">🎵 Jump Back In</h3>
                    <div class="dashboard-grid">
                        ${recentAlbums.map(track => `
                            <div class="dashboard-card" data-track-id="${track.id}" onclick="playHistoryTrack('${track.id}')">
                                <img src="${track.album_art || '/static/icon.svg'}" alt="${escapeHtml(track.album || track.name)}" loading="lazy">
                                <div class="dashboard-card-info">
                                    <p class="dashboard-card-title">${escapeHtml(track.album || track.name)}</p>
                                    <p class="dashboard-card-subtitle">${escapeHtml(track.artists)}</p>
                                </div>
                            </div>
                        `).join('')}
                    </div>
                </section>
            `;
        }
    }

    // Recent Artists
    if (hasHistory) {
        const seenArtists = new Set();
        const recentArtists = [];
        for (const track of state.history) {
            const artist = (track.artists || '').split(',')[0].trim();
            if (artist && !seenArtists.has(artist) && recentArtists.length < 6) {
                seenArtists.add(artist);
                recentArtists.push({ name: artist, art: track.album_art });
            }
        }

        if (recentArtists.length > 0) {
            html += `
                <section class="dashboard-section">
                    <h3 class="dashboard-title">🎤 Your Artists</h3>
                    <div class="dashboard-grid dashboard-grid-artists">
                        ${recentArtists.map(artist => `
                            <div class="dashboard-card dashboard-card-artist" onclick="searchArtist('${escapeHtml(artist.name)}')">
                                <img src="${artist.art || '/static/icon.svg'}" alt="${escapeHtml(artist.name)}" loading="lazy">
                                <div class="dashboard-card-info">
                                    <p class="dashboard-card-title">${escapeHtml(artist.name)}</p>
                                </div>
                            </div>
                        `).join('')}
                    </div>
                </section>
            `;
        }
    }

    // Library
    if (hasLibrary) {
        html += `
            <section class="dashboard-section">
                <h3 class="dashboard-title">⭐ Your Library <span class="dashboard-count">(${state.library.length})</span></h3>
                <div class="dashboard-grid">
                    ${state.library.slice(0, 8).map(track => `
                        <div class="dashboard-card" data-track-id="${track.id}" onclick="playHistoryTrack('${track.id}')">
                            <img src="${track.album_art || '/static/icon.svg'}" alt="${escapeHtml(track.name)}" loading="lazy">
                            <div class="dashboard-card-info">
                                <p class="dashboard-card-title">${escapeHtml(track.name)}</p>
                                <p class="dashboard-card-subtitle">${escapeHtml(track.artists)}</p>
                            </div>
                        </div>
                    `).join('')}
                </div>
                ${state.library.length > 8 ? '<button class="dashboard-see-all" onclick="showLibraryView()">See All →</button>' : ''}
            </section>
        `;
    }

    // Playlists
    if (hasPlaylists) {
        html += `
            <section class="dashboard-section">
                <h3 class="dashboard-title">📋 Your Playlists</h3>
                <div class="dashboard-grid">
                    ${state.playlists.slice(0, 4).map(playlist => `
                        <div class="dashboard-card" onclick="openPlaylistById('${playlist.id}')">
                            <img src="${playlist.tracks[0]?.album_art || '/static/icon.svg'}" alt="${escapeHtml(playlist.name)}" loading="lazy">
                            <div class="dashboard-card-info">
                                <p class="dashboard-card-title">${escapeHtml(playlist.name)}</p>
                                <p class="dashboard-card-subtitle">${playlist.tracks.length} tracks</p>
                            </div>
                        </div>
                    `).join('')}
                </div>
            </section>
        `;
    }

    html += '</div>';
    resultsContainer.innerHTML = html;
}

// ========== DASHBOARD HELPERS ==========
import { getEpisodePosition } from './data.js';

export function playHistoryTrack(trackId) {
    const track = state.history.find(t => t.id === trackId) || state.library.find(t => t.id === trackId);
    if (track) {
        state.queue = [track];
        state.currentIndex = 0;

        if (track.source === 'podcast' || track.source === 'audiobook') {
            const savedPos = getEpisodePosition(track.id);
            if (savedPos > 10) {
                const resumeMin = Math.floor(savedPos / 60);
                const resumeSec = savedPos % 60;
                showToast(`Resuming from ${resumeMin}:${String(resumeSec).padStart(2, '0')}`);
                track._resumeAt = savedPos;
            }
        }

        emit('loadTrack', track);
    }
}

export function searchArtist(artistName) {
    searchInput.value = artistName;
    state.searchType = 'artist';
    emit('performSearch', artistName);
}

export function openPlaylistById(playlistId) {
    const playlist = state.playlists.find(p => p.id === playlistId);
    if (playlist) {
        emit('showPlaylistDetail', playlist);
    }
}

export function showLibraryView() {
    const libraryPlaylist = {
        id: '__library__',
        name: '⭐ Your Library',
        tracks: state.library,
        is_user_playlist: true
    };
    emit('showPlaylistDetail', libraryPlaylist);
}

// ========== THEME PICKER ==========
const themeBtn = $('#theme-btn');
const themePicker = $('#theme-picker');
const themeOptions = $$('.theme-option');

// Load saved theme on startup
(function loadSavedTheme() {
    const savedTheme = localStorage.getItem('freedify_theme') || '';
    if (savedTheme) {
        document.body.classList.add(savedTheme);
    }
    themeOptions.forEach(opt => {
        if (opt.dataset.theme === savedTheme) {
            opt.classList.add('active');
        }
    });

    const metaThemeColor = document.querySelector('meta[name="theme-color"]');
    if (metaThemeColor && savedTheme) {
        setTimeout(() => {
            const accentColor = getComputedStyle(document.documentElement).getPropertyValue('--accent').trim();
            if (accentColor) metaThemeColor.content = accentColor;
        }, 50);
    }
})();

themeBtn?.addEventListener('click', (e) => {
    e.stopPropagation();
    themePicker.classList.toggle('hidden');
});

themeOptions.forEach(opt => {
    opt.addEventListener('click', () => {
        const newTheme = opt.dataset.theme;

        document.body.classList.remove('theme-purple', 'theme-blue', 'theme-green', 'theme-pink', 'theme-orange', 'theme-dracula', 'theme-catppuccin', 'theme-nightowl', 'theme-nuclear');

        if (newTheme) {
            document.body.classList.add(newTheme);
        }

        localStorage.setItem('freedify_theme', newTheme);

        themeOptions.forEach(o => o.classList.remove('active'));
        opt.classList.add('active');

        themePicker.classList.add('hidden');

        showToast(`Theme changed to ${opt.textContent}`);

        const metaThemeColor = document.querySelector('meta[name="theme-color"]');
        if (metaThemeColor) {
            setTimeout(() => {
                const accentColor = getComputedStyle(document.documentElement).getPropertyValue('--accent').trim();
                if (accentColor) metaThemeColor.content = accentColor;
            }, 50);
        }
    });
});

document.addEventListener('click', (e) => {
    if (themePicker && !themePicker.contains(e.target) && e.target !== themeBtn) {
        themePicker.classList.add('hidden');
    }
});

// ========== HiFi MODE ==========
const hifiBtn = $('#hifi-btn');

export function updateHifiButtonUI() {
    if (hifiBtn) {
        const currentTrack = state.queue[state.currentIndex];
        const source = currentTrack?.source || '';

        const isLossySource = source === 'ytmusic' || source === 'youtube' || source === 'podcast' || source === 'import';

        if (isLossySource) {
            hifiBtn.classList.remove('hi-res');
            hifiBtn.classList.add('active', 'lossy');
            hifiBtn.title = "Playing: Compressed Audio (MP3/AAC)";
            hifiBtn.textContent = "MP3";
        } else {
            hifiBtn.classList.add('active');
            hifiBtn.classList.remove('lossy');
            hifiBtn.classList.toggle('hi-res', state.hiResMode);

            if (state.hiResMode) {
                const qualityLabel = state.hiResQuality === '5' ? '192kHz/24-bit' : '96kHz/24-bit';
                hifiBtn.title = `Hi-Res Mode ON (${qualityLabel})`;
                hifiBtn.textContent = state.hiResQuality === '5' ? 'Hi-Res+' : 'Hi-Res';
            } else {
                hifiBtn.title = 'HiFi Mode ON (16-bit)';
                hifiBtn.textContent = 'HiFi';
            }
        }
    }
}

if (hifiBtn) {
    hifiBtn.addEventListener('click', () => {
        if (!state.hiResMode) {
            state.hiResMode = true;
            state.hiResQuality = '6';
            showToast('Hi-Res Mode ON — 96kHz / 24-bit', 3000);
        } else if (state.hiResQuality === '6') {
            state.hiResQuality = '5';
            showToast('Hi-Res MAX — 192kHz / 24-bit', 3000);
        } else {
            state.hiResMode = false;
            state.hiResQuality = '6';
            showToast('HiFi Mode ON — 16-bit Audio', 3000);
        }
        localStorage.setItem('freedify_hires', state.hiResMode);
        localStorage.setItem('freedify_hires_quality', state.hiResQuality);
        updateHifiButtonUI();
    });

    updateHifiButtonUI();
}

// ========== MOOD SELECTOR ==========

const MOOD_LIST = ['Focus', 'Workout', 'Chill', 'Party', 'Late Night', 'Commute'];

export function renderMoodSelector(containerEl) {
    if (!containerEl) return;

    const stats = MOOD_LIST.map(m => ({ mood: m, count: getMoodStatsForWeek(m) }));
    // Escape user-provided mood for safe injection into innerHTML
    const escapedMood = state.currentMood ? escapeHtml(state.currentMood) : '';
    const isFreeform = state.currentMood && !MOOD_LIST.includes(state.currentMood);

    containerEl.innerHTML = `
        <div class="mood-selector">
            <div class="mood-buttons">
                ${MOOD_LIST.map(m => {
                    const count = stats.find(s => s.mood === m)?.count || 0;
                    const active = state.currentMood === m ? 'active' : '';
                    return `<button class="mood-btn ${active}" data-mood="${m}">
                        ${m}${count > 0 ? ` <span class="mood-count">(${count})</span>` : ''}
                    </button>`;
                }).join('')}
            </div>
            <div class="mood-freeform">
                <input type="text" id="mood-freeform-input"
                    placeholder="Or describe your mood..."
                    value="${isFreeform ? escapedMood : ''}" />
            </div>
            ${state.currentMood ? `<div class="mood-active-label">AI Radio — Mood: ${escapedMood}</div>` : ''}
        </div>
    `;

    // Button click handlers
    containerEl.querySelectorAll('.mood-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const mood = btn.dataset.mood;
            if (state.currentMood === mood) {
                // Deselect
                state.currentMood = null;
            } else {
                state.currentMood = mood;
            }
            localStorage.setItem('freedify_current_mood', JSON.stringify(state.currentMood));
            const freeformInput = containerEl.querySelector('#mood-freeform-input');
            if (freeformInput) freeformInput.value = '';
            renderMoodSelector(containerEl); // Re-render
            emit('moodChanged', state.currentMood);
        });
    });

    // Free-form input handler
    const freeformInput = containerEl.querySelector('#mood-freeform-input');
    if (freeformInput) {
        freeformInput.addEventListener('change', () => {
            const val = freeformInput.value.trim();
            if (val) {
                state.currentMood = val;
                containerEl.querySelectorAll('.mood-btn').forEach(b => b.classList.remove('active'));
            } else {
                state.currentMood = null;
            }
            localStorage.setItem('freedify_current_mood', JSON.stringify(state.currentMood));
            renderMoodSelector(containerEl);
            emit('moodChanged', state.currentMood);
        });
    }
}
