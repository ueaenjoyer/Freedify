/**
 * Freedify Cross-Device Sync Module
 * WebSocket lifecycle, state apply/send, reconnection, rate limiting
 */

import { state } from './state.js';
import { showToast } from './utils.js';
import { audio, getActivePlayer } from './audio-engine.js';
import { emit } from './event-bus.js';

// ========== DEVICE IDENTITY ==========
function getSyncDeviceName() {
    let name = localStorage.getItem('freedify_sync_device_name');
    if (!name) {
        name = `freedify-${Math.random().toString(36).slice(2, 8)}`;
        localStorage.setItem('freedify_sync_device_name', name);
    }
    return name;
}

// ========== INTERNAL STATE ==========
let _ws = null;
let _reconnectAttempts = 0;
let _reconnectTimer = null;
let _lastSentTime = 0;
let _fullSyncJitterTimer = null;
let _serverUrl = null;

// ========== CONNECT / DISCONNECT ==========
export function connectSync(url) {
    if (_ws) {
        _ws.close();
        _ws = null;
    }

    _serverUrl = url || _serverUrl;
    if (!_serverUrl) return;

    const wsUrl = _serverUrl.replace(/^http/, 'ws') + '/api/sync/ws';

    try {
        _ws = new WebSocket(wsUrl);
    } catch (e) {
        console.error('Sync WebSocket creation failed:', e);
        scheduleReconnect();
        return;
    }

    _ws.onopen = () => {
        _reconnectAttempts = 0;
        // Connected successfully

        // Broadcast request_full_sync
        sendMessage({ type: 'request_full_sync', source: getSyncDeviceName() });

        localStorage.setItem('freedify_sync_last_ip', _serverUrl);
        emit('syncStatusChanged', 'connected');
    };

    _ws.onmessage = (event) => {
        try {
            if (typeof event.data === 'string' && event.data.length > 1_000_000) {
                console.warn('Sync: message too large, ignoring');
                return;
            }
            const msg = JSON.parse(event.data);
            handleIncomingMessage(msg);
        } catch (e) {
            console.error('Sync: invalid message', e);
        }
    };

    _ws.onclose = () => {
        emit('syncStatusChanged', 'disconnected');
        if (state.syncEnabled) {
            scheduleReconnect();
        }
    };

    _ws.onerror = (e) => {
        console.error('Sync WebSocket error:', e);
    };
}

export function disableSync() {
    state.syncEnabled = false;
    localStorage.setItem('freedify_sync_enabled', JSON.stringify(false));
    if (_reconnectTimer) {
        clearTimeout(_reconnectTimer);
        _reconnectTimer = null;
    }
    if (_fullSyncJitterTimer) {
        clearTimeout(_fullSyncJitterTimer);
        _fullSyncJitterTimer = null;
    }
    if (_ws) {
        _ws.close();
        _ws = null;
    }
    state.syncConnectedDevices = [];
    emit('syncStatusChanged', 'off');
}

export function enableSync(url) {
    state.syncEnabled = true;
    localStorage.setItem('freedify_sync_enabled', JSON.stringify(true));
    emit('syncStatusChanged', 'connecting');
    connectSync(url);
}

function scheduleReconnect() {
    if (!state.syncEnabled) return;
    if (_reconnectAttempts >= 3) {
        showToast('Sync disconnected. Check your network.');
        return;
    }
    const delay = Math.pow(2, _reconnectAttempts) * 1000;
    _reconnectTimer = setTimeout(() => {
        _reconnectAttempts++;
        connectSync();
    }, delay);
}

// ========== SEND ==========
function sendMessage(msg) {
    if (!_ws || _ws.readyState !== WebSocket.OPEN) return;
    _ws.send(JSON.stringify(msg));
}

export function sendFullState() {
    const player = getActivePlayer();
    const now = Date.now();
    state.syncLastAppliedTimestamp = now;
    sendMessage({
        type: 'state_update',
        source: getSyncDeviceName(),
        timestamp: now,
        payload: {
            queue: state.queue,
            currentIndex: state.currentIndex,
            currentTime: player ? player.currentTime : 0,
            isPlaying: state.isPlaying,
            volume: state.volume,
            repeatMode: state.repeatMode,
        }
    });
}

export function sendDelta(fields) {
    const now = Date.now();
    state.syncLastAppliedTimestamp = now;
    sendMessage({
        type: 'delta',
        source: getSyncDeviceName(),
        timestamp: now,
        payload: fields,
    });
}

