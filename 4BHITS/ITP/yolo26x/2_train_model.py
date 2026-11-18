"""
2_train_model.py
----------------
Fine-tunes a YOLO26x (`yolo26x.pt`) object detection model on a single class ("robot")
using your Roboflow-labeled `data.yaml` dataset for 50 epochs on the GPU (`device='cuda:0'`).

After training completes, the best weights are automatically copied to `./best.pt`
and `./models/best.pt` (and exported to TensorRT FP16 `./best.engine` / `./models/best.engine`
when running on CUDA) so `3_live_tracking.py` can run immediately.

Usage:
    python 2_train_model.py --data data.yaml --epochs 50 --imgsz 1280 --batch 32
"""

import argparse
import os
import shutil
import sys
from pathlib import Path
import torch
from ultralytics import YOLO

DEFAULT_DATA_YAML = "data.yaml"
DEFAULT_BASE_MODEL = "yolo26x.pt"
DEFAULT_EPOCHS = 50
DEFAULT_IMGSZ = 1280
DEFAULT_BATCH = 32
DEFAULT_DEVICE = "auto"


def resolve_training_device(device: str = DEFAULT_DEVICE) -> str:
	"""Validates or auto-detects the best hardware acceleration device (CUDA -> Apple MPS -> CPU)."""
	dev_lower = str(device).strip().lower()
	if dev_lower in ("auto", "default", ""):
		if torch.cuda.is_available():
			dev_lower = "cuda:0"
		elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
			dev_lower = "mps"
		else:
			dev_lower = "cpu"

	if dev_lower.startswith("cuda"):
		if not torch.cuda.is_available():
			print("[WARN] CUDA requested but not available in current PyTorch build. Falling back to CPU.")
			return "cpu"
		gpu_name = torch.cuda.get_device_name(0)
		vram_gb = torch.cuda.get_device_properties(0).total_memory / (1024 ** 3)
		print(f"[GPU] Using {dev_lower} -> {gpu_name} ({vram_gb:.1f} GB VRAM, CUDA {torch.version.cuda})")
		return dev_lower
	elif dev_lower == "mps":
		if not (hasattr(torch.backends, "mps") and torch.backends.mps.is_available()):
			print("[WARN] Apple MPS requested but not available. Falling back to CPU.")
			return "cpu"
		print("[ACCEL] Using Apple Silicon Metal Performance Shaders (MPS).")
		return "mps"
	else:
		print("[INFO] Training on CPU (training may take longer without dedicated GPU acceleration).")
		return "cpu"


def export_tensorrt_engine(
	weights_path: Path,
	imgsz: int = DEFAULT_IMGSZ,
	device: str = "cuda:0",
) -> Path:
	"""
	Exports trained `.pt` weights to an FP16 TensorRT `.engine` (natively end-to-end
	without NMS for YOLO26) and copies it to `./best.engine` and `./models/best.engine`.
	"""
	weights_path = Path(weights_path).resolve()
	if not weights_path.is_file():
		raise FileNotFoundError(f"Cannot export TensorRT engine: weights not found at '{weights_path}'.")

	print(f"[INFO] Exporting TensorRT FP16 engine from {weights_path} (imgsz={imgsz}, device={device})...")
	model = YOLO(str(weights_path))
	exported = model.export(format="engine", half=True, imgsz=imgsz, device=device)
	exported_path = Path(exported).resolve() if exported else weights_path.with_suffix(".engine")
	if not exported_path.is_file():
		candidate = weights_path.with_suffix(".engine")
		if candidate.is_file():
			exported_path = candidate.resolve()
		else:
			raise FileNotFoundError(f"TensorRT export finished, but engine file was not found at '{exported_path}'.")

	root_engine = Path("best.engine").resolve()
	models_dir = Path("models")
	models_dir.mkdir(parents=True, exist_ok=True)
	models_engine = (models_dir / "best.engine").resolve()

	if exported_path != root_engine:
		shutil.copy2(exported_path, root_engine)
	if exported_path != models_engine:
		shutil.copy2(exported_path, models_engine)

	print(f"[ENGINE] Exported engine: {exported_path}")
	print(f"[ENGINE] Copied to root : {root_engine}")
	print(f"[ENGINE] Copied to dir  : {models_engine}")
	return root_engine


