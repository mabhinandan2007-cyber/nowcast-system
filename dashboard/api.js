/**
 * API Client for Convective-Scale Nowcasting System
 * Connects to /status, /hazards, /forecast, and ws:///live
 * Supports Replay Mode with embedded fallback dataset
 */

const ApiService = (function () {
    // Dynamic host discovery
    const isFileProtocol = window.location.protocol === 'file:';
    const apiHost = isFileProtocol ? 'http://127.0.0.1:8000' : window.location.origin;
    const wsHost = isFileProtocol 
        ? 'ws://127.0.0.1:8000/live' 
        : `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}/live`;

    let replayMode = false;
    let ws = null;
    let wsReconnectTimeout = null;
    let pingInterval = null;

    return {
        isReplayMode() {
            return replayMode;
        },

        setReplayMode(enabled) {
            replayMode = enabled;
            console.log(`[API] Replay Mode ${replayMode ? 'ENABLED (Offline Demo)' : 'DISABLED (Live API)'}`);
            if (replayMode && ws) {
                ws.close();
            }
        },

        async getStatus() {
            if (replayMode) {
                return window.REPLAY_DATA ? window.REPLAY_DATA.status : null;
            }
            try {
                const res = await fetch(`${apiHost}/status`);
                if (!res.ok) throw new Error(`HTTP ${res.status}`);
                return await res.json();
            } catch (err) {
                console.warn('[API] Failed to fetch /status, falling back to replay data:', err.message);
                return window.REPLAY_DATA ? window.REPLAY_DATA.status : null;
            }
        },

        async getHazards(severity = null, hazardType = null) {
            if (replayMode) {
                if (!window.REPLAY_DATA) return { type: 'FeatureCollection', features: [] };
                let features = [...window.REPLAY_DATA.hazards.features];
                if (severity) {
                    features = features.filter(f => f.properties?.severity?.toLowerCase() === severity.toLowerCase());
                }
                if (hazardType) {
                    features = features.filter(f => f.properties?.hazard_type?.toLowerCase() === hazardType.toLowerCase());
                }
                return {
                    ...window.REPLAY_DATA.hazards,
                    features,
                    metadata: {
                        ...window.REPLAY_DATA.hazards.metadata,
                        filtered_count: features.length
                    }
                };
            }

            try {
                const params = new URLSearchParams();
                if (severity) params.append('severity', severity);
                if (hazardType) params.append('hazard_type', hazardType);
                const query = params.toString() ? `?${params.toString()}` : '';
                
                const res = await fetch(`${apiHost}/hazards${query}`);
                if (!res.ok) throw new Error(`HTTP ${res.status}`);
                return await res.json();
            } catch (err) {
                console.warn('[API] Failed to fetch /hazards, falling back to replay snapshot:', err.message);
                return window.REPLAY_DATA ? window.REPLAY_DATA.hazards : { type: 'FeatureCollection', features: [] };
            }
        },

        async getForecast(model = 'optical_flow', leadTime = null) {
            if (replayMode) {
                if (!window.REPLAY_DATA) return { status: 'not_yet_available', frames: [] };
                let data = { ...window.REPLAY_DATA.forecast };
                if (leadTime !== null && data.frames) {
                    data.frames = data.frames.filter(f => f.lead_time_minutes === leadTime);
                }
                return data;
            }

            try {
                const params = new URLSearchParams({ model });
                if (leadTime !== null) params.append('lead_time', leadTime);
                const res = await fetch(`${apiHost}/forecast?${params.toString()}`);
                if (!res.ok) throw new Error(`HTTP ${res.status}`);
                return await res.json();
            } catch (err) {
                console.warn('[API] Failed to fetch /forecast, falling back to replay snapshot:', err.message);
                return window.REPLAY_DATA ? window.REPLAY_DATA.forecast : { status: 'not_yet_available', frames: [] };
            }
        },

        initWebSocket(onMessage, onConnectionChange) {
            if (replayMode) return;

            const connect = () => {
                if (replayMode) return;

                try {
                    ws = new WebSocket(wsHost);

                    ws.onopen = () => {
                        console.log('[WS] Connected to live nowcast stream.');
                        if (onConnectionChange) onConnectionChange(true);
                        
                        // Heartbeat ping every 25s
                        clearInterval(pingInterval);
                        pingInterval = setInterval(() => {
                            if (ws && ws.readyState === WebSocket.OPEN) {
                                ws.send(JSON.stringify({ action: 'ping' }));
                            }
                        }, 25000);
                    };

                    ws.onmessage = (event) => {
                        try {
                            const data = JSON.parse(event.data);
                            if (onMessage) onMessage(data);
                        } catch (e) {
                            console.error('[WS] Parse error:', e);
                        }
                    };

                    ws.onclose = () => {
                        console.warn('[WS] Live stream disconnected. Reconnecting in 5s...');
                        if (onConnectionChange) onConnectionChange(false);
                        clearInterval(pingInterval);
                        clearTimeout(wsReconnectTimeout);
                        if (!replayMode) {
                            wsReconnectTimeout = setTimeout(connect, 5000);
                        }
                    };

                    ws.onerror = (err) => {
                        console.warn('[WS] Stream error:', err);
                        ws.close();
                    };
                } catch (e) {
                    console.error('[WS] Connection exception:', e);
                    if (!replayMode) {
                        wsReconnectTimeout = setTimeout(connect, 5000);
                    }
                }
            };

            connect();
        }
    };
})();
