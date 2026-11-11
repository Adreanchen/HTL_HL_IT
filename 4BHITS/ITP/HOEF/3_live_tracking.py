"""
3_live_tracking.py
------------------
Real-time FLL LEGO Robot YOLOv8 GPU Tracker with Smooth Optical Zoom & Panning.

Features:
- Opens webcam (`cv2.VideoCapture(0)`) with low-latency MJPG capture & auto-reconnect on disconnect.
- Runs custom-trained YOLOv8 weights (`best.pt`) on the GPU (`device='cuda:0'`) with FP16 acceleration.
- Strictly tracks the "robot" class while rejecting human hands, arms, and shadows via configurable
  confidence (`CONF_THRESHOLD`), bounding-box geometry, and motion gating.
- Calculates real-time (X, Y) center coordinates, draws bounding boxes + telemetry HUD, and drives a
  2-stage fluid-head Smooth Zoom In/Out & Panning camera view.
- Gracefully handles scenarios where the robot is temporarily out of frame or stationary by smoothly
  zooming back out to the full table view.

Hotkeys (while window is active):
    q / ESC : Quit gracefully
    v       : Toggle display mode (Side-by-Side Split View vs. Zoomed View Only vs. Tracker HUD Only)
    r       : Reset camera zoom & tracking state
    m       : Toggle require-movement gate (unfocus when robot is completely stationary)
    + / =   : Increase confidence threshold (+0.05) to be stricter against hands/shadows
    -       : Decrease confidence threshold (-0.05) to be more sensitive

Usage:
    python 3_live_tracking.py --weights best.pt --source 0 --conf 0.55
"""

import argparse
import ctypes
import math
import os
import sys
import time
from pathlib import Path
from typing import Optional, Tuple
import cv2
import numpy as np

try:
	import torch
	from ultralytics import YOLO
except ImportError as exc:
	print(
		f"[ERROR] Missing required dependency ({exc}). Install with:\n"
		"  pip install -r requirements.txt",
		file=sys.stderr,
	)
	sys.exit(1)


# =====================================================================
# TUNABLE TRACKING & FALSE-POSITIVE REJECTION PARAMETERS
# =====================================================================
# 1. CONF_THRESHOLD (0.0 .. 1.0):
#    Minimum YOLOv8 confidence score required to accept a "robot" detection.
#    - Increase (e.g. 0.60 - 0.75) if human hands, sleeves, or shadows trigger false positives.
#    - Decrease (e.g. 0.40 - 0.50) if the robot is missed during fast turns or motion blur.
CONF_THRESHOLD = 0.55

# 2. IOU_THRESHOLD (0.0 .. 1.0):
#    Non-Maximum Suppression (NMS) overlap threshold so a single robot never gets duplicate boxes.
IOU_THRESHOLD = 0.45

# 3. AREA & ASPECT RATIO GUARDS:
#    Rejects tiny mat specks (< MIN_BOX_AREA_RATIO) and large human arms/torsos leaning over the
#    table (> MAX_BOX_AREA_RATIO).
MIN_BOX_AREA_RATIO = 0.0015
MAX_BOX_AREA_RATIO = 0.35

# 4. SMOOTH CAMERA ZOOM & FLUID-HEAD PANNING PHYSICS:
TARGET_FPS = 60
ROBOT_ZOOM_W = 0.58          # Zoomed window width as fraction of full frame width
ROBOT_ZOOM_ASPECT = 9.0 / 16.0
ROBOT_ZOOM_H_MAX = 0.62
TARGET_SMOOTH_SPEED = 8.0    # Stage-1 target trajectory smoothing rate
PAN_SPEED = 6.5              # Stage-2 fluid-head camera pan speed
ZOOM_SPEED = 4.5             # Stage-2 smooth zoom in/out speed
PAN_DEADZONE_RATIO = 0.012   # Deadzone ratio to prevent micro-jitter
OUT_OF_FRAME_HOLD_SEC = 0.30 # Seconds to hold focus before smoothly zooming out when lost/stopped


def enable_high_res_timer() -> None:
	"""Enables 1ms OS timer resolution on Windows for smooth 60 FPS frame pacing."""
	if sys.platform.startswith("win"):
		try:
			ctypes.windll.winmm.timeBeginPeriod(1)
		except Exception:
			pass


