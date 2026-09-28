import os
import time
import datetime
import logging
import numpy as np
import rasterio
from rasterio.transform import from_origin
import boto3
from botocore import UNSIGNED
from botocore.config import Config

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("dwr_proxy")

try:
    import pyart
    HAS_PYART = True
except ImportError:
    HAS_PYART = False
    logger.warning("arm-pyart not installed or failed to import. Will use fallback grid generation.")

DATA_DIR = os.path.join(os.path.dirname(__file__), '..', 'data', 'dwr_proxy')
os.makedirs(DATA_DIR, exist_ok=True)

def download_latest_nexrad(station="KTLX"):
    """
    Downloads the latest NEXRAD Level 2 file from the AWS open data bucket.
    No authentication is needed.
    """
    logger.info(f"Connecting to NOAA NEXRAD AWS bucket for station {station}...")
    s3 = boto3.client('s3', config=Config(signature_version=UNSIGNED))
    bucket = 'unidata-nexrad-level2'
    
    now = datetime.datetime.utcnow()
    # Check current and previous hour to ensure we find files
    prefixes = [
        now.strftime(f"%Y/%m/%d/{station}/"),
        (now - datetime.timedelta(hours=1)).strftime(f"%Y/%m/%d/{station}/")
    ]
    
    latest_file_key = None
    for prefix in prefixes:
        logger.info(f"Attempting to list objects with Prefix: {prefix} in Bucket: {bucket}")
        try:
            response = s3.list_objects_v2(Bucket=bucket, Prefix=prefix)
            if 'Contents' in response and len(response['Contents']) > 0:
                # Sort by last modified
                sorted_files = sorted(response['Contents'], key=lambda obj: obj['LastModified'])
                latest_file_key = sorted_files[-1]['Key']
                break
        except Exception as e:
            logger.error(f"Error listing prefix {prefix}: {e}")
            raise e
            
    if not latest_file_key:
        logger.error(f"No recent NEXRAD files found for {station}")
        return None
        
    local_path = os.path.join(DATA_DIR, os.path.basename(latest_file_key))
    if not os.path.exists(local_path):
        logger.info(f"Downloading {latest_file_key} to {local_path}...")
        s3.download_file(bucket, latest_file_key, local_path)
        logger.info("Download complete.")
    else:
        logger.info(f"Latest file already exists locally: {local_path}")
        
    return local_path

def process_nexrad_to_india_grid(radar_file, output_path, scan_time, ingested_at):
    """
    proxy_source: NEXRAD
    Reads the real NEXRAD file and maps its reflectivity to a configurable 
    India-region bounding box (1-3km resolution) for architecture-testing.
    """
    # India bounding box (approx)
    lon_min, lat_max = 68.0, 38.0
    lon_max, lat_min = 98.0, 6.0
    
    # Target resolution: approx 3km (0.027 degrees)
    pixel_size = 0.027
    width = int((lon_max - lon_min) / pixel_size)
    height = int((lat_max - lat_min) / pixel_size)
    
    proxy_source = "NEXRAD"
    
    if HAS_PYART and radar_file != "dummy_file.nc":
        try:
            logger.info("Parsing NEXRAD with PyART...")
            radar = pyart.io.read_nexrad_archive(radar_file)
            refl = radar.fields['reflectivity']['data']
            sweep_data = refl[radar.get_slice(0)]
            import cv2 
            sweep_2d = np.ma.filled(sweep_data, 0)
            proxy_grid = cv2.resize(sweep_2d, (width, height))
            logger.info("Real NEXRAD data mapped to India grid.")
        except Exception as e:
            logger.error(f"PyART processing failed: {e}. Falling back to pseudo-data.")
            proxy_grid = _generate_pseudo_grid(width, height)
            proxy_source = "PSEUDO_DATA"
    else:
        logger.info("Generating pseudo-data seeded from real file size (proxy_source: PSEUDO_DATA)")
        proxy_source = "PSEUDO_DATA"
        if os.path.exists(radar_file) and radar_file != "dummy_file.nc":
            file_size = os.path.getsize(radar_file)
        else:
            file_size = int(time.time())
            
        np.random.seed(file_size % 10000)
        proxy_grid = _generate_pseudo_grid(width, height)
        
    transform = from_origin(lon_min, lat_max, pixel_size, pixel_size)
    
    with rasterio.open(
        output_path,
        'w',
        driver='GTiff',
        height=height,
        width=width,
        count=1,
        dtype=np.float32,
        crs='+proj=latlong',
        transform=transform,
    ) as dst:
        dst.write(proxy_grid.astype(np.float32), 1)
        # Add metadata tags
        dst.update_tags(
            proxy_source=proxy_source,
            scan_time=scan_time,
            ingested_at=ingested_at
        )
        
    logger.info(f"Saved DWR proxy grid to {output_path}")

def _generate_pseudo_grid(width, height):
    # Simulated convection cells
    grid = np.zeros((height, width), dtype=np.float32)
    num_cells = 20
    for _ in range(num_cells):
        cx, cy = np.random.randint(0, width), np.random.randint(0, height)
        radius = np.random.randint(10, 50)
        intensity = np.random.uniform(20, 60)
        y, x = np.ogrid[-cy:height-cy, -cx:width-cx]
        mask = x*x + y*y <= radius*radius
        grid[mask] = intensity
    return grid

def fetch_and_process_dwr():
    ingested_at = datetime.datetime.utcnow().isoformat() + "Z"
    
    try:
        radar_file = download_latest_nexrad("KABR")
    except Exception as e:
        logger.error(f"Download failed: {e}")
        radar_file = None
        
    try:
        if radar_file and radar_file != "dummy_file.nc" and os.path.exists(radar_file):
            # Extract scan time from NEXRAD filename e.g. KABR20260927_161144_V06
            base_filename = os.path.basename(radar_file)
            try:
                time_str = base_filename[4:19]
                dt = datetime.datetime.strptime(time_str, "%Y%m%d_%H%M%S")
                timestamp = dt.strftime("%Y%m%d_%H%M")
                scan_time = dt.isoformat() + "Z"
            except Exception as e:
                raise ValueError(f"Failed to parse time from real NEXRAD filename {base_filename}") from e
        else:
            dt = datetime.datetime.utcnow()
            timestamp = dt.strftime("%Y%m%d_%H%M")
            scan_time = dt.isoformat() + "Z"
            
        output_filename = f"dwr_proxy_{timestamp}.tif"
        output_path = os.path.join(DATA_DIR, output_filename)
        
        if not radar_file:
            logger.warning("No radar file downloaded, falling back to pure pseudo-data generation.")
            radar_file = "dummy_file.nc" 
            
        process_nexrad_to_india_grid(radar_file, output_path, scan_time, ingested_at)
    except Exception as e:
        logger.error(f"Error in DWR proxy fetch: {e}")

if __name__ == "__main__":
    fetch_and_process_dwr()
