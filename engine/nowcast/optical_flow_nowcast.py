import os
import glob
import datetime
import numpy as np
import rasterio
import matplotlib.pyplot as plt

try:
    import pysteps
    from pysteps.motion.lucaskanade import dense_lucaskanade
    from pysteps.nowcasts.extrapolation import forecast
    HAS_PYSTEPS = True
except ImportError as e:
    HAS_PYSTEPS = False
    print(f"PySteps import error: {e}")

base_dir = os.path.dirname(os.path.abspath(__file__))
DWR_DIR = os.path.join(base_dir, '..', 'data', 'dwr_proxy')
OUT_DIR = os.path.join(base_dir, '..', 'data', 'nowcast_optical_flow')

def get_recent_frames(num_frames=3):
    files = glob.glob(os.path.join(DWR_DIR, "*.tif"))
    files.sort(key=os.path.getctime)
    return files[-num_frames:]

def run_optical_flow_nowcast(num_forecast_frames=12):
    if not HAS_PYSTEPS:
        print("Error: PySteps is not installed. Cannot run optical flow.")
        return None
        
    frames = get_recent_frames(num_frames=3)
    if len(frames) < 2:
        print("Need at least 2 frames for optical flow.")
        return None
        
    print(f"Loading {len(frames)} frames for PySteps optical flow...")
    
    data_list = []
    transform = None
    crs = None
    
    for f in frames:
        with rasterio.open(f) as src:
            data = src.read(1)
            # pysteps expects missing data as nan, and typically needs dBZ or dBR
            data = np.where(data <= 0, np.nan, data)
            data_list.append(data)
            transform = src.transform
            crs = src.crs
            
    # PySteps expects shape (time, y, x)
    precip_seq = np.stack(data_list)
    
    # Fill Nans with 0 for optical flow calculation
    precip_seq_filled = np.nan_to_num(precip_seq, nan=0.0)
    
    # 1. Estimate motion field using Lucas-Kanade
    print("Estimating motion field (Lucas-Kanade)...")
    motion_field = dense_lucaskanade(precip_seq_filled)
    
    # 2. Extrapolate forward
    print(f"Extrapolating {num_forecast_frames} frames (6 hours at 30-min intervals)...")
    # extrapolation.forecast expects the most recent precipitation frame
    extrapolated = forecast(
        precip_seq_filled[-1],
        motion_field,
        num_timesteps=num_forecast_frames
    )
    
    # Restore NaNs where 0
    extrapolated = np.where(extrapolated == 0, np.nan, extrapolated)
    
    # Save the output frames
    now = datetime.datetime.utcnow()
    forecast_files = []
    
    for i in range(num_forecast_frames):
        # 30-minute intervals
        fcst_time = now + datetime.timedelta(minutes=30 * (i + 1))
        ts_str = fcst_time.strftime("%Y%m%d_%H%M")
        out_path = os.path.join(OUT_DIR, f"opt_flow_fcst_{ts_str}.tif")
        
        with rasterio.open(
            out_path, 'w',
            driver='GTiff',
            height=extrapolated.shape[1], width=extrapolated.shape[2],
            count=1, dtype=np.float32,
            crs=crs, transform=transform
        ) as dst:
            dst.write(extrapolated[i].astype(np.float32), 1)
            
        forecast_files.append(out_path)
        
    print(f"Successfully saved {num_forecast_frames} PySteps optical flow forecast frames.")
    return forecast_files

if __name__ == "__main__":
    run_optical_flow_nowcast()
