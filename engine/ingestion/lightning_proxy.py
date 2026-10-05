import os
import glob
import json
import time
import datetime
import logging
import numpy as np
import rasterio

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("lightning_proxy")

DATA_DIR = os.path.join(os.path.dirname(__file__), '..', 'data', 'lightning_proxy')
INSAT_DIR = os.path.join(os.path.dirname(__file__), '..', 'data', 'insat')
DWR_DIR = os.path.join(os.path.dirname(__file__), '..', 'data', 'dwr_proxy')

os.makedirs(DATA_DIR, exist_ok=True)

def get_latest_file(directory, extension):
    files = glob.glob(os.path.join(directory, f"*.{extension}"))
    if not files:
        return None
    return max(files, key=os.path.getctime)

def generate_lightning_geojson():
    """
    Reads the latest INSAT IR and DWR Proxy outputs and generates synthetic 
    lightning strike events correlated with convective intensity.
    """
    logger.info("Generating synthetic lightning points...")
    
    insat_file = get_latest_file(INSAT_DIR, "tif")
    dwr_file = get_latest_file(DWR_DIR, "tif")
    
    strikes = []
    
    dwr_bounds = None
    if dwr_file:
        try:
            with rasterio.open(dwr_file) as src:
                dwr_bounds = src.bounds
        except:
            pass

    # Try using DWR first for high reflectivity correlation
    if dwr_file:
        try:
            with rasterio.open(dwr_file) as src:
                dwr_data = src.read(1)
                transform = src.transform
                # Find pixels with high reflectivity (> 40 dBZ)
                y_coords, x_coords = np.where(dwr_data > 40)
                
                # Sample a subset of these as lightning strikes
                if len(y_coords) > 0:
                    num_strikes = min(len(y_coords) // 10, 500) # max 500 strikes
                    indices = np.random.choice(len(y_coords), num_strikes, replace=False)
                    for idx in indices:
                        lon, lat = rasterio.transform.xy(transform, y_coords[idx], x_coords[idx])
                        strikes.append({
                            "type": "Feature",
                            "geometry": {"type": "Point", "coordinates": [lon, lat]},
                            "properties": {
                                "timestamp": datetime.datetime.utcnow().isoformat(),
                                "intensity": float(np.random.uniform(10, 100)), # kA
                                "source": "synthetic_dwr_correlated"
                            }
                        })
        except Exception as e:
            logger.error(f"Error reading DWR for lightning proxy: {e}")

    # If no DWR hits, try INSAT for cold IR correlation
    if not strikes and insat_file:
        try:
            with rasterio.open(insat_file) as src:
                insat_data = src.read(1)
                transform = src.transform
                # Assuming data is brightness temp in Kelvin, cold clouds < 230K
                y_coords, x_coords = np.where(insat_data < 230)
                
                if len(y_coords) > 0:
                    valid_coords = []
                    for idx in range(len(y_coords)):
                        lon, lat = rasterio.transform.xy(transform, y_coords[idx], x_coords[idx])
                        if dwr_bounds:
                            if lon < dwr_bounds.left or lon > dwr_bounds.right or lat < dwr_bounds.bottom or lat > dwr_bounds.top:
                                continue
                        valid_coords.append((lon, lat))
                    
                    if valid_coords:
                        num_strikes = min(len(valid_coords) // 20, 300)
                        
                        import random
                        sampled_coords = random.sample(valid_coords, num_strikes)
                        
                        for lon, lat in sampled_coords:
                            strikes.append({
                                "type": "Feature",
                                "geometry": {"type": "Point", "coordinates": [lon, lat]},
                                "properties": {
                                    "timestamp": datetime.datetime.utcnow().isoformat(),
                                    "intensity": float(np.random.uniform(5, 50)),
                                    "source": "synthetic_insat_correlated"
                                }
                            })
        except Exception as e:
            logger.error(f"Error reading INSAT for lightning proxy: {e}")
            
    # If both fail or yield nothing, generate some random strikes over India
    if not strikes:
        logger.warning("No correlation data found. Generating random strikes.")
        for _ in range(50):
            lon = np.random.uniform(68.0, 98.0)
            lat = np.random.uniform(6.0, 38.0)
            strikes.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [lon, lat]},
                "properties": {
                    "timestamp": datetime.datetime.utcnow().isoformat(),
                    "intensity": float(np.random.uniform(10, 100)),
                    "source": "synthetic_random"
                }
            })

    geojson = {
        "type": "FeatureCollection",
        "features": strikes
    }
    
    timestamp = datetime.datetime.utcnow().strftime("%Y%m%d_%H%M")
    output_filename = f"lightning_proxy_{timestamp}.geojson"
    output_path = os.path.join(DATA_DIR, output_filename)
    
    with open(output_path, 'w') as f:
        json.dump(geojson, f, indent=2)
        
    logger.info(f"Saved {len(strikes)} lightning proxy events to {output_path}")

if __name__ == "__main__":
    generate_lightning_geojson()
