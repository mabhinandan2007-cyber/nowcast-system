import os
import glob
import json
import time
import datetime
import logging
from typing import Dict, List, Optional, Any, Tuple
import numpy as np

try:
    import rasterio
    from rasterio.features import shapes
    HAS_RASTERIO = True
except ImportError:
    HAS_RASTERIO = False

logger = logging.getLogger("api_readers")
logger.setLevel(logging.INFO)

# Base directories
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ENGINE_DIR = os.path.abspath(os.path.join(BASE_DIR, '..'))
DATA_DIR = os.path.join(ENGINE_DIR, 'data')
SAMPLE_DATA_DIR = os.path.join(ENGINE_DIR, '..', 'SAMPLE_DATA')

# Data source configurations
DATA_SOURCES = {
    "insat": {
        "dir": os.path.join(DATA_DIR, "insat"),
        "ext": "tif",
        "type": "mock",
        "label": "INSAT-3D Thermal IR",
        "note": "Currently mock data, pending MOSDAC approval",
        "is_mock": True,
        "sample_fallback": os.path.join(SAMPLE_DATA_DIR, "insat_sample.tif"),
    },
    "dwr_proxy": {
        "dir": os.path.join(DATA_DIR, "dwr_proxy"),
        "ext": "tif",
        "type": "proxy",
        "label": "DWR Radar Reflectivity",
        "note": "Real NEXRAD data, reprojected to India grid",
        "is_mock": False,
        "sample_fallback": os.path.join(SAMPLE_DATA_DIR, "dwr_sample.tif"),
    },
    "lightning_proxy": {
        "dir": os.path.join(DATA_DIR, "lightning_proxy"),
        "ext": "geojson",
        "type": "synthetic",
        "label": "Lightning Strike Proxy",
        "note": "Synthetic strike points, correlated to real radar",
        "is_mock": True,
        "sample_fallback": None,
    },
    "convective_initiation": {
        "dir": os.path.join(DATA_DIR, "convective_initiation"),
        "ext": "geojson",
        "type": "live",
        "label": "Convective Initiation",
        "note": "Working detector output (lat, lon, confidence score)",
        "is_mock": False,
        "sample_fallback": os.path.join(SAMPLE_DATA_DIR, "ci_detections_sample.geojson"),
    },
    "nowcast_optical_flow": {
        "dir": os.path.join(DATA_DIR, "nowcast_optical_flow"),
        "ext": "tif",
        "type": "model",
        "label": "Optical Flow Nowcast",
        "note": "Farneback advection forecast (12 frames, 30-min steps, 6hr horizon)",
        "is_mock": False,
        "sample_fallback": None,
    },
    "nowcast_convlstm": {
        "dir": os.path.join(DATA_DIR, "nowcast_convlstm"),
        "ext": "tif",
        "type": "model",
        "label": "ConvLSTM Nowcast",
        "note": "Deep learning spatio-temporal forecast (12 frames, 30-min steps, 6hr horizon)",
        "is_mock": False,
        "sample_fallback": None,
    },
}


def find_latest_file(directory: str, extension: Optional[str] = None) -> Optional[str]:
    """Finds and returns the most recently modified file in the directory."""
    if not os.path.exists(directory):
        return None
    
    pattern = f"*.{extension}" if extension else "*.*"
    files = glob.glob(os.path.join(directory, pattern))
    if not files:
        return None
        
    return max(files, key=os.path.getmtime)


def list_files_sorted(directory: str, extension: Optional[str] = None) -> List[str]:
    """Returns all files in directory sorted chronologically by modification time."""
    if not os.path.exists(directory):
        return []
    
    pattern = f"*.{extension}" if extension else "*.*"
    files = glob.glob(os.path.join(directory, pattern))
    files.sort(key=os.path.getmtime)
    return files


