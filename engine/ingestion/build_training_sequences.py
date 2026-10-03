import os
import glob
import datetime
import traceback

import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '.')))
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'nowcast')))

from dwr_proxy import process_nexrad_to_cartesian

def build_sequences(raw_base="D:/SIH_Data/training_raw", seq_base="D:/SIH_Data/training_sequences"):
    folders = glob.glob(os.path.join(raw_base, "*_*"))
    for folder in folders:
        station_date = os.path.basename(folder)
        parts = station_date.split('_')
        if len(parts) != 2:
            continue
        station, date_str = parts[0], parts[1]
        
        target_dir = os.path.join(seq_base, station_date)
        os.makedirs(target_dir, exist_ok=True)
        
        files = glob.glob(os.path.join(folder, "*"))
        # Filter valid nexrad files (no temp extensions, no MDM)
        valid_files = [f for f in files if "MDM" not in f and not os.path.basename(f).split(".")[-1].islower()]
        
        for f in valid_files:
            base_filename = os.path.basename(f)
            # Try to parse time
            try:
                # KTLX20260424_000002_V06
                time_str = base_filename[4:19]
                dt = datetime.datetime.strptime(time_str, "%Y%m%d_%H%M%S")
                timestamp = dt.strftime("%Y%m%d_%H%M")
                scan_time = dt.isoformat() + "Z"
            except:
                print(f"Skipping {f} - couldn't parse time")
                continue
                
            out_name = f"{station}_{timestamp}.tif"
            out_path = os.path.join(target_dir, out_name)
            
            if os.path.exists(out_path):
                continue
                
            print(f"Processing {base_filename} -> {out_name}")
            try:
                process_nexrad_to_cartesian(f, out_path, scan_time, scan_time, station=station)
            except Exception as e:
                print(f"Failed to process {f}: {e}")
                traceback.print_exc()

if __name__ == "__main__":
    build_sequences()
