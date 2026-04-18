/**
 * Freedify Data Module
 * All CRUD for playlists, library, history, podcasts, audiobooks, tags
 */

import { state, enforceArrayCap, MAX_LIBRARY_SIZE } from './state.js';
import { showToast } from './utils.js';
import { emit } from './event-bus.js';
import { markDirty } from './cloud-sync.js';

// ========== PLAYLIST MANAGEMENT ==========
export function savePlaylists() {
    localStorage.setItem('freedify_playlists', JSON.stringify(state.playlists));
    markDirty('playlists');
}

export function createPlaylist(name, tracks = []) {
    const playlist = {
        id: 'playlist_' + Date.now(),
        name: name,
        created: new Date().toISOString(),
        tracks: tracks.map(t => ({
            id: t.id,
            name: t.name,
            artists: t.artists,
            album: t.album || '',
            album_art: t.album_art || t.image || '/static/icon.svg',
            isrc: t.isrc || t.id,
            duration: t.duration || '0:00'
        }))
    };
    state.playlists.push(playlist);
    savePlaylists();
    showToast(`Created playlist "${name}"`);
    return playlist;
}

export function addToPlaylist(playlistId, trackOrTracks) {
    const playlist = state.playlists.find(p => p.id === playlistId);
    if (!playlist) return;

    const tracksToAdd = Array.isArray(trackOrTracks) ? trackOrTracks : [trackOrTracks];
    let addedCount = 0;

    tracksToAdd.forEach(track => {
        if (playlist.tracks.some(t => t.id === track.id)) return;

        playlist.tracks.push({
            id: track.id,
            name: track.name,
            artists: track.artists,
            album: track.album || '',
            album_art: track.album_art || track.image || '/static/icon.svg',
            isrc: track.isrc || track.id,
            duration: track.duration || '0:00'
        });
        addedCount++;
    });

    if (addedCount > 0) {
        savePlaylists();
        showToast(`Added ${addedCount} tracks to "${playlist.name}"`);
    } else {
        showToast('Tracks already in playlist');
    }
}

export function deleteFromPlaylist(playlistId, trackId) {
    const playlist = state.playlists.find(p => p.id === playlistId);
    if (!playlist) return;

    const idx = playlist.tracks.findIndex(t => t.id === trackId);
    if (idx !== -1) {
        playlist.tracks.splice(idx, 1);
        savePlaylists();
        showToast('Track removed');
        // Refresh view if currently viewing this playlist
        if (state.currentPlaylistView === playlistId) {
            emit('showPlaylistDetail', playlist);
        }
    }
}

export function deletePlaylist(playlistId) {
    state.playlists = state.playlists.filter(p => p.id !== playlistId);
    savePlaylists();
    showToast('Playlist deleted');
    emit('renderPlaylistsView');
}

// ========== WATCHED PLAYLISTS ==========
export function saveWatchedPlaylists() {
    localStorage.setItem('freedify_watched', JSON.stringify(state.watchedPlaylists));
    markDirty('watched_playlists');
}

export function watchPlaylist(spotifyId, name, coverArt, tracks) {
    if (state.watchedPlaylists.some(w => w.spotifyId === spotifyId)) {
        showToast(`Already watching "${name}"`);
        return;
    }

    const trackHashes = new Set();
    tracks.forEach(t => {
        const key = `${(t.artists || '').toLowerCase()}|||${(t.name || '').toLowerCase()}`;
        trackHashes.add(key);
    });

    // Store full track data for instant offline opening (same shape as regular playlists)
    const storedTracks = tracks.map(t => ({
        id: t.id,
        name: t.name,
        artists: t.artists,
        album: t.album || '',
        album_art: t.album_art || t.image || '/static/icon.svg',
        album_id: t.album_id || '',
        isrc: t.isrc || t.id,
        duration: t.duration || '0:00',
        source: t.source || 'spotify'
    }));

    state.watchedPlaylists.push({
        spotifyId: spotifyId,
        name: name,
        coverArt: coverArt || '/static/icon.svg',
        trackCount: tracks.length,
        trackHashes: Array.from(trackHashes),
        tracks: storedTracks,
        lastSynced: new Date().toISOString(),
        newTracks: 0
    });

    saveWatchedPlaylists();
    showToast(`Now watching "${name}" — you'll be notified of new tracks!`);
}

