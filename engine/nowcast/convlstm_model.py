import os
import glob
import numpy as np
import torch
import torch.nn as nn
import rasterio

# --- ConvLSTM Cell Implementation ---
class ConvLSTMCell(nn.Module):
    def __init__(self, input_dim, hidden_dim, kernel_size, bias):
        super(ConvLSTMCell, self).__init__()
        
        self.input_dim = input_dim
        self.hidden_dim = hidden_dim
        self.padding = kernel_size[0] // 2, kernel_size[1] // 2
        
        self.conv = nn.Conv2d(
            in_channels=self.input_dim + self.hidden_dim,
            out_channels=4 * self.hidden_dim,
            kernel_size=kernel_size,
            padding=self.padding,
            bias=bias
        )
        
    def forward(self, input_tensor, cur_state):
        h_cur, c_cur = cur_state
        combined = torch.cat([input_tensor, h_cur], dim=1)
        combined_conv = self.conv(combined)
        cc_i, cc_f, cc_o, cc_g = torch.split(combined_conv, self.hidden_dim, dim=1)
        
        i = torch.sigmoid(cc_i)
        f = torch.sigmoid(cc_f)
        o = torch.sigmoid(cc_o)
        g = torch.tanh(cc_g)
        
        c_next = f * c_cur + i * g
        h_next = o * torch.tanh(c_next)
        
        return h_next, c_next
        
    def init_hidden(self, batch_size, image_size):
        height, width = image_size
        return (torch.zeros(batch_size, self.hidden_dim, height, width, device=self.conv.weight.device),
                torch.zeros(batch_size, self.hidden_dim, height, width, device=self.conv.weight.device))

# --- Encoder-Decoder ConvLSTM Architecture ---
class NowcastConvLSTM(nn.Module):
    def __init__(self, in_channels=2, hidden_dim=16, kernel_size=(3,3), out_frames=12):
        super(NowcastConvLSTM, self).__init__()
        self.out_frames = out_frames
        
        # Encoder cell
        self.encoder_cell = ConvLSTMCell(input_dim=in_channels, hidden_dim=hidden_dim, kernel_size=kernel_size, bias=True)
        # Decoder cell
        self.decoder_cell = ConvLSTMCell(input_dim=hidden_dim, hidden_dim=hidden_dim, kernel_size=kernel_size, bias=True)
        
        self.out_conv = nn.Conv2d(in_channels=hidden_dim, out_channels=1, kernel_size=1)
        
    def forward(self, x, teacher_forcing=False, target=None):
        # x shape: (B, T_in, C, H, W)
        b, seq_len, _, h, w = x.size()
        
        h_t, c_t = self.encoder_cell.init_hidden(b, (h, w))
        
        # Encode
        for t in range(seq_len):
            h_t, c_t = self.encoder_cell(x[:, t, :, :, :], (h_t, c_t))
            
        # Decode
        outputs = []
        decoder_input = h_t
        h_t2, c_t2 = self.decoder_cell.init_hidden(b, (h, w))
        
        for t in range(self.out_frames):
            h_t2, c_t2 = self.decoder_cell(decoder_input, (h_t2, c_t2))
            pred = torch.sigmoid(self.out_conv(h_t2))
            outputs.append(pred)
            
            # Simple recurrent input (feed output back)
            # In a real model, we might use a CNN to embed the prediction first, 
            # but for simplicity we just feed the hidden state forward
            decoder_input = h_t2 
            
        return torch.stack(outputs, dim=1) # (B, T_out, C, H, W)

def create_synthetic_sequence(seq_in=3, seq_out=12, img_size=(128, 128)):
    total_frames = seq_in + seq_out
    seq = []
    
    # Random initial position, velocity, and blob size
    x0, y0 = np.random.uniform(20, 108, 2)
    vx, vy = np.random.uniform(-4, 4, 2)
    sigma = np.random.uniform(8, 15)
    max_dbz = np.random.uniform(30, 60)
    
    xx, yy = np.meshgrid(np.arange(img_size[1]), np.arange(img_size[0]))
    
    for t in range(total_frames):
        # Move blob
        cx = x0 + vx * t
        cy = y0 + vy * t
        
        # Add slight intensity variation over time
        intensity = max_dbz * (1.0 + 0.1 * np.sin(t * 0.5))
        
        # Gaussian blob
        blob = intensity * np.exp(-((xx - cx)**2 + (yy - cy)**2) / (2 * sigma**2))
        
        # Add noise
        noise = np.random.normal(0, 2, img_size)
        frame = blob + noise
        
        # Clip to realistic dBZ
        frame = np.clip(frame, 0, 60)
        seq.append(frame)
        
    seq = np.stack(seq)
    # Normalize to [0, 1]
    seq = seq / 60.0
    
    return seq[:seq_in], seq[seq_in:]

