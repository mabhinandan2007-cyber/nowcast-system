"""
NOTE ON GROUND TRUTH:
This module generates weak/heuristic labels for convective initiation (CI). 
It is a heuristic proxy (based on rapid IR cooling and texture) and NOT 
ground truth. It is used strictly to bootstrap the training pipeline 
until true labelled convective initiation datasets are integrated.
"""

import numpy as np

def generate_heuristic_labels(features, source='insat', cooling_rate_thresh=-16.0, texture_thresh=1.5, refl_rate_thresh=20.0):
    """
    source: 'insat' or 'dwr'
    cooling_rate_thresh: K/hour (e.g. -16 K/hr = -4K/15min)
    texture_thresh: spatial variance threshold
    refl_rate_thresh: dBZ/hour (e.g. +20 dBZ/hr = +5dBZ/15min)
    """
    rate = features['temporal_rate']
    texture = features['texture_variance']
    val = features['value']
    
    # Initialize labels with 0
    labels = np.zeros_like(val, dtype=np.int8)
    
    if source == 'insat':
        # Convective initiation: rapid cooling (negative rate) + high texture + cold clouds
        # Wait, initiation usually starts warmer and gets cold, but let's just use rate & texture.
        ci_mask = (rate < cooling_rate_thresh) & (texture > texture_thresh) & (val < 273.15)
        labels[ci_mask] = 1
    elif source == 'dwr':
        # Convective initiation: rapid reflectivity increase + high texture
        ci_mask = (rate > refl_rate_thresh) & (texture > texture_thresh) & (val > 20.0)
        labels[ci_mask] = 1
        
    return labels

if __name__ == "__main__":
    from features import process_frames, get_latest_consecutive_files
    import os
    base_dir = os.path.dirname(os.path.abspath(__file__))
    insat_dir = os.path.join(base_dir, '..', 'data', 'insat')
    
    files = get_latest_consecutive_files(insat_dir)
    if files:
        feats = process_frames(files)
        # For mock data we might need looser thresholds to get positive labels
        labels = generate_heuristic_labels(feats, 'insat', cooling_rate_thresh=0.0, texture_thresh=0.1)
        print(f"Total positive CI pixels (INSAT): {np.sum(labels)}")