export function unwatchPlaylist(spotifyId) {
    const wp = state.watchedPlaylists.find(w => w.spotifyId === spotifyId);
    state.watchedPlaylists = state.watchedPlaylists.filter(w => w.spotifyId !== spotifyId);
    saveWatchedPlaylists();
    if (wp) showToast(`Stopped watching "${wp.name}"`);
    emit('renderPlaylistsView');
}

export function isWatchedPlaylist(spotifyId) {
    return state.watchedPlaylists.some(w => w.spotifyId === spotifyId);
}

export async function syncOneWatchedPlaylist(watched) {
    const url = `https://open.spotify.com/playlist/${watched.spotifyId}`;
    try {
        const response = await fetch(`/api/search?q=${encodeURIComponent(url)}&type=playlist`);
        const data = await response.json();
        if (!response.ok || !data.tracks) return null;

        const currentHashes = new Set();
        data.tracks.forEach(t => {
            const key = `${(t.artists || '').toLowerCase()}|||${(t.name || '').toLowerCase()}`;
            currentHashes.add(key);
        });

        const oldHashes = new Set(watched.trackHashes || []);
        const newTrackKeys = [];
        currentHashes.forEach(key => {
            if (!oldHashes.has(key)) newTrackKeys.push(key);
        });

        watched.trackHashes = Array.from(currentHashes);
        watched.trackCount = data.tracks.length;
        watched.lastSynced = new Date().toISOString();
        watched.newTracks = newTrackKeys.length;
        if (data.results && data.results[0]) {
            watched.name = data.results[0].name || watched.name;
            watched.coverArt = data.results[0].album_art || data.results[0].image || watched.coverArt;
        }

        // Update stored tracks with fresh data from API
        watched.tracks = data.tracks.map(t => ({
            id: t.id,
            name: t.name,
            artists: t.artists,
            album: t.album || '',
            album_art: t.album_art || t.image || '/static/icon.svg',
            album_id: t.album_id || '',
            isrc: t.isrc || t.id,
            duration: t.duration || '0:00',
            source: t.source || 'spotify'
        }));

        return { watched, newCount: newTrackKeys.length, playlistName: watched.name };
    } catch (e) {
        console.warn(`Failed to sync watched playlist ${watched.name}:`, e);
        return null;
    }
}

export async function syncAllWatchedPlaylists(showProgress = true) {
    if (state.watchedPlaylists.length === 0) return;

    if (showProgress) showToast('Syncing watched playlists...');

    let totalNew = 0;
    const updates = [];

    for (const watched of state.watchedPlaylists) {
        const result = await syncOneWatchedPlaylist(watched);
        if (result && result.newCount > 0) {
            totalNew += result.newCount;
            updates.push(`${result.newCount} new in "${result.playlistName}"`);
        }
    }

    saveWatchedPlaylists();

    if (totalNew > 0) {
        showToast(`${totalNew} new track${totalNew !== 1 ? 's' : ''} found! ${updates.join(', ')}`);
    } else if (showProgress) {
        showToast('All watched playlists are up to date');
    }

    if (state.searchType === 'favorites') {
        emit('renderPlaylistsView');
    }
}

// ========== LISTENING HISTORY ==========
export function saveHistory() {
    localStorage.setItem('freedify_history', JSON.stringify(state.history));
    markDirty('history');
}

export function addToHistory(track) {
    if (!track || !track.id) return;

    const historyEntry = {
        id: track.id,
        name: track.name,
        artists: track.artists,
        album: track.album || '',
        album_art: track.album_art || track.image || '/static/icon.svg',
        album_id: track.album_id || '',
        isrc: track.isrc || track.id,
        duration: track.duration || '0:00',
        listenedAt: Date.now(),
        source: track.source || 'youtube'
    };

    state.history = state.history.filter(h => h.id !== track.id);
    state.history.unshift(historyEntry);

    if (state.history.length > 50) {
        state.history = state.history.slice(0, 50);
    }

    saveHistory();
}

// ========== MY LIBRARY (STARRED TRACKS) ==========
export function saveLibrary() {
    localStorage.setItem('freedify_library', JSON.stringify(state.library));
    markDirty('library');
}