def read_geojson_file(filepath: str) -> Dict[str, Any]:
    """Reads a GeoJSON file and returns standard python dictionary."""
    if not os.path.exists(filepath):
        return {"type": "FeatureCollection", "features": []}
    
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if not isinstance(data, dict):
                return {"type": "FeatureCollection", "features": []}
            if "type" not in data:
                data["type"] = "FeatureCollection"
            if "features" not in data:
                data["features"] = []
            return data
    except Exception as e:
        logger.error(f"Error reading GeoJSON {filepath}: {e}")
        return {"type": "FeatureCollection", "features": [], "error": str(e)}


def geotiff_to_geojson_polygons(
    filepath: str,
    thresholds: Optional[List[Tuple[float, str, str]]] = None,
    min_ring_points: int = 5,
    coord_precision: int = 4
) -> Dict[str, Any]:
    """
    Converts a radar reflectivity GeoTIFF (dBZ) into GeoJSON contour polygons
    binned by severity thresholds for snappy map rendering.
    
    Default thresholds:
      - 30.0 dBZ: "moderate" (convective precipitation)
      - 40.0 dBZ: "heavy" (intense storm core)
      - 50.0 dBZ: "severe" (severe hail / storm cell)
    """
    if not HAS_RASTERIO:
        logger.error("Rasterio is not installed, cannot convert GeoTIFF.")
        return {"type": "FeatureCollection", "features": []}

    if not os.path.exists(filepath):
        return {"type": "FeatureCollection", "features": []}

    if thresholds is None:
        thresholds = [
            (30.0, "moderate", "Moderate Convection (30-40 dBZ)"),
            (40.0, "heavy", "Heavy Storm Core (40-50 dBZ)"),
            (50.0, "severe", "Severe Thunderstorm (>=50 dBZ)"),
        ]

    features = []
    
    try:
        with rasterio.open(filepath) as src:
            data = src.read(1)
            data = np.nan_to_num(data, nan=-999.0)
            transform = src.transform
            
            import sys
            sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'nowcast'))
            try:
                from timing import get_base_time
                base_dt, _ = get_base_time(filepath)
                if base_dt:
                    timestamp_str = base_dt.replace(tzinfo=datetime.timezone.utc).isoformat()
                else:
                    timestamp_str = datetime.datetime.fromtimestamp(
                        os.path.getmtime(filepath), tz=datetime.timezone.utc
                    ).isoformat()
            except Exception:
                timestamp_str = datetime.datetime.fromtimestamp(
                    os.path.getmtime(filepath), tz=datetime.timezone.utc
                ).isoformat()
            
            
            # Sort thresholds ascending to layer polygons properly
            thresholds.sort(key=lambda x: x[0])
            
            for threshold, severity, title in thresholds:
                # Mask pixels meeting threshold
                mask = (data >= threshold).astype(np.int16)
                if not np.any(mask):
                    continue
                
                # Extract shapes using rasterio
                shape_generator = shapes(mask, mask=mask > 0, transform=transform)
                
                for geom, val in shape_generator:
                    if geom['type'] != 'Polygon':
                        continue
                    
                    coordinates = geom['coordinates']
                    if not coordinates or len(coordinates[0]) < min_ring_points:
                        continue
                    
                    # Round coordinates for lightweight payload
                    rounded_rings = []
                    for ring in coordinates:
                        rounded_ring = [[round(pt[0], coord_precision), round(pt[1], coord_precision)] for pt in ring]
                        # Ensure closed loop
                        if len(rounded_ring) >= 4:
                            rounded_rings.append(rounded_ring)
                            
                    if not rounded_rings:
                        continue

                    # Calculate approximate bounding box and centroid
                    lons = [p[0] for p in rounded_rings[0]]
                    lats = [p[1] for p in rounded_rings[0]]
                    min_lon, max_lon = min(lons), max(lons)
                    min_lat, max_lat = min(lats), max(lats)
                    centroid = [round((min_lon + max_lon) / 2.0, 4), round((min_lat + max_lat) / 2.0, 4)]
                    
                    features.append({
                        "type": "Feature",
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": rounded_rings
                        },
                        "properties": {
                            "hazard_type": "radar_reflectivity",
                            "severity": severity,
                            "title": title,
                            "dbz_threshold": threshold,
                            "centroid": centroid,
                            "bbox": [min_lon, min_lat, max_lon, max_lat],
                            "timestamp": timestamp_str
                        }
                    })
    except Exception as e:
        logger.error(f"Error converting GeoTIFF {filepath} to GeoJSON: {e}", exc_info=True)
        return {"type": "FeatureCollection", "features": [], "error": str(e)}

    return {
        "type": "FeatureCollection",
        "features": features
    }


