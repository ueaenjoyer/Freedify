/**
 * Freedify Audio Engine Module
 * Equalizer (Web Audio API), crossfade, gapless playback, preloading
 */

import { state } from './state.js';
import { $ , $$, audioPlayer, audioPlayer2 } from './dom.js';

// ========== SHARED AUDIO STATE ==========
export const audio = {
    audioContext: null,
    sourceNode: null,
    sourceNode2: null,
    gainNode1: null,
    gainNode2: null,
    eqFilters: [],
    bassBoostFilter: null,
    volumeBoostGain: null,
    eqConnected: false,
    activePlayer: 1,
    crossfadeEnabled: localStorage.getItem('freedify_crossfade') === 'true',
    CROSSFADE_DURATION: 1000,
    crossfadeTimeout: null,
    preloadedPlayer: null,
    preloadedReady: false,
    preloadedTrackId: null,
    transitionInProgress: false,
    loadInProgress: false,
    loadTimeoutId: null,
    consecutiveFailures: 0,
    MAX_CONSECUTIVE_FAILURES: 5,
    stallRecoveryTimer: null,
    waitingWatchdog: null,
};

// ========== PLAYER ACCESSORS ==========
export function getActivePlayer() {
    return audio.activePlayer === 1 ? audioPlayer : audioPlayer2;
}

export function getInactivePlayer() {
    return audio.activePlayer === 1 ? audioPlayer2 : audioPlayer;
}

// ========== CROSSFADE ==========
export function performCrossfade() {
    const oldPlayer = audio.activePlayer === 1 ? audioPlayer : audioPlayer2;
    const newPlayer = audio.activePlayer === 1 ? audioPlayer2 : audioPlayer;
    const fadeOutGain = audio.activePlayer === 1 ? audio.gainNode1 : audio.gainNode2;
    const fadeInGain = audio.activePlayer === 1 ? audio.gainNode2 : audio.gainNode1;

    if (!audio.audioContext || !fadeOutGain || !fadeInGain) return;

    const now = audio.audioContext.currentTime;
    const fadeDuration = audio.CROSSFADE_DURATION / 1000;

    audio.activePlayer = audio.activePlayer === 1 ? 2 : 1;

    // Propagate playback speed & pitch preservation to the new player
    const currentTrack = state.queue?.[state.currentIndex];
    if (currentTrack && (currentTrack.source === 'podcast' || currentTrack.source === 'audiobook')) {
        newPlayer.preservesPitch = true;
        newPlayer.playbackRate = state.playbackSpeed;
    } else {
        newPlayer.preservesPitch = true;
        newPlayer.playbackRate = 1.0;
    }

    newPlayer.play().catch(e => console.error('Crossfade play error:', e));

    fadeOutGain.gain.setValueAtTime(1, now);
    fadeOutGain.gain.linearRampToValueAtTime(0, now + fadeDuration);

    fadeInGain.gain.setValueAtTime(0, now);
    fadeInGain.gain.linearRampToValueAtTime(1, now + fadeDuration);

    setTimeout(() => {
        oldPlayer.pause();
        oldPlayer.currentTime = 0;
    }, audio.CROSSFADE_DURATION + 100);
}

// ========== GAPLESS SWITCH ==========
export function performGaplessSwitch() {
    const oldPlayer = audio.activePlayer === 1 ? audioPlayer : audioPlayer2;
    const newPlayer = audio.activePlayer === 1 ? audioPlayer2 : audioPlayer;
    const fadeOutGain = audio.activePlayer === 1 ? audio.gainNode1 : audio.gainNode2;
    const fadeInGain = audio.activePlayer === 1 ? audio.gainNode2 : audio.gainNode1;

    audio.activePlayer = audio.activePlayer === 1 ? 2 : 1;

    if (fadeOutGain) fadeOutGain.gain.value = 0;
    if (fadeInGain) fadeInGain.gain.value = 1;

    // Propagate playback speed & pitch preservation to the new player
    const currentTrack = state.queue?.[state.currentIndex];
    if (currentTrack && (currentTrack.source === 'podcast' || currentTrack.source === 'audiobook')) {
        newPlayer.preservesPitch = true;
        newPlayer.playbackRate = state.playbackSpeed;
    } else {
        newPlayer.preservesPitch = true;
        newPlayer.playbackRate = 1.0;
    }

    newPlayer.play().catch(e => console.error('Gapless play error:', e));
    oldPlayer.pause();
    oldPlayer.currentTime = 0;
}

