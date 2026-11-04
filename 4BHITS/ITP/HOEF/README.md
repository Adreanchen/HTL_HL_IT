# FLL Robot Game Livestream & YOLOv8 Vision Tracker

## 1. One-Time Setup

Install all Python dependencies (FastAPI backend + OpenCV + CUDA PyTorch + YOLOv8) from the single root [`requirements.txt`](./requirements.txt):

```powershell
pip install -r requirements.txt
```

*(Frontend `node_modules` are installed automatically the first time you run `python run.py`.)*

---

## 2. Run Everything with One Command

From this root folder, run:

```powershell
python run.py
```

This single command starts both servers together:
- **Video Wall / OBS Display**: `http://localhost:3000`
- **Phone / PC Match Control & Calibration UI**: `http://<YOUR-PC-IP>:8002`

Press `Ctrl+C` to stop everything at once.

---

## 3. Custom YOLOv8 Robot Training Workflow (Optional)

If you want to train a custom YOLOv8 model (`best.pt`) so the tracker recognizes your specific LEGO robot on the mat while ignoring human hands:

1. **Extract frames from a match video (`.mp4`) into `dataset/raw/`**:
   ```powershell
   python run.py extract --video match.mp4 --interval 10
   ```
2. **Label in Roboflow**:
   Upload `dataset/raw/` to Roboflow, draw bounding boxes around the **`robot`** class only (leave hands/arms unlabeled), and export in **YOLOv8** format into `dataset/` (see [`data.yaml`](./data.yaml)).
3. **Train YOLOv8n for 50 epochs on GPU (`cuda:0`)**:
   ```powershell
   python run.py train
   ```
   *(Automatically saves the trained weights to `best.pt`, which `python run.py` and `3_live_tracking.py` pick up automatically.)*
4. **Test standalone OpenCV live tracking window**:
   ```powershell
   python run.py track
   ```
