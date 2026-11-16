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
OUT_OF_FRAME_HOLD_SEC = 0.45 # Seconds to hold focus before smoothly zooming out when lost


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
		opened = cv2.morphologyEx(mask, cv2.MORPH_OPEN, self.kernel)
		if cv2.countNonZero(opened) > int(self.width * self.height * 0.45):
			return np.zeros((self.height, self.width), dtype=np.uint8)
		return opened

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


def is_human_hand_or_arm(frame: np.ndarray, bbox: Tuple[int, int, int, int]) -> bool:
	"""
	Rejects human hands, fingers, and arms reaching over the table border by combining
	YCrCb + HSV skin-tone detection with LEGO chassis brick counter-evidence.
	"""
	fh, fw = frame.shape[:2]
	x1, y1, x2, y2 = bbox
	x1 = max(0, min(fw - 1, x1))
	y1 = max(0, min(fh - 1, y1))
	x2 = max(x1 + 1, min(fw, x2))
	y2 = max(y1 + 1, min(fh, y2))

	crop = frame[y1:y2, x1:x2]
	area = float((x2 - x1) * (y2 - y1))
	if area <= 0 or crop.size == 0:
		return False

	ycrcb = cv2.cvtColor(crop, cv2.COLOR_BGR2YCrCb)
	hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
	skin_ycrcb = cv2.inRange(ycrcb, (40, 135, 80), (255, 172, 125))
	skin_hsv = cv2.inRange(hsv, (0, 35, 60), (20, 175, 255))
	skin_mask = cv2.bitwise_and(skin_ycrcb, skin_hsv)
	skin_ratio = cv2.countNonZero(skin_mask) / area

	# LEGO SPIKE / Mindstorms robots have bright white/grey hub surfaces or cyan/colored bricks
	white_grey_px = cv2.countNonZero(cv2.inRange(hsv, (0, 0, 165), (180, 40, 255)))
	cyan_px = cv2.countNonZero(cv2.inRange(hsv, (82, 60, 55), (106, 255, 255)))
	lego_ratio = (white_grey_px + cyan_px) / area

	touches_border = (
		x1 <= int(fw * 0.03)
		or y1 <= int(fh * 0.03)
		or x2 >= int(fw * 0.97)
		or y2 >= int(fh * 0.97)
	)
	if touches_border and skin_ratio > 0.22 and lego_ratio < 0.20:
		return True
	if skin_ratio > 0.36 and lego_ratio < 0.18:
		return True
	return False


def has_lego_robot_appearance(frame: np.ndarray, bbox: Tuple[int, int, int, int]) -> bool:
	"""
	Verifies that a static candidate bounding box actually contains LEGO robot visual features
	(bright white/light-grey hub/chassis bricks or SPIKE cyan accents) rather than a dark
	mission model or flat mat artwork.
	"""
	fh, fw = frame.shape[:2]
	x1, y1, x2, y2 = bbox
	x1 = max(0, min(fw - 1, x1))
	y1 = max(0, min(fh - 1, y1))
	x2 = max(x1 + 1, min(fw, x2))
	y2 = max(y1 + 1, min(fh, y2))

	crop = frame[y1:y2, x1:x2]
	area = float((x2 - x1) * (y2 - y1))
	if area < 64.0 or crop.size == 0:
		return False

	hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
	white_px = cv2.countNonZero(cv2.inRange(hsv, (0, 0, 185), (180, 45, 255)))
	cyan_px = cv2.countNonZero(cv2.inRange(hsv, (82, 60, 55), (106, 255, 255)))
	white_ratio = white_px / area
	cyan_ratio = cyan_px / area
	return white_ratio >= 0.08 or cyan_ratio >= 0.03


