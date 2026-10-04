import os
import datetime

def get_base_time(path):
    import rasterio
    import re
    try:
        with rasterio.open(path) as src:
            tags = src.tags()
            iso_time = tags.get('scan_time') or tags.get('base_time')
            if iso_time:
                dt = datetime.datetime.fromisoformat(iso_time.replace('Z', '+00:00')).replace(tzinfo=None)
                return dt, iso_time
    except Exception:
        pass
        
    base_filename = os.path.basename(path)
    match = re.search(r"(\d{8}_\d{4})", base_filename)
    if match:
        ts_part = match.group(1)
        base_dt = datetime.datetime.strptime(ts_part, "%Y%m%d_%H%M")
        return base_dt, base_dt.isoformat() + "Z"
        
    raise ValueError(f"Could not parse timestamp from {base_filename} and no scan_time tag.")