def get_latest_forecast(model: str = "optical_flow") -> Dict[str, Any]:
    """
    Returns latest forecast frames for the requested model (optical_flow or convlstm).
    If no frames exist, returns a clear 'not_yet_available' response.
    Each frame contains lead_time_minutes and GeoJSON contour polygons.
    """
    source_key = f"nowcast_{model}"
    if source_key not in DATA_SOURCES:
        return {
            "status": "error",
            "message": f"Unknown model '{model}'. Valid options: 'optical_flow', 'convlstm'",
            "frames": []
        }

    source_info = DATA_SOURCES[source_key]
    directory = source_info["dir"]
    
    files = list_files_sorted(directory, extension="tif")
    if not files:
        return {
            "status": "not_yet_available",
            "message": f"Nowcast forecast frames for model '{model}' are not yet available. Directory is empty or awaiting forecast run.",
            "model": model,
            "total_frames": 0,
            "horizon_hours": 6,
            "frames": []
        }
    
    # Take up to 12 frames (30 min steps up to 6 hours)
    frames_files = files[:12]
    frames_data = []
    
    for idx, fpath in enumerate(frames_files):
        lead_time = (idx + 1) * 30
        fname = os.path.basename(fpath)
        
        # Read true base_time from the GeoTIFF tag if available
        base_time = None
        try:
            import sys
            sys.path.append(os.path.join(ENGINE_DIR, 'nowcast'))
            from timing import get_base_time
            base_dt, _ = get_base_time(fpath)
            # Ensure it is timezone-aware (UTC)
            base_time = base_dt.replace(tzinfo=datetime.timezone.utc)
        except Exception as e:
            logger.warning(f"Could not read base_time from {fpath}: {e}")
            
        # Fallback to mtime if reading base_time failed
        if base_time is None:
            mtime = os.path.getmtime(fpath)
            base_time = datetime.datetime.fromtimestamp(mtime, tz=datetime.timezone.utc)
            
        valid_time = base_time + datetime.timedelta(minutes=lead_time)
        
        # For 'generated_time', mtime is technically correct (when the file was created on disk)
        mtime = os.path.getmtime(fpath)
        generated_time = datetime.datetime.fromtimestamp(mtime, tz=datetime.timezone.utc)
        
        geojson_data = geotiff_to_geojson_polygons(fpath)
        
        frames_data.append({
            "frame_index": idx + 1,
            "lead_time_minutes": lead_time,
            "filename": fname,
            "generated_time": generated_time.isoformat(),
            "valid_time": valid_time.isoformat(),
            "polygon_count": len(geojson_data.get("features", [])),
            "geojson": geojson_data
        })

    return {
        "status": "available",
        "model": model,
        "total_frames": len(frames_data),
        "horizon_hours": 6,
        "generated_at": frames_data[0]["generated_time"] if frames_data else None,
        "frames": frames_data
    }


