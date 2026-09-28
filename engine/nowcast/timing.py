import os
import datetime

def get_base_time(path):
    """
    Parses the DWR proxy filename (e.g. dwr_proxy_20260927_1618.tif)
    and returns (base_dt, iso_base_time).
    Raises ValueError if the filename cannot be parsed.
    """
    base_filename = os.path.basename(path)
    
    # Try to extract YYYYMMDD_HHMM
    # Assuming filename format is dwr_proxy_YYYYMMDD_HHMM.tif
    if not base_filename.startswith('dwr_proxy_'):
        raise ValueError(f"Filename {base_filename} does not start with expected prefix 'dwr_proxy_'")
        
    ts_part = base_filename.replace('dwr_proxy_', '').split('.')[0]
    
    try:
        base_dt = datetime.datetime.strptime(ts_part, "%Y%m%d_%H%M")
    except ValueError as e:
        raise ValueError(f"Could not parse timestamp '{ts_part}' from filename '{base_filename}'. Expected YYYYMMDD_HHMM.") from e
        
    iso_base_time = base_dt.isoformat() + "Z"
    return base_dt, iso_base_time
