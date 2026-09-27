import os
import json
import datetime
import numpy as np
import joblib
import rasterio
from features import process_frames, get_latest_consecutive_files

def run_inference():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    model_path = os.path.join(base_dir, 'models', 'ci_classifier.pkl')
    insat_dir = os.path.join(base_dir, '..', 'data', 'insat')
    out_dir = os.path.join(base_dir, '..', 'data', 'convective_initiation')
    
    if not os.path.exists(model_path):
        print(f"Model not found at {model_path}. Please train first.")
        return
        
    clf = joblib.load(model_path)
    
    files = get_latest_consecutive_files(insat_dir, num_files=2)
    if len(files) < 2:
        print("Not enough frames to run detection inference.")
        return
        
    print(f"Running CI detection on latest frames: {files}")
    feats = process_frames(files)
    
    v = feats['value'].flatten()
    r = feats['temporal_rate'].flatten()
    t = feats['texture_variance'].flatten()
    
    valid = ~np.isnan(v) & ~np.isnan(r) & ~np.isnan(t)
    
    X = np.column_stack((v[valid], r[valid], t[valid]))
    
    # Predict probabilities
    probs = clf.predict_proba(X)[:, 1]
    
    # Reconstruct 2D grid
    prob_grid = np.zeros_like(v)
    prob_grid[valid] = probs
    prob_grid = prob_grid.reshape(feats['shape'])
    
    # Threshold for GeoJSON extraction
    # Using 0.5 as standard binary threshold
    y_coords, x_coords = np.where(prob_grid > 0.5)
    
    features_list = []
    transform = feats['transform']
    
    # Limit to top 500 points to keep GeoJSON small
    if len(y_coords) > 0:
        # Sort by highest probability
        high_prob_indices = np.argsort(prob_grid[y_coords, x_coords])[::-1]
        top_indices = high_prob_indices[:500]
        
        for idx in top_indices:
            y_c, x_c = y_coords[idx], x_coords[idx]
            lon, lat = rasterio.transform.xy(transform, y_c, x_c)
            prob = float(prob_grid[y_c, x_c])
            
            features_list.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [lon, lat]},
                "properties": {
                    "confidence": prob,
                    "cooling_rate": float(feats['temporal_rate'][y_c, x_c]),
                    "texture_variance": float(feats['texture_variance'][y_c, x_c]),
                    "timestamp": datetime.datetime.utcnow().isoformat()
                }
            })
            
    geojson = {
        "type": "FeatureCollection",
        "features": features_list
    }
    
    timestamp = datetime.datetime.utcnow().strftime("%Y%m%d_%H%M")
    output_filename = f"ci_detections_{timestamp}.geojson"
    output_path = os.path.join(out_dir, output_filename)
    
    with open(output_path, 'w') as f:
        json.dump(geojson, f, indent=2)
        
    print(f"Detection complete. Saved {len(features_list)} CI points to {output_path}")

if __name__ == "__main__":
    run_inference()
