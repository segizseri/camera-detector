import torch
import torch.nn as nn
import os

class ActionLSTM(nn.Module):
    def __init__(self, num_keypoints=17, hidden_dim=64, num_layers=2, num_classes=4):
        super(ActionLSTM, self).__init__()
        # Input shape: (batch_size, seq_len, num_keypoints * 2)
        # 17 keypoints each with (x, y) coordinates
        self.input_dim = num_keypoints * 2
        
        self.lstm = nn.LSTM(
            input_size=self.input_dim,
            hidden_size=hidden_dim,
            num_layers=num_layers,
            batch_first=True,
            dropout=0.2 if num_layers > 1 else 0
        )
        
        self.fc = nn.Sequential(
            nn.Linear(hidden_dim, 32),
            nn.ReLU(),
            nn.Dropout(0.2),
            nn.Linear(32, num_classes)
            # PyTorch CrossEntropyLoss takes raw logits, so no Softmax here.
        )
        
    def forward(self, x):
        lstm_out, (hidden, cell) = self.lstm(x)
        last_hidden = hidden[-1]
        logits = self.fc(last_hidden)
        return logits

def create_or_load_model(weights_path="action_lstm.pt"):
    model = ActionLSTM(num_keypoints=17, hidden_dim=64, num_layers=2, num_classes=5)
    if os.path.exists(weights_path):
        model.load_state_dict(torch.load(weights_path, map_location="cpu"))
        print(f"Loaded AI Action Detector weights from {weights_path}")
    else:
        print(f"Weights {weights_path} not found! Using untrained placeholder weights...")
    
    model.eval()
    return model