import glob

def build_real_dataset(seq_in=3, seq_out=12, crop_size=128):
    import rasterio
    import os
    X, Y = [], []
    base_dir = 'D:/SIH_Data/training_sequences'
    folders = [os.path.join(base_dir, 'KTLX_20260424'), os.path.join(base_dir, 'KTLX_20260508')]
    
    for folder in folders:
        files = glob.glob(os.path.join(folder, '*.tif'))
        # Sort files to ensure temporal order
        files.sort(key=os.path.getctime)
        if len(files) < seq_in + seq_out:
            continue
            
        for i in range(len(files) - (seq_in + seq_out) + 1):
            window_files = files[i:i + seq_in + seq_out]
            
            with rasterio.open(window_files[0]) as src:
                h, w = src.shape
                
            top = np.random.randint(0, max(1, h - crop_size))
            left = np.random.randint(0, max(1, w - crop_size))
            
            x_seq, y_seq = [], []
            
            for j, f in enumerate(window_files):
                with rasterio.open(f) as src:
                    img = src.read(1)
                    crop_img = img[top:top+crop_size, left:left+crop_size]
                    
                    if j < seq_in:
                        mask = (~np.isnan(crop_img)).astype(np.float32)
                        clean_img = np.nan_to_num(crop_img, nan=0.0)
                        clean_img = np.clip(clean_img, 0, 60) / 60.0
                        x_seq.append(np.stack([clean_img, mask], axis=0))
                    else:
                        # Keep NaNs for loss masking, but normalize valid values
                        target_img = np.clip(crop_img, 0, 60) / 60.0
                        y_seq.append(target_img[np.newaxis, :, :])
                        
            X.append(np.stack(x_seq, axis=0))
            Y.append(np.stack(y_seq, axis=0))
            
    return torch.tensor(np.array(X), dtype=torch.float32), torch.tensor(np.array(Y), dtype=torch.float32)

def build_synthetic_dataset(num_seqs=50, seq_in=3, seq_out=12, img_size=(128, 128)):
    X, Y = [], []
    for _ in range(num_seqs):
        x_seq, y_seq = create_synthetic_sequence(seq_in, seq_out, img_size)
        
        # x_seq is (T, H, W). Add mask channel to make it (T, 2, H, W)
        mask = np.ones_like(x_seq)
        x_seq_2ch = np.stack([x_seq, mask], axis=1)
        
        X.append(x_seq_2ch)
        Y.append(y_seq[:, np.newaxis, :, :])
        
    return torch.tensor(np.array(X), dtype=torch.float32), torch.tensor(np.array(Y), dtype=torch.float32)

def weighted_mse_loss(pred, target_raw):
    valid_mask = ~torch.isnan(target_raw)
    target = torch.nan_to_num(target_raw, nan=0.0)

    weight = torch.ones_like(target)
    weight[target > 0.1] = 10.0
    weight = weight * valid_mask.float()  # zero out contribution from NaN pixels entirely

    loss = weight * (pred - target) ** 2
    # Normalize by valid pixel count, not total pixel count - otherwise a
    # crop that's mostly NaN would misleadingly report a tiny average loss
    return loss.sum() / valid_mask.float().sum().clamp(min=1.0)

def train_convlstm():
    print("Initializing ConvLSTM Model...")
    base_dir = os.path.dirname(os.path.abspath(__file__))
    model_dir = os.path.join(base_dir, 'models')
    os.makedirs(model_dir, exist_ok=True)
    
    model = NowcastConvLSTM(in_channels=2, hidden_dim=16, out_frames=12)
    # Moved to GPU if available, else CPU (for this env likely CPU is fine)
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    model = model.to(device)
    
    optimizer = torch.optim.Adam(model.parameters(), lr=0.005)
    
    print("Building real training dataset from historical sequences...")
    X_train, y_train = build_real_dataset()
    
    # Use DataLoader for batching
    dataset = torch.utils.data.TensorDataset(X_train, y_train)
    dataloader = torch.utils.data.DataLoader(dataset, batch_size=4, shuffle=True)
    
    print(f"Training Data Shape: X={X_train.shape}, Y={y_train.shape}")
    
    print("Running training loop (15 epochs)...")
    model.train()
    
    import time
    for epoch in range(15):
        epoch_start = time.time()
        epoch_loss = 0.0
        for batch_X, batch_y in dataloader:
            batch_X, batch_y = batch_X.to(device), batch_y.to(device)
            
            optimizer.zero_grad()
            output = model(batch_X)
            
            loss = weighted_mse_loss(output, batch_y)
            loss.backward()
            optimizer.step()
            
            epoch_loss += loss.item()
            
        epoch_time = time.time() - epoch_start
        print(f"Epoch {epoch+1}/15 - Avg Loss: {epoch_loss / len(dataloader):.4f} ({epoch_time:.1f}s)")
        
    out_path = os.path.join(model_dir, 'convlstm_real_v1.pt')
    torch.save(model.state_dict(), out_path)
    print(f"ConvLSTM weights saved to {out_path}")