def train_robot_detector(
	data_yaml: str = DEFAULT_DATA_YAML,
	base_weights: str = DEFAULT_BASE_MODEL,
	epochs: int = DEFAULT_EPOCHS,
	imgsz: int = DEFAULT_IMGSZ,
	batch: int = DEFAULT_BATCH,
	device: str = DEFAULT_DEVICE,
	project: str = "runs/detect",
	name: str = "fll_robot_yolo26x",
	export_trt: bool = True,
) -> Path:
	"""
	Loads `yolo26x.pt` and fine-tunes it for `epochs` epochs on the selected device.
	Returns the path to the trained `best.pt` weights.
	"""
	data_path = Path(data_yaml).resolve()
	if not data_path.is_file():
		dataset_cand = Path("dataset") / data_yaml
		if dataset_cand.is_file():
			data_path = dataset_cand.resolve()
		else:
			raise FileNotFoundError(
				f"Dataset configuration file not found at '{data_path}' or '{dataset_cand.resolve()}'.\n"
				f"Ensure 'data.yaml' exists and points to your labeled train/valid image folders."
			)

	resolved_device = resolve_training_device(device)

	print(f"[INFO] Loading base model: {base_weights}")
	model = YOLO(base_weights)

	print(f"[INFO] Starting YOLO26x fine-tuning for {epochs} epochs on {resolved_device}...")
	results = model.train(
		data=str(data_path),
		epochs=epochs,
		imgsz=imgsz,
		batch=batch,
		device=resolved_device,
		project=project,
		name=name,
		exist_ok=True,
		pretrained=True,
		single_cls=True,        # Enforce single-class ("robot") detection
		amp=resolved_device.startswith("cuda"),  # Mixed-precision training for faster GPU throughput
		mosaic=1.0,             # Helps generalize across colorful FLL mat backgrounds
		close_mosaic=10,        # Refines tight bounding boxes on un-mosaicked images in final 10 epochs
		hsv_h=0.015,
		hsv_s=0.5,
		hsv_v=0.4,
		scale=0.5,
		translate=0.1,
		fliplr=0.5,
		flipud=0.2,
		workers=8 if not resolved_device.startswith("cpu") else 0,
		verbose=True,
	)

	save_dir = Path(getattr(results, "save_dir", Path(project) / name))
	best_weights = save_dir / "weights" / "best.pt"

	if not best_weights.is_file():
		raise FileNotFoundError(f"Training completed, but best.pt was not found at '{best_weights}'.")

	# Copy best.pt to workspace root and ./models/best.pt for convenient inference
	root_best = Path("best.pt").resolve()
	models_dir = Path("models")
	models_dir.mkdir(parents=True, exist_ok=True)
	models_best = (models_dir / "best.pt").resolve()

	shutil.copy2(best_weights, root_best)
	shutil.copy2(best_weights, models_best)

	print(f"\n[SUCCESS] Training finished!")
	print(f"[WEIGHTS] Run weights   : {best_weights.resolve()}")
	print(f"[WEIGHTS] Copied to root: {root_best}")
	print(f"[WEIGHTS] Copied to dir : {models_best}")

	if export_trt and resolved_device.startswith("cuda"):
		export_tensorrt_engine(root_best, imgsz=imgsz, device=resolved_device)

	print("[NEXT STEP] Run live tracking with: python 3_live_tracking.py")
	return root_best


def parse_args():
	parser = argparse.ArgumentParser(
		description="Fine-tune YOLO26x on the single 'robot' class for 50 epochs using GPU (cuda:0)."
	)
	parser.add_argument(
		"--data",
		"-d",
		type=str,
		default=DEFAULT_DATA_YAML,
		help=f"Path to data.yaml (default: {DEFAULT_DATA_YAML})",
	)
	parser.add_argument(
		"--model",
		"-m",
		type=str,
		default=DEFAULT_BASE_MODEL,
		help=f"Base YOLO26x weights (default: {DEFAULT_BASE_MODEL})",
	)
	parser.add_argument(
		"--epochs",
		"-e",
		type=int,
		default=DEFAULT_EPOCHS,
		help=f"Number of training epochs (default: {DEFAULT_EPOCHS})",
	)
	parser.add_argument(
		"--imgsz",
		type=int,
		default=DEFAULT_IMGSZ,
		help=f"Training image resolution (default: {DEFAULT_IMGSZ})",
	)
	parser.add_argument(
		"--batch",
		"-b",
		type=int,
		default=DEFAULT_BATCH,
		help=f"Batch size (default: {DEFAULT_BATCH})",
	)
	parser.add_argument(
		"--device",
		type=str,
		default=DEFAULT_DEVICE,
		help=f"Acceleration device: 'auto' (CUDA -> MPS -> CPU), 'cuda:0', 'mps', or 'cpu' (default: {DEFAULT_DEVICE})",
	)
	parser.add_argument(
		"--no-export",
		action="store_true",
		help="Skip automatic TensorRT FP16 (.engine) export after training.",
	)
	parser.add_argument(
		"--export-only",
		type=str,
		default=None,
		help="Path to a .pt weights file to export to TensorRT FP16 without training.",
	)
	return parser.parse_args()


if __name__ == "__main__":
	args = parse_args()
	try:
		if args.export_only:
			resolved_device = resolve_training_device(args.device)
			if not resolved_device.startswith("cuda"):
				raise RuntimeError(
					f"TensorRT export requires a CUDA GPU, but resolved device is '{resolved_device}'."
				)
			export_tensorrt_engine(Path(args.export_only), imgsz=args.imgsz, device=resolved_device)
		else:
			train_robot_detector(
				data_yaml=args.data,
				base_weights=args.model,
				epochs=args.epochs,
				imgsz=args.imgsz,
				batch=args.batch,
				device=args.device,
				export_trt=not args.no_export,
			)
	except Exception as exc:
		print(f"[ERROR] {exc}", file=sys.stderr)
		sys.exit(1)
