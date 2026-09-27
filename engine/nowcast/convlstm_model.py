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
    def __init__(self, in_channels=1, hidden_dim=16, kernel_size=(3,3), out_frames=12):
        super(NowcastConvLSTM, self).__init__()
        self.out_frames = out_frames
        
        # Encoder cell
        self.encoder_cell = ConvLSTMCell(input_dim=in_channels, hidden_dim=hidden_dim, kernel_size=kernel_size, bias=True)
        # Decoder cell
        self.decoder_cell = ConvLSTMCell(input_dim=hidden_dim, hidden_dim=hidden_dim, kernel_size=kernel_size, bias=True)
        
        self.out_conv = nn.Conv2d(in_channels=hidden_dim, out_channels=in_channels, kernel_size=1)
        
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

def build_synthetic_dataset(num_seqs=50, seq_in=3, seq_out=12, img_size=(128, 128)):
    X, Y = [], []
    for _ in range(num_seqs):
        x_seq, y_seq = create_synthetic_sequence(seq_in, seq_out, img_size)
        X.append(x_seq[:, np.newaxis, :, :])
        Y.append(y_seq[:, np.newaxis, :, :])
        
    return torch.tensor(np.array(X), dtype=torch.float32), torch.tensor(np.array(Y), dtype=torch.float32)

def weighted_mse_loss(pred, target):
    # Upweight pixels that have actual storm data in the target
    # target is normalized [0, 1]. Let's weight pixels > 0.1 (6 dBZ) higher.
    weight = torch.ones_like(target)
    weight[target > 0.1] = 10.0  # 10x penalty for missing storm pixels
    
    loss = weight * (pred - target) ** 2
    return loss.mean()

def train_convlstm():
    print("Initializing ConvLSTM Model...")
    base_dir = os.path.dirname(os.path.abspath(__file__))
    model_dir = os.path.join(base_dir, 'models')
    os.makedirs(model_dir, exist_ok=True)
    
    model = NowcastConvLSTM(in_channels=1, hidden_dim=16, out_frames=12)
    # Moved to GPU if available, else CPU (for this env likely CPU is fine)
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    model = model.to(device)
    
    optimizer = torch.optim.Adam(model.parameters(), lr=0.005)
    
    print("Building synthetic dataset (50 sequences of moving blobs)...")
    X_train, y_train = build_synthetic_dataset(num_seqs=50)
    
    # Use DataLoader for batching
    dataset = torch.utils.data.TensorDataset(X_train, y_train)
    dataloader = torch.utils.data.DataLoader(dataset, batch_size=4, shuffle=True)
    
    print(f"Training Data Shape: X={X_train.shape}, Y={y_train.shape}")
    
    print("Running training loop (10 epochs)...")
    model.train()
    
    for epoch in range(10):
        epoch_loss = 0.0
        for batch_X, batch_y in dataloader:
            batch_X, batch_y = batch_X.to(device), batch_y.to(device)
            
            optimizer.zero_grad()
            output = model(batch_X)
            
            loss = weighted_mse_loss(output, batch_y)
            loss.backward()
            optimizer.step()
            
            epoch_loss += loss.item()
            
        print(f"Epoch {epoch+1}/10 - Avg Loss: {epoch_loss / len(dataloader):.4f}")
        
    out_path = os.path.join(model_dir, 'convlstm.pt')
    torch.save(model.state_dict(), out_path)
    print(f"ConvLSTM weights saved to {out_path}")

def run_convlstm_inference(num_forecast_frames=12, target_size=(128, 128)):
    # Load model
    base_dir = os.path.dirname(os.path.abspath(__file__))
    dwr_dir = os.path.join(base_dir, '..', 'data', 'dwr_proxy')
    model_path = os.path.join(base_dir, 'models', 'convlstm.pt')
    
    if not os.path.exists(model_path):
        print("ConvLSTM weights not found. Train first.")
        return None
        
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    model = NowcastConvLSTM(in_channels=1, hidden_dim=16, out_frames=num_forecast_frames)
    model.load_state_dict(torch.load(model_path, map_location=device))
    model = model.to(device)
    model.eval()
    
    import cv2
    files = glob.glob(os.path.join(dwr_dir, '*.tif'))
    files.sort(key=os.path.getctime)
    if len(files) == 0:
        return None
        
    # Read the latest 3 files to give a sequence, not just repeating 1
    recent_files = files[-3:]
    # If we have less than 3, just pad with the first one
    while len(recent_files) < 3:
        recent_files.insert(0, recent_files[0])
        
    x_seq = []
    for f in recent_files:
        with rasterio.open(f) as src:
            img = src.read(1)
            img = np.nan_to_num(img)
            img = cv2.resize(img, target_size)
            # Normalize input
            img = np.clip(img, 0, 60) / 60.0
            x_seq.append(img)
            
    x_tensor = torch.tensor(np.array(x_seq), dtype=torch.float32).unsqueeze(0).unsqueeze(2) # (1, 3, 1, H, W)
    x_tensor = x_tensor.to(device)
    
    print("Running ConvLSTM inference...")
    with torch.no_grad():
        preds = model(x_tensor)
        
    preds = preds.squeeze(0).squeeze(1).cpu().numpy() # (12, H, W)
    
    # Denormalize
    preds = preds * 60.0
    
    # Output stats
    print(f"ConvLSTM inference produced {len(preds)} frames.")
    print(f"Raw Output Tensor Stats (after denorm) - Min: {np.min(preds):.4f}, Max: {np.max(preds):.4f}, Mean: {np.mean(preds):.4f}")
    
    return preds

if __name__ == "__main__":
    train_convlstm()