def resolve_weights_path(preferred: str) -> str:
	"""Finds `best.pt` across common output locations or falls back to `yolov8n.pt`."""
	candidates = [
		preferred,
		"best.pt",
		os.path.join("models", "best.pt"),
		os.path.join("runs", "detect", "fll_robot_yolov8n", "weights", "best.pt"),
		os.path.join("runs", "detect", "train", "weights", "best.pt"),
	]
	for path in candidates:
		if path and os.path.isfile(path):
			return path

	print(
		f"[WARN] Custom trained weights '{preferred}' not found yet.\n"
		"[WARN] Falling back to base 'yolov8n.pt' so you can test the live tracking pipeline now.\n"
		"[WARN] Run `python 2_train_model.py` after labeling to generate your custom `best.pt`."
	)
	return "yolov8n.pt"


def open_camera_robust(source, width: int = 1280, height: int = 720, fps: int = TARGET_FPS):
	"""
	Opens a webcam index (e.g. 0) or video file path with low-latency DirectShow + MJPG settings.
	Returns an opened `cv2.VideoCapture` instance or `None` if unavailable.
	"""
	if isinstance(source, int) and sys.platform.startswith("win"):
		cap = cv2.VideoCapture(source, cv2.CAP_DSHOW)
		if cap.isOpened():
			cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
			cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
			cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
			cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
			cap.set(cv2.CAP_PROP_FPS, fps)
			ret, frame = cap.read()
			if ret and frame is not None:
				return cap
			cap.release()

	cap = cv2.VideoCapture(source)
	if cap.isOpened():
		cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
		cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
		cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
		cap.set(cv2.CAP_PROP_FPS, fps)
		ret, frame = cap.read()
		if ret and frame is not None:
			return cap
		cap.release()

	return None


class SmoothCameraController:
	"""
	Two-stage exponential smoothing virtual camera that smoothly pans to follow the robot's
	(X, Y) center coordinates and zooms in while active, then smoothly zooms back out to the
	full table view when the robot is out of frame or stationary.
	"""

	def __init__(self):
		self.cam_x: Optional[float] = None
		self.cam_y: Optional[float] = None
		self.cur_win_w: Optional[float] = None
		self.cur_win_h: Optional[float] = None
		self.smooth_tx: Optional[float] = None
		self.smooth_ty: Optional[float] = None
		self.anchor_tx: Optional[float] = None
		self.anchor_ty: Optional[float] = None

	def reset(self, frame_w: int, frame_h: int) -> None:
		self.cam_x = frame_w * 0.5
		self.cam_y = frame_h * 0.5
		self.smooth_tx = self.cam_x
		self.smooth_ty = self.cam_y
		self.anchor_tx = self.cam_x
		self.anchor_ty = self.cam_y
		self.cur_win_w = float(frame_w)
		self.cur_win_h = float(frame_h)

	def update(
		self,
		frame_w: int,
		frame_h: int,
		target_center: Optional[Tuple[int, int]],
		dt: float,
	) -> Tuple[int, int, int, int]:
		"""
		Updates smooth pan/zoom state and returns the current crop window `(wx, wy, win_w, win_h)`.
		When `target_center` is None, smoothly zooms out to the full uncropped frame.
		"""
		if self.cam_x is None or self.cur_win_w is None:
			self.reset(frame_w, frame_h)

		dt = max(0.001, min(0.1, dt))
		aspect = frame_h / float(max(1, frame_w))

		if target_center is not None:
			raw_tx, raw_ty = float(target_center[0]), float(target_center[1])
			deadzone_px = max(4.0, min(frame_w, frame_h) * PAN_DEADZONE_RATIO)
			if (
				self.anchor_tx is None
				or math.hypot(raw_tx - self.anchor_tx, raw_ty - self.anchor_ty) > deadzone_px
			):
				self.anchor_tx, self.anchor_ty = raw_tx, raw_ty

			target_win_w = float(max(120.0, min(float(frame_w), frame_w * ROBOT_ZOOM_W)))
			target_win_h = float(max(90.0, min(float(frame_h), target_win_w * aspect)))
		else:
			# No robot detected or no movement -> unfocus and zoom smoothly out to full frame
			self.anchor_tx = frame_w * 0.5
			self.anchor_ty = frame_h * 0.5
			target_win_w = float(frame_w)
			target_win_h = float(frame_h)

		# Stage 1: Smooth target trajectory
		t_alpha = 1.0 - math.exp(-TARGET_SMOOTH_SPEED * dt)
		self.smooth_tx += (self.anchor_tx - self.smooth_tx) * t_alpha
		self.smooth_ty += (self.anchor_ty - self.smooth_ty) * t_alpha

		# Stage 2: Fluid-head camera pan & optical zoom
		pan_alpha = 1.0 - math.exp(-PAN_SPEED * dt)
		zoom_alpha = 1.0 - math.exp(-ZOOM_SPEED * dt)
		self.cam_x += (self.smooth_tx - self.cam_x) * pan_alpha
		self.cam_y += (self.smooth_ty - self.cam_y) * pan_alpha
		self.cur_win_w += (target_win_w - self.cur_win_w) * zoom_alpha
		self.cur_win_h += (target_win_h - self.cur_win_h) * zoom_alpha

		win_w = max(64, min(frame_w, int(round(self.cur_win_w))))
		win_h = max(64, min(frame_h, int(round(self.cur_win_h))))

		if win_w >= frame_w - 2 and win_h >= frame_h - 2:
			return 0, 0, frame_w, frame_h

		wx = max(0, int(round(self.cam_x - win_w * 0.5)))
		wy = max(0, int(round(self.cam_y - win_h * 0.5)))
		if wx + win_w > frame_w:
			wx = max(0, frame_w - win_w)
		if wy + win_h > frame_h:
			wy = max(0, frame_h - win_h)
		return wx, wy, win_w, win_h


