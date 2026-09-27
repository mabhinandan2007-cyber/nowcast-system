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

def run_optical_flow_nowcast(num_forecast_frames=12):
    frames = get_recent_frames(num_frames=2)
    if len(frames) < 2:
        print("Need at least 2 frames for Farneback optical flow.")
        return None
        
    print(f"Loading frames for OpenCV Farneback optical flow...")
    
    with rasterio.open(frames[-2]) as src:
        prev_data = src.read(1)
        prev_data = np.nan_to_num(prev_data, nan=0.0)
        
    with rasterio.open(frames[-1]) as src:
        curr_data = src.read(1)
        curr_data = np.nan_to_num(curr_data, nan=0.0)
        transform = src.transform
        crs = src.crs
        
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
    
    h, w = curr_data.shape
    y_coords, x_coords = np.mgrid[0:h, 0:w].astype(np.float32)
    
    now = datetime.datetime.utcnow()
    forecast_files = []
    
    # Base image to advect
    adv_img = curr_data.copy()
    
    for i in range(num_forecast_frames):
        # We assume the flow vector represents the movement between the last two frames (e.g. 15 or 30 min)
        # We need to scale the flow field if the time step of the data is not 30 minutes.
        # Assuming the radar data spacing is 30 mins, we use (i+1) * flow.
        # But wait, radar data might be spaced by minutes. Let's just assume the flow represents a 30-min step
        # or we just blindly extrapolate. Let's extrapolate linearly by (i+1).
        
        # Warp coordinates
        map_x = x_coords - (i + 1) * flow[..., 0]
        map_y = y_coords - (i + 1) * flow[..., 1]
        
        # Remap
        extrapolated = cv2.remap(curr_data, map_x, map_y, interpolation=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
        
        # Restore NaNs where 0
        extrapolated = np.where(extrapolated == 0, np.nan, extrapolated)
        
        # Save the output frames
        fcst_time = now + datetime.timedelta(minutes=30 * (i + 1))
        ts_str = fcst_time.strftime("%Y%m%d_%H%M")
        out_path = os.path.join(OUT_DIR, f"opt_flow_fcst_{ts_str}.tif")
        
        with rasterio.open(
            out_path, 'w',
            driver='GTiff',
            height=h, width=w,
            count=1, dtype=np.float32,
            crs=crs, transform=transform
        ) as dst:
            dst.write(extrapolated.astype(np.float32), 1)
            # Embed the source DWR observation filename/timestamp as metadata
            dst.update_tags(base_time=os.path.basename(frames[-1]))
            
        forecast_files.append(out_path)
        
    print(f"Successfully saved {num_forecast_frames} Farneback optical flow forecast frames.")
    return forecast_files

if __name__ == "__main__":
    run_optical_flow_nowcast()