def run_convlstm_inference(num_forecast_frames=12, target_size=None, input_frames=None, out_dir=None, model_name='convlstm.pt'):
    # Load model
    base_dir = os.path.dirname(os.path.abspath(__file__))
    dwr_dir = os.path.join(base_dir, '..', 'data', 'dwr_proxy')
    model_path = os.path.join(base_dir, 'models', model_name)
    
    if out_dir is None:
        out_dir = os.path.join(base_dir, '..', 'data', 'nowcast_convlstm')
    os.makedirs(out_dir, exist_ok=True)
    
    if not os.path.exists(model_path):
        print("ConvLSTM weights not found. Train first.")
        return None
        
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    model = NowcastConvLSTM(in_channels=2, hidden_dim=16, out_frames=num_forecast_frames)
    model.load_state_dict(torch.load(model_path, map_location=device))
    model = model.to(device)
    model.eval()
    
    import cv2
    if input_frames is None:
        files = glob.glob(os.path.join(dwr_dir, '*.tif'))
        files.sort(key=os.path.getctime)
        if len(files) == 0:
            return None
            
        recent_files = files[-3:]
    else:
        recent_files = input_frames
        
    while len(recent_files) < 3:
        recent_files.insert(0, recent_files[0])
        
    x_seq = []
    native_shape = None
    for f in recent_files:
        with rasterio.open(f) as src:
            img = src.read(1)
            if native_shape is None:
                native_shape = img.shape
            
            mask = (~np.isnan(img)).astype(np.float32)
            img = np.nan_to_num(img, nan=0.0)
            
            if target_size is not None and target_size != img.shape:
                img = cv2.resize(img, target_size)
                mask = cv2.resize(mask, target_size)
                mask = (mask > 0.5).astype(np.float32)
                
            # Normalize input
            img = np.clip(img, 0, 60) / 60.0
            
            x_seq.append(np.stack([img, mask], axis=0))
            
    final_shape = target_size if target_size is not None else native_shape
    
    x_tensor = torch.tensor(np.array(x_seq), dtype=torch.float32).unsqueeze(0) # (1, 3, 2, H, W)
    x_tensor = x_tensor.to(device)
    
    print("Running ConvLSTM inference...")
    with torch.no_grad():
        preds = model(x_tensor)
        print("Model Output Tensor Shape:", preds.shape)
        
    preds = preds.squeeze(0).squeeze(1).cpu().numpy() # (12, H, W)
    
    # Denormalize
    preds = preds * 60.0
    
    # Save the output frames to disk
    out_dir = os.path.join(base_dir, '..', 'data', 'nowcast_convlstm')
    os.makedirs(out_dir, exist_ok=True)
    
    import datetime
    from timing import get_base_time
    
    base_dt, iso_base_time = get_base_time(recent_files[-1])
        
    forecast_files = []
    
    for i in range(num_forecast_frames):
        fcst_time = base_dt + datetime.timedelta(minutes=30 * (i + 1))
        ts_str = fcst_time.strftime("%Y%m%d_%H%M")
        out_path = os.path.join(out_dir, f"convlstm_fcst_{ts_str}.tif")
        
        # We need crs/transform from the last input file for geospatial alignment
        with rasterio.open(recent_files[-1]) as src:
            transform = src.transform
            crs = src.crs
            
        # Scale the transform if the output resolution differs from the native resolution
        if final_shape != native_shape:
            scale_y = native_shape[0] / final_shape[0]
            scale_x = native_shape[1] / final_shape[1]
            transform = transform * transform.scale(scale_x, scale_y)
            
        # Saving predictions
        with rasterio.open(
            out_path, 'w',
            driver='GTiff',
            height=final_shape[0], width=final_shape[1],
            count=1, dtype=np.float32,
            crs=crs, transform=transform,
            nodata=np.nan
        ) as dst:
            dst.write(preds[i].astype(np.float32), 1)
            dst.update_tags(base_time=iso_base_time)
            
        forecast_files.append(out_path)
    
    # Output stats
    print(f"ConvLSTM inference produced {len(preds)} frames.")
    print(f"Raw Output Tensor Stats (after denorm) - Min: {np.min(preds):.4f}, Max: {np.max(preds):.4f}, Mean: {np.mean(preds):.4f}")
    
    return forecast_files

if __name__ == "__main__":
    train_convlstm()