// Throttled currentTime sender — only if change > 2s
export function sendTimeUpdate(currentTime) {
    if (Math.abs(currentTime - _lastSentTime) < 2) return;
    _lastSentTime = currentTime;
    sendDelta({ currentTime });
}

// ========== RECEIVE ==========
function handleIncomingMessage(msg) {
    if (msg.source === getSyncDeviceName()) return; // Ignore own messages

    if (msg.type === 'request_full_sync') {
        // Respond with full state after random jitter (0-300ms)
        // Cancel if we receive a state_update from another peer first
        if (_fullSyncJitterTimer) clearTimeout(_fullSyncJitterTimer);
        _fullSyncJitterTimer = setTimeout(() => {
            sendFullState();
            _fullSyncJitterTimer = null;
        }, Math.random() * 300);
        return;
    }

    if (msg.type === 'state_update' || msg.type === 'delta') {
        // Cancel pending full sync response if another peer already responded
        if (msg.type === 'state_update' && _fullSyncJitterTimer) {
            clearTimeout(_fullSyncJitterTimer);
            _fullSyncJitterTimer = null;
        }

        // Conflict resolution: last-write-wins
        if (msg.timestamp <= state.syncLastAppliedTimestamp) return;
        state.syncLastAppliedTimestamp = msg.timestamp;

        applyRemoteState(msg.payload, msg.type === 'state_update');
    }
}

function applyRemoteState(payload, isFull) {
    // Defer currentIndex changes during crossfade
    if (audio.transitionInProgress && payload.currentIndex !== undefined) {
        const deferred = { ...payload };
        const check = setInterval(() => {
            if (!audio.transitionInProgress) {
                clearInterval(check);
                applyRemoteState(deferred, isFull);
            }
        }, 100);
        return;
    }

    const player = getActivePlayer();

    // Apply queue (full sync only)
    if (isFull && payload.queue !== undefined) {
        state.queue = payload.queue;
        emit('updateQueueUI');
    }

    // Apply current track
    if (payload.currentIndex !== undefined && payload.currentIndex !== state.currentIndex) {
        state.currentIndex = payload.currentIndex;
        if (state.queue[state.currentIndex]) {
            emit('loadTrack', state.queue[state.currentIndex]);
        }
    }

    // Apply playback position
    if (payload.currentTime !== undefined && player) {
        const diff = Math.abs(player.currentTime - payload.currentTime);
        if (diff > 3) { // Only seek if > 3s difference
            player.currentTime = payload.currentTime;
        }
    }

    // Apply play/pause
    if (payload.isPlaying !== undefined) {
        if (payload.isPlaying && player.paused) {
            player.play().catch(() => {});
            state.isPlaying = true;
        } else if (!payload.isPlaying && !player.paused) {
            player.pause();
            state.isPlaying = false;
        }
        // Keep audio muted if this device is in remote mode
        if (state.syncRole === 'remote') {
            player.muted = true;
        }
        emit('updatePlayButton');
    }

    // Apply volume with 200ms ramp (skip if remote — audio is muted)
    if (payload.volume !== undefined && payload.volume !== state.volume && state.syncRole !== 'remote') {
        state.volume = payload.volume;
        if (audio.audioContext && audio.gainNode1) {
            const gainNode = audio.activePlayer === 1 ? audio.gainNode1 : audio.gainNode2;
            gainNode.gain.linearRampToValueAtTime(
                payload.volume,
                audio.audioContext.currentTime + 0.2
            );
        } else {
            player.volume = payload.volume;
        }
        emit('updateVolume', payload.volume);
    }

    // Apply repeat mode
    if (payload.repeatMode !== undefined) {
        state.repeatMode = payload.repeatMode;
    }
}

// ========== DISCOVERY ==========
export async function discoverDevices() {
    try {
        const resp = await fetch('/api/sync/discover');
        const data = await resp.json();
        return data.devices || [];
    } catch (e) {
        console.error('Sync discovery failed:', e);
        return [];
    }
}

// ========== INIT ==========
export function initSync() {
    // Auto-reconnect on page load if sync was enabled
    if (state.syncEnabled) {
        const lastIp = localStorage.getItem('freedify_sync_last_ip');
        if (lastIp) {
            emit('syncStatusChanged', 'connecting');
            connectSync(lastIp);
        }
    }
}
