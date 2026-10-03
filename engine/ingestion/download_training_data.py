import os
import argparse
import nexradaws
from datetime import datetime

def download_data(station, date_str, base_dir="D:/SIH_Data/training_raw"):
    # Parse date
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    
    # Initialize connection to AWS
    conn = nexradaws.NexradAwsInterface()
    
    # Get available scans for the station and date
    scans = conn.get_avail_scans(dt.year, f"{dt.month:02d}", f"{dt.day:02d}", station)
    print(f"Found {len(scans)} scans for {station} on {date_str}.")
    
    if len(scans) == 0:
        return
        
    # Create target directory
    target_dir = os.path.join(base_dir, f"{station}_{dt.strftime('%Y%m%d')}")
    os.makedirs(target_dir, exist_ok=True)
    print(f"Downloading to {target_dir}...")
    
    # Download
    results = conn.download(scans, target_dir, threads=20)
    print(f"Successfully downloaded {results.success_count} files.")
    if results.failed_count > 0:
        print(f"Failed to download {results.failed_count} files.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Download NEXRAD archive data for training.")
    parser.add_argument("--station", type=str, default="KTLX", help="NEXRAD station code (e.g., KTLX)")
    parser.add_argument("--date", type=str, required=True, help="Date in YYYY-MM-DD format")
    parser.add_argument("--dir", type=str, default="D:/SIH_Data/training_raw", help="Base download directory")
    args = parser.parse_args()
    
    download_data(args.station, args.date, args.dir)