export function addToLibrary(track) {
    if (!track || !track.id) return false;
    if (state.library.some(t => t.id === track.id)) return false;

    const libraryEntry = {
        id: track.id,
        name: track.name,
        artists: track.artists,
        album: track.album || '',
        album_art: track.album_art || track.image || '/static/icon.svg',
        isrc: track.isrc || track.id,
        duration: track.duration || '0:00',
        addedAt: Date.now(),
        source: track.source || 'youtube'
    };

    state.library.unshift(libraryEntry);
    enforceArrayCap(state.library, MAX_LIBRARY_SIZE);
    saveLibrary();
    showToast(`Added "${track.name}" to Library`);
    return true;
}

export function removeFromLibrary(trackId) {
    const idx = state.library.findIndex(t => t.id === trackId);
    if (idx !== -1) {
        const track = state.library[idx];
        state.library.splice(idx, 1);
        saveLibrary();
        showToast(`Removed "${track.name}" from Library`);
        return true;
    }
    return false;
}

export function isInLibrary(trackId) {
    return state.library.some(t => t.id === trackId);
}

export function toggleLibrary(track) {
    if (isInLibrary(track.id)) {
        removeFromLibrary(track.id);
        return false;
    } else {
        addToLibrary(track);
        return true;
    }
}

export function addAllToLibrary(tracks) {
    if (!tracks || tracks.length === 0) {
        showToast('No tracks to add');
        return 0;
    }

    let addedCount = 0;
    tracks.forEach(track => {
        if (track && track.id && !isInLibrary(track.id)) {
            const libraryEntry = {
                id: track.id,
                name: track.name,
                artists: track.artists,
                album: track.album || '',
                album_art: track.album_art || track.image || '/static/icon.svg',
                isrc: track.isrc || track.id,
                duration: track.duration || '0:00',
                addedAt: Date.now(),
                source: track.source || 'youtube'
            };
            state.library.unshift(libraryEntry);
            addedCount++;
        }
    });

    if (addedCount > 0) {
        enforceArrayCap(state.library, MAX_LIBRARY_SIZE);
        saveLibrary();
        showToast(`Added ${addedCount} of ${tracks.length} tracks to Library`);
    } else {
        showToast('All tracks already in Library');
    }
    return addedCount;
}

// ========== PODCAST FAVORITES ==========
export function savePodcastFavorites() {
    localStorage.setItem('freedify_podcasts', JSON.stringify(state.podcastFavorites));
    markDirty('podcast_favorites');
}

export function addPodcastFavorite(podcast) {
    if (!podcast || !podcast.id) return false;
    if (state.podcastFavorites.some(p => p.id === podcast.id)) return false;

    state.podcastFavorites.unshift({
        id: podcast.id,
        name: podcast.name,
        artist: podcast.artists || podcast.artist || '',
        artwork: podcast.album_art || podcast.artwork || '/static/icon.svg',
        addedAt: Date.now(),
        tags: []
    });
    savePodcastFavorites();
    showToast(`Saved "${podcast.name}" to My Podcasts`);
    return true;
}

export function removePodcastFavorite(podcastId) {
    const idx = state.podcastFavorites.findIndex(p => p.id === podcastId);
    if (idx !== -1) {
        const podcast = state.podcastFavorites[idx];
        state.podcastFavorites.splice(idx, 1);
        savePodcastFavorites();
        showToast(`Removed "${podcast.name}" from My Podcasts`);
        return true;
    }
    return false;
}

export function isPodcastFavorited(podcastId) {
    return state.podcastFavorites.some(p => p.id === podcastId);
}

export function togglePodcastFavorite(podcast) {
    if (isPodcastFavorited(podcast.id)) {
        removePodcastFavorite(podcast.id);
        return false;
    } else {
        addPodcastFavorite(podcast);
        return true;
    }
}

// ========== AUDIOBOOK FAVORITES ==========
export function saveAudiobookFavorites() {
    localStorage.setItem('freedify_audiobooks', JSON.stringify(state.audiobookFavorites));
    markDirty('audiobook_favorites');
}