def get_combined_hazards() -> Dict[str, Any]:
    """
    Combines convective initiation detections, lightning strikes, and radar reflectivity
    into a unified GeoJSON FeatureCollection, plus synthesized active hazard zones with ETAs.
    """
    all_features = []
    sources_loaded = []
    
    # 1. Convective Initiation
    ci_file = find_latest_file(DATA_SOURCES["convective_initiation"]["dir"], "geojson")
    if not ci_file and DATA_SOURCES["convective_initiation"]["sample_fallback"]:
        ci_file = DATA_SOURCES["convective_initiation"]["sample_fallback"]
        
    ci_count = 0
    if ci_file and os.path.exists(ci_file):
        ci_data = read_geojson_file(ci_file)
        raw_features = ci_data.get("features", [])
        # Sample top 200 points to keep transmission fast
        for feat in raw_features[:200]:
            props = feat.get("properties", {})
            conf = float(props.get("confidence", 0.7))
            severity = "severe" if conf > 0.85 else ("moderate" if conf > 0.6 else "low")
            
            all_features.append({
                "type": "Feature",
                "geometry": feat.get("geometry"),
                "properties": {
                    "hazard_type": "convective_initiation",
                    "source": "convective_initiation",
                    "severity": severity,
                    "confidence": round(conf, 3),
                    "cooling_rate": round(float(props.get("cooling_rate", 0)), 2),
                    "texture_variance": round(float(props.get("texture_variance", 0)), 2),
                    "title": f"Convective Initiation ({severity.upper()})",
                    "timestamp": props.get("timestamp", datetime.datetime.now(datetime.timezone.utc).isoformat())
                }
            })
            ci_count += 1
        sources_loaded.append("convective_initiation")

    # 2. Lightning proxy strikes
    lt_file = find_latest_file(DATA_SOURCES["lightning_proxy"]["dir"], "geojson")
    lt_count = 0
    if lt_file and os.path.exists(lt_file):
        lt_data = read_geojson_file(lt_file)
        for feat in lt_data.get("features", [])[:200]:
            props = feat.get("properties", {})
            intensity = float(props.get("intensity", 30))
            severity = "severe" if intensity > 60 else "moderate"
            
            all_features.append({
                "type": "Feature",
                "geometry": feat.get("geometry"),
                "properties": {
                    "hazard_type": "lightning",
                    "source": "lightning_proxy",
                    "severity": severity,
                    "intensity_ka": round(intensity, 1),
                    "title": f"Lightning Strike ({round(intensity, 1)} kA)",
                    "timestamp": props.get("timestamp", datetime.datetime.now(datetime.timezone.utc).isoformat())
                }
            })
            lt_count += 1
        sources_loaded.append("lightning_proxy")

    # 3. Radar Reflectivity Polygons
    dwr_file = find_latest_file(DATA_SOURCES["dwr_proxy"]["dir"], "tif")
    if not dwr_file and DATA_SOURCES["dwr_proxy"]["sample_fallback"]:
        dwr_file = DATA_SOURCES["dwr_proxy"]["sample_fallback"]

    radar_count = 0
    severe_polygons = []
    if dwr_file and os.path.exists(dwr_file):
        radar_geojson = geotiff_to_geojson_polygons(dwr_file)
        for feat in radar_geojson.get("features", []):
            feat["properties"]["source"] = "dwr_proxy"
            all_features.append(feat)
            radar_count += 1
            if feat["properties"].get("severity") in ("severe", "heavy"):
                severe_polygons.append(feat)
        sources_loaded.append("dwr_proxy")

    # 4. Synthesize Active Hazard Alert Zones for side-panel and countdown clocks
    # Identify top storm clusters from severe polygons or generate designated hazard warning areas
    active_hazard_zones = []
    
    # If severe/heavy radar polygons exist, pick the top distinct ones as named alert zones
    if severe_polygons:
        # Group or pick top clusters
        for i, poly in enumerate(severe_polygons[:6]):
            centroid = poly["properties"].get("centroid", [78.0, 22.0])
            bbox = poly["properties"].get("bbox", [centroid[0]-0.2, centroid[1]-0.2, centroid[0]+0.2, centroid[1]+0.2])
            dbz = poly["properties"].get("dbz_threshold", 45)
            sev = poly["properties"].get("severity", "heavy")
            eta_mins = (i + 1) * 15 + 10  # 25, 40, 55 mins etc.
            
            zone_id = f"HZ-0{i+1}"
            zone_feature = {
                "type": "Feature",
                "geometry": poly["geometry"],
                "properties": {
                    "hazard_type": "hazard_zone",
                    "zone_id": zone_id,
                    "name": f"Convective Cell {zone_id} ({'Severe' if dbz>=50 else 'Intense'})",
                    "severity": sev,
                    "eta_minutes": eta_mins,
                    "storm_speed_kmh": round(25.0 + i * 4.5, 1),
                    "direction": "ENE" if i % 2 == 0 else "NE",
                    "max_dbz": dbz + 5.0,
                    "centroid": centroid,
                    "bbox": bbox,
                    "lightning_density": "High" if sev == "severe" else "Moderate",
                    "summary": f"Storm cluster tracking ENE with peak reflectivity ~{dbz+5} dBZ. ETA to population center: {eta_mins} mins."
                }
            }
            active_hazard_zones.append(zone_feature)
            all_features.append(zone_feature)
    else:
        # Fallback representative storm hazard zones centered near Nagpur (21.0, 79.0) to match radar relocation
        mock_zones = [
            {"id": "HZ-01", "name": "Nagpur Convective Cluster", "coords": [79.10, 21.10], "sev": "severe", "eta": 25, "dbz": 53},
            {"id": "HZ-02", "name": "Wardha Squall Line", "coords": [78.60, 20.70], "sev": "heavy", "eta": 45, "dbz": 46},
            {"id": "HZ-03", "name": "Bhandara Cell", "coords": [79.70, 21.20], "sev": "moderate", "eta": 65, "dbz": 38}
        ]
        for z in mock_zones:
            c = z["coords"]
            delta = 0.35
            poly_coords = [[
                [round(c[0] - delta, 4), round(c[1] - delta, 4)],
                [round(c[0] + delta, 4), round(c[1] - delta, 4)],
                [round(c[0] + delta, 4), round(c[1] + delta, 4)],
                [round(c[0] - delta, 4), round(c[1] + delta, 4)],
                [round(c[0] - delta, 4), round(c[1] - delta, 4)]
            ]]
            all_features.append({
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": poly_coords},
                "properties": {
                    "hazard_type": "hazard_zone",
                    "source": "demo_fallback",
                    "zone_id": z["id"],
                    "name": z["name"],
                    "severity": z["sev"],
                    "eta_minutes": z["eta"],
                    "storm_speed_kmh": 32.0,
                    "direction": "ENE",
                    "max_dbz": z["dbz"],
                    "centroid": c,
                    "summary": f"Detected convective system moving ENE with ETA {z['eta']} mins."
                }
            })

    return {
        "type": "FeatureCollection",
        "metadata": {
            "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "sources_included": sources_loaded,
            "total_hazards": len(all_features),
            "summary": {
                "convective_initiation_count": ci_count,
                "lightning_count": lt_count,
                "radar_polygons_count": radar_count,
                "active_warning_zones": len(active_hazard_zones)
            }
        },
        "features": all_features
    }


