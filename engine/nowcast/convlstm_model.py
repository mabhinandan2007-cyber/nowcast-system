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
            pred = self.out_conv(h_t2)
            outputs.append(pred)
            
            # Simple recurrent input (feed output back)
            # In a real model, we might use a CNN to embed the prediction first, 
            # but for simplicity we just feed the hidden state forward
            decoder_input = h_t2 
            
        return torch.stack(outputs, dim=1) # (B, T_out, C, H, W)

def build_dummy_dataset(dwr_dir, seq_in=3, seq_out=12, img_size=(128, 128)):
    import cv2
    files = glob.glob(os.path.join(dwr_dir, '*.tif'))
    files.sort(key=os.path.getctime)
    
    if len(files) == 0:
        return None
        
    # Just take up to the last N files we need, or repeat the last one to simulate history
    # For a demo training loop, we generate synthetic shifts of the real data
    # so we have enough frames to "train" a single batch.
    
    with rasterio.open(files[-1]) as src:
        base_img = src.read(1)
        base_img = np.nan_to_num(base_img)
        # Resize for ConvLSTM training to fit in memory easily (128x128 for demo)
        base_img = cv2.resize(base_img, img_size)
    
    # Generate shifting sequence
    X = []
    Y = []
    
    # 1 batch for demo
    x_seq = []
    for i in range(seq_in):
        # Shift slightly
        shifted = np.roll(base_img, i*2, axis=1)
        x_seq.append(shifted)
        
    y_seq = []
    for i in range(seq_out):
        shifted = np.roll(base_img, (seq_in + i)*2, axis=1)
        y_seq.append(shifted)
        
    X.append(np.stack(x_seq)[:, np.newaxis, :, :])
    Y.append(np.stack(y_seq)[:, np.newaxis, :, :])
    
    return torch.tensor(np.array(X), dtype=torch.float32), torch.tensor(np.array(Y), dtype=torch.float32)

def train_convlstm():
    print("Initializing ConvLSTM Model...")
    base_dir = os.path.dirname(os.path.abspath(__file__))
    dwr_dir = os.path.join(base_dir, '..', 'data', 'dwr_proxy')
    model_dir = os.path.join(base_dir, 'models')
    os.makedirs(model_dir, exist_ok=True)
    
    # Setup
    model = NowcastConvLSTM(in_channels=1, hidden_dim=8, out_frames=12)
    optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)
    criterion = nn.MSELoss()
    
    dataset = build_dummy_dataset(dwr_dir)
    if dataset is None:
        print("No DWR proxy files found to bootstrap training.")
        return
        
    X_train, y_train = dataset
    print(f"Demo Training Data Shape: X={X_train.shape}, Y={y_train.shape}")
    
    print("Running training loop (5 epochs for demo)...")
    model.train()
    for epoch in range(5):
        optimizer.zero_grad()
        output = model(X_train)
        loss = criterion(output, y_train)
        loss.backward()
        optimizer.step()
        print(f"Epoch {epoch+1}/5 - Loss: {loss.item():.4f}")
        
    out_path = os.path.join(model_dir, 'convlstm.pt')
    torch.save(model.state_dict(), out_path)
    print(f"ConvLSTM weights saved to {out_path}")

def run_convlstm_inference(num_forecast_frames=12, target_size=(128, 128)):
    # Load model
    base_dir = os.path.dirname(os.path.abspath(__file__))
    dwr_dir = os.path.join(base_dir, '..', 'data', 'dwr_proxy')
    out_dir = os.path.join(base_dir, '..', 'data', 'nowcast_comparison')
    model_path = os.path.join(base_dir, 'models', 'convlstm.pt')
    os.makedirs(out_dir, exist_ok=True)
    
    if not os.path.exists(model_path):
        print("ConvLSTM weights not found. Train first.")
        return None
        
    model = NowcastConvLSTM(in_channels=1, hidden_dim=8, out_frames=num_forecast_frames)
    model.load_state_dict(torch.load(model_path))
    model.eval()
    
    import cv2
    files = glob.glob(os.path.join(dwr_dir, '*.tif'))
    files.sort(key=os.path.getctime)
    if len(files) == 0:
        return None
        
    with rasterio.open(files[-1]) as src:
        base_img = src.read(1)
        base_img = np.nan_to_num(base_img)
        input_img = cv2.resize(base_img, target_size)
        
    # Create a sequence of 3 identical inputs just for inference demo
    x_seq = [input_img, input_img, input_img]
    x_tensor = torch.tensor(np.array(x_seq), dtype=torch.float32).unsqueeze(0).unsqueeze(2) # (1, 3, 1, H, W)
    
    print("Running ConvLSTM inference...")
    with torch.no_grad():
        preds = model(x_tensor)
        
    preds = preds.squeeze(0).squeeze(1).numpy() # (12, H, W)
    
    print(f"ConvLSTM inference produced {len(preds)} frames.")
    return preds

if __name__ == "__main__":
    train_convlstm()