export function addAudiobookFavorite(book) {
    if (!book || !book.id) return false;
    if (state.audiobookFavorites.some(b => b.id === book.id)) return false;

    state.audiobookFavorites.unshift({
        id: book.id,
        name: book.name || book.title,
        artist: book.artists || book.artist || 'AudiobookBay',
        artwork: book.album_art || book.cover_image || book.artwork || '/static/icon.svg',
        folder_id: book.folder_id || null,
        premiumize_id: book.premiumize_id || null,
        addedAt: Date.now()
    });
    saveAudiobookFavorites();
    showToast(`Saved "${book.name || book.title}" to My Books`);
    return true;
}

export function removeAudiobookFavorite(bookId) {
    const idx = state.audiobookFavorites.findIndex(b => b.id === bookId);
    if (idx !== -1) {
        const book = state.audiobookFavorites[idx];
        state.audiobookFavorites.splice(idx, 1);
        saveAudiobookFavorites();
        showToast(`Removed "${book.name}" from My Books`);
        return true;
    }
    return false;
}

export function isAudiobookFavorited(bookId) {
    return state.audiobookFavorites.some(b => b.id === bookId);
}

export function toggleAudiobookFavorite(book) {
    if (isAudiobookFavorited(book.id)) {
        removeAudiobookFavorite(book.id);
        return false;
    } else {
        addAudiobookFavorite(book);
        return true;
    }
}

// ========== PODCAST EPISODE TRACKING ==========
export function savePodcastPlayed() {
    localStorage.setItem('freedify_podcast_played', JSON.stringify(state.podcastPlayedEpisodes));
    markDirty('podcast_played');
}

export function markEpisodePlayed(episodeId) {
    state.podcastPlayedEpisodes[episodeId] = true;
    savePodcastPlayed();
}

export function markEpisodeUnplayed(episodeId) {
    delete state.podcastPlayedEpisodes[episodeId];
    savePodcastPlayed();
}

export function isEpisodePlayed(episodeId) {
    return !!state.podcastPlayedEpisodes[episodeId];
}

export function toggleEpisodePlayed(episodeId) {
    if (isEpisodePlayed(episodeId)) {
        markEpisodeUnplayed(episodeId);
        return false;
    } else {
        markEpisodePlayed(episodeId);
        return true;
    }
}

// ========== PODCAST RESUME POSITIONS ==========
export function savePodcastResumePositions() {
    localStorage.setItem('freedify_podcast_resume', JSON.stringify(state.podcastResumePositions));
    markDirty('resume_positions');
}

export function saveEpisodePosition(episodeId, seconds) {
    if (seconds > 5) {
        state.podcastResumePositions[episodeId] = Math.floor(seconds);
        savePodcastResumePositions();
    }
}

export function getEpisodePosition(episodeId) {
    return state.podcastResumePositions[episodeId] || 0;
}

export function clearEpisodePosition(episodeId) {
    delete state.podcastResumePositions[episodeId];
    savePodcastResumePositions();
}

// ========== PODCAST HISTORY ==========
export function savePodcastHistory() {
    localStorage.setItem('freedify_podcast_history', JSON.stringify(state.podcastHistory));
    markDirty('podcast_history');
}

export function addToPodcastHistory(episode) {
    if (!episode || !episode.id) return;
    state.podcastHistory = state.podcastHistory.filter(e => e.id !== episode.id);
    state.podcastHistory.unshift({
        id: episode.id,
        name: episode.name,
        artists: episode.artists || '',
        album_art: episode.album_art || '/static/icon.svg',
        duration: episode.duration || '0:00',
        playedAt: Date.now(),
        source: episode.source || 'podcast'
    });
    if (state.podcastHistory.length > 50) state.podcastHistory = state.podcastHistory.slice(0, 50);
    savePodcastHistory();
}

// ========== AUDIOBOOK HISTORY ==========
export function saveAudiobookHistory() {
    localStorage.setItem('freedify_audiobook_history', JSON.stringify(state.audiobookHistory));
    markDirty('audiobook_history');
}

export function addToAudiobookHistory(episode) {
    if (!episode || !episode.id) return;
    state.audiobookHistory = state.audiobookHistory.filter(e => e.id !== episode.id);
    state.audiobookHistory.unshift({
        id: episode.id,
        name: episode.name,
        artists: episode.artists || '',
        album_art: episode.album_art || '/static/icon.svg',
        duration: episode.duration || '0:00',
        url: episode.url || '',
        src: episode.src || '',
        is_local: episode.is_local || false,
        track_number: episode.track_number || '',
        playedAt: Date.now(),
        source: episode.source || 'audiobook'
    });
    if (state.audiobookHistory.length > 50) state.audiobookHistory = state.audiobookHistory.slice(0, 50);
    saveAudiobookHistory();
}

