"""
NOTE: This is a custom Farneback-based advection nowcast (same methodological 
family as PySteps' extrapolation method). It replaces the PySteps library 
because PySteps requires a local C++ build toolchain (for its Cython extensions) 
that is not available on this machine.
"""

import os
import glob
import datetime
import numpy as np
import rasterio
import cv2

base_dir = os.path.dirname(os.path.abspath(__file__))
DWR_DIR = os.path.join(base_dir, '..', 'data', 'dwr_proxy')
OUT_DIR = os.path.join(base_dir, '..', 'data', 'nowcast_optical_flow')

def get_recent_frames(num_frames=2):
    files = glob.glob(os.path.join(DWR_DIR, "*.tif"))
    files.sort(key=os.path.getctime)
    return files[-num_frames:]

def run_optical_flow_nowcast(num_forecast_frames=12, input_frames=None, out_dir=None):
    if input_frames is None:
        frames = get_recent_frames(num_frames=2)
    else:
        frames = input_frames
        
    if out_dir is None:
        out_dir = OUT_DIR
        
    os.makedirs(out_dir, exist_ok=True)
    
    if len(frames) < 2:
        print("Need at least 2 frames for Farneback optical flow.")
        return None
        
    print(f"Loading frames for OpenCV Farneback optical flow...")
    
    with rasterio.open(frames[-2]) as src:
        prev_data = src.read(1)
        prev_data = np.nan_to_num(prev_data, nan=0.0)
        from timing import get_base_time
        prev_dt, _ = get_base_time(frames[-2])
        
    with rasterio.open(frames[-1]) as src:
        curr_data_raw = src.read(1)
        curr_data = np.nan_to_num(curr_data_raw, nan=0.0)
        transform = src.transform
        crs = src.crs
        curr_dt, iso_base_time = get_base_time(frames[-1])
        
    # Calculate true time gap between frames in minutes
    actual_gap_minutes = (curr_dt - prev_dt).total_seconds() / 60.0
    if actual_gap_minutes <= 0:
        actual_gap_minutes = 5.0 # fallback if times are identical or inverted
        
    # OpenCV Optical flow expects 8-bit images or 32-bit floats
    # Reflectivity usually 0-60 dBZ, normalize to 0-255 for better flow estimation
    norm_prev = np.clip(prev_data * (255.0 / 60.0), 0, 255).astype(np.uint8)
    norm_curr = np.clip(curr_data * (255.0 / 60.0), 0, 255).astype(np.uint8)
    
    # 1. Estimate motion field using Farneback
    print("Estimating motion field (Farneback)...")
    flow = cv2.calcOpticalFlowFarneback(
        norm_prev, norm_curr, None, 
        pyr_scale=0.5, levels=3, winsize=15, 
        iterations=3, poly_n=5, poly_sigma=1.2, flags=0
    )
    
    # 2. Extrapolate forward
    print(f"Extrapolating {num_forecast_frames} frames (6 hours at 30-min intervals)...")
    print(f"Input frames were {actual_gap_minutes:.1f} minutes apart. Scaling flow field accordingly.")
    
    h, w = curr_data.shape
    y_coords, x_coords = np.mgrid[0:h, 0:w].astype(np.float32)
    
    forecast_files = []
        
    for i in range(num_forecast_frames):
        target_minutes_ahead = 30 * (i + 1)
        flow_multiplier = target_minutes_ahead / actual_gap_minutes
        
        # Warp coordinates
        map_x = x_coords - flow_multiplier * flow[..., 0]
        map_y = y_coords - flow_multiplier * flow[..., 1]
        
        # Remap using the RAW array (which contains true NaNs) and set out-of-bounds to NaN
        extrapolated = cv2.remap(curr_data_raw, map_x, map_y, interpolation=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=np.nan)
        
        # Save the output frames
        base_dt = curr_dt
        fcst_time = base_dt + datetime.timedelta(minutes=30 * (i + 1))
        ts_str = fcst_time.strftime("%Y%m%d_%H%M")
        out_path = os.path.join(out_dir, f"opt_flow_fcst_{ts_str}.tif")
        
        with rasterio.open(
            out_path, 'w',
            driver='GTiff',
            height=h, width=w,
            count=1, dtype=np.float32,
            crs=crs, transform=transform,
            nodata=np.nan
        ) as dst:
            dst.write(extrapolated.astype(np.float32), 1)
            dst.update_tags(base_time=iso_base_time)
            
        forecast_files.append(out_path)
        
    print(f"Successfully saved {num_forecast_frames} Farneback optical flow forecast frames.")
    return forecast_files

if __name__ == "__main__":
    run_optical_flow_nowcast()
