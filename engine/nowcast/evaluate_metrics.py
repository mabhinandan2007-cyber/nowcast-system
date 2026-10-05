import os
import glob
import datetime
import numpy as np
import rasterio
import pandas as pd
import matplotlib.pyplot as plt

import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '.')))

from optical_flow_nowcast import run_optical_flow_nowcast
from convlstm_model import run_convlstm_inference
from timing import get_base_time

def calculate_metrics(pred, true, threshold, valid_mask):
    pred_bin = (pred >= threshold) & valid_mask
    true_bin = (true >= threshold) & valid_mask
    
    hits = np.sum(pred_bin & true_bin)
    misses = np.sum(~pred_bin & true_bin & valid_mask)
    false_alarms = np.sum(pred_bin & ~true_bin & valid_mask)
    
    pod = hits / (hits + misses) if (hits + misses) > 0 else np.nan
    far = false_alarms / (hits + false_alarms) if (hits + false_alarms) > 0 else np.nan
    csi = hits / (hits + misses + false_alarms) if (hits + misses + false_alarms) > 0 else np.nan
    
    return pod, far, csi

def find_closest_real_frame(target_time, files_dict, tolerance_minutes=5):
    closest_file = None
    min_diff = datetime.timedelta(minutes=tolerance_minutes + 1)
    
    for ft, path in files_dict.items():
        diff = abs(ft - target_time)
        if diff <= datetime.timedelta(minutes=tolerance_minutes):
            if diff < min_diff:
                min_diff = diff
                closest_file = path
    return closest_file

def evaluate():
    seq_base = "D:/SIH_Data/training_sequences"
    out_dir = os.path.join(os.path.dirname(__file__), '..', 'data', 'evaluation')
    os.makedirs(out_dir, exist_ok=True)
    
    results = []
    thresholds = [20, 30, 40]
    lead_times = [30, 60, 90, 120, 150, 180, 210, 240, 270, 300, 330, 360]
    
    folders = glob.glob(os.path.join(seq_base, "*_*"))
    for folder in folders:
        station_date = os.path.basename(folder)
        files = glob.glob(os.path.join(folder, "*.tif"))
        if len(files) < 4:
            continue
            
        files.sort(key=os.path.getctime)
        
        # Build dictionary of true times
        files_dict = {}
        for f in files:
            try:
                with rasterio.open(f) as src:
                    tags = src.tags()
                    scan_time = tags.get('scan_time')
                    if scan_time:
                        dt = datetime.datetime.fromisoformat(scan_time.replace("Z", "+00:00")).replace(tzinfo=None)
                        files_dict[dt] = f
                    else:
                        print(f"No scan_time tag in {f}")
            except Exception as e:
                print(f"Skipping file {f} for dict: {e}")
                
        # Sorted times
        sorted_times = sorted(files_dict.keys())
        
        # Sliding window
        for i in range(len(sorted_times) - 3):
            t1, t2, t3 = sorted_times[i], sorted_times[i+1], sorted_times[i+2]
            input_files = [files_dict[t1], files_dict[t2], files_dict[t3]]
            
            print(f"Evaluating window ending at {t3}...")
            
            # Predict
            opt_fcsts = run_optical_flow_nowcast(num_forecast_frames=12, input_frames=input_files, out_dir=out_dir)
            conv_fcsts = run_convlstm_inference(num_forecast_frames=12, input_frames=input_files, out_dir=out_dir)
            
            if not opt_fcsts or not conv_fcsts:
                continue
                
            # Persistence: just repeat the last frame
            with rasterio.open(input_files[-1]) as src:
                pers_data = src.read(1)
                
            base_time = t3
            
            for j, lead_min in enumerate(lead_times):
                target_time = base_time + datetime.timedelta(minutes=lead_min)
                real_file = find_closest_real_frame(target_time, files_dict, tolerance_minutes=5)
                
                if not real_file:
                    continue
                    
                with rasterio.open(real_file) as src:
                    true_data = src.read(1)
                    
                with rasterio.open(opt_fcsts[j]) as src:
                    opt_data = src.read(1)
                    
                with rasterio.open(conv_fcsts[j]) as src:
                    conv_data = src.read(1)
                    
                valid_mask = ~np.isnan(true_data) & ~np.isnan(opt_data) & ~np.isnan(conv_data) & ~np.isnan(pers_data)
                valid_fraction = np.sum(valid_mask) / true_data.size if true_data.size > 0 else 0.0
                
                for thresh in thresholds:
                    pod_o, far_o, csi_o = calculate_metrics(opt_data, true_data, thresh, valid_mask)
                    pod_c, far_c, csi_c = calculate_metrics(conv_data, true_data, thresh, valid_mask)
                    pod_p, far_p, csi_p = calculate_metrics(pers_data, true_data, thresh, valid_mask)
                    
                    results.append({
                        "station_date": station_date,
                        "base_time": base_time,
                        "lead_time": lead_min,
                        "threshold": thresh,
                        "method": "Optical Flow",
                        "POD": pod_o, "FAR": far_o, "CSI": csi_o, "valid_pixel_fraction": valid_fraction
                    })
                    results.append({
                        "station_date": station_date,
                        "base_time": base_time,
                        "lead_time": lead_min,
                        "threshold": thresh,
                        "method": "ConvLSTM",
                        "POD": pod_c, "FAR": far_c, "CSI": csi_c, "valid_pixel_fraction": valid_fraction
                    })
                    results.append({
                        "station_date": station_date,
                        "base_time": base_time,
                        "lead_time": lead_min,
                        "threshold": thresh,
                        "method": "Persistence",
                        "POD": pod_p, "FAR": far_p, "CSI": csi_p, "valid_pixel_fraction": valid_fraction
                    })
            
            # Clean up generated forecast files to save space
            for f in opt_fcsts + conv_fcsts:
                try:
                    os.remove(f)
                except:
                    pass

    if len(results) == 0:
        print("No evaluation results generated.")
        return
        
    df = pd.DataFrame(results)
    df.to_csv(os.path.join(out_dir, 'evaluation_metrics.csv'), index=False)
    
    # Plot CSI vs Lead Time
    for thresh in thresholds:
        plt.figure(figsize=(10, 6))
        df_t = df[df['threshold'] == thresh]
        if df_t.empty:
            continue
            
        summary = df_t.groupby(['method', 'lead_time'])['CSI'].mean().unstack(level=0)
        
        for method in summary.columns:
            plt.plot(summary.index, summary[method], marker='o', label=method)
            
        plt.title(f'Average CSI vs Lead Time (Threshold: {thresh} dBZ)')
        plt.xlabel('Lead Time (minutes)')
        plt.ylabel('Critical Success Index (CSI)')
        plt.ylim(0, 1)
        plt.legend()
        plt.grid(True)
        plt.savefig(os.path.join(out_dir, f'csi_vs_lead_time_{thresh}dBZ.png'))
        plt.close()
        
    print(f"Evaluation complete. Results saved to {out_dir}")

if __name__ == "__main__":
    evaluate()