// ========== PODCAST TAGS ==========
export function savePodcastTags() {
    localStorage.setItem('freedify_podcast_tags', JSON.stringify(state.podcastTags));
}

export function setPodcastTags(podcastId, tags) {
    state.podcastTags[podcastId] = tags;
    savePodcastTags();
    const fav = state.podcastFavorites.find(p => p.id === podcastId);
    if (fav) {
        fav.tags = tags;
        savePodcastFavorites();
    }
}

export function getPodcastTags(podcastId) {
    return state.podcastTags[podcastId] || [];
}

export function getAllUsedTags() {
    const tags = new Set();
    Object.values(state.podcastTags).forEach(arr => arr.forEach(t => tags.add(t)));
    return [...tags].sort();
}

// ========== MOOD TRACKING ==========
const PREDEFINED_MOODS = ['Focus', 'Workout', 'Chill', 'Party', 'Late Night', 'Commute'];
const MAX_MOOD_HISTORY = 500;
const MAX_MOOD_PREF_PER_LIST = 50;

export function saveMoodEvent(mood, track, percentage) {
    if (!mood || !track || !track.id) return;
    if (!isFinite(percentage) || percentage < 0) return;

    // Log to moodHistory (all moods including free-form)
    state.moodHistory.unshift({
        mood,
        trackId: track.id,
        trackName: track.name || 'Unknown',
        trackArtist: track.artists || 'Unknown',
        timestamp: Date.now(),
        percentage
    });
    // Prune to cap (front-push / tail-splice)
    if (state.moodHistory.length > MAX_MOOD_HISTORY) {
        state.moodHistory.splice(MAX_MOOD_HISTORY);
    }
    localStorage.setItem('freedify_mood_history', JSON.stringify(state.moodHistory));

    // Only update moodPreferences for predefined moods
    if (!PREDEFINED_MOODS.includes(mood)) return;
    if (!state.moodPreferences[mood]) return;

    const trackObj = { id: track.id, name: track.name || 'Unknown', artist: track.artists || 'Unknown' };

    if (percentage >= 0.75) {
        // Liked — remove from disliked first if present
        const dislikedIdx = state.moodPreferences[mood].disliked.findIndex(t => t.id === track.id);
        if (dislikedIdx !== -1) state.moodPreferences[mood].disliked.splice(dislikedIdx, 1);
        // Deduplicate
        if (!state.moodPreferences[mood].liked.find(t => t.id === track.id)) {
            state.moodPreferences[mood].liked.unshift(trackObj);
            if (state.moodPreferences[mood].liked.length > MAX_MOOD_PREF_PER_LIST) {
                state.moodPreferences[mood].liked.splice(MAX_MOOD_PREF_PER_LIST);
            }
        }
    } else if (percentage < 0.50) {
        // Disliked — remove from liked first if present
        const likedIdx = state.moodPreferences[mood].liked.findIndex(t => t.id === track.id);
        if (likedIdx !== -1) state.moodPreferences[mood].liked.splice(likedIdx, 1);
        // Deduplicate
        if (!state.moodPreferences[mood].disliked.find(t => t.id === track.id)) {
            state.moodPreferences[mood].disliked.unshift(trackObj);
            if (state.moodPreferences[mood].disliked.length > MAX_MOOD_PREF_PER_LIST) {
                state.moodPreferences[mood].disliked.splice(MAX_MOOD_PREF_PER_LIST);
            }
        }
    }
    // 50-75% is neutral — no logging to preferences

    localStorage.setItem('freedify_mood_preferences', JSON.stringify(state.moodPreferences));
}

export function getMoodPreferences(mood) {
    if (!mood || !state.moodPreferences[mood]) return { liked: [], disliked: [] };
    return state.moodPreferences[mood];
}

export function getMoodStatsForWeek(mood) {
    const oneWeekAgo = Date.now() - (7 * 24 * 60 * 60 * 1000);
    return state.moodHistory.filter(
        entry => entry.mood === mood && entry.timestamp >= oneWeekAgo
    ).length;
}
