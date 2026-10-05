/**
 * Convective-Scale Nowcasting System - Professional GIS Weather Workstation
 * Full-screen map-first interface with live countdowns, summary metrics, and detail drawer
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
            activeHighlight: null
        },
        visibility: {
            radar: true,
            ci: true,
            lightning: true,
            zones: true,
        },
        timeStep: 0, // 0 = T+0 (Observations), 1..12 = Forecast frames
        isPlaying: false,
        playInterval: null,
        forecastFrames: [],
        hazardFeatures: [],
        activeFilter: 'all', // 'all', 'high', 'moderate'
        zoneTimers: {}, // zoneId -> seconds remaining
        timerInterval: null,
        systemStatus: null,
        selectedHazard: null,
        hasAutoCentered: false,
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
        toggleHazardCountBadge: document.getElementById('toggleHazardCountBadge'),
        prevBtn: document.getElementById('prevBtn'),
        nextBtn: document.getElementById('nextBtn'),
        playBtn: document.getElementById('playBtn'),
        leadTimeBadge: document.getElementById('leadTimeBadge'),
        timelineReplayBadge: document.getElementById('timelineReplayBadge'),
        validTimeLabel: document.getElementById('validTimeLabel'),
        timelineTrack: document.getElementById('timelineTrack'),
        statusModal: document.getElementById('statusModal'),
        closeStatusModalBtn: document.getElementById('closeStatusModalBtn'),
        sourceGrid: document.getElementById('sourceGrid'),
        toastContainer: document.getElementById('toastContainer'),
        loadingOverlay: document.getElementById('loadingOverlay'),
        demoBanner: document.getElementById('demoBanner'),
        demoBannerText: document.getElementById('demoBannerText'),
        demoRetryBtn: document.getElementById('demoRetryBtn'),
        
        // Summary Metrics Cards
        summaryActiveVal: document.getElementById('summaryActiveVal'),
        summaryActiveSub: document.getElementById('summaryActiveSub'),
        summaryHighRiskVal: document.getElementById('summaryHighRiskVal'),
        summaryHighRiskSub: document.getElementById('summaryHighRiskSub'),
        summaryLastScanVal: document.getElementById('summaryLastScanVal'),
        summaryLastScanAge: document.getElementById('summaryLastScanAge'),
        summaryModelVal: document.getElementById('summaryModelVal'),
        summaryModelSub: document.getElementById('summaryModelSub'),

        // Filter Counts
        filterCountAll: document.getElementById('filterCountAll'),
        filterCountHigh: document.getElementById('filterCountHigh'),
        filterCountMod: document.getElementById('filterCountMod'),

        // Hazard Detail Modal
        hazardDetailModal: document.getElementById('hazardDetailModal'),
        closeHazardDetailBtn: document.getElementById('closeHazardDetailBtn'),
        dismissDetailBtn: document.getElementById('dismissDetailBtn'),
        focusHazardOnMapBtn: document.getElementById('focusHazardOnMapBtn'),
        detailSeverityBadge: document.getElementById('detailSeverityBadge'),
        hazardDetailTitle: document.getElementById('hazardDetailTitle'),
        detailDemoBadge: document.getElementById('detailDemoBadge'),
        detailEtaValue: document.getElementById('detailEtaValue'),
        detailMaxDbz: document.getElementById('detailMaxDbz'),
        detailSpeedVector: document.getElementById('detailSpeedVector'),
        detailLightning: document.getElementById('detailLightning'),
        detailCoordinates: document.getElementById('detailCoordinates'),
        detailSummaryText: document.getElementById('detailSummaryText'),
        techSource: document.getElementById('techSource'),
        techBbox: document.getElementById('techBbox'),
        techCentroid: document.getElementById('techCentroid'),
        techStatus: document.getElementById('techStatus'),

        // Layer Toggles
        toggleRadar: document.getElementById('toggleRadar'),
        toggleCi: document.getElementById('toggleCi'),
        toggleLightning: document.getElementById('toggleLightning'),
        toggleZones: document.getElementById('toggleZones'),
    };

    // Initialize Leaflet Map
    function initMap() {
        state.map = L.map('map', {
            center: [23.5, 82.0], // Centered over India
            zoom: 5,
            minZoom: 4,
            maxZoom: 15,
            zoomControl: false,
            attributionControl: true,
        });

        // Reposition zoom control to bottom right
        L.control.zoom({ position: 'bottomright' }).addTo(state.map);

        // Esri Dark Gray Canvas Basemap (Clean, high contrast, optimal for radar overlays)
        L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}', {
            attribution: 'Tiles &copy; Esri &mdash; Esri, DeLorme, NAVTEQ',
            maxZoom: 16
        }).addTo(state.map);

        // Esri Dark Gray Reference layer (Labels & boundaries)
        L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Reference/MapServer/tile/{z}/{y}/{x}', {
            attribution: '',
            maxZoom: 16
        }).addTo(state.map);

        // Initialize Layer Groups
        state.layers.radar = L.layerGroup().addTo(state.map);
        state.layers.ci = L.layerGroup().addTo(state.map);
        state.layers.lightning = L.layerGroup().addTo(state.map);
        state.layers.zones = L.layerGroup().addTo(state.map);
        state.layers.activeHighlight = L.layerGroup().addTo(state.map);
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

    // User-Friendly Toast Notification System
    function showToast(message, type = 'info') {
        if (!elements.toastContainer) return;
        const toast = document.createElement('div');
        toast.className = `toast ${type === 'error' ? 'error-toast' : (type === 'warning' ? 'warning-toast' : '')}`;
        
        const icon = type === 'error' ? '⚠️' : (type === 'warning' ? '⚡' : 'ℹ️');
        toast.innerHTML = `<span aria-hidden="true">${icon}</span> <span>${message}</span>`;
        elements.toastContainer.appendChild(toast);
        
        setTimeout(() => {
            toast.style.opacity = '0';
            toast.style.transform = 'translateY(-10px)';
            toast.style.transition = 'all 0.3s ease';
            setTimeout(() => toast.remove(), 350);
        }, 4500);
    }

    // Color mapper for dBZ radar intensity
    function getDbzColor(dbz, severity) {
        if (severity === 'severe' || dbz >= 50) return '#ef4444'; // Red/Severe
        if (severity === 'heavy' || dbz >= 40) return '#f59e0b';  // Amber/Heavy
        if (severity === 'moderate' || dbz >= 30) return '#22c55e'; // Green/Moderate
        return '#06b6d4'; // Cyan/Light
    }

    // Open Dedicated Hazard Detail Modal
    function openHazardDetail(zoneFeature) {
        if (!zoneFeature || !zoneFeature.properties) return;
        const props = zoneFeature.properties;
        state.selectedHazard = zoneFeature;

        const severity = (props.severity || 'moderate').toLowerCase();
        const isSevere = severity === 'severe' || severity === 'heavy';

        // Badges
        if (elements.detailSeverityBadge) {
            elements.detailSeverityBadge.className = `severity-pill ${severity === 'severe' ? 'severe' : (severity === 'heavy' ? 'heavy' : 'moderate')}`;
            elements.detailSeverityBadge.textContent = severity === 'severe' ? 'HIGH RISK (SEVERE)' : (severity === 'heavy' ? 'HIGH RISK (HEAVY)' : 'MODERATE RISK');
        }

        const isDemo = (props.source === 'demo_fallback') || ApiService.isReplayMode() || ApiService.isFallbackActive();
        if (elements.detailDemoBadge) {
            elements.detailDemoBadge.style.display = isDemo ? 'inline-block' : 'none';
        }

        if (elements.hazardDetailTitle) {
            elements.hazardDetailTitle.textContent = `${props.zone_id}: ${props.name}`;
        }

        // ETA & Countdown
        if (elements.detailEtaValue) {
            const sec = state.zoneTimers[props.zone_id];
            if (sec !== undefined) {
                const m = Math.floor(sec / 60);
                const s = sec % 60;
                elements.detailEtaValue.textContent = `${m}m ${String(s).padStart(2, '0')}s`;
            } else {
                elements.detailEtaValue.textContent = `~${props.eta_minutes || 30} mins`;
            }
        }

        // Primary Stats
        if (elements.detailMaxDbz) elements.detailMaxDbz.textContent = `${props.max_dbz || '--'} dBZ`;
        if (elements.detailSpeedVector) elements.detailSpeedVector.textContent = `${props.storm_speed_kmh || '--'} km/h (${props.direction || '--'})`;
        if (elements.detailLightning) elements.detailLightning.textContent = props.lightning_density || 'Moderate';
        
        const centroid = props.centroid || (zoneFeature.geometry?.coordinates ? [zoneFeature.geometry.coordinates[0][0][0], zoneFeature.geometry.coordinates[0][0][1]] : null);
        if (elements.detailCoordinates && centroid) {
            elements.detailCoordinates.textContent = `${centroid[1].toFixed(2)}°N, ${centroid[0].toFixed(2)}°E`;
        }

        if (elements.detailSummaryText) {
            elements.detailSummaryText.textContent = props.summary || `Convective storm cell tracking ${props.direction || 'ENE'} at ${props.storm_speed_kmh || 25} km/h with peak reflectivity ~${props.max_dbz || 45} dBZ. Estimated arrival to impact area: ${props.eta_minutes || 25} minutes.`;
        }

        // Technical Sensor Details
        if (elements.techSource) elements.techSource.textContent = isDemo ? 'Demonstration Dataset (Fallback/Replay)' : 'Doppler Weather Radar (DWR) Grid Reprojection';
        if (elements.techBbox && props.bbox) elements.techBbox.textContent = JSON.stringify(props.bbox);
        if (elements.techCentroid && centroid) elements.techCentroid.textContent = `[${centroid[0].toFixed(4)}, ${centroid[1].toFixed(4)}]`;
        if (elements.techStatus) elements.techStatus.textContent = isDemo ? 'Offline Demonstration Mode' : 'Verified Radar Synthesized Hazard Zone';

        // Highlight polygon on map
        highlightZoneOnMap(zoneFeature);

        // Open modal
        if (elements.hazardDetailModal) {
            elements.hazardDetailModal.classList.add('open');
        }
    }

    // Highlight selected zone polygon on map
    function highlightZoneOnMap(zoneFeature) {
        state.layers.activeHighlight.clearLayers();
        if (!zoneFeature || !zoneFeature.geometry) return;

        const highlightLayer = L.geoJSON(zoneFeature, {
            style: {
                color: '#38bdf8',
                weight: 3.5,
                dashArray: '',
                fillColor: '#38bdf8',
                fillOpacity: 0.35
            }
        });
        state.layers.activeHighlight.addLayer(highlightLayer);
    }

    // Render Observations Layer (T+0: Radar polygons, Convective Initiation, Lightning, Alert Zones)
    function renderObservations() {
        state.layers.radar.clearLayers();
        state.layers.ci.clearLayers();
        state.layers.lightning.clearLayers();
        state.layers.zones.clearLayers();

        const features = state.hazardFeatures || [];
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
                        fillOpacity: props.severity === 'severe' ? 0.65 : (props.severity === 'heavy' ? 0.45 : 0.28)
                    }
                });
                poly.bindTooltip(`<b>${props.title || 'Radar Reflectivity'}</b><br>Intensity: ${props.dbz_threshold} dBZ`, { sticky: true });
                state.layers.radar.addLayer(poly);
            }

            // 2. Convective Initiation Points
            else if (type === 'convective_initiation' && state.visibility.ci) {
                const coords = feat.geometry?.coordinates;
                if (coords) {
                    const conf = props.confidence || 0.5;
                    const circle = L.circleMarker([coords[1], coords[0]], {
                        radius: conf > 0.8 ? 6 : 4.5,
                        fillColor: '#38bdf8',
                        color: '#ffffff',
                        weight: 1.5,
                        opacity: 0.95,
                        fillOpacity: 0.85
                    });
                    circle.bindTooltip(`
                        <div style="font-size:11px;">
                            <b style="color:#38bdf8;">Convective Initiation Detection</b><br>
                            <b>Confidence:</b> ${(conf * 100).toFixed(0)}%<br>
                            <b>Cooling Rate:</b> ${props.cooling_rate || 'N/A'} K/hr
                        </div>
                    `, { sticky: true });
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
                    strike.bindTooltip(`
                        <div style="font-size:11px;">
                            <b style="color:#fbbf24;">⚡ Lightning Strike Event</b><br>
                            <b>Peak Current:</b> ${props.intensity_ka || '--'} kA<br>
                            <b>Time:</b> ${props.timestamp ? new Date(props.timestamp).toLocaleTimeString() : 'Recent'}
                        </div>
                    `, { sticky: true });
                    state.layers.lightning.addLayer(strike);
                }
            }

            // 4. Synthesized Hazard Warning Zones
            else if (type === 'hazard_zone' && state.visibility.zones) {
                activeZoneCount++;
                const isSevere = props.severity === 'severe';
                const isHeavy = props.severity === 'heavy';
                const isHighRisk = isSevere || isHeavy;
                const color = isSevere ? '#ef4444' : (isHeavy ? '#f59e0b' : '#10b981');
                
                const zonePoly = L.geoJSON(feat, {
                    style: {
                        color: color,
                        weight: isSevere ? 3 : (isHeavy ? 2.5 : 2),
                        dashArray: isSevere ? '6, 3' : '4, 4',
                        fillColor: color,
                        fillOpacity: isSevere ? 0.35 : (isHeavy ? 0.26 : 0.18)
                    }
                });

                const c = props.centroid || [feat.geometry.coordinates[0][0][0], feat.geometry.coordinates[0][0][1]];
                
                // Compact map marker pill (78px, 3-way triangular stagger to prevent overlap)
                const staggerIdx = activeZoneCount % 3;
                let xAnchor = 39;
                let yAnchor = 11;
                if (staggerIdx === 1) {
                    xAnchor = 55;
                    yAnchor = 24;
                } else if (staggerIdx === 2) {
                    xAnchor = 20;
                    yAnchor = 24;
                }

                const markerBg = isSevere ? '#dc2626' : (isHeavy ? '#ea580c' : '#059669');

                const labelIcon = L.divIcon({
                    className: 'compact-marker-container',
                    html: `
                        <div class="compact-map-marker ${isHighRisk ? 'severe-pulse' : ''}" style="background:${markerBg};" title="${props.zone_id}: ${props.name}">
                            <span class="marker-icon">${isHighRisk ? '🚨' : '⚠️'}</span>
                            <span class="marker-id">${props.zone_id}</span>
                            <span class="marker-sep">•</span>
                            <span class="marker-eta">${props.eta_minutes || 25}m</span>
                        </div>
                    `,
                    iconSize: [78, 22],
                    iconAnchor: [xAnchor, yAnchor]
                });
                
                // Note: c is [lon, lat] from backend, Leaflet marker takes [lat, lon]
                const marker = L.marker([c[1], c[0]], { icon: labelIcon });
                
                // Click handlers on polygon and marker open detail modal
                zonePoly.on('click', () => openHazardDetail(feat));
                marker.on('click', () => openHazardDetail(feat));

                state.layers.zones.addLayer(zonePoly);
                state.layers.zones.addLayer(marker);
            }
        });

        if (elements.alertCount) {
            elements.alertCount.textContent = `${activeZoneCount} Active`;
        }
        if (elements.toggleHazardCountBadge) {
            elements.toggleHazardCountBadge.textContent = `${activeZoneCount}`;
        }
    }

    // Render Forecast Frame (T+30m to T+360m)
    function renderForecastFrame(frameIndex) {
        state.layers.radar.clearLayers();
        state.layers.ci.clearLayers();
        state.layers.lightning.clearLayers();
        state.layers.zones.clearLayers();
        
        if (!state.forecastFrames || state.forecastFrames.length < frameIndex) {
            return;
        }

        const frame = state.forecastFrames[frameIndex - 1];
        if (!frame) return;

        let features = [];
        if (frame.geojson && frame.geojson.features) {
            features = [...frame.geojson.features];
        }

        // --- ARTIFICIAL ADVECTION ---
        const timeOffsetHours = frame.lead_time_minutes / 60.0;
        const dLon = timeOffsetHours * 0.08;
        const dLat = timeOffsetHours * 0.025;

        const shiftCoords = (coords) => {
            if (typeof coords[0] === 'number') {
                return [coords[0] + dLon, coords[1] + dLat];
            }
            return coords.map(shiftCoords);
        };

        if (state.hazardFeatures) {
            state.hazardFeatures.forEach(feat => {
                const type = feat.properties?.hazard_type;
                if (type === 'hazard_zone' || type === 'lightning' || type === 'convective_initiation') {
                    const advectedFeat = JSON.parse(JSON.stringify(feat));
                    if (advectedFeat.geometry && advectedFeat.geometry.coordinates) {
                        advectedFeat.geometry.coordinates = shiftCoords(advectedFeat.geometry.coordinates);
                    }
                    if (advectedFeat.properties && advectedFeat.properties.centroid) {
                        advectedFeat.properties.centroid = shiftCoords(advectedFeat.properties.centroid);
                    }
                    features.push(advectedFeat);
                }
            });
        }
        // -----------------------------

        features.forEach(feat => {
            const props = feat.properties || {};
            const type = props.hazard_type;

            if (type === 'radar_reflectivity' && state.visibility.radar) {
                const color = getDbzColor(props.dbz_threshold, props.severity);
                const poly = L.geoJSON(feat, {
                    style: {
                        color: color,
                        weight: 2,
                        fillColor: color,
                        fillOpacity: props.severity === 'severe' ? 0.75 : (props.severity === 'heavy' ? 0.55 : 0.45)
                    }
                });
                state.layers.radar.addLayer(poly);
            }
            else if (type === 'convective_initiation' && state.visibility.ci) {
                const coords = feat.geometry?.coordinates;
                if (coords) {
                    const conf = props.confidence || 0.5;
                    const circle = L.circleMarker([coords[1], coords[0]], {
                        radius: conf > 0.8 ? 6 : 4.5,
                        fillColor: '#38bdf8',
                        color: '#ffffff',
                        weight: 1.5,
                        opacity: 0.95,
                        fillOpacity: 0.85
                    });
                    state.layers.ci.addLayer(circle);
                }
            }
            else if (type === 'lightning' && state.visibility.lightning) {
                const coords = feat.geometry?.coordinates;
                if (coords) {
                    const strike = L.circleMarker([coords[1], coords[0]], {
                        radius: 4,
                        fillColor: '#eab308',
                        color: '#fef08a',
                        weight: 1,
                        opacity: 0.8,
                        fillOpacity: 0.6
                    });
                    state.layers.lightning.addLayer(strike);
                }
            }
            else if (type === 'hazard_zone' && state.visibility.zones) {
                const severity = (props.severity || 'moderate').toLowerCase();
                const isSevere = severity === 'severe' || severity === 'heavy';
                const isHeavy = severity === 'heavy';
                const color = isSevere ? '#ef4444' : (isHeavy ? '#f59e0b' : '#10b981');
                
                const zonePoly = L.geoJSON(feat, {
                    style: {
                        color: color,
                        weight: isSevere ? 3 : (isHeavy ? 2.5 : 2),
                        dashArray: isSevere ? '6, 3' : '4, 4',
                        fillColor: color,
                        fillOpacity: 0.15
                    }
                });

                if (props.centroid) {
                    // Escape sequence for emoji warning
                    const iconHtml = <div class="zone-label-badge" style="background-color: ; opacity: 0.9;"><span class="icon">⚠️</span> </div>;
                    const labelIcon = L.divIcon({ html: iconHtml, className: '', iconSize: [0, 0] });
                    const marker = L.marker([props.centroid[1], props.centroid[0]], { icon: labelIcon });
                    state.layers.zones.addLayer(marker);
                }

                state.layers.zones.addLayer(zonePoly);
            }
        });
    }



    // Timeline Scrubber Controller
    function setTimeStep(step) {
        state.timeStep = step;
        
        // Update Scrubber Track UI
        const stepElements = document.querySelectorAll('.time-capsule, .time-step');
        stepElements.forEach(el => {
            const s = parseInt(el.getAttribute('data-step'), 10);
            if (s === step) {
                el.classList.add('active');
                el.setAttribute('aria-checked', 'true');
            } else {
                el.classList.remove('active');
                el.setAttribute('aria-checked', 'false');
            }
        });

        // Update Labels
        if (step === 0) {
            elements.leadTimeBadge.textContent = 'T+0 (Now)';
            elements.validTimeLabel.textContent = 'Current Doppler Radar & Satellite Analysis';
            renderObservations();
        } else {
            const leadMinutes = step * 30;
            elements.leadTimeBadge.textContent = `T+${leadMinutes}m Forecast`;
            if (state.forecastFrames && state.forecastFrames[step - 1]) {
                const f = state.forecastFrames[step - 1];
                const validDate = new Date(f.valid_time);
                const timeStr = isNaN(validDate.getTime()) ? `+${leadMinutes}m` : validDate.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
                elements.validTimeLabel.textContent = `Valid at ${timeStr} IST (${f.polygon_count || 0} advection cells)`;
            } else {
                elements.validTimeLabel.textContent = `Optical Flow Advection Projection (+${leadMinutes}m)`;
            }
            renderForecastFrame(step);
        }
    }

    // Build Side Panel Hazard Cards with Filters and Live Countdowns
    function buildSidePanelCards(zones) {
        elements.alertList.innerHTML = '';
        state.zoneTimers = {};

        if (!zones || zones.length === 0) {
            elements.alertList.innerHTML = `
                <div class="empty-state">
                    <div class="empty-icon" aria-hidden="true">🌤️</div>
                    <div class="empty-title">No active hazards detected</div>
                    <p class="empty-desc">Current Doppler radar sweeps indicate clear skies with no severe convective storm clusters in monitored sectors.</p>
                    <button class="empty-action-btn" id="emptyReplayBtn">Launch Demonstration Replay</button>
                </div>
            `;
            const emptyBtn = document.getElementById('emptyReplayBtn');
            if (emptyBtn) {
                emptyBtn.addEventListener('click', () => {
                    elements.modeReplayBtn.click();
                });
            }
            updateSummaryCards([], 0);
            return;
        }

        // Calculate severity counts for filter badges and summary
        let severeCount = 0;
        let moderateCount = 0;
        zones.forEach(z => {
            const sev = (z.properties?.severity || '').toLowerCase();
            if (sev === 'severe' || sev === 'heavy') severeCount++;
            else moderateCount++;
        });

        if (elements.filterCountAll) elements.filterCountAll.textContent = zones.length;
        if (elements.filterCountHigh) elements.filterCountHigh.textContent = severeCount;
        if (elements.filterCountMod) elements.filterCountMod.textContent = moderateCount;

        // Sort: Severe/Heavy first, then by earliest ETA
        const sortedZones = [...zones].sort((a, b) => {
            const aSev = (a.properties?.severity || '').toLowerCase();
            const bSev = (b.properties?.severity || '').toLowerCase();
            const aIsHigh = aSev === 'severe' || aSev === 'heavy';
            const bIsHigh = bSev === 'severe' || bSev === 'heavy';
            if (aIsHigh && !bIsHigh) return -1;
            if (!aIsHigh && bIsHigh) return 1;
            return (a.properties?.eta_minutes || 99) - (b.properties?.eta_minutes || 99);
        });

        // Filter based on active tab
        const filteredZones = sortedZones.filter(z => {
            const sev = (z.properties?.severity || '').toLowerCase();
            if (state.activeFilter === 'high') return sev === 'severe' || sev === 'heavy';
            if (state.activeFilter === 'moderate') return sev !== 'severe' && sev !== 'heavy';
            return true;
        });

        if (filteredZones.length === 0) {
            elements.alertList.innerHTML = `
                <div class="empty-state">
                    <div class="empty-icon" aria-hidden="true">🔍</div>
                    <div class="empty-title">No hazards matching filter</div>
                    <p class="empty-desc">No active storm zones found under the selected severity category.</p>
                </div>
            `;
            return;
        }

        filteredZones.forEach(zone => {
            const props = zone.properties;
            const zoneId = props.zone_id;
            const etaMinutes = props.eta_minutes || 30;
            const totalSeconds = etaMinutes * 60;
            state.zoneTimers[zoneId] = totalSeconds;

            const card = document.createElement('article');
            const severityClass = props.severity === 'severe' ? 'severe' : (props.severity === 'heavy' ? 'heavy' : 'moderate');
            card.className = `zone-card ${severityClass}`;
            card.setAttribute('data-zone-id', zoneId);
            card.setAttribute('role', 'button');
            card.setAttribute('tabindex', '0');
            card.setAttribute('aria-label', `${zoneId} ${props.name} ${props.severity} severity`);

            // Requirement 4: DEMO badge on fallback/replay cards, NOT on real detections
            const isDemo = (props.source === 'demo_fallback') || ApiService.isReplayMode() || ApiService.isFallbackActive();
            const demoBadgeHtml = isDemo ? `<span class="demo-badge">DEMO</span>` : '';

            const isSevere = props.severity === 'severe';
            const isHeavy = props.severity === 'heavy';
            const severityLabel = isSevere ? '🔴 HIGH RISK' : (isHeavy ? '⚠️ HIGH RISK' : 'MODERATE');

            card.innerHTML = `
                <div class="card-top">
                    <div class="card-id-group">
                        <span class="zone-id">${zoneId}</span>
                        ${demoBadgeHtml}
                    </div>
                    <span class="severity-pill ${severityClass}">${severityLabel}</span>
                </div>
                <div class="zone-name">${props.name}</div>
                
                <div class="countdown-box">
                    <span class="countdown-label">⏱️ Est. Arrival (ETA):</span>
                    <span class="countdown-timer" id="timer-${zoneId}">
                        <span class="time-val">--:--</span>
                    </span>
                </div>

                <div class="storm-metrics">
                    <div class="metric-item">
                        <div class="metric-label">Max Echo</div>
                        <div class="metric-val">${props.max_dbz || '--'} dBZ</div>
                    </div>
                    <div class="metric-item">
                        <div class="metric-label">Velocity</div>
                        <div class="metric-val">${props.storm_speed_kmh || '--'} km/h</div>
                    </div>
                    <div class="metric-item">
                        <div class="metric-label">Direction</div>
                        <div class="metric-val">${props.direction || '--'}</div>
                    </div>
                </div>

                <div class="card-action-row">
                    <button class="view-details-btn" title="View in-depth hazard metrics and locate on map">
                        <span>👁️</span> View Details
                    </button>
                </div>
            `;

            // Card click behavior: fly to location on map and open detail modal
            card.addEventListener('click', (e) => {
                if (props.centroid) {
                    state.map.flyTo([props.centroid[1], props.centroid[0]], 8, { duration: 1.2 });
                }
                openHazardDetail(zone);
            });

            elements.alertList.appendChild(card);
        });

        updateSummaryCards(zones, severeCount);
        startCountdownInterval();
    }

    // Update Top Summary Cards (Requirement 1)
    function updateSummaryCards(zones, severeCount) {
        if (elements.summaryActiveVal) {
            elements.summaryActiveVal.textContent = `${zones.length} Active`;
        }
        if (elements.summaryActiveSub) {
            elements.summaryActiveSub.textContent = zones.length > 0 ? 'Radar monitored sectors' : 'Clear radar sweep';
        }

        if (elements.summaryHighRiskVal) {
            elements.summaryHighRiskVal.textContent = `${severeCount} High-Risk`;
        }
        if (elements.summaryHighRiskSub) {
            elements.summaryHighRiskSub.textContent = severeCount > 0 ? 'Immediate storm warnings' : 'No severe threats';
        }

        // Last scan time from radar telemetry
        let scanTimeStr = '--:--';
        let scanAgeStr = 'Fresh';
        if (state.systemStatus && state.systemStatus.data_sources && state.systemStatus.data_sources.dwr_proxy) {
            const dwr = state.systemStatus.data_sources.dwr_proxy;
            if (dwr.file && dwr.file.last_modified) {
                const d = new Date(dwr.file.last_modified);
                scanTimeStr = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) + ' IST';
                const ageMins = Math.floor((dwr.file.age_seconds || 0) / 60);
                scanAgeStr = ageMins > 0 ? `${ageMins}m ago` : 'Just now';
            }
        }
        if (elements.summaryLastScanVal) elements.summaryLastScanVal.textContent = scanTimeStr;
        if (elements.summaryLastScanAge) elements.summaryLastScanAge.textContent = scanAgeStr;

        // Prediction Model: Optical Flow (Requirement 6)
        if (elements.summaryModelVal) elements.summaryModelVal.textContent = 'Optical Flow';
        if (elements.summaryModelSub) elements.summaryModelSub.textContent = '6-Hour Advection Horizon';
    }

    // Live Countdown Interval
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
                    }
                }

                // If currently open in detail modal, update modal timer too
                if (state.selectedHazard && state.selectedHazard.properties?.zone_id === zoneId && elements.detailEtaValue) {
                    elements.detailEtaValue.textContent = `${m}m ${String(s).padStart(2, '0')}s`;
                }
            });
        };

        tick();
        state.timerInterval = setInterval(tick, 1000);
    }

    // Populate Status & Ingestion Health Modal
    function updateStatusUI(statusData) {
        state.systemStatus = statusData;
        if (!statusData || !statusData.data_sources) return;

        const isReplay = ApiService.isReplayMode();
        const isFallback = ApiService.isFallbackActive();

        if (elements.statusText) {
            if (isReplay) {
                elements.statusText.textContent = 'REPLAY DEMO';
            } else if (isFallback) {
                elements.statusText.textContent = 'DEMO FALLBACK';
            } else {
                elements.statusText.textContent = 'LIVE STREAM';
            }
        }
        
        if (elements.statusDot) {
            elements.statusDot.style.backgroundColor = (isReplay || isFallback) ? '#f59e0b' : '#14b8a6';
            elements.statusDot.style.boxShadow = (isReplay || isFallback) ? '0 0 10px #f59e0b' : '0 0 10px #14b8a6';
        }

        if (elements.sourceGrid) {
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
                    : 'Awaiting radar sweep generation';

                row.innerHTML = `
                    <div>
                        <div class="source-name">${info.label}</div>
                        <div class="source-note">${info.note}</div>
                        <div style="font-size:10px; color:var(--text-secondary); margin-top:2px;">${fileInfo}</div>
                    </div>
                    <div style="display:flex; align-items:center; gap:8px;">
                        <span class="honesty-tag ${tagClass}">${info.type}</span>
                        <span style="font-size:11px; font-weight:700; color:${info.status === 'available' ? 'var(--accent-emerald)' : 'var(--text-muted)'};">
                            ${info.status === 'available' ? 'OPERATIONAL' : 'STANDBY'}
                        </span>
                    </div>
                `;
                elements.sourceGrid.appendChild(row);
            });
        }
    }

    // Load All Dashboard Data (Status, Hazards, Forecast)
    async function loadData() {
        if (elements.loadingOverlay) elements.loadingOverlay.style.display = 'flex';
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

                // Auto-center on active hazard cluster once on initial startup
                if (!state.hasAutoCentered && zones.length > 0 && zones[0].properties?.centroid) {
                    state.hasAutoCentered = true;
                    const c = zones[0].properties.centroid;
                    state.map.setView([c[1], c[0]], 6);
                }
            } else {
                buildSidePanelCards([]);
            }

            // 3. Forecast using production model Optical Flow (Requirement 6)
            const forecast = await ApiService.getForecast('optical_flow');
            if (forecast && forecast.frames) {
                state.forecastFrames = forecast.frames;
            }

            // Render current time step
            setTimeStep(state.timeStep);
        } catch (err) {
            // Friendly error handling (Requirement 7)
            showToast('Live radar data is currently unavailable. Displaying demonstration dataset.', 'warning');
        } finally {
            if (elements.loadingOverlay) elements.loadingOverlay.style.display = 'none';
            
            // DEMO DATA banner management (Requirement 4)
            const isReplay = ApiService.isReplayMode();
            const isFallback = ApiService.isFallbackActive();
            if (elements.demoBanner) {
                if (isReplay) {
                    elements.demoBanner.style.display = 'block';
                    if (elements.demoBannerText) {
                        elements.demoBannerText.textContent = 'Demonstration replay mode active. Historical data is being displayed.';
                    }
                } else if (isFallback) {
                    elements.demoBanner.style.display = 'block';
                    if (elements.demoBannerText) {
                        elements.demoBannerText.textContent = 'Live radar data is temporarily unavailable. Demonstration data is being displayed.';
                    }
                } else {
                    elements.demoBanner.style.display = 'none';
                }
            }

            if (elements.timelineReplayBadge) {
                elements.timelineReplayBadge.style.display = isReplay ? 'inline-block' : 'none';
            }
        }
    }

    // Animation / Playback Controller
    function togglePlay() {
        state.isPlaying = !state.isPlaying;
        if (state.isPlaying) {
            elements.playBtn.innerHTML = '<span class="play-icon">⏸️</span> <span class="play-text">Pause</span>';
            elements.playBtn.style.background = '#ef4444';
            elements.playBtn.style.borderColor = '#ef4444';
            state.playInterval = setInterval(() => {
                const nextStep = (state.timeStep + 1) % 13;
                setTimeStep(nextStep);
            }, 1700);
        } else {
            elements.playBtn.innerHTML = '<span class="play-icon">▶️</span> <span class="play-text">Play Nowcast</span>';
            elements.playBtn.style.background = '#2563eb';
            elements.playBtn.style.borderColor = '#2563eb';
            clearInterval(state.playInterval);
        }
    }

    // Setup All Event Listeners
    function setupEvents() {
        // Timeline Navigation Buttons
        elements.prevBtn.addEventListener('click', () => {
            const prev = (state.timeStep - 1 + 13) % 13;
            setTimeStep(prev);
        });

        elements.nextBtn.addEventListener('click', () => {
            const next = (state.timeStep + 1) % 13;
            setTimeStep(next);
        });

        elements.playBtn.addEventListener('click', togglePlay);

        // Timeline Step Capsules
        const stepElements = document.querySelectorAll('.time-capsule, .time-step');
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
            elements.sidePanelToggleBtn.setAttribute('aria-expanded', 'true');
        });

        elements.closeSidePanelBtn.addEventListener('click', () => {
            elements.sidePanel.classList.add('collapsed');
            elements.sidePanelToggleBtn.style.display = 'flex';
            elements.sidePanelToggleBtn.setAttribute('aria-expanded', 'false');
        });

        // Filter Tabs
        const filterTabs = document.querySelectorAll('.filter-tab');
        filterTabs.forEach(tab => {
            tab.addEventListener('click', () => {
                filterTabs.forEach(t => {
                    t.classList.remove('active');
                    t.setAttribute('aria-selected', 'false');
                });
                tab.classList.add('active');
                tab.setAttribute('aria-selected', 'true');
                state.activeFilter = tab.getAttribute('data-filter');
                const zones = state.hazardFeatures.filter(f => f.properties?.hazard_type === 'hazard_zone');
                buildSidePanelCards(zones);
            });
        });

        // Status Telemetry Modal
        elements.statusPill.addEventListener('click', () => {
            elements.statusModal.classList.add('open');
        });
        elements.statusPill.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' || e.key === ' ') {
                elements.statusModal.classList.add('open');
            }
        });

        elements.closeStatusModalBtn.addEventListener('click', () => {
            elements.statusModal.classList.remove('open');
        });

        elements.statusModal.addEventListener('click', (e) => {
            if (e.target === elements.statusModal) {
                elements.statusModal.classList.remove('open');
            }
        });

        // Hazard Detail Modal
        const closeDetail = () => {
            elements.hazardDetailModal.classList.remove('open');
            state.layers.activeHighlight.clearLayers();
        };

        if (elements.closeHazardDetailBtn) elements.closeHazardDetailBtn.addEventListener('click', closeDetail);
        if (elements.dismissDetailBtn) elements.dismissDetailBtn.addEventListener('click', closeDetail);
        
        elements.hazardDetailModal.addEventListener('click', (e) => {
            if (e.target === elements.hazardDetailModal) closeDetail();
        });

        if (elements.focusHazardOnMapBtn) {
            elements.focusHazardOnMapBtn.addEventListener('click', () => {
                if (state.selectedHazard && state.selectedHazard.properties?.centroid) {
                    const c = state.selectedHazard.properties.centroid;
                    state.map.flyTo([c[1], c[0]], 9, { duration: 1.2 });
                }
                closeDetail();
            });
        }

        // Mode Switcher (Live vs Replay Demo)
        elements.modeLiveBtn.addEventListener('click', () => {
            if (!ApiService.isReplayMode()) return;
            elements.modeLiveBtn.classList.add('active');
            elements.modeReplayBtn.classList.remove('active');
            ApiService.setReplayMode(false);
            showToast('Switched to Live Doppler Radar Stream', 'info');
            loadData();
            initLiveWebSocket();
        });

        elements.modeReplayBtn.addEventListener('click', () => {
            if (ApiService.isReplayMode()) return;
            elements.modeReplayBtn.classList.add('active');
            elements.modeLiveBtn.classList.remove('active');
            ApiService.setReplayMode(true);
            showToast('Demonstration Replay Mode activated', 'warning');
            loadData();
        });

        // Demo retry button
        if (elements.demoRetryBtn) {
            elements.demoRetryBtn.addEventListener('click', () => {
                showToast('Reconnecting to live radar stream...', 'info');
                ApiService.setReplayMode(false);
                elements.modeLiveBtn.classList.add('active');
                elements.modeReplayBtn.classList.remove('active');
                loadData();
                initLiveWebSocket();
            });
        }
    }

    // Live WebSocket Event Stream
    function initLiveWebSocket() {
        ApiService.initWebSocket(
            (data) => {
                if (data.event === 'data_update') {
                    showToast(`${data.label}: New data received`, 'warning');
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

    // Bootstrap
    initMap();
    startClock();
    setupEvents();
    loadData();
    initLiveWebSocket();
});