def select_best_robot_detection(
	results,
	frame_w: int,
	frame_h: int,
	conf_threshold: float,
	last_center: Optional[Tuple[int, int]],
	motion_gate: Optional[MotionActivityGate] = None,
	motion_mask: Optional[np.ndarray] = None,
	require_motion: bool = False,
	frame: Optional[np.ndarray] = None,
) -> Optional[Tuple[int, int, int, int, int, int, float]]:
	"""
	Extracts the best "robot" bounding box `(x1, y1, x2, y2, cx, cy, conf)` from YOLOv8 output.
	Applies confidence, area, skin/hand rejection, and optional movement filtering.
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

		is_moving = False
		if motion_gate is not None and motion_mask is not None:
			is_moving = motion_gate.is_bbox_moving(motion_mask, (x1, y1, x2, y2), frame_w, frame_h)

		if require_motion and not is_moving:
			continue

		if frame is not None:
			if is_human_hand_or_arm(frame, (x1, y1, x2, y2)):
				continue
			if not has_lego_robot_appearance(frame, (x1, y1, x2, y2)):
				continue

		cx = int(round((x1 + x2) * 0.5))
		cy = int(round((y1 + y2) * 0.5))

		# Score by confidence with a gentle continuity bonus near previous tracked center
		score = conf * (1.15 if is_moving else 1.0)
		if last_center is not None:
			dist = math.hypot(cx - last_center[0], cy - last_center[1])
			if dist < max(frame_w, frame_h) * 0.35:
				score *= 1.25

		if score > best_score:
			best_score = score
			best_candidate = (x1, y1, x2, y2, cx, cy, conf)

	return best_candidate


def _find_runs_1d(profile: np.ndarray, thresh: float, max_gap: int = 3, min_len: int = 2):
	indices = np.where(profile >= thresh)[0]
	runs = []
	for idx in indices:
		i = int(idx)
		if not runs or i > runs[-1][1] + max_gap:
			runs.append([i, i])
		else:
			runs[-1][1] = i
	return [r for r in runs if (r[1] - r[0] + 1) >= min_len]


def _detect_dual_table_rois(frame: np.ndarray):
	"""
	Detects the inner playable bounds of Left and Right FLL tables from a full wide-angle
	camera frame so `detect_stationary_lego_robot` works both on full dual-table frames
	and on cropped single-table frames.
	"""
	h, w = frame.shape[:2]
	scale = min(1.0, 512.0 / max(1, w))
	sw = max(64, int(w * scale))
	sh = max(64, int(h * scale))

	small = cv2.resize(frame, (sw, sh), interpolation=cv2.INTER_AREA)
	hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
	gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)

	wood_mask = (cv2.inRange(hsv, (7, 30, 70), (32, 185, 245)) > 0).astype(np.float32)
	vy0, vy1 = int(sh * 0.15), int(sh * 0.85)
	col_wood = wood_mask[vy0:vy1, :].mean(axis=0)
	min_rail_w = max(2, int(sw * 0.012))
	v_runs = _find_runs_1d(col_wood, 0.40, max_gap=4, min_len=min_rail_w)

	left_rails = [r for r in v_runs if r[1] < sw * 0.28]
	center_rails = [r for r in v_runs if sw * 0.35 < (r[0] + r[1]) * 0.5 < sw * 0.65]
	right_rails = [r for r in v_runs if r[0] > sw * 0.72]

	grad_x = np.abs(cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3))
	col_grad = grad_x[vy0:vy1, :].mean(axis=0)

	if left_rails:
		lx1 = (left_rails[-1][1] + 1) / float(sw)
	else:
		l_zone = col_grad[int(sw * 0.02) : int(sw * 0.20)]
		if len(l_zone) and float(l_zone.max()) > float(col_grad.mean()) * 1.8:
			lx1 = (int(np.argmax(l_zone)) + int(sw * 0.02)) / float(sw)
		else:
			lx1 = 0.0

	if center_rails:
		c_best = max(center_rails, key=lambda r: float(col_wood[r[0] : r[1] + 1].sum()))
		lx2 = c_best[0] / float(sw)
		rx1 = (c_best[1] + 1) / float(sw)
	else:
		c_zone = col_grad[int(sw * 0.42) : int(sw * 0.58)]
		cx = (int(np.argmax(c_zone)) + int(sw * 0.42)) / float(sw) if len(c_zone) else 0.5
		lx2 = max(0.35, cx - 0.005)
		rx1 = min(0.65, cx + 0.005)

	if right_rails:
		rx2 = right_rails[0][0] / float(sw)
	else:
		r_zone = col_grad[int(sw * 0.80) : int(sw * 0.98)]
		if len(r_zone) and float(r_zone.max()) > float(col_grad.mean()) * 1.8:
			rx2 = (int(np.argmax(r_zone)) + int(sw * 0.80)) / float(sw)
		else:
			rx2 = 1.0

	if not left_rails and right_rails:
		lx1 = max(0.0, min(lx1, lx2 - (rx2 - rx1)))
	elif left_rails and not right_rails:
		rx2 = min(1.0, max(rx2, rx1 + (lx2 - lx1)))

	min_rail_h = max(2, int(sh * 0.012))

	def find_y_bounds(x_start_r: float, x_end_r: float):
		xa = max(0, int(x_start_r * sw) + 2)
		xb = min(sw, int(x_end_r * sw) - 2)
		if xb - xa < 10:
			return 0.0, 1.0
		row_wood = wood_mask[:, xa:xb].mean(axis=1)
		row_roughness = grad_x[:, xa:xb].mean(axis=1)
		smooth_wood = np.where(row_roughness < 38.0, row_wood, 0.0)
		h_runs = _find_runs_1d(smooth_wood, 0.40, max_gap=3, min_len=min_rail_h)
		top_cands = [r for r in h_runs if r[1] < sh * 0.25]
		bot_cands = [r for r in h_runs if r[0] > sh * 0.78]
		y1 = (top_cands[-1][1] + 1) / float(sh) if top_cands else 0.0
		y2 = bot_cands[0][0] / float(sh) if bot_cands else 1.0
		return y1, y2

	ly1, ly2 = find_y_bounds(lx1, lx2)
	ry1, ry2 = find_y_bounds(rx1, rx2)
	if ly1 > 0.01 and ry1 == 0.0:
		ry1 = ly1
	elif ry1 > 0.01 and ly1 == 0.0:
		ly1 = ry1
	if ly2 < 0.99 and ry2 == 1.0:
		ry2 = ly2
	elif ry2 < 0.99 and ly2 == 1.0:
		ly2 = ry2

	if (lx2 - lx1) < 0.18 or (rx2 - rx1) < 0.18 or (ly2 - ly1) < 0.40 or (ry2 - ry1) < 0.40:
		return [(0, 0, w // 2, h), (w // 2, 0, w, h)]

	return [
		(int(lx1 * w), int(ly1 * h), int(lx2 * w), int(ly2 * h)),
		(int(rx1 * w), int(ry1 * h), int(rx2 * w), int(ry2 * h)),
	]


def _detect_stationary_on_single_table(
	table_frame: np.ndarray,
) -> Optional[Tuple[int, int, int, int, float]]:
	"""
	Detects a LEGO SPIKE Prime / Technic robot standing on a single FLL table mat or inside
	any of the white corner launch areas while ignoring printed mat graphics and mission models.
	Returns `(x1, y1, x2, y2, conf)` in `table_frame` coordinates or `None`.
	"""
	th, tw = table_frame.shape[:2]
	if th < 32 or tw < 32:
		return None

	gray_full = cv2.cvtColor(table_frame, cv2.COLOR_BGR2GRAY)
	# Ignore outer 4px in case of screenshot border
	inner_gray = gray_full[4 : max(5, th - 4), 4 : max(5, tw - 4)]
	valid_cols = np.where(inner_gray.mean(axis=0) > 38)[0] + 4
	valid_rows = np.where(inner_gray.mean(axis=1) > 38)[0] + 4
	if len(valid_cols) < 16 or len(valid_rows) < 16:
		ox0, oy0, ox1, oy1 = 0, 0, tw, th
	else:
		ox0, ox1 = max(0, int(valid_cols[0])), min(tw, int(valid_cols[-1] + 1))
		oy0, oy1 = max(0, int(valid_rows[0])), min(th, int(valid_rows[-1] + 1))

	sub_img = table_frame[oy0:oy1, ox0:ox1]
	sh, sw = sub_img.shape[:2]
	if sh < 32 or sw < 32:
		return None

	W, H_grid = 320, 560
	img = cv2.resize(sub_img, (W, H_grid), interpolation=cv2.INTER_AREA)
	hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
	H, S, V = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
	B = img[:, :, 0].astype(np.int16)
	G = img[:, :, 1].astype(np.int16)
	R = img[:, :, 2].astype(np.int16)

	kernel_small = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
	kernel_hub = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
	kernel_cluster = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (21, 21))

	# LEGO SPIKE Prime Medium Azure / Cyan wheel & motor signature
	teal_mask = (
		(H >= 64) & (H <= 108) & (S >= 42) & (V >= 60) & (V <= 215) & (B > R + 10) & (G > R + 8)
	).astype(np.uint8) * 255
	teal_mask = cv2.morphologyEx(teal_mask, cv2.MORPH_OPEN, kernel_small)

	# 1. Robot on the mat: solid bright rectangular hub top + adjacent cyan wheel/accents
	hub_mask = ((V >= 208) & (S <= 54) & (R >= 202) & (B >= 188)).astype(np.uint8) * 255
	hub_mask = cv2.morphologyEx(hub_mask, cv2.MORPH_OPEN, kernel_hub)

	contours, _ = cv2.findContours(hub_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
	best_box = None
	best_score = 0.0
	for c in contours:
		area = cv2.contourArea(c)
		if area < 95 or area > 1600:
			continue
		x, y, w, h = cv2.boundingRect(c)
		if w < 10 or h < 10 or w > 95 or h > 95:
			continue
		hull_area = max(1.0, cv2.contourArea(cv2.convexHull(c)))
		solidity = area / hull_area
		aspect = max(w, h) / max(1.0, min(w, h))
		if solidity < 0.70 or aspect > 2.4:
			continue
		# Reject printed black-and-white line-following ovals (which have a dark stripe down their center)
		cx0, cy0 = x + w // 4, y + h // 4
		cx1, cy1 = max(cx0 + 2, x + (3 * w) // 4), max(cy0 + 2, y + (3 * h) // 4)
		center_v = V[cy0:cy1, cx0:cx1]
		if float(np.percentile(center_v, 15)) < 185.0 or float(center_v.mean()) < 210.0:
			continue
		x0, y0 = max(0, x - 18), max(0, y - 18)
		x1, y1 = min(W, x + w + 18), min(H_grid, y + h + 18)
		teal_near = int(np.count_nonzero(teal_mask[y0:y1, x0:x1]))
		if teal_near < 28:
			continue
		rx0, ry0 = max(0, x - 12), max(0, y - 10)
		rx1, ry1 = min(W, x + w + 16), min(H_grid, y + h + 20)
		score = float(teal_near) * solidity
		if score > best_score:
			best_score = score
			best_box = (rx0, ry0, rx1 - rx0, ry1 - ry0, min(0.95, 0.75 + teal_near / 400.0))

	if best_box is not None:
		bx, by, bw, bh, conf = best_box
		fx = ox0 + int(round(bx * sw / float(W)))
		fy = oy0 + int(round(by * sh / float(H_grid)))
		fw_box = int(round(bw * sw / float(W)))
		fh_box = int(round(bh * sh / float(H_grid)))
		return (fx, fy, fx + fw_box, fy + fh_box, round(conf, 2))

	# 2. Robot inside any of the 4 white quarter-circle corner launch areas
	corners = (
		(0, 135, 0, 150, 0, 0),
		(0, 135, H_grid - 150, H_grid, 0, H_grid),
		(W - 135, W, 0, 150, W, 0),
		(W - 135, W, H_grid - 150, H_grid, W, H_grid),
	)
	for x0, x1, y0, y1, cx_c, cy_c in corners:
		ch, cs, cv_ = H[y0:y1, x0:x1], S[y0:y1, x0:x1], V[y0:y1, x0:x1]
		white_frac = np.count_nonzero((cv_ > 185) & (cs < 48)) / float(ch.size)
		if white_frac < 0.28:
			continue
		yy, xx = np.mgrid[y0:y1, x0:x1]
		dist = np.hypot(xx - cx_c, yy - cy_c)
		in_arc = ((dist > 14) & (dist < 118)).astype(np.uint8) * 255
		teal_in_arc = cv2.bitwise_and(teal_mask[y0:y1, x0:x1], in_arc)
		teal_cnt = int(np.count_nonzero(teal_in_arc))
		if teal_cnt >= 35:
			clustered = cv2.morphologyEx(teal_in_arc, cv2.MORPH_CLOSE, kernel_cluster)
			t_cnts, _ = cv2.findContours(clustered, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
			if not t_cnts:
				continue
			main_c = max(t_cnts, key=cv2.contourArea)
			tx, ty, tw_c, th_c = cv2.boundingRect(main_c)
			tx0, ty0 = x0 + tx, y0 + ty
			tx1, ty1 = tx0 + tw_c, ty0 + th_c
			rx0 = max(x0 + 4, tx0 - 24)
			ry0 = max(y0 + 4, ty0 - 14)
			rx1 = min(x1 - 4, tx1 + 10)
			ry1 = min(y1 - 4, ty1 + 26)
			bw, bh = max(40, rx1 - rx0), max(44, ry1 - ry0)
			fx = ox0 + int(round(rx0 * sw / float(W)))
			fy = oy0 + int(round(ry0 * sh / float(H_grid)))
			fw_box = int(round(bw * sw / float(W)))
			fh_box = int(round(bh * sh / float(H_grid)))
			conf = min(0.95, 0.78 + teal_cnt / 400.0)
			return (fx, fy, fx + fw_box, fy + fh_box, round(conf, 2))

	return None


def detect_stationary_lego_robot(
	frame: np.ndarray,
	last_center: Optional[Tuple[int, int]] = None,
) -> Optional[Tuple[int, int, int, int, int, int, float]]:
	"""
	Visual LEGO SPIKE Prime / Mindstorms robot detector for stationary and slow-moving robots.
	Handles both cropped single-table frames and full wide-angle dual-table camera frames.
	Returns `(x1, y1, x2, y2, cx, cy, conf)` in `frame` coordinates or `None`.
	"""
	if frame is None or frame.size == 0:
		return None

	fh, fw = frame.shape[:2]
	if fh < 32 or fw < 32:
		return None

	regions = []
	if fw >= int(fh * 1.15):
		# Wide dual-table camera frame or split-view screenshot: inspect calibrated table ROIs
		for rx1, ry1, rx2, ry2 in _detect_dual_table_rois(frame):
			if (rx2 - rx1) >= 32 and (ry2 - ry1) >= 32:
				regions.append((rx1, ry1, rx2, ry2))
		# Also include left/right halves as fallback if calibrated ROIs differ from split view
		regions.append((0, 0, fw // 2, fh))
		regions.append((fw // 2, 0, fw, fh))
	else:
		regions.append((0, 0, fw, fh))

	best_candidate = None
	best_score = -1.0

	for rx1, ry1, rx2, ry2 in regions:
		sub = frame[ry1:ry2, rx1:rx2]
		res = _detect_stationary_on_single_table(sub)
		if res is None:
			continue
		sx1, sy1, sx2, sy2, conf = res
		x1 = max(0, min(fw - 1, rx1 + sx1))
		y1 = max(0, min(fh - 1, ry1 + sy1))
		x2 = max(x1 + 1, min(fw, rx1 + sx2))
		y2 = max(y1 + 1, min(fh, ry1 + sy2))
		if is_human_hand_or_arm(frame, (x1, y1, x2, y2)):
			continue
		cx = int(round((x1 + x2) * 0.5))
		cy = int(round((y1 + y2) * 0.5))
		score = conf
		if last_center is not None and math.hypot(cx - last_center[0], cy - last_center[1]) < max(fw, fh) * 0.35:
			score *= 1.25
		if score > best_score:
			best_score = score
			best_candidate = (x1, y1, x2, y2, cx, cy, conf)
		# If calibrated table regions already matched, no need to re-test raw halves
		if len(regions) > 2 and best_candidate is not None:
			break

	return best_candidate


def detect_motion_fallback(
	motion_mask: np.ndarray,
	frame_w: int,
	frame_h: int,
	frame: Optional[np.ndarray] = None,
	last_center: Optional[Tuple[int, int]] = None,
) -> Optional[Tuple[int, int, int, int, int, int, float]]:
	"""
	Fallback motion contour tracker used when a moving LEGO robot is not classified by YOLO
	(e.g. before custom training or during fast motion blur), while rejecting human hands/arms.
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

	best_candidate = None
	best_score = -1.0

	for c in contours:
		area = cv2.contourArea(c)
		if area < 18 or area > (mw * mh * 0.45):
			continue

		bx, by, bw, bh = cv2.boundingRect(c)
		x1 = max(0, int(round(bx * sx)))
		y1 = max(0, int(round(by * sy)))
		x2 = min(frame_w, int(round((bx + bw) * sx)))
		y2 = min(frame_h, int(round((by + bh) * sy)))

		if frame is not None and is_human_hand_or_arm(frame, (x1, y1, x2, y2)):
			continue

		cx = int(round((x1 + x2) * 0.5))
		cy = int(round((y1 + y2) * 0.5))
		score = float(area)
		if last_center is not None and math.hypot(cx - last_center[0], cy - last_center[1]) < max(frame_w, frame_h) * 0.35:
			score *= 1.35
		if score > best_score:
			best_score = score
			best_candidate = (x1, y1, x2, y2, cx, cy, 0.85)

	return best_candidate


def run_live_tracking(
	weights_path: str = "best.pt",
	source=0,
	conf_threshold: float = CONF_THRESHOLD,
	iou_threshold: float = IOU_THRESHOLD,
	device: str = "cuda:0",
	imgsz: int = 640,
	require_motion: bool = False,
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
				frame=frame,
			)

			# Fallback 1: Moving LEGO robot contour tracker (rejecting human hands/arms)
			if det is None:
				det = detect_motion_fallback(
					motion_mask=motion_mask,
					frame_w=frame_w,
					frame_h=frame_h,
					frame=frame,
					last_center=last_center,
				)

			# Fallback 2: Visual stationary LEGO robot detector (launch areas & field)
			if det is None and not require_motion:
				det = detect_stationary_lego_robot(frame, last_center=last_center)

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
		default=True,
		help="Stay focused on stationary robots even when there is no movement (default: enabled)",
	)
	parser.add_argument(
		"--require-motion",
		action="store_true",
		default=False,
		help="Only track robots while they are actively moving",
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
			require_motion=bool(args.require_motion),
		)
	except Exception as exc:
		print(f"[ERROR] {exc}", file=sys.stderr)
		sys.exit(1)