// ========== PRELOADING ==========
export function preloadNextTrack() {
    if (state.currentIndex === -1 || state.currentIndex >= state.queue.length - 1) return;

    const nextTrack = state.queue[state.currentIndex + 1];
    if (!nextTrack || nextTrack.id === audio.preloadedTrackId) return;

    audio.preloadedTrackId = nextTrack.id;
    audio.preloadedReady = false;

    const query = `${nextTrack.name} ${nextTrack.artists}`;
    const hiresParam = state.hiResMode ? '&hires=true' : '&hires=false';
    const qualityParam = state.hiResMode ? `&hires_quality=${state.hiResQuality}` : '';
    const sourceParam = nextTrack.source ? `&source=${nextTrack.source}` : '';
    const streamUrl = `/api/stream/${nextTrack.isrc || nextTrack.id}?q=${encodeURIComponent(query)}${hiresParam}${qualityParam}${sourceParam}`;

    const inactivePlayer = audio.activePlayer === 1 ? audioPlayer2 : audioPlayer;

    const onReady = () => {
        audio.preloadedReady = true;
        inactivePlayer.removeEventListener('canplaythrough', onReady);
    };
    const onError = () => {
        audio.preloadedReady = false;
        audio.preloadedTrackId = null;
        audio.preloadedPlayer = null;
        inactivePlayer.removeEventListener('canplaythrough', onReady);
        inactivePlayer.removeEventListener('error', onError);
    };
    inactivePlayer.addEventListener('canplaythrough', onReady);
    inactivePlayer.addEventListener('error', onError, { once: true });

    inactivePlayer.src = streamUrl;
    inactivePlayer.load();
    audio.preloadedPlayer = inactivePlayer;
}

// ========== EQUALIZER ==========
const EQ_BANDS = [
    { id: 'eq-60', freq: 60, type: 'lowshelf' },
    { id: 'eq-230', freq: 230, type: 'peaking' },
    { id: 'eq-910', freq: 910, type: 'peaking' },
    { id: 'eq-3600', freq: 3600, type: 'peaking' },
    { id: 'eq-7500', freq: 7500, type: 'highshelf' }
];

const EQ_PRESETS = {
    flat: [0, 0, 0, 0, 0],
    bass: [6, 4, 0, 0, 0],
    treble: [0, 0, 0, 3, 6],
    vocal: [-2, 0, 4, 2, -1]
};

const eqPanel = $('#eq-panel');
const eqToggleBtn = $('#eq-toggle-btn');
const eqCloseBtn = $('#eq-close-btn');
const eqPresets = $$('.eq-preset');
const bassBoostSlider = $('#bass-boost');
const bassBoostVal = $('#bass-boost-val');
const volumeBoostSlider = $('#volume-boost');
const volumeBoostVal = $('#volume-boost-val');

export function initEqualizer() {
    if (audio.audioContext) return;

    try {
        audio.audioContext = new (window.AudioContext || window.webkitAudioContext)();

        audio.audioContext.onstatechange = () => {
            if (audio.audioContext.state === 'suspended' && state.isPlaying) {
                audio.audioContext.resume();
            }
        };

        audio.sourceNode = audio.audioContext.createMediaElementSource(audioPlayer);
        audio.sourceNode2 = audio.audioContext.createMediaElementSource(audioPlayer2);

        audio.gainNode1 = audio.audioContext.createGain();
        audio.gainNode2 = audio.audioContext.createGain();
        audio.gainNode1.gain.value = 1;
        audio.gainNode2.gain.value = 0;

        audio.eqFilters = EQ_BANDS.map(band => {
            const filter = audio.audioContext.createBiquadFilter();
            filter.type = band.type;
            filter.frequency.value = band.freq;
            filter.gain.value = 0;
            if (band.type === 'peaking') filter.Q.value = 1;
            return filter;
        });

        audio.bassBoostFilter = audio.audioContext.createBiquadFilter();
        audio.bassBoostFilter.type = 'lowshelf';
        audio.bassBoostFilter.frequency.value = 100;
        audio.bassBoostFilter.gain.value = 0;

        audio.volumeBoostGain = audio.audioContext.createGain();
        audio.volumeBoostGain.gain.value = 1;

        audio.sourceNode.connect(audio.gainNode1);
        audio.sourceNode2.connect(audio.gainNode2);

        const firstFilter = audio.eqFilters[0];
        audio.gainNode1.connect(firstFilter);
        audio.gainNode2.connect(firstFilter);

        let lastNode = firstFilter;
        for (let i = 1; i < audio.eqFilters.length; i++) {
            lastNode.connect(audio.eqFilters[i]);
            lastNode = audio.eqFilters[i];
        }
        lastNode.connect(audio.bassBoostFilter);
        audio.bassBoostFilter.connect(audio.volumeBoostGain);
        audio.volumeBoostGain.connect(audio.audioContext.destination);

        audio.eqConnected = true;

        loadEqSettings();
    } catch (e) {
        console.error('Failed to initialize equalizer:', e);
    }
}

