/**
 * Freedify - Music Streaming PWA
 * Entry module: imports all modules, wires event bus, registers window globals
 */

// ========== IMPORTS ==========
import { on, emit } from './event-bus.js';
import { state } from './state.js';
import { showToast, escapeHtml, formatTime } from './utils.js';
import {
    audioPlayer, audioPlayer2, volumeSlider, searchInput,
    resultsSection, detailView, backBtn, queueAllBtn, shuffleBtn,
    domState,
} from './dom.js';
import {
    deleteFromPlaylist, toggleLibrary, isInLibrary, addAllToLibrary,
    togglePodcastFavorite, isPodcastFavorited, toggleAudiobookFavorite,
    toggleEpisodePlayed, isEpisodePlayed, setPodcastTags, getPodcastTags,
    saveEpisodePosition,
} from './data.js';
import { audio, getActivePlayer, performGaplessSwitch, preloadNextTrack } from './audio-engine.js';
import {
    playTrack, loadTrack, togglePlay, playNext, playPrevious,
    updateQueueUI, updatePlayerUI, updatePlayButton, updateVolume,
    removeFromQueue, loadQueueFromStorage, setPlaybackDeps,
    updateFormatBadge, toggleFullScreen, updateFullscreenUI,
} from './playback.js';
import {
    showLoading, hideLoading, showError, showEmptyState,
    playHistoryTrack, openJumpBackInAlbum, searchArtist, openPlaylistById, showLibraryView,
    updateHifiButtonUI,
} from './ui.js';
import {
    performSearch, renderResults, addToQueue, openDownloadModal,
    renderTrackCard, renderAlbumCard, renderArtistCard,
} from './search.js';
import {
    renderPlaylistsView, showPlaylistDetail, openAlbum, openArtist,
    showDetailView, openPodcastEpisodes, showPodcastModal,
    renderMyPodcastsView, renderMyBooksView, showLyricsModal,
    showMusicVideo, initPlaylistExportImport, initAudiobooks,
    openAudiobook,
} from './views.js';
import {
    updateMediaSession, submitNowPlaying, submitScrobble,
    updateMiniPlayer, toggleMiniPlayer, openAddToPlaylistModal,
    renderRecommendations, initLocalFiles, initGoogleDriveSync,
    initSpotifyOAuth, initAIRadio, initAIAssistant, checkAndAddTracks,
    initSyncUI,
    initDataExportImport,
} from './integrations.js';
import {
    initDJMode, fetchAudioFeaturesForTracks, renderDJBadgeForTrack,
    initVisualizer, initConcertAlerts, showArtistBio,
    visualizerActive, showVisualizerInfoBriefly,
} from './dj.js';
import {
    initSync, enableSync, disableSync, connectSync,
    sendFullState, sendDelta, sendTimeUpdate, discoverDevices,
} from './sync.js';

// ========== WIRE PLAYBACK DEPENDENCIES ==========
// Break circular deps by passing function refs to playback module
setPlaybackDeps({
    performSearch,
    openAlbum,
    showPodcastModal,
    updateMiniPlayer,
    updateMediaSession,
    submitNowPlaying,
    submitScrobble,
    showLoading,
    hideLoading,
    showError,
    updateHifiButtonUI,
    showVisualizerInfoBriefly,
    openAddToPlaylistModal,
});

// ========== EVENT BUS WIRING ==========
// These connect modules that can't directly import each other

on('loadTrack', (track) => loadTrack(track));
on('playTrack', (track) => playTrack(track));
on('togglePlay', () => togglePlay());
on('playNext', (force) => playNext(force));
on('playPrevious', () => playPrevious());
on('updateQueueUI', () => updateQueueUI());
on('updatePlayerUI', () => updatePlayerUI());
on('updatePlayButton', () => updatePlayButton());
on('updateVolume', (vol) => updateVolume(vol));
on('performSearch', (data) => {
    // Support both string and { query, append } signatures
    if (typeof data === 'string') {
        performSearch(data);
    } else if (data && data.query) {
        performSearch(data.query, data.append);
    }
});
on('showDetailView', (item, tracks) => {
    // Handle both (item, tracks) and ({ item, tracks }) signatures
    if (item && item.item && item.tracks) {
        showDetailView(item.item, item.tracks);
    } else {
        showDetailView(item, tracks);
    }
});
on('openAlbum', (id) => openAlbum(id));
on('openArtist', (id) => openArtist(id));
on('openPodcastEpisodes', (podcast) => openPodcastEpisodes(podcast));
on('openAudiobook', (id) => openAudiobook(id));
on('renderPlaylistsView', () => renderPlaylistsView());
on('renderMyPodcastsView', () => renderMyPodcastsView());
on('renderMyBooksView', () => renderMyBooksView());
on('renderRecommendations', () => renderRecommendations());
on('showPlaylistDetail', (playlist) => showPlaylistDetail(playlist));
on('toggleMiniPlayer', () => toggleMiniPlayer());
on('fetchAudioFeaturesForTracks', (tracks) => fetchAudioFeaturesForTracks(tracks));
on('openDownloadModal', ({ tracks, isBatch }) => {
    if (openDownloadModal) openDownloadModal(tracks, isBatch);
});
on('addToQueue', (track) => addToQueue(track));
on('trackStarted', (track) => {
    // Hook for AI Radio and other listeners
});
on('moodChanged', (mood) => {
    // If AI Radio is active, re-generate queue with new mood
    if (state.aiRadioActive) {
        state.queue.splice(state.currentIndex + 1); // Clear upcoming tracks
        checkAndAddTracks(); // Re-fetch with new mood context
    }
});

