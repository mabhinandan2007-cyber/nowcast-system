import os
import sys
import time
import logging
import schedule
from logging.handlers import RotatingFileHandler

# Add parent dir to path if needed
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import insat_fetch
import dwr_proxy
import lightning_proxy

# Configure logging to file
LOG_DIR = os.path.join(os.path.dirname(__file__), '..', 'logs')
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, 'ingestion.log')

# Setup logger
logger = logging.getLogger("ingestion_orchestrator")
logger.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# File handler
fh = RotatingFileHandler(LOG_FILE, maxBytes=5*1024*1024, backupCount=2)
fh.setFormatter(formatter)
logger.addHandler(fh)

# Console handler
ch = logging.StreamHandler()
ch.setFormatter(formatter)
logger.addHandler(ch)

# Inject file logger into imported modules so they log to the same file
insat_fetch.logger.addHandler(fh)
dwr_proxy.logger.addHandler(fh)
lightning_proxy.logger.addHandler(fh)

def job_insat():
    logger.info("--- Starting INSAT job ---")
    try:
        insat_fetch.fetch_insat_data()
        logger.info("INSAT job completed successfully.")
    except Exception as e:
        logger.error(f"INSAT job failed: {e}", exc_info=True)

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'nowcast'))
try:
    from optical_flow_nowcast import run_optical_flow_nowcast
except ImportError:
    run_optical_flow_nowcast = None

def job_dwr():
    logger.info("--- Starting DWR Proxy job ---")
    try:
        dwr_proxy.fetch_and_process_dwr()
        logger.info("DWR Proxy job completed successfully.")
        
        # Trigger Optical Flow Nowcast if available
        if run_optical_flow_nowcast:
            logger.info("Triggering Optical Flow Nowcast...")
            run_optical_flow_nowcast()
            logger.info("Optical Flow Nowcast completed successfully.")
    except Exception as e:
        logger.error(f"DWR Proxy job failed: {e}", exc_info=True)

def job_lightning():
    logger.info("--- Starting Lightning Proxy job ---")
    try:
        lightning_proxy.generate_lightning_geojson()
        logger.info("Lightning Proxy job completed successfully.")
    except Exception as e:
        logger.error(f"Lightning Proxy job failed: {e}", exc_info=True)

def main():
    logger.info("Initializing Data Ingestion Layer...")
    
    # Run all jobs once immediately for testing/startup
    job_insat()
    job_dwr()
    job_lightning()
    
    # Schedule them
    schedule.every(15).minutes.do(job_insat)
    schedule.every(5).minutes.do(job_dwr)
    schedule.every(1).minutes.do(job_lightning)
    
    logger.info("Scheduler started. Press Ctrl+C to exit.")
    
    # Optional: run scheduler loop if this is deployed as a service
    # For now we'll just do a short test loop or let the user run it once
    # Uncomment for continuous running:
    # while True:
    #     schedule.run_pending()
    #     time.sleep(1)

if __name__ == "__main__":
    main()
