/**
 * Convective-Scale Nowcasting System - GIS Dashboard Controller
 * Full-screen map-first interface with live countdowns and timeline scrubber
 */

document.addEventListener('DOMContentLoaded', () => {
    // Application State
    const state = {
        map: null,
        layers: {
            radar: null,
            ci: null,
            lightning: null,
            zones: null,
        },
        visibility: {
            radar: true,
            ci: true,
            lightning: true,
            zones: true,
        },
        timeStep: 0, // 0 = T+0 (Current Observations), 1..12 = Forecast frames
        isPlaying: false,
        playInterval: null,
        forecastFrames: [],
        hazardFeatures: [],
        zoneTimers: {}, // zoneId -> seconds remaining
        timerInterval: null,
        systemStatus: null,
    };

    // DOM Elements
    const elements = {
        map: document.getElementById('map'),
        statusPill: document.getElementById('statusPill'),
        statusDot: document.getElementById('statusDot'),
        statusText: document.getElementById('statusText'),
        utcClock: document.getElementById('utcClock'),
        istClock: document.getElementById('istClock'),
        modeLiveBtn: document.getElementById('modeLiveBtn'),
        modeReplayBtn: document.getElementById('modeReplayBtn'),
        sidePanel: document.getElementById('sidePanel'),
        sidePanelToggleBtn: document.getElementById('sidePanelToggleBtn'),
        closeSidePanelBtn: document.getElementById('closeSidePanelBtn'),
        alertList: document.getElementById('alertList'),
        alertCount: document.getElementById('alertCount'),
        prevBtn: document.getElementById('prevBtn'),
        nextBtn: document.getElementById('nextBtn'),
        playBtn: document.getElementById('playBtn'),
        leadTimeBadge: document.getElementById('leadTimeBadge'),
        validTimeLabel: document.getElementById('validTimeLabel'),
        timelineTrack: document.getElementById('timelineTrack'),
        statusModal: document.getElementById('statusModal'),
        closeStatusModalBtn: document.getElementById('closeStatusModalBtn'),
        sourceGrid: document.getElementById('sourceGrid'),
        toastContainer: document.getElementById('toastContainer'),
        // Layer Toggles
        toggleRadar: document.getElementById('toggleRadar'),
        toggleCi: document.getElementById('toggleCi'),
        toggleLightning: document.getElementById('toggleLightning'),
        toggleZones: document.getElementById('toggleZones'),
    };

    // Initialize Map
    function initMap() {
        state.map = L.map('map', {
            center: [23.5, 82.0], // Centered over India
            zoom: 5,
            minZoom: 4,
            maxZoom: 14,
            zoomControl: false,
            attributionControl: true,
        });

        // Reposition zoom control to bottom right
        L.control.zoom({ position: 'bottomright' }).addTo(state.map);

        // CartoDB Dark Matter Tiles (ideal for radar/lightning contrast)
        L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
            attribution: '&copy; <a href="https://carto.com/">CARTO</a> &copy; OpenStreetMap contributors',
            subdomains: 'abcd',
            maxZoom: 19
        }).addTo(state.map);

        // Initialize Layer Groups
        state.layers.radar = L.layerGroup().addTo(state.map);
        state.layers.ci = L.layerGroup().addTo(state.map);
        state.layers.lightning = L.layerGroup().addTo(state.map);
        state.layers.zones = L.layerGroup().addTo(state.map);
    }

    // Live Clocks (UTC & IST)
    function startClock() {
        const update = () => {
            const now = new Date();
            const utcStr = now.toISOString().slice(11, 19) + ' UTC';
            const istStr = now.toLocaleTimeString('en-IN', { timeZone: 'Asia/Kolkata', hour12: false }) + ' IST';
            if (elements.utcClock) elements.utcClock.textContent = utcStr;
            if (elements.istClock) elements.istClock.textContent = istStr;
        };
        update();
        setInterval(update, 1000);
    }

    // Toast Notification System
    function showToast(message, icon = '⚡') {
        const toast = document.createElement('div');
        toast.className = 'toast';
        toast.innerHTML = `<span>${icon}</span> <span>${message}</span>`;
        elements.toastContainer.appendChild(toast);
        setTimeout(() => {
            toast.style.opacity = '0';
            toast.style.transform = 'translateY(-10px)';
            toast.style.transition = 'all 0.3s ease';
            setTimeout(() => toast.remove(), 300);
        }, 4000);
    }

    // Styling Helpers
    function getDbzColor(dbz, severity) {
        if (severity === 'severe' || dbz >= 50) return '#ef4444'; // Red/Severe
        if (severity === 'heavy' || dbz >= 40) return '#f59e0b';  // Amber/Heavy
        if (severity === 'moderate' || dbz >= 30) return '#22c55e'; // Green/Moderate
        return '#06b6d4'; // Cyan
    }

    // Render Hazards Layer (Observation / T+0)
    function renderObservations() {
        state.layers.radar.clearLayers();
        state.layers.ci.clearLayers();
        state.layers.lightning.clearLayers();
        state.layers.zones.clearLayers();

        const features = state.hazardFeatures;
        let activeZoneCount = 0;

        features.forEach(feat => {
            const props = feat.properties || {};
            const type = props.hazard_type;

            // 1. Radar Reflectivity Polygons
            if (type === 'radar_reflectivity' && state.visibility.radar) {
                const color = getDbzColor(props.dbz_threshold, props.severity);
                const poly = L.geoJSON(feat, {
                    style: {
                        color: color,
                        weight: 1.5,
                        fillColor: color,
                        fillOpacity: props.severity === 'severe' ? 0.65 : (props.severity === 'heavy' ? 0.45 : 0.3)
                    }
                });
                poly.bindTooltip(`<b>${props.title}</b><br>Intensity: ${props.dbz_threshold} dBZ`, { sticky: true });
                state.layers.radar.addLayer(poly);
            }

            // 2. Convective Initiation Points
            else if (type === 'convective_initiation' && state.visibility.ci) {
                const coords = feat.geometry?.coordinates;
                if (coords) {
                    const conf = props.confidence || 0.5;
                    const circle = L.circleMarker([coords[1], coords[0]], {
                        radius: conf > 0.8 ? 6 : 4,
                        fillColor: '#38bdf8',
                        color: '#ffffff',
                        weight: 1,
                        opacity: 0.9,
                        fillOpacity: 0.8
                    });
                    circle.bindPopup(`
                        <div style="font-size:12px; min-width:140px;">
                            <b style="color:#38bdf8;">Convective Initiation</b><br>
                            <b>Confidence:</b> ${(conf * 100).toFixed(1)}%<br>
                            <b>Cooling Rate:</b> ${props.cooling_rate || 'N/A'} K/hr<br>
                            <b>Texture Var:</b> ${props.texture_variance || 'N/A'}
                        </div>
                    `);
                    state.layers.ci.addLayer(circle);
                }
            }

            // 3. Lightning Strikes
            else if (type === 'lightning' && state.visibility.lightning) {
                const coords = feat.geometry?.coordinates;
                if (coords) {
                    const strike = L.circleMarker([coords[1], coords[0]], {
                        radius: 5,
                        fillColor: '#fbbf24',
                        color: '#fef08a',
                        weight: 1.5,
                        opacity: 1,
                        fillOpacity: 0.85
                    });
                    strike.bindPopup(`
                        <div style="font-size:12px;">
                            <b style="color:#fbbf24;">⚡ Lightning Discharge</b><br>
                            <b>Intensity:</b> ${props.intensity_ka} kA<br>
                            <b>Timestamp:</b> ${new Date(props.timestamp).toLocaleTimeString()}
                        </div>
                    `);
                    state.layers.lightning.addLayer(strike);
                }
            }

            // 4. Synthesized Hazard Warning Zones
            else if (type === 'hazard_zone' && state.visibility.zones) {
                activeZoneCount++;
                const color = props.severity === 'severe' ? '#f43f5e' : (props.severity === 'heavy' ? '#f59e0b' : '#10b981');
                const zonePoly = L.geoJSON(feat, {
                    style: {
                        color: color,
                        weight: 2.5,
                        dashArray: '6, 6',
                        fillColor: color,
                        fillOpacity: 0.25
                    }
                });

                const c = props.centroid || [feat.geometry.coordinates[0][0][1], feat.geometry.coordinates[0][0][0]];
                
                // Add permanent label
                const labelIcon = L.divIcon({
                    className: 'zone-map-label',
                    html: `<div style="background:${color}; color:#fff; font-size:10px; font-weight:700; padding:2px 6px; border-radius:4px; box-shadow:0 2px 6px rgba(0,0,0,0.5);">${props.zone_id}: ETA ${props.eta_minutes}m</div>`,
                    iconSize: [80, 20],
                    iconAnchor: [40, 10]
                });
                const marker = L.marker([c[1], c[0]], { icon: labelIcon });
                
                zonePoly.bindPopup(`
                    <div style="font-size:13px; min-width:180px;">
                        <b style="color:${color}; font-size:14px;">${props.name}</b><br>
                        <b>Severity:</b> <span style="text-transform:uppercase;">${props.severity}</span><br>
                        <b>ETA to Arrival:</b> ~${props.eta_minutes} mins<br>
                        <b>Storm Speed:</b> ${props.storm_speed_kmh} km/h (${props.direction})<br>
                        <b>Peak Echo:</b> ${props.max_dbz} dBZ<br>
                        <p style="margin-top:6px; font-size:11px; color:#cbd5e1;">${props.summary || ''}</p>
                    </div>
                `);

                state.layers.zones.addLayer(zonePoly);
                state.layers.zones.addLayer(marker);
            }
        });

        if (elements.alertCount) {
            elements.alertCount.textContent = `${activeZoneCount} Active`;
        }
    }

    // Render Forecast Frame (T+30m to T+360m)
    function renderForecastFrame(frameIndex) {
        state.layers.radar.clearLayers();
        
        if (!state.forecastFrames || state.forecastFrames.length < frameIndex) {
            return;
        }

        const frame = state.forecastFrames[frameIndex - 1];
        if (!frame || !frame.geojson) return;

        // Render forecast contour polygons
        if (state.visibility.radar) {
            const features = frame.geojson.features || [];
            features.forEach(feat => {
                const props = feat.properties || {};
                const color = getDbzColor(props.dbz_threshold, props.severity);
                const poly = L.geoJSON(feat, {
                    style: {
                        color: color,
                        weight: 1.5,
                        fillColor: color,
                        fillOpacity: props.severity === 'severe' ? 0.6 : (props.severity === 'heavy' ? 0.4 : 0.25)
                    }
                });
                poly.bindTooltip(`<b>Forecast T+${frame.lead_time_minutes}m</b><br>${props.title}`, { sticky: true });
                state.layers.radar.addLayer(poly);
            });
        }
    }

    // Timeline Update Controller
    function setTimeStep(step) {
        state.timeStep = step;
        
        // Update Scrubber Track UI
        const stepElements = document.querySelectorAll('.time-step');
        stepElements.forEach(el => {
            const s = parseInt(el.getAttribute('data-step'), 10);
            if (s === step) {
                el.classList.add('active');
            } else {
                el.classList.remove('active');
            }
        });

        // Update Labels
        if (step === 0) {
            elements.leadTimeBadge.textContent = 'T+0 (Now)';
            elements.validTimeLabel.textContent = 'Current Radar & Satellite Analysis';
            renderObservations();
        } else {
            const leadMinutes = step * 30;
            elements.leadTimeBadge.textContent = `T+${leadMinutes}m Forecast`;
            if (state.forecastFrames && state.forecastFrames[step - 1]) {
                const f = state.forecastFrames[step - 1];
                const validDate = new Date(f.valid_time);
                elements.validTimeLabel.textContent = `Valid: ${validDate.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })} (${f.polygon_count || 0} cells)`;
            } else {
                elements.validTimeLabel.textContent = `Estimated Advection`;
            }
            renderForecastFrame(step);
        }
    }

    // Live Countdown Clocks in Side Panel
    function buildSidePanelCards(zones) {
        elements.alertList.innerHTML = '';
        state.zoneTimers = {};

        if (!zones || zones.length === 0) {
            elements.alertList.innerHTML = `
                <div style="text-align:center; padding: 30px 10px; color: var(--text-muted); font-size:12px;">
                    No active convective hazard warnings in this region.
                </div>
            `;
            return;
        }

        zones.forEach(zone => {
            const props = zone.properties;
            const zoneId = props.zone_id;
            const etaMinutes = props.eta_minutes || 30;
            const totalSeconds = etaMinutes * 60;
            state.zoneTimers[zoneId] = totalSeconds;

            const card = document.createElement('div');
            card.className = `zone-card ${props.severity}`;
            card.setAttribute('data-zone-id', zoneId);

            card.innerHTML = `
                <div class="card-top">
                    <span class="zone-id">${zoneId}</span>
                    <span class="severity-pill ${props.severity}">${props.severity}</span>
                </div>
                <div class="zone-name">${props.name}</div>
                <div class="countdown-box">
                    <span class="countdown-label">Est. Storm Arrival (ETA):</span>
                    <span class="countdown-timer" id="timer-${zoneId}">
                        <span>⏱️</span> <span class="time-val">--:--</span>
                    </span>
                </div>
                <div class="storm-metrics">
                    <div class="metric-item">
                        <div class="metric-label">Max Echo</div>
                        <div class="metric-val">${props.max_dbz} dBZ</div>
                    </div>
                    <div class="metric-item">
                        <div class="metric-label">Speed</div>
                        <div class="metric-val">${props.storm_speed_kmh} km/h</div>
                    </div>
                    <div class="metric-item">
                        <div class="metric-label">Vector</div>
                        <div class="metric-val">${props.direction}</div>
                    </div>
                </div>
            `;

            // Fly-to Map interaction
            card.addEventListener('click', () => {
                if (props.centroid) {
                    state.map.flyTo([props.centroid[1], props.centroid[0]], 8, { duration: 1.2 });
                }
            });

            elements.alertList.appendChild(card);
        });

        startCountdownInterval();
    }

    function startCountdownInterval() {
        if (state.timerInterval) clearInterval(state.timerInterval);

        const tick = () => {
            Object.keys(state.zoneTimers).forEach(zoneId => {
                if (state.zoneTimers[zoneId] > 0) {
                    state.zoneTimers[zoneId] -= 1;
                }
                const sec = state.zoneTimers[zoneId];
                const m = Math.floor(sec / 60);
                const s = sec % 60;
                const formatted = `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
                
                const el = document.getElementById(`timer-${zoneId}`);
                if (el) {
                    const timeSpan = el.querySelector('.time-val');
                    if (timeSpan) timeSpan.textContent = formatted;
                    if (sec < 600) {
                        el.style.color = '#f43f5e';
                        el.style.animation = 'dot-pulse 1s infinite';
                    }
                }
            });
        };

        tick();
        state.timerInterval = setInterval(tick, 1000);
    }

    // Populate Status & Honesty Modal
    function updateStatusUI(statusData) {
        state.systemStatus = statusData;
        if (!statusData || !statusData.data_sources) return;

        const isReplay = ApiService.isReplayMode();
        if (elements.statusText) {
            elements.statusText.textContent = isReplay ? 'REPLAY (OFFLINE DEMO)' : 'SYSTEM OPERATIONAL';
        }
        if (elements.statusDot) {
            elements.statusDot.style.backgroundColor = isReplay ? 'var(--accent-amber)' : 'var(--accent-emerald)';
            elements.statusDot.style.boxShadow = isReplay ? '0 0 10px var(--accent-amber)' : '0 0 10px var(--accent-emerald)';
        }

        elements.sourceGrid.innerHTML = '';
        Object.entries(statusData.data_sources).forEach(([key, info]) => {
            const row = document.createElement('div');
            row.className = 'source-row';

            const tagClass = info.type.toLowerCase().includes('live') ? 'live' 
                : (info.type.toLowerCase().includes('proxy') ? 'proxy' 
                : (info.type.toLowerCase().includes('mock') ? 'mock' 
                : (info.type.toLowerCase().includes('synthetic') ? 'synthetic' : 'model')));

            const fileInfo = info.file 
                ? `Last file: ${info.file.filename} (${info.file.age_seconds}s ago)`
                : 'No files generated yet';

            row.innerHTML = `
                <div>
                    <div class="source-name">${info.label}</div>
                    <div class="source-note">${info.note}</div>
                    <div style="font-size:10px; color:var(--text-secondary); margin-top:2px;">${fileInfo}</div>
                </div>
                <div style="display:flex; align-items:center; gap:8px;">
                    <span class="honesty-tag ${tagClass}">${info.type}</span>
                    <span style="font-size:11px; font-weight:600; color:${info.status === 'available' ? 'var(--accent-emerald)' : 'var(--text-muted)'};">
                        ${info.status === 'available' ? 'AVAILABLE' : 'PENDING'}
                    </span>
                </div>
            `;
            elements.sourceGrid.appendChild(row);
        });
    }

    // Load All Data from API
    async function loadData() {
        try {
            // 1. Status
            const status = await ApiService.getStatus();
            if (status) updateStatusUI(status);

            // 2. Hazards
            const hazards = await ApiService.getHazards();
            if (hazards && hazards.features) {
                state.hazardFeatures = hazards.features;
                const zones = hazards.features.filter(f => f.properties?.hazard_type === 'hazard_zone');
                buildSidePanelCards(zones);
            }

            // 3. Forecast
            const forecast = await ApiService.getForecast('optical_flow');
            if (forecast && forecast.frames) {
                state.forecastFrames = forecast.frames;
            }

            // Render current time step
            setTimeStep(state.timeStep);
        } catch (err) {
            console.error('Error loading dashboard data:', err);
            showToast('Connection to nowcasting API failed. Replay data loaded.', '⚠️');
        }
    }

    // Animation / Playback Controller
    function togglePlay() {
        state.isPlaying = !state.isPlaying;
        if (state.isPlaying) {
            elements.playBtn.innerHTML = '⏸️ Pause';
            elements.playBtn.style.background = 'var(--accent-rose)';
            state.playInterval = setInterval(() => {
                const nextStep = (state.timeStep + 1) % 13;
                setTimeStep(nextStep);
            }, 1600);
        } else {
            elements.playBtn.innerHTML = '▶️ Play';
            elements.playBtn.style.background = 'var(--accent-indigo)';
            clearInterval(state.playInterval);
        }
    }

    // Setup Event Listeners
    function setupEvents() {
        // Timeline buttons
        elements.prevBtn.addEventListener('click', () => {
            const prev = (state.timeStep - 1 + 13) % 13;
            setTimeStep(prev);
        });

        elements.nextBtn.addEventListener('click', () => {
            const next = (state.timeStep + 1) % 13;
            setTimeStep(next);
        });

        elements.playBtn.addEventListener('click', togglePlay);

        // Click on individual step capsules
        const stepElements = document.querySelectorAll('.time-step');
        stepElements.forEach(el => {
            el.addEventListener('click', () => {
                const s = parseInt(el.getAttribute('data-step'), 10);
                setTimeStep(s);
            });
        });

        // Layer Toggles
        elements.toggleRadar.addEventListener('change', (e) => {
            state.visibility.radar = e.target.checked;
            setTimeStep(state.timeStep);
        });
        elements.toggleCi.addEventListener('change', (e) => {
            state.visibility.ci = e.target.checked;
            if (state.timeStep === 0) renderObservations();
        });
        elements.toggleLightning.addEventListener('change', (e) => {
            state.visibility.lightning = e.target.checked;
            if (state.timeStep === 0) renderObservations();
        });
        elements.toggleZones.addEventListener('change', (e) => {
            state.visibility.zones = e.target.checked;
            if (state.timeStep === 0) renderObservations();
        });

        // Side panel collapse / expand
        elements.sidePanelToggleBtn.addEventListener('click', () => {
            elements.sidePanel.classList.remove('collapsed');
            elements.sidePanelToggleBtn.style.display = 'none';
        });

        elements.closeSidePanelBtn.addEventListener('click', () => {
            elements.sidePanel.classList.add('collapsed');
            elements.sidePanelToggleBtn.style.display = 'flex';
        });

        // Status Modal
        elements.statusPill.addEventListener('click', () => {
            elements.statusModal.classList.add('open');
        });

        elements.closeStatusModalBtn.addEventListener('click', () => {
            elements.statusModal.classList.remove('open');
        });

        elements.statusModal.addEventListener('click', (e) => {
            if (e.target === elements.statusModal) {
                elements.statusModal.classList.remove('open');
            }
        });

        // Mode Switcher (Live vs Replay)
        elements.modeLiveBtn.addEventListener('click', () => {
            if (!ApiService.isReplayMode()) return;
            elements.modeLiveBtn.classList.add('active');
            elements.modeReplayBtn.classList.remove('active');
            ApiService.setReplayMode(false);
            showToast('Switched to Live API Server mode', '🌐');
            loadData();
            initLiveWebSocket();
        });

        elements.modeReplayBtn.addEventListener('click', () => {
            if (ApiService.isReplayMode()) return;
            elements.modeReplayBtn.classList.add('active');
            elements.modeLiveBtn.classList.remove('active');
            ApiService.setReplayMode(true);
            showToast('Switched to Offline Demo / Replay Mode', '📼');
            loadData();
        });
    }

    // WebSocket Live Updates
    function initLiveWebSocket() {
        ApiService.initWebSocket(
            (data) => {
                if (data.event === 'data_update') {
                    showToast(`${data.message}`, '⚡');
                    // Automatically refresh data
                    loadData();
                }
            },
            (connected) => {
                if (!ApiService.isReplayMode()) {
                    if (connected) {
                        elements.statusDot.classList.add('pulse');
                    } else {
                        elements.statusDot.classList.remove('pulse');
                    }
                }
            }
        );
    }

    // Bootstrap Dashboard
    initMap();
    startClock();
    setupEvents();
    loadData();
    initLiveWebSocket();
});