// Cross-device sync events
on('enableSync', (url) => enableSync(url));
on('disableSync', () => disableSync());
on('syncDiscoverDevices', async () => {
    const devices = await discoverDevices();
    emit('syncDevicesFound', devices);
});

// Send sync deltas on local state changes
on('trackStarted', () => {
    if (state.syncEnabled) sendDelta({ currentIndex: state.currentIndex, isPlaying: true, currentTime: 0 });
});
on('playStateChanged', (isPlaying) => {
    if (state.syncEnabled) sendDelta({ isPlaying });
});
on('queueChanged', () => {
    if (state.syncEnabled) sendFullState();
});
on('repeatModeChanged', (mode) => {
    if (state.syncEnabled) sendDelta({ repeatMode: mode });
});
on('volumeChanged', (vol) => {
    if (state.syncEnabled) sendDelta({ volume: vol });
});

// ========== GLOBAL CLICK DELEGATION ==========
// Detail tracks click handler
document.addEventListener('click', (e) => {
    const trackItem = e.target.closest('#detail-tracks .track-item');
    if (!trackItem) return;

    if (e.target.closest('.download-btn') || e.target.closest('.delete-track-btn') || e.target.closest('.info-btn') || e.target.closest('.star-btn')) return;

    const index = parseInt(trackItem.dataset.index, 10);
    if (isNaN(index)) return;

    const sourceTracks = (state.detailTracks && state.detailTracks.length > 0) ? state.detailTracks : [];
    if (sourceTracks.length === 0) return;

    const clickedTrack = sourceTracks[index];
    if (clickedTrack && clickedTrack.source === 'podcast') {
        showPodcastModal(encodeURIComponent(JSON.stringify(clickedTrack)));
        return;
    }

    const remainingTracks = sourceTracks.slice(index);

    state.queue = remainingTracks;
    state.currentIndex = 0;

    showToast(`Queueing ${remainingTracks.length} tracks...`);

    updateQueueUI();

    if (audio.preloadedTrackId === clickedTrack.id && audio.preloadedReady && audio.preloadedPlayer) {
        audio.preloadedTrackId = null;
        audio.preloadedReady = false;
        updatePlayerUI();
        updateFullscreenUI(clickedTrack);
        performGaplessSwitch();
        updateFormatBadge(getActivePlayer().src);
        setTimeout(() => preloadNextTrack(), 500);
    } else {
        loadTrack(clickedTrack);
    }
});

// Star button delegation
document.addEventListener('click', (e) => {
    const starBtn = e.target.closest('.star-btn');
    if (!starBtn) return;

    e.stopPropagation();
    const trackId = starBtn.dataset.trackId;
    if (!trackId) return;

    let track = state.history.find(t => t.id === trackId)
             || state.library.find(t => t.id === trackId)
             || state.detailTracks.find(t => t.id === trackId)
             || state.queue.find(t => t.id === trackId)
             || state.lastSearchResults.find(t => t.id === trackId);

    if (!track) {
        const trackItem = starBtn.closest('.track-item');
        if (trackItem) {
            const nameEl = trackItem.querySelector('.track-name');
            const artistEl = trackItem.querySelector('.track-artist');
            const artEl = trackItem.querySelector('.track-album-art');
            track = {
                id: trackId,
                name: nameEl?.textContent || 'Unknown',
                artists: artistEl?.textContent || '',
                album_art: artEl?.src || '/static/icon.svg',
                isrc: trackId
            };
        }
    }

    if (track) {
        const nowStarred = toggleLibrary(track);
        starBtn.textContent = nowStarred ? '★' : '☆';
        starBtn.classList.toggle('starred', nowStarred);
        starBtn.title = nowStarred ? 'Remove from Library' : 'Add to Library';
    }
});

// Back button
backBtn?.addEventListener('click', () => {
    detailView.classList.add('hidden');
    resultsSection.classList.remove('hidden');
    state.currentPlaylistView = null;
});

// Queue All
queueAllBtn?.addEventListener('click', () => {
    const tracks = state.detailTracks || [];
    if (tracks.length === 0) {
        showToast('No tracks to add');
        return;
    }
    tracks.forEach(t => {
        if (!state.queue.some(q => q.id === t.id)) {
            state.queue.push(t);
        }
    });
    updateQueueUI();
    showToast(`Added ${tracks.length} tracks to queue`);
});