class MotionActivityGate:
	"""
	Fast frame-difference motion gate so that if there is zero movement on the table,
	the camera does not stay focused on a stationary object.
	"""

	def __init__(self, width: int = 240, height: int = 135):
		self.width = width
		self.height = height
		self.prev_blur: Optional[np.ndarray] = None
		self.kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))

	def get_motion_mask(self, frame: np.ndarray) -> np.ndarray:
		small = cv2.resize(frame, (self.width, self.height), interpolation=cv2.INTER_AREA)
		blur = cv2.GaussianBlur(small, (5, 5), 0)
		if self.prev_blur is None:
			self.prev_blur = blur
			return np.zeros((self.height, self.width), dtype=np.uint8)

		diff = np.max(cv2.absdiff(blur, self.prev_blur), axis=2)
		self.prev_blur = blur
		base = float(cv2.mean(diff)[0])
		th = max(14, min(36, int(round(base * 2.2 + 11.0))))
		_, mask = cv2.threshold(diff, th, 255, cv2.THRESH_BINARY)
		return cv2.morphologyEx(mask, cv2.MORPH_OPEN, self.kernel)

	def is_bbox_moving(self, motion_mask: np.ndarray, bbox: Tuple[int, int, int, int], fw: int, fh: int) -> bool:
		x1, y1, x2, y2 = bbox
		sx = self.width / float(max(1, fw))
		sy = self.height / float(max(1, fh))
		mx1 = max(0, int(x1 * sx) - 2)
		my1 = max(0, int(y1 * sy) - 2)
		mx2 = min(self.width, int(x2 * sx) + 2)
		my2 = min(self.height, int(y2 * sy) + 2)
		if mx2 <= mx1 or my2 <= my1:
			return False
		active_px = int(cv2.countNonZero(motion_mask[my1:my2, mx1:mx2]))
		return active_px >= 10


def select_best_robot_detection(
	results,
	frame_w: int,
	frame_h: int,
	conf_threshold: float,
	last_center: Optional[Tuple[int, int]],
	motion_gate: Optional[MotionActivityGate] = None,
	motion_mask: Optional[np.ndarray] = None,
	require_motion: bool = True,
) -> Optional[Tuple[int, int, int, int, int, int, float]]:
	"""
	Extracts the best "robot" bounding box `(x1, y1, x2, y2, cx, cy, conf)` from YOLOv8 output.
	Applies confidence, area, and optional movement filtering to reject hands, shadows, and static clutter.
	"""
	if not results or len(results) == 0:
		return None

	boxes = results[0].boxes
	if boxes is None or len(boxes) == 0:
		return None

	total_area = float(frame_w * frame_h)
	xyxy_arr = boxes.xyxy.detach().cpu().numpy()
	conf_arr = boxes.conf.detach().cpu().numpy()

	best_candidate = None
	best_score = -1.0

	for i in range(len(xyxy_arr)):
		conf = float(conf_arr[i])
		if conf < conf_threshold:
			continue

		x1, y1, x2, y2 = [int(round(v)) for v in xyxy_arr[i]]
		x1 = max(0, min(frame_w - 1, x1))
		y1 = max(0, min(frame_h - 1, y1))
		x2 = max(x1 + 1, min(frame_w, x2))
		y2 = max(y1 + 1, min(frame_h, y2))

		bw = x2 - x1
		bh = y2 - y1
		area = float(bw * bh)

		# Reject specks or large human arm/body intrusions
		if area < total_area * MIN_BOX_AREA_RATIO or area > total_area * MAX_BOX_AREA_RATIO:
			continue

		if require_motion and motion_gate is not None and motion_mask is not None:
			if not motion_gate.is_bbox_moving(motion_mask, (x1, y1, x2, y2), frame_w, frame_h):
				continue

		cx = int(round((x1 + x2) * 0.5))
		cy = int(round((y1 + y2) * 0.5))

		# Score by confidence with a gentle continuity bonus near previous tracked center
		score = conf
		if last_center is not None:
			dist = math.hypot(cx - last_center[0], cy - last_center[1])
			if dist < max(frame_w, frame_h) * 0.35:
				score *= 1.25

		if score > best_score:
			best_score = score
			best_candidate = (x1, y1, x2, y2, cx, cy, conf)

	return best_candidate