function loadEqSettings() {
    const saved = localStorage.getItem('freedify_eq');
    if (saved) {
        try {
            const settings = JSON.parse(saved);
            EQ_BANDS.forEach((band, i) => {
                const slider = $(`#${band.id}`);
                if (slider && settings.bands[i] !== undefined) {
                    slider.value = settings.bands[i];
                    if (audio.eqFilters[i]) audio.eqFilters[i].gain.value = settings.bands[i];
                }
            });
            if (settings.bass !== undefined) {
                bassBoostSlider.value = settings.bass;
                if (audio.bassBoostFilter) audio.bassBoostFilter.gain.value = settings.bass;
                bassBoostVal.textContent = `${settings.bass}dB`;
            }
            if (settings.volume !== undefined) {
                volumeBoostSlider.value = settings.volume;
                if (audio.volumeBoostGain) audio.volumeBoostGain.gain.value = Math.pow(10, settings.volume / 20);
                volumeBoostVal.textContent = `${settings.volume}dB`;
            }
        } catch (e) { console.error('Error loading EQ settings:', e); }
    }
}

function saveEqSettings() {
    const settings = {
        bands: EQ_BANDS.map(band => parseFloat($(`#${band.id}`).value)),
        bass: parseFloat(bassBoostSlider.value),
        volume: parseFloat(volumeBoostSlider.value)
    };
    localStorage.setItem('freedify_eq', JSON.stringify(settings));
}

function applyPreset(preset) {
    const values = EQ_PRESETS[preset];
    if (!values) return;

    EQ_BANDS.forEach((band, i) => {
        const slider = $(`#${band.id}`);
        slider.value = values[i];
        if (audio.eqFilters[i]) audio.eqFilters[i].gain.value = values[i];
    });

    eqPresets.forEach(btn => btn.classList.remove('active'));
    document.querySelector(`[data-preset="${preset}"]`)?.classList.add('active');

    saveEqSettings();
}

// ========== EQ EVENT LISTENERS ==========
eqToggleBtn?.addEventListener('click', () => {
    if (!audio.audioContext) initEqualizer();
    eqPanel.classList.toggle('hidden');
    eqToggleBtn.classList.toggle('active');
});

eqCloseBtn?.addEventListener('click', () => {
    eqPanel.classList.add('hidden');
    eqToggleBtn.classList.remove('active');
});

eqPresets.forEach(btn => {
    btn.addEventListener('click', () => applyPreset(btn.dataset.preset));
});

EQ_BANDS.forEach((band, i) => {
    const slider = $(`#${band.id}`);
    slider?.addEventListener('input', () => {
        if (audio.eqFilters[i]) audio.eqFilters[i].gain.value = parseFloat(slider.value);
        saveEqSettings();
        eqPresets.forEach(btn => btn.classList.remove('active'));
    });
});

bassBoostSlider?.addEventListener('input', () => {
    const val = parseFloat(bassBoostSlider.value);
    if (audio.bassBoostFilter) audio.bassBoostFilter.gain.value = val;
    bassBoostVal.textContent = `${val}dB`;
    saveEqSettings();
});

volumeBoostSlider?.addEventListener('input', () => {
    const val = parseFloat(volumeBoostSlider.value);
    if (audio.volumeBoostGain) audio.volumeBoostGain.gain.value = Math.pow(10, val / 20);
    volumeBoostVal.textContent = `${val}dB`;
    saveEqSettings();
});

// Resume AudioContext when audio starts playing
export function handleEQResume() {
    if (!audio.audioContext) {
        initEqualizer();
        // initEqualizer may create a suspended context (browser autoplay policy
        // blocks AudioContext creation after an async break in the user gesture
        // chain). Resume immediately so audio isn't silenced.
        if (audio.audioContext && audio.audioContext.state === 'suspended') {
            audio.audioContext.resume().catch(() => {});
        }
    } else if (audio.audioContext.state === 'suspended') {
        audio.audioContext.resume();
    }
}

audioPlayer.addEventListener('play', handleEQResume);
audioPlayer2.addEventListener('play', handleEQResume);