// Shuffle & Play
shuffleBtn?.addEventListener('click', () => {
    const tracks = state.detailTracks || [];
    if (tracks.length === 0) {
        showToast('No tracks to shuffle');
        return;
    }
    const shuffled = [...tracks];
    for (let i = shuffled.length - 1; i > 0; i--) {
        const j = Math.floor(Math.random() * (i + 1));
        [shuffled[i], shuffled[j]] = [shuffled[j], shuffled[i]];
    }
    state.queue = shuffled;
    state.currentIndex = 0;
    updateQueueUI();
    loadTrack(shuffled[0]);
    showToast(`Shuffling ${shuffled.length} tracks`);
});

// ========== WINDOW GLOBALS (for inline onclick handlers) ==========
window.deleteFromPlaylist = deleteFromPlaylist;
window.toggleLibrary = toggleLibrary;
window.isInLibrary = isInLibrary;
window.addAllToLibrary = addAllToLibrary;
window.togglePodcastFavorite = togglePodcastFavorite;
window.isPodcastFavorited = isPodcastFavorited;
window.toggleAudiobookFavorite = toggleAudiobookFavorite;
window.toggleEpisodePlayed = toggleEpisodePlayed;
window.isEpisodePlayed = isEpisodePlayed;
window.setPodcastTags = setPodcastTags;
window.getPodcastTags = getPodcastTags;
window.playHistoryTrack = playHistoryTrack;
window.openJumpBackInAlbum = openJumpBackInAlbum;
window.searchArtist = searchArtist;
window.openPlaylistById = openPlaylistById;
window.showLibraryView = showLibraryView;
window.removeFromQueue = removeFromQueue;
window.openAddToPlaylistModal = openAddToPlaylistModal;
window.showPodcastModal = showPodcastModal;
window.openAlbum = openAlbum;
window.openAudiobook = openAudiobook;
window.connectSyncDevice = (url) => { enableSync(url); };
window.openArtist = openArtist;
window.addToQueue = addToQueue;
window.performSearch = performSearch;
window.showDetailView = showDetailView;
window.openDownloadModal = openDownloadModal;
window.renderPlaylistsView = renderPlaylistsView;
window.showPlaylistDetail = showPlaylistDetail;
window.openPodcastEpisodes = openPodcastEpisodes;
window.showArtistBio = showArtistBio;
window.showLyricsModal = showLyricsModal;
window.showMusicVideo = showMusicVideo;
window.loadTrack = loadTrack;
window.playTrack = playTrack;
window.togglePlay = togglePlay;
window.playNext = playNext;
window.updateQueueUI = updateQueueUI;
window.updatePlayerUI = updatePlayerUI;
window.toggleFullScreen = toggleFullScreen;
window.showLoading = showLoading;
window.hideLoading = hideLoading;
window.showError = showError;
window.escapeHtml = escapeHtml;
window.formatTime = formatTime;
window.renderTrackCard = renderTrackCard;
window.renderAlbumCard = renderAlbumCard;
window.renderArtistCard = renderArtistCard;
window.renderMyPodcastsView = renderMyPodcastsView;
window.renderMyBooksView = renderMyBooksView;
window.fetchAudioFeaturesForTracks = fetchAudioFeaturesForTracks;
window.renderDJBadgeForTrack = renderDJBadgeForTrack;

// ========== SERVICE WORKER ==========
if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/sw.js').catch(console.error);
}

// ========== BEFOREUNLOAD ==========
window.addEventListener('beforeunload', () => {
    try {
        const currentTrack = state.queue && state.queue[state.currentIndex];
        if (currentTrack && (currentTrack.source === 'podcast' || currentTrack.source === 'audiobook')) {
            const player = document.getElementById('audio-player');
            const player2 = document.getElementById('audio-player-2');
            const activeP = (player && !player.paused) ? player : (player2 && !player2.paused) ? player2 : player;
            if (activeP && activeP.currentTime > 5) {
                saveEpisodePosition(currentTrack.id, activeP.currentTime);
            }
        }
    } catch (e) { /* ignore errors during unload */ }
});

// ========== INIT ==========
showEmptyState();

// Deferred init
setTimeout(() => {
    loadQueueFromStorage();
    audioPlayer.volume = state.volume;
    audioPlayer2.volume = state.volume;
    if (volumeSlider) {
        volumeSlider.value = Math.round(state.volume * 100);
    }
}, 100);

// Init deferred features
initPlaylistExportImport();
initAudiobooks();
initLocalFiles();
initGoogleDriveSync();
initDJMode();
initVisualizer();
initConcertAlerts();
initAIRadio();
initAIAssistant();
initSpotifyOAuth();
initDataExportImport();
initSync();
initSyncUI();