def detect_motion_fallback(
	motion_mask: np.ndarray,
	frame_w: int,
	frame_h: int,
) -> Optional[Tuple[int, int, int, int, int, int, float]]:
	"""
	Fallback motion contour tracker used only when testing with un-finetuned `yolov8n.pt`
	if the base COCO model does not classify a custom LEGO robot.
	"""
	if cv2.countNonZero(motion_mask) < 20:
		return None

	closed = cv2.morphologyEx(
		motion_mask,
		cv2.MORPH_CLOSE,
		cv2.getStructuringElement(cv2.MORPH_RECT, (11, 11)),
	)
	contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
	if not contours:
		return None

	mw, mh = motion_mask.shape[1], motion_mask.shape[0]
	sx = frame_w / float(mw)
	sy = frame_h / float(mh)

	best_c = max(contours, key=cv2.contourArea)
	area = cv2.contourArea(best_c)
	if area < 18 or area > (mw * mh * 0.50):
		return None

	bx, by, bw, bh = cv2.boundingRect(best_c)
	x1 = int(round(bx * sx))
	y1 = int(round(by * sy))
	x2 = min(frame_w, int(round((bx + bw) * sx)))
	y2 = min(frame_h, int(round((by + bh) * sy)))
	cx = int(round((x1 + x2) * 0.5))
	cy = int(round((y1 + y2) * 0.5))
	return (x1, y1, x2, y2, cx, cy, 1.0)


