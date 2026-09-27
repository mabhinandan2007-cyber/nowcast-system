import os
import glob
import numpy as np
import lightgbm as lgb
import joblib
from features import process_frames
from label_generator import generate_heuristic_labels

from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, precision_score, recall_score

def build_dataset():
    """
    Builds a training dataset (X, y) from whatever historical frames exist 
    in /engine/data/. Uses the heuristic labels.
    """
    base_dir = os.path.dirname(os.path.abspath(__file__))
    insat_dir = os.path.join(base_dir, '..', 'data', 'insat')
    
    insat_files = glob.glob(os.path.join(insat_dir, '*.tif'))
    insat_files.sort(key=os.path.getctime)
    
    X_list = []
    y_list = []
    
    total_pixels = 0
    total_positives = 0
    
    # We need pairs of consecutive frames to compute rate
    # For a small demo, we just group them into sliding windows of 2
    for i in range(len(insat_files) - 1):
        pair = insat_files[i:i+2]
        feats = process_frames(pair)
        # Use looser thresholds for the mock data to ensure we get some positive labels
        labels = generate_heuristic_labels(feats, 'insat', cooling_rate_thresh=-5.0, texture_thresh=0.5)
        
        # Flatten and stack features
        # X shape: (num_pixels, 3)
        v = feats['value'].flatten()
        r = feats['temporal_rate'].flatten()
        t = feats['texture_variance'].flatten()
        l = labels.flatten()
        
        # Filter out NaN/invalid
        valid = ~np.isnan(v) & ~np.isnan(r) & ~np.isnan(t)
        
        X_frame = np.column_stack((v[valid], r[valid], t[valid]))
        y_frame = l[valid]
        
        total_pixels += len(y_frame)
        total_positives += np.sum(y_frame)
        
        X_list.append(X_frame)
        y_list.append(y_frame)
        
    print(f"Dataset summary before sampling:")
    print(f"Total valid pixels processed: {total_pixels}")
    print(f"Total positive heuristic labels generated: {total_positives} ({(total_positives/total_pixels*100):.2f}% of total)")
    
    if not X_list:
        return np.array([]), np.array([])
        
    X = np.vstack(X_list)
    y = np.concatenate(y_list)
    
    # Subsample to balance and speed up training (since 500x500 = 250k pixels per frame)
    pos_idx = np.where(y == 1)[0]
    neg_idx = np.where(y == 0)[0]
    
    if len(pos_idx) > 0:
        # Sample negatives equal to positives * 3
        num_neg = min(len(neg_idx), len(pos_idx) * 3)
        neg_sampled = np.random.choice(neg_idx, num_neg, replace=False)
        keep_idx = np.concatenate((pos_idx, neg_sampled))
        np.random.shuffle(keep_idx)
        return X[keep_idx], y[keep_idx]
    
    return X, y

def train_model():
    X, y = build_dataset()
    if len(X) == 0:
        print("No historical pairs found to train on.")
        return
        
    if np.sum(y) == 0:
        print("Warning: No positive CI labels found in the dataset. Adjusting labels dynamically for demo...")
        # Artificially inject some positive labels so LightGBM doesn't fail
        y[:len(y)//10] = 1 

    print(f"\nTraining dataset after subsampling: {len(X)} samples ({np.sum(y)} positives)...")
    
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
    
    clf = lgb.LGBMClassifier(
        n_estimators=100,
        learning_rate=0.05,
        max_depth=5,
        random_state=42
    )
    clf.fit(X_train, y_train)
    
    # Evaluate
    y_pred = clf.predict(X_test)
    print("\n--- Evaluation on 20% Held-out Split ---")
    print(f"Accuracy : {accuracy_score(y_test, y_pred):.4f}")
    print(f"Precision: {precision_score(y_test, y_pred, zero_division=0):.4f}")
    print(f"Recall   : {recall_score(y_test, y_pred, zero_division=0):.4f}")
    
    # Save model
    model_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'models')
    os.makedirs(model_dir, exist_ok=True)
    model_path = os.path.join(model_dir, 'ci_classifier.pkl')
    
    joblib.dump(clf, model_path)
    print(f"Model saved successfully to {model_path}")
    print("Feature importances [Value, Rate, Texture]:", clf.feature_importances_)

if __name__ == "__main__":
    train_model()
