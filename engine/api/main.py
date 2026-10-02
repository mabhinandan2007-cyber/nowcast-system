import os
import sys
import json
import asyncio
import datetime
import logging
from contextlib import asynccontextmanager
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# Ensure engine path is available for imports
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
ENGINE_DIR = os.path.abspath(os.path.join(CURRENT_DIR, '..'))
if ENGINE_DIR not in sys.path:
    sys.path.insert(0, ENGINE_DIR)

from api.readers import (
    DATA_SOURCES,
    find_latest_file,
    get_system_status,
    get_combined_hazards,
    get_latest_forecast,
    read_geojson_file
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("nowcast_api")

# In-memory list of active WebSocket connections
active_connections: List[WebSocket] = []

# State for polling-based folder watcher
folder_state_cache: Dict[str, Optional[float]] = {}


async def file_watcher_loop():
    """
    Background polling task that watches the data folders every 3 seconds.
    When a new file appears or changes, pushes a notification to all connected WebSockets.
    """
    logger.info("File watcher background polling started.")
    
    # Initialize cache
    for key, cfg in DATA_SOURCES.items():
        latest = find_latest_file(cfg["dir"], cfg["ext"])
        folder_state_cache[key] = os.path.getmtime(latest) if latest else None

    while True:
        try:
            await asyncio.sleep(3)
            
            for key, cfg in DATA_SOURCES.items():
                latest = find_latest_file(cfg["dir"], cfg["ext"])
                current_mtime = os.path.getmtime(latest) if latest else None
                prev_mtime = folder_state_cache.get(key)
                
                if current_mtime is not None and (prev_mtime is None or current_mtime > prev_mtime):
                    folder_state_cache[key] = current_mtime
                    fname = os.path.basename(latest)
                    logger.info(f"File watcher detected update in {key}: {fname}")
                    
                    # Notify WebSocket clients
                    notification = {
                        "event": "data_update",
                        "source": key,
                        "label": cfg["label"],
                        "filename": fname,
                        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                        "message": f"New file arrived for {cfg['label']}: {fname}"
                    }
                    
                    # Broadcast
                    disconnected = []
                    for ws in active_connections:
                        try:
                            await ws.send_json(notification)
                        except Exception:
                            disconnected.append(ws)
                            
                    for ws in disconnected:
                        if ws in active_connections:
                            active_connections.remove(ws)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Error in file watcher loop: {e}", exc_info=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start background file watcher
    watcher_task = asyncio.create_task(file_watcher_loop())
    yield
    # Cleanup on shutdown
    watcher_task.cancel()
    try:
        await watcher_task
    except asyncio.CancelledError:
        pass


app = FastAPI(
    title="Convective-Scale Nowcasting System API",
    description="High-frequency GIS API serving live radar reflectivity, convective initiation, lightning, and 6-hour nowcast advection forecasts.",
    version="1.0.0",
    lifespan=lifespan
)

# Enable CORS for local and remote dashboard development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


from fastapi.staticfiles import StaticFiles

DASHBOARD_DIR = os.path.abspath(os.path.join(CURRENT_DIR, '..', '..', 'dashboard'))
if os.path.exists(DASHBOARD_DIR):
    app.mount("/dashboard", StaticFiles(directory=DASHBOARD_DIR, html=True), name="dashboard")


@app.get("/")
def get_root():
    """Service index and endpoint directory."""
    return {
        "service": "Nowcast System Backend API",
        "version": "1.0.0",
        "documentation": "/docs",
        "dashboard": "/dashboard/",
        "endpoints": {
            "dashboard": "/dashboard/",
            "status": "/status",
            "hazards": "/hazards",
            "forecast": "/forecast?model=optical_flow",
            "websocket_live": "ws://<host>:<port>/live",
            "replay": "/replay"
        }
    }


@app.get("/status")
def get_status():
    """
    Data freshness and system health check.
    Returns status for all 6 data sources, indicating which feeds are live vs mock/proxy,
    latest file timestamps, and age in seconds.
    """
    return get_system_status()


@app.get("/hazards")
def get_hazards(
    severity: Optional[str] = Query(None, description="Filter by severity: 'low', 'moderate', 'heavy', 'severe'"),
    hazard_type: Optional[str] = Query(None, description="Filter by hazard_type: 'convective_initiation', 'lightning', 'radar_reflectivity', 'hazard_zone'")
):
    """
    Returns current multi-source hazard zones combining:
    - Convective Initiation detection points
    - Lightning strike events
    - Radar reflectivity contour polygons
    - Synthesized storm hazard alert zones with ETA countdowns
    """
    hazards_data = get_combined_hazards()
    features = hazards_data.get("features", [])
    
    if severity:
        features = [f for f in features if f.get("properties", {}).get("severity", "").lower() == severity.lower()]
        
    if hazard_type:
        features = [f for f in features if f.get("properties", {}).get("hazard_type", "").lower() == hazard_type.lower()]
        
    hazards_data["features"] = features
    hazards_data["metadata"]["filtered_count"] = len(features)
    return hazards_data


@app.get("/forecast")
def get_forecast(
    model: str = Query("optical_flow", description="Nowcast model: 'optical_flow' or 'convlstm'"),
    lead_time: Optional[int] = Query(None, description="Optional lead time filter in minutes (e.g. 30, 60, ..., 360)")
):
    """
    Returns latest nowcast forecast frames as GeoJSON with lead_time_minutes.
    If frames are not yet available, returns a clear 'not_yet_available' response.
    """
    forecast_data = get_latest_forecast(model=model)
    
    if forecast_data.get("status") != "available":
        return forecast_data
        
    if lead_time is not None:
        matched_frames = [f for f in forecast_data.get("frames", []) if f.get("lead_time_minutes") == lead_time]
        if not matched_frames:
            raise HTTPException(
                status_code=404,
                detail=f"Frame with lead_time_minutes={lead_time} not found. Available lead times: {[f.get('lead_time_minutes') for f in forecast_data.get('frames', [])]}"
            )
        forecast_data["frames"] = matched_frames
        forecast_data["total_frames"] = len(matched_frames)
        
    return forecast_data


@app.get("/replay")
def get_replay_data():
    """
    Cached historical/demo replay dataset for offline or venue Wi-Fi demo mode.
    Bundles status, current hazards, and forecast frames in a single snapshot.
    """
    status = get_system_status()
    hazards = get_combined_hazards()
    forecast = get_latest_forecast(model="optical_flow")
    
    return {
        "mode": "replay_demo",
        "snapshot_timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "status": status,
        "hazards": hazards,
        "forecast": forecast
    }


@app.websocket("/live")
async def websocket_live_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint pushing real-time notifications whenever new files appear in watched folders.
    Also handles client pings and delivers initial status on handshake.
    """
    await websocket.accept()
    active_connections.append(websocket)
    client_host = websocket.client.host if websocket.client else "unknown"
    logger.info(f"WebSocket client connected from {client_host}. Total active: {len(active_connections)}")
    
    try:
        # Send initial connection confirmation and current status snapshot
        await websocket.send_json({
            "event": "connected",
            "message": "Connected to Nowcast System Live Event Stream",
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "status": get_system_status()
        })
        
        # Keep connection alive & handle incoming client messages
        while True:
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
                action = msg.get("action")
                if action == "ping":
                    await websocket.send_json({
                        "event": "pong",
                        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()
                    })
                elif action == "get_status":
                    await websocket.send_json({
                        "event": "status_update",
                        "status": get_system_status()
                    })
            except json.JSONDecodeError:
                pass
    except WebSocketDisconnect:
        logger.info(f"WebSocket client disconnected: {client_host}")
    except Exception as e:
        logger.warning(f"WebSocket error: {e}")
    finally:
        if websocket in active_connections:
            active_connections.remove(websocket)
        logger.info(f"Remaining active WebSocket connections: {len(active_connections)}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("engine.api.main:app", host="127.0.0.1", port=8000, reload=True)
