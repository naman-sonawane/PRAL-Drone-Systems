"""
stage4_interest_map.py

Demonstrates the Stage 4a0 → 4a pipeline on a single posed image:
  1. SAM 2 center-point prompt  → foreground mask
  2. DINO v2 attention          → per-pixel interest map
  3. Mask applied               → background zeroed
  4. Overlay saved              → pipeline/data/interest_map_<frame>.jpg

Run:
    python3.12 pipeline/stage4_interest_map.py
    python3.12 pipeline/stage4_interest_map.py stage4data/M60/00220.jpg

Requires: torch, transformers, sam2, opencv-python, numpy, pillow
"""

import os
import sys
import numpy as np
import cv2
from PIL import Image

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
DEFAULT_IMG = "stage4data/M60/00001.jpg"
IMG_PATH = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_IMG

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
DATA_DIR = os.path.join(SCRIPT_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)

img_full_path = os.path.join(PROJECT_ROOT, IMG_PATH)
frame_name = os.path.splitext(os.path.basename(IMG_PATH))[0]
OUT_PATH = os.path.join(DATA_DIR, f"interest_map_{frame_name}.jpg")

# ---------------------------------------------------------------------------
# Device
# ---------------------------------------------------------------------------
import torch
if torch.cuda.is_available():
    device = torch.device("cuda")
elif torch.backends.mps.is_available():
    device = torch.device("mps")
else:
    device = torch.device("cpu")
print(f"Device: {device}")

# ---------------------------------------------------------------------------
# Load image
# ---------------------------------------------------------------------------
img_bgr = cv2.imread(img_full_path)
if img_bgr is None:
    print(f"ERROR: could not read {img_full_path}")
    sys.exit(1)
img_rgb = img_bgr[:, :, ::-1].copy()
H, W = img_bgr.shape[:2]
print(f"Image: {IMG_PATH}  ({W}x{H})")

# ---------------------------------------------------------------------------
# Step 4a0 — SAM 2 foreground mask (center-point prompt)
# ---------------------------------------------------------------------------
print("Running SAM 2 ...")
try:
    from sam2.sam2_image_predictor import SAM2ImagePredictor

    predictor = SAM2ImagePredictor.from_pretrained("facebook/sam2-hiera-large")

    with torch.inference_mode():
        predictor.set_image(img_rgb)
        masks, scores, _ = predictor.predict(
            point_coords=np.array([[W // 2, H // 2]]),
            point_labels=np.array([1]),   # 1 = foreground
            multimask_output=True,
        )
    mask = masks[np.argmax(scores)]   # (H, W) bool
    print(f"  SAM 2 mask: {mask.sum()} / {H * W} pixels ({mask.mean() * 100:.1f}% foreground)")

except Exception as e:
    print(f"  SAM 2 unavailable ({e}), using full-frame fallback mask")
    mask = np.ones((H, W), dtype=bool)

# ---------------------------------------------------------------------------
# Step 4a — DINO v2 interest map
# ---------------------------------------------------------------------------
print("Running DINO v2 ...")
from transformers import AutoImageProcessor, AutoModel

processor = AutoImageProcessor.from_pretrained("facebook/dinov2-base")
model = AutoModel.from_pretrained("facebook/dinov2-base").to(device).eval()

inputs = processor(images=Image.fromarray(img_rgb), return_tensors="pt").to(device)

with torch.no_grad():
    outputs = model(**inputs, output_attentions=True)

# Last-layer CLS attention averaged over heads -> patch grid
attn = outputs.attentions[-1][0]          # (heads, N+1, N+1)
cls_attn = attn[:, 0, 1:].mean(dim=0)    # (N,)
patch_h = inputs["pixel_values"].shape[2] // model.config.patch_size
patch_w = inputs["pixel_values"].shape[3] // model.config.patch_size
attn_map = cls_attn.reshape(patch_h, patch_w).cpu().numpy()

# Upsample to original resolution
attn_up = cv2.resize(attn_map, (W, H), interpolation=cv2.INTER_LINEAR)

# Normalize to [0, 1]
attn_up = (attn_up - attn_up.min()) / (attn_up.max() - attn_up.min() + 1e-8)

# Apply SAM 2 mask: zero out background
attn_up[~mask] = 0.0
print(f"  Interest map: min={attn_up[mask].min():.3f}  max={attn_up[mask].max():.3f}  "
      f"mean={attn_up[mask].mean():.3f}  (masked to foreground)")

# ---------------------------------------------------------------------------
# Save outputs
# ---------------------------------------------------------------------------

# 1. Heat overlay: original frame + jet colormap blended
heatmap = cv2.applyColorMap((attn_up * 255).astype(np.uint8), cv2.COLORMAP_JET)
# Black out heatmap where mask is False so background stays dark
heatmap[~mask] = 0
overlay = cv2.addWeighted(img_bgr, 0.5, heatmap, 0.5, 0)

# 2. Draw SAM 2 mask outline in white
mask_u8 = mask.astype(np.uint8) * 255
contours, _ = cv2.findContours(mask_u8, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
cv2.drawContours(overlay, contours, -1, (255, 255, 255), 2)

# 3. Mark center point used for SAM 2 prompt
cv2.circle(overlay, (W // 2, H // 2), 8, (0, 255, 255), -1)

cv2.imwrite(OUT_PATH, overlay)
print(f"Saved: {OUT_PATH}")
print("Legend: red=high interest  blue=low interest  white outline=SAM2 mask  cyan dot=prompt point")
