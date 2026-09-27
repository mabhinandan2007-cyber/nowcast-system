import os
import glob
import numpy as np
import matplotlib.pyplot as plt
import rasterio

from optical_flow_nowcast import run_optical_flow_nowcast
from convlstm_model import run_convlstm_inference

def compare():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    out_dir = os.path.join(base_dir, '..', 'data', 'nowcast_comparison')
    os.makedirs(out_dir, exist_ok=True)
    
    print("Running Optical Flow baseline...")
    opt_files = run_optical_flow_nowcast(num_forecast_frames=12)
    
    print("Running ConvLSTM baseline...")
    conv_preds = run_convlstm_inference(num_forecast_frames=12)
    
    if not opt_files or conv_preds is None:
        print("Missing outputs. Cannot compare.")
        return
        
    # Read optical flow frames (take 1, 6, 12 for +30m, +3h, +6h)
    indices = [0, 5, 11]
    time_labels = ["+30m", "+3h", "+6h"]
    
    opt_frames = []
    for idx in indices:
        if idx < len(opt_files):
            with rasterio.open(opt_files[idx]) as src:
                opt_frames.append(src.read(1))
        else:
            opt_frames.append(np.zeros_like(conv_preds[0]))
            
    conv_frames = [conv_preds[idx] for idx in indices]
    
    fig, axes = plt.subplots(2, 3, figsize=(15, 10))
    fig.suptitle('Nowcast Baseline Comparison: Optical Flow (PySteps) vs ConvLSTM', fontsize=16)
    
    for i, (ax, frame, label) in enumerate(zip(axes[0], opt_frames, time_labels)):
        ax.imshow(frame, cmap='jet', vmin=0, vmax=60)
        ax.set_title(f'Optical Flow {label}')
        ax.axis('off')
        
    for i, (ax, frame, label) in enumerate(zip(axes[1], conv_frames, time_labels)):
        ax.imshow(frame, cmap='jet', vmin=0, vmax=60)
        ax.set_title(f'ConvLSTM {label}')
        ax.axis('off')
        
    plt.tight_layout()
    out_path = os.path.join(out_dir, 'baselines_comparison.png')
    plt.savefig(out_path, dpi=150)
    print(f"Comparison visualization saved to {out_path}")

if __name__ == "__main__":
    compare()
