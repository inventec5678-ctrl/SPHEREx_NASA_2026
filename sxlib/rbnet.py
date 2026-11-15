"""Real/bogus CNN definition + inference helper.

The layer names (b1, b2, b3, head) and shapes are those of the trained checkpoint models/rb_cnn.pt: do not rename.
"""
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

STAMP_CHANNELS = 4      # sci, ref, S/N, catalogue/ghost mask (sxlib.detect.CHANNELS)
WIDTH = 32
BATCH = 4096


class RBNet(nn.Module):
    """~0.3M-parameter CNN for 4x21x21 stamps (sci, ref, S/N, catalogue/ghost mask)."""

    def __init__(self, cin=STAMP_CHANNELS, w=WIDTH):
        super().__init__()

        def block(a, b):
            return nn.Sequential(nn.Conv2d(a, b, 3, padding=1), nn.BatchNorm2d(b), nn.ReLU(inplace=True),
                                 nn.Conv2d(b, b, 3, padding=1), nn.BatchNorm2d(b), nn.ReLU(inplace=True))
        self.b1, self.b2, self.b3 = block(cin, w), block(w, 2 * w), block(2 * w, 4 * w)
        self.head = nn.Sequential(nn.Linear(8 * w, 128), nn.ReLU(inplace=True), nn.Dropout(0.3), nn.Linear(128, 1))

    def forward(self, x):
        x = F.max_pool2d(self.b1(x), 2)       # 21 -> 10
        x = F.max_pool2d(self.b2(x), 2)       # 10 -> 5
        x = self.b3(x)
        x = torch.cat([x.mean((2, 3)), x.amax((2, 3))], 1)
        return self.head(x).squeeze(1)


def _sigmoid(z):
    return 1 / (1 + np.exp(-z))


class Scorer:
    """Loads models/rb_cnn.pt; returns calibrated (temperature-scaled) probabilities for stamps."""

    def __init__(self, path, device=None):
        self.dev = device or ("cuda" if torch.cuda.is_available() else "cpu")
        ck = torch.load(path, map_location=self.dev)
        self.model = RBNet().to(self.dev).eval()
        self.model.load_state_dict(ck["state"])
        self.T = float(ck["temperature"])
        self.thr_logit = float(ck["threshold_logit"])
        self.thr_prob = float(_sigmoid(self.thr_logit))

    @torch.inference_mode()
    def __call__(self, stamps, bs=BATCH):
        n = len(stamps)
        if not n:
            return _sigmoid(np.zeros(0))
        logit = np.empty(n, np.float32)
        for i in range(0, n, bs):
            x = torch.from_numpy(np.ascontiguousarray(stamps[i:i + bs], np.float32)).to(self.dev)
            logit[i:i + bs] = self.model(x).float().cpu().numpy()
        return _sigmoid(logit / self.T)