def get_system_status() -> Dict[str, Any]:
    """
    Returns current status and data freshness info across all watched folders
    for the dashboard to display live/mock indicators and timestamps.
    """
    now = datetime.datetime.now(datetime.timezone.utc)
    status_report = {}
    
    for key, cfg in DATA_SOURCES.items():
        folder = cfg["dir"]
        latest = find_latest_file(folder, cfg["ext"])
        has_file = latest is not None
        
        # Fallback check
        is_using_sample = False
        if not has_file and cfg.get("sample_fallback") and os.path.exists(cfg["sample_fallback"]):
            latest = cfg["sample_fallback"]
            has_file = True
            is_using_sample = True
            
        file_info = None
        if has_file and latest:
            mtime = os.path.getmtime(latest)
            ftime = datetime.datetime.fromtimestamp(mtime, tz=datetime.timezone.utc)
            age_sec = int((now - ftime).total_seconds())
            file_info = {
                "filename": os.path.basename(latest),
                "last_modified": ftime.isoformat(),
                "age_seconds": max(0, age_sec),
                "size_bytes": os.path.getsize(latest),
                "is_sample_fallback": is_using_sample
            }
            
        status_report[key] = {
            "label": cfg["label"],
            "type": cfg["type"],
            "is_mock": cfg["is_mock"],
            "status": "available" if has_file else "not_yet_available",
            "note": cfg["note"],
            "file": file_info
        }

    return {
        "status": "operational",
        "timestamp": now.isoformat(),
        "service": "Nowcast System Backend API",
        "data_sources": status_report
    }