def run_live_tracking(
	weights_path: str = "best.pt",
	source=0,
	conf_threshold: float = CONF_THRESHOLD,
	iou_threshold: float = IOU_THRESHOLD,
	device: str = "cuda:0",
	imgsz: int = 640,
	require_motion: bool = True,
) -> None:
	enable_high_res_timer()

	# Auto-resolve acceleration device
	dev_lower = str(device).strip().lower()
	if dev_lower in ("auto", "default", ""):
		if torch.cuda.is_available():
			device = "cuda:0"
		elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
			device = "mps"
		else:
			device = "cpu"
	elif device.startswith("cuda") and not torch.cuda.is_available():
		print("[WARN] CUDA is not available in current PyTorch environment; falling back to CPU.")
		device = "cpu"
	use_half = device.startswith("cuda")

	resolved_weights = resolve_weights_path(weights_path)
	is_custom_best = os.path.basename(resolved_weights).lower() == "best.pt"
	print(f"[INFO] Loading YOLOv8 weights: {resolved_weights} on {device} (FP16={use_half})")
	model = YOLO(resolved_weights)

	print(f"[INFO] Opening camera source: {source}...")
	cap = open_camera_robust(source)
	if cap is None:
		raise RuntimeError(f"Could not open video source '{source}'. Check that the webcam is connected.")

	camera_ctrl = SmoothCameraController()
	motion_gate = MotionActivityGate()

	last_detection: Optional[Tuple[int, int, int, int, int, int, float]] = None
	last_seen_time = 0.0
	last_center: Optional[Tuple[int, int]] = None
	view_mode = 0  # 0 = Split View (Tracker HUD + Smooth Zoom), 1 = Smooth Zoom Only, 2 = Tracker HUD Only

	window_name = "FLL YOLOv8 Robot Tracker (q: quit | v: view | m: motion-gate | +/-: conf)"
	cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)

	prev_time = time.perf_counter()
	fps_ema = 60.0
	disconnect_streak = 0

	try:
		while True:
			now = time.perf_counter()
			dt = max(0.001, now - prev_time)
			prev_time = now
			fps_ema = fps_ema * 0.9 + (1.0 / dt) * 0.1

			ret, frame = cap.read()
			if not ret or frame is None:
				disconnect_streak += 1
				if isinstance(source, str):
					# Loop video file seamlessly
					cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
					continue

				if disconnect_streak >= 15:
					print("[WARN] Camera frame read failed. Attempting to reconnect webcam...")
					try:
						cap.release()
					except Exception:
						pass
					time.sleep(0.5)
					cap = open_camera_robust(source)
					disconnect_streak = 0
				else:
					time.sleep(0.01)
				continue

			disconnect_streak = 0
			frame_h, frame_w = frame.shape[:2]
			motion_mask = motion_gate.get_motion_mask(frame)

			# Run YOLOv8 inference on GPU
			with torch.inference_mode():
				results = model.predict(
					source=frame,
					device=device,
					conf=conf_threshold,
					iou=iou_threshold,
					imgsz=imgsz,
					half=use_half,
					verbose=False,
				)

			det = select_best_robot_detection(
				results=results,
				frame_w=frame_w,
				frame_h=frame_h,
				conf_threshold=conf_threshold,
				last_center=last_center,
				motion_gate=motion_gate,
				motion_mask=motion_mask,
				require_motion=require_motion,
			)

			# If testing with stock yolov8n.pt before custom training, allow motion fallback
			if det is None and not is_custom_best:
				det = detect_motion_fallback(motion_mask, frame_w, frame_h)

			if det is not None:
				last_detection = det
				last_seen_time = now
				last_center = (det[4], det[5])
			elif last_detection is not None and (now - last_seen_time) > OUT_OF_FRAME_HOLD_SEC:
				# Robot is out of frame or stopped moving -> clear focus
				last_detection = None
				last_center = None

			active_target = (last_detection[4], last_detection[5]) if last_detection is not None else None
			wx, wy, win_w, win_h = camera_ctrl.update(frame_w, frame_h, active_target, dt)

			# 1. Build Smooth Zoomed View
			cropped = frame[wy : wy + win_h, wx : wx + win_w]
			zoom_view = cv2.resize(cropped, (frame_w, frame_h), interpolation=cv2.INTER_LINEAR)

			# 2. Build Full-Field Tracker HUD View
			hud_view = frame.copy()

			# Draw active smooth-zoom camera window rectangle in cyan
			if win_w < frame_w - 2 or win_h < frame_h - 2:
				cv2.rectangle(hud_view, (wx, wy), (wx + win_w, wy + win_h), (255, 200, 0), 2)

			# Draw robot bounding box and (X, Y) center coordinates
			if last_detection is not None:
				x1, y1, x2, y2, cx, cy, conf = last_detection
				cv2.rectangle(hud_view, (x1 - 1, y1 - 1), (x2 + 1, y2 + 1), (10, 15, 10), 4)
				cv2.rectangle(hud_view, (x1, y1), (x2, y2), (0, 240, 75), 2)

				# Draw center crosshair at (cx, cy)
				cv2.drawMarker(
					hud_view,
					(cx, cy),
					(0, 255, 255),
					markerType=cv2.MARKER_CROSS,
					markerSize=16,
					thickness=2,
				)

				label = f"ROBOT ({cx}, {cy}) | conf={conf:.2f}"
				cv2.rectangle(hud_view, (x1, max(0, y1 - 28)), (min(frame_w, x1 + 290), y1), (0, 180, 55), -1)
				cv2.putText(
					hud_view,
					label,
					(x1 + 6, max(18, y1 - 8)),
					cv2.FONT_HERSHEY_SIMPLEX,
					0.55,
					(255, 255, 255),
					2,
					cv2.LINE_AA,
				)

			# Telemetry status bar
			status_txt = (
				f"FPS: {fps_ema:4.1f} | Conf: {conf_threshold:.2f} | "
				f"MotionGate: {'ON' if require_motion else 'OFF'} | "
				f"Center: {active_target if active_target else 'IDLE (Full Table)'}"
			)
			cv2.rectangle(hud_view, (10, 10), (min(frame_w - 10, 680), 44), (15, 23, 42), -1)
			cv2.putText(
				hud_view,
				status_txt,
				(18, 33),
				cv2.FONT_HERSHEY_SIMPLEX,
				0.55,
				(255, 255, 255),
				1,
				cv2.LINE_AA,
			)

			if view_mode == 0:
				half_w = max(320, frame_w // 2)
				half_h = max(180, frame_h // 2)
				left_pane = cv2.resize(hud_view, (half_w, half_h), interpolation=cv2.INTER_AREA)
				right_pane = cv2.resize(zoom_view, (half_w, half_h), interpolation=cv2.INTER_AREA)
				cv2.putText(left_pane, "TRACKER HUD (Full Table)", (12, half_h - 12), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 240, 75), 2)
				cv2.putText(right_pane, "SMOOTH AUTO-ZOOM VIEW", (12, half_h - 12), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 200, 0), 2)
				display_img = np.hstack((left_pane, right_pane))
			elif view_mode == 1:
				display_img = zoom_view
			else:
				display_img = hud_view

			cv2.imshow(window_name, display_img)

			key = cv2.waitKey(1) & 0xFF
			if key in (27, ord("q"), ord("Q")):
				print("[INFO] Exit key pressed. Shutting down tracker...")
				break
			elif key in (ord("v"), ord("V")):
				view_mode = (view_mode + 1) % 3
			elif key in (ord("r"), ord("R")):
				camera_ctrl.reset(frame_w, frame_h)
				last_detection = None
				last_center = None
			elif key in (ord("m"), ord("M")):
				require_motion = not require_motion
				print(f"[INFO] Motion gate set to: {require_motion}")
			elif key in (ord("+"), ord("=")):
				conf_threshold = min(0.95, round(conf_threshold + 0.05, 2))
				print(f"[INFO] Confidence threshold increased to {conf_threshold:.2f}")
			elif key in (ord("-"), ord("_")):
				conf_threshold = max(0.15, round(conf_threshold - 0.05, 2))
				print(f"[INFO] Confidence threshold decreased to {conf_threshold:.2f}")

			# Handle window 'X' button close gracefully
			if cv2.getWindowProperty(window_name, cv2.WND_PROP_VISIBLE) < 1:
				break

	except KeyboardInterrupt:
		print("\n[INFO] Interrupted by user (Ctrl+C).")
	finally:
		try:
			if cap is not None:
				cap.release()
		except Exception:
			pass
		cv2.destroyAllWindows()
		print("[INFO] Camera released and windows closed cleanly.")


