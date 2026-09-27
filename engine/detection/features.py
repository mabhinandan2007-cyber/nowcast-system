import os
import glob
import datetime
import numpy as np
import rasterio
from scipy.ndimage import uniform_filter

def extract_spatial_texture(data, window_size=3):
    """
    Computes spatial texture variance as a proxy for convective cell structure.
    Uses E[X^2] - E[X]^2 for fast vectorized local variance.
    """
    c1 = uniform_filter(data, window_size, mode='reflect')
    c2 = uniform_filter(data**2, window_size, mode='reflect')
    variance = c2 - c1**2
    # Floating point issues can sometimes cause tiny negative variances
    variance = np.clip(variance, 0, None)
    return variance

def compute_temporal_rate(data_current, data_previous, dt_minutes=15):
    """
    Computes temporal change rate (e.g., cooling rate K/hour or refl change/hour).
    delta / (dt_minutes / 60)
    """
    dt_hours = dt_minutes / 60.0
    if dt_hours <= 0:
        dt_hours = 0.25 # default 15 min
    rate = (data_current - data_previous) / dt_hours
    return rate

def process_frames(frame_paths, dt_minutes=15):
    """
    Processes a list of consecutive GeoTIFF frame paths (ordered chronologically).
    Returns the features for the most recent frame.
    Returns:
        dict of { 'value': arr, 'temporal_rate': arr, 'texture_variance': arr, 'transform': transform }
    """
    if len(frame_paths) < 2:
        raise ValueError("Need at least 2 frames to compute temporal cooling rate.")
        
    latest_path = frame_paths[-1]
    prev_path = frame_paths[-2]
    
    with rasterio.open(latest_path) as src_curr:
        data_curr = src_curr.read(1).astype(np.float32)
        transform = src_curr.transform
        
    with rasterio.open(prev_path) as src_prev:
        data_prev = src_prev.read(1).astype(np.float32)
        # Assuming same shape and georeferencing
        
    texture_var = extract_spatial_texture(data_curr)
    temp_rate = compute_temporal_rate(data_curr, data_prev, dt_minutes)
    
    return {
        'value': data_curr,
        'temporal_rate': temp_rate,
        'texture_variance': texture_var,
        'transform': transform,
        'shape': data_curr.shape
    }

def get_latest_consecutive_files(directory, ext='tif', num_files=2):
    """Helper to fetch the N most recent files in chronological order"""
    files = glob.glob(os.path.join(directory, f"*.{ext}"))
    if len(files) < num_files:
        return []
    # Sort chronologically
    files.sort(key=os.path.getctime)
    return files[-num_files:]

if __name__ == "__main__":
    # Test script on actual ingestion outputs
    base_dir = os.path.dirname(os.path.abspath(__file__))
    insat_dir = os.path.join(base_dir, '..', 'data', 'insat')
    dwr_dir = os.path.join(base_dir, '..', 'data', 'dwr_proxy')
    
    insat_files = get_latest_consecutive_files(insat_dir)
    if insat_files:
        print(f"Processing INSAT files: {insat_files}")
        feats = process_frames(insat_files)
        print("INSAT Temp Rate min/max:", np.min(feats['temporal_rate']), np.max(feats['temporal_rate']))
        print("INSAT Texture Var mean:", np.mean(feats['texture_variance']))
        
    dwr_files = get_latest_consecutive_files(dwr_dir)
    if dwr_files:
        print(f"Processing DWR files: {dwr_files}")
        feats = process_frames(dwr_files)
        print("DWR Rate min/max:", np.min(feats['temporal_rate']), np.max(feats['temporal_rate']))
        print("DWR Texture Var mean:", np.mean(feats['texture_variance']))
