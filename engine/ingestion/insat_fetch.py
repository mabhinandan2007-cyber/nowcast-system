import os
import glob
import time
import datetime
import numpy as np
import rasterio
from rasterio.transform import from_origin
import h5py
import schedule
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("insat_fetch")

DATA_DIR = os.path.join(os.path.dirname(__file__), '..', 'data', 'insat')
# Simulating a manual download directory constraint
MANUAL_DOWNLOAD_DIR = os.path.join(os.path.dirname(__file__), '..', 'data', 'insat_raw')

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(MANUAL_DOWNLOAD_DIR, exist_ok=True)

def parse_insat_hdf_to_geotiff(hdf_path, output_path):
    """
    Reads an INSAT-3D/3DR HDF5 file and extracts the Thermal IR band,
    saving it as a georeferenced GeoTIFF.
    """
    logger.info(f"Parsing actual MOSDAC data from {hdf_path}")
    try:
        with h5py.File(hdf_path, 'r') as hf:
            # Note: The exact dataset path depends on the specific INSAT L1B product
            # Typically something like 'IMG_TIR1' or 'TIR1' 
            # Read TIR1 raw counts and apply LUT
            if 'IMG_TIR1' not in hf.keys() or 'IMG_TIR1_TEMP' not in hf.keys():
                raise ValueError("IMG_TIR1 or IMG_TIR1_TEMP LUT not found in HDF5")
                
            tir1_counts = hf['IMG_TIR1'][:]
            # If it has a dummy first dimension (e.g., 1, 1616, 1737), squeeze it
            if len(tir1_counts.shape) == 3 and tir1_counts.shape[0] == 1:
                tir1_counts = tir1_counts[0]
                
            tir1_lut = hf['IMG_TIR1_TEMP'][:]
            tir1_data = tir1_lut[tir1_counts]
            
            # 1023 is the raw _FillValue for digital counts in IMG_TIR1
            tir1_data = np.where(tir1_counts == 1023, np.nan, tir1_data)
            
            tir_data = tir1_data
            
            # Simulated geo-bounds for INSAT-3D (India focus)
            lon_min, lat_max = 68.0, 38.0
            lon_max, lat_min = 98.0, 6.0
            
            height, width = tir_data.shape
            pixel_size_x = (lon_max - lon_min) / width
            pixel_size_y = (lat_max - lat_min) / height
            
            transform = from_origin(lon_min, lat_max, pixel_size_x, pixel_size_y)
            
            with rasterio.open(
                output_path,
                'w',
                driver='GTiff',
                height=height,
                width=width,
                count=1,
                dtype=tir_data.dtype,
                crs='+proj=latlong',
                transform=transform,
            ) as dst:
                dst.write(tir_data, 1)
        logger.info(f"Successfully created GeoTIFF: {output_path}")
    except Exception as e:
        logger.error(f"Failed to parse HDF5 {hdf_path}: {e}")

def create_mock_geotiff(output_path):
    """
    Creates a mock GeoTIFF if no actual manual data is found, 
    to ensure the pipeline can be tested end-to-end.
    """
    logger.info(f"No manual data found. Generating mock INSAT IR test GeoTIFF at {output_path}")
    width, height = 500, 500
    # Simulate some thermal cooling patterns (random noise + gradient)
    np.random.seed(int(time.time()) % 1000)
    base = np.linspace(280, 220, height).reshape(height, 1) * np.ones((1, width))
    noise = np.random.normal(0, 10, (height, width))
    mock_tir = (base + noise).astype(np.float32)
    
    lon_min, lat_max = 68.0, 38.0
    pixel_size = 30.0 / width
    transform = from_origin(lon_min, lat_max, pixel_size, pixel_size)
    
    with rasterio.open(
        output_path,
        'w',
        driver='GTiff',
        height=height,
        width=width,
        count=1,
        dtype=mock_tir.dtype,
        crs='+proj=latlong',
        transform=transform,
    ) as dst:
        dst.write(mock_tir, 1)
    logger.info("Mock GeoTIFF created.")

def fetch_insat_data():
    """
    CONSTRAINT NOTE: Full automation of INSAT-3D/3DR data is not feasible here 
    because MOSDAC requires a registered account and authentication for their API 
    (mdapi.py / config.json) or manual ordering. 
    
    This fetcher assumes a 'manual-download-then-parse' workflow where users 
    place downloaded HDF5 files in the MANUAL_DOWNLOAD_DIR. If none are found, 
    it generates a mock proxy file for pipeline testing.
    """
    logger.info("Checking for new INSAT IR data...")
    timestamp = datetime.datetime.utcnow().strftime("%Y%m%d_%H%M")
    output_filename = f"insat_{timestamp}.tif"
    output_path = os.path.join(DATA_DIR, output_filename)
    
    hdf_files = glob.glob(os.path.join(MANUAL_DOWNLOAD_DIR, "*.h5"))
    
    if hdf_files:
        # Process the most recent file
        latest_file = max(hdf_files, key=os.path.getctime)
        parse_insat_hdf_to_geotiff(latest_file, output_path)
        # Move or delete after processing? (Skipping for now)
    else:
        create_mock_geotiff(output_path)

def start_scheduler(interval_minutes=15):
    logger.info(f"Starting INSAT fetcher schedule: every {interval_minutes} minutes.")
    schedule.every(interval_minutes).minutes.do(fetch_insat_data)
    # Run once immediately
    fetch_insat_data()
    while True:
        schedule.run_pending()
        time.sleep(1)

if __name__ == "__main__":
    # If run standalone, execute once
    fetch_insat_data()