def parse_args():
	parser = argparse.ArgumentParser(
		description="Real-time YOLOv8 FLL LEGO Robot Tracker with GPU acceleration and smooth zoom."
	)
	parser.add_argument(
		"--weights",
		"-w",
		type=str,
		default="best.pt",
		help="Path to trained YOLOv8 weights (default: best.pt)",
	)
	parser.add_argument(
		"--source",
		"-s",
		type=str,
		default="0",
		help="Webcam index (default: 0) or path to video file",
	)
	parser.add_argument(
		"--conf",
		"-c",
		type=float,
		default=CONF_THRESHOLD,
		help=f"Confidence threshold 0..1 to reject hands/shadows (default: {CONF_THRESHOLD})",
	)
	parser.add_argument(
		"--iou",
		type=float,
		default=IOU_THRESHOLD,
		help=f"NMS IoU threshold (default: {IOU_THRESHOLD})",
	)
	parser.add_argument(
		"--device",
		type=str,
		default="auto",
		help="Inference device: 'auto' (CUDA -> MPS -> CPU), 'cuda:0', 'mps', or 'cpu' (default: auto)",
	)
	parser.add_argument(
		"--imgsz",
		type=int,
		default=640,
		help="YOLOv8 inference image size (default: 640)",
	)
	parser.add_argument(
		"--track-stationary",
		action="store_true",
		help="Stay focused on stationary robots even when there is no movement",
	)
	return parser.parse_args()


if __name__ == "__main__":
	args = parse_args()
	src = int(args.source) if args.source.isdigit() else args.source
	try:
		run_live_tracking(
			weights_path=args.weights,
			source=src,
			conf_threshold=args.conf,
			iou_threshold=args.iou,
			device=args.device,
			imgsz=args.imgsz,
			require_motion=not args.track_stationary,
		)
	except Exception as exc:
		print(f"[ERROR] {exc}", file=sys.stderr)
		sys.exit(1)
