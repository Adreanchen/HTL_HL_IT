from collections import deque
import math
import os
import cv2
import numpy as np

try:
	import torch
	from ultralytics import YOLO
except Exception:
	torch = None
	YOLO = None

from .config import (
	AUTO_ENHANCE_ENABLED,
	CONFIRM_FRAMES,
	DETECTION_HEIGHT,
	DETECTION_WIDTH,
	MAX_AREA_RATIO,
	MAX_BBOX_H_RATIO,
	MAX_BBOX_W_RATIO,
	MAX_STEP_RATIO,
	MIN_AREA_RATIO,
	MIN_MOTION_PIXELS,
	TARGET_BRIGHTNESS,
)


class AutoEnhancer:
	"""
	Real-time automatic brightness (adaptive gamma), contrast (soft percentile stretch),
	and white-balance normalizer using a 1x256x3 Look-Up Table (cv2.LUT).
	Smooths lighting parameters over time so camera brightness never flickers.
	"""

	def __init__(self, target_luma: float = TARGET_BRIGHTNESS):
		self.target_luma = float(target_luma)
		self._initialized = False
		self._mean_b = 128.0
		self._mean_g = 128.0
		self._mean_r = 128.0
		self._mean_luma = 128.0
		self._p_low = 8.0
		self._p_high = 245.0
		self._lut = np.arange(256, dtype=np.uint8).reshape(1, 256, 1).repeat(3, axis=2)

	def update_from_sample(self, sample_bgr: np.ndarray) -> None:
		if not AUTO_ENHANCE_ENABLED or sample_bgr is None or sample_bgr.size == 0:
			return

		# Subsample 4x for <0.05ms statistics calculation
		sub = sample_bgr[::4, ::4]
		b = sub[:, :, 0].astype(np.float32)
		g = sub[:, :, 1].astype(np.float32)
		r = sub[:, :, 2].astype(np.float32)
		luma = 0.114 * b + 0.587 * g + 0.299 * r

		# Ignore pure black letterboxing (<10) when estimating scene exposure
		valid = luma[luma > 10.0]
		if valid.size < 32:
			valid = luma.reshape(-1)

		cur_luma = float(np.mean(valid))
		cur_low = float(np.percentile(valid, 3))
		cur_high = float(np.percentile(valid, 98))
		cur_b = max(24.0, float(np.mean(b)))
		cur_g = max(24.0, float(np.mean(g)))
		cur_r = max(24.0, float(np.mean(r)))

		if not self._initialized:
			self._initialized = True
			self._mean_luma = cur_luma
			self._p_low = cur_low
			self._p_high = cur_high
			self._mean_b = cur_b
			self._mean_g = cur_g
			self._mean_r = cur_r
		else:
			a = 0.08
			self._mean_luma += (cur_luma - self._mean_luma) * a
			self._p_low += (cur_low - self._p_low) * a
			self._p_high += (cur_high - self._p_high) * a
			self._mean_b += (cur_b - self._mean_b) * a
			self._mean_g += (cur_g - self._mean_g) * a
			self._mean_r += (cur_r - self._mean_r) * a

		# 1. Soft contrast stretch (clamped so dark noise is never over-amplified)
		lo = max(0.0, min(42.0, self._p_low * 0.65))
		hi = min(255.0, max(lo + 145.0, self._p_high))
		x = np.arange(256, dtype=np.float32)
		norm = np.clip((x - lo) / max(1.0, hi - lo), 0.0, 1.0)

		# 2. Adaptive gamma for automatic brightness normalization
		mid = max(28.0, min(225.0, (self._mean_luma - lo) / max(1.0, hi - lo) * 255.0))
		gamma = math.log(max(0.15, min(0.85, self.target_luma / 255.0))) / math.log(mid / 255.0)
		gamma = max(0.68, min(1.42, gamma))
		curved = np.power(norm, gamma) * 255.0

		# 3. Gentle gray-world auto white balance (clamped to +-9% per channel)
		avg_rgb = (self._mean_b + self._mean_g + self._mean_r) / 3.0
		gain_b = max(0.91, min(1.09, avg_rgb / self._mean_b))
		gain_g = max(0.93, min(1.07, avg_rgb / self._mean_g))
		gain_r = max(0.91, min(1.09, avg_rgb / self._mean_r))

		lut = np.empty((1, 256, 3), dtype=np.uint8)
		lut[0, :, 0] = np.clip(curved * gain_b, 0.0, 255.0).astype(np.uint8)
		lut[0, :, 1] = np.clip(curved * gain_g, 0.0, 255.0).astype(np.uint8)
		lut[0, :, 2] = np.clip(curved * gain_r, 0.0, 255.0).astype(np.uint8)
		self._lut = lut

	def apply(self, img: np.ndarray) -> np.ndarray:
		if not AUTO_ENHANCE_ENABLED or not self._initialized or img is None:
			return img
		return cv2.LUT(img, self._lut)


class DetectorHybrid:
	"""
	Multi-horizon 3-channel BGR motion detector optimized for FLL tables.
	Tracks any actively moving object on the table and immediately clears focus
	when there is no movement.
	"""

	def __init__(self):
		self.kernel_open = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
		self.kernel_dilate = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))
		self.kernel_close = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 15))

		self.history = deque(maxlen=5)
		self.bg_float = None
		self.last_center = None
		self.pending_center = None
		self.confirm_streak = 0
		self.miss_streak = 0
		self.smooth_bbox = None

		self.yolo_model = None
		self.yolo_device = "cpu"
		if YOLO is not None and torch is not None:
			repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
			for cand_path in (
				os.path.join(repo_root, "best.pt"),
				os.path.join(repo_root, "models", "best.pt"),
				os.path.join(repo_root, "fll-vision", "best.pt"),
			):
				if os.path.isfile(cand_path):
					try:
						self.yolo_device = "cuda:0" if torch.cuda.is_available() else "cpu"
						self.yolo_model = YOLO(cand_path)
						break
					except Exception:
						self.yolo_model = None

	def reset(self):
		self.last_center = None
		self.pending_center = None
		self.confirm_streak = 0
		self.miss_streak = 0
		self.smooth_bbox = None

	def _decay_and_none(self):
		self.miss_streak += 1
		if self.miss_streak >= 2:
			self.confirm_streak = 0
			self.last_center = None
			self.smooth_bbox = None
		return None

	def detect(self, table_frame: np.ndarray):
		orig_h, orig_w = table_frame.shape[:2]
		if orig_h < 16 or orig_w < 16:
			return None

		# Use raw un-enhanced frame for motion differencing so LUT updates never trigger false motion
		small = cv2.resize(table_frame, (DETECTION_WIDTH, DETECTION_HEIGHT), interpolation=cv2.INTER_AREA)
		blur = cv2.GaussianBlur(small, (5, 5), 0)

		if not self.history or self.bg_float is None:
			self.history.append(blur)
			self.bg_float = blur.astype(np.float32)
			return None

		prev_1 = self.history[-1]
		prev_2 = self.history[-2] if len(self.history) >= 2 else self.history[-1]
		prev_long = self.history[0]
		self.history.append(blur)

		d1 = np.max(cv2.absdiff(blur, prev_1), axis=2)
		d2 = np.max(cv2.absdiff(blur, prev_2), axis=2)
		diff_short = np.maximum(d1, (d2 * 0.75).astype(np.uint8))
		diff_long = np.max(cv2.absdiff(blur, prev_long), axis=2)

		bg_u8 = cv2.convertScaleAbs(self.bg_float)
		diff_bg = np.max(cv2.absdiff(blur, bg_u8), axis=2)

		base_s = float(cv2.mean(d1)[0])
		base_l = float(cv2.mean(diff_long)[0])
		th_1 = max(14, min(36, int(round(base_s * 2.2 + 11.0))))
		th_short = max(15, min(38, int(round(base_s * 2.2 + 12.0))))
		th_long = max(16, min(42, int(round(base_l * 2.2 + 13.0))))

		_, mask_1 = cv2.threshold(d1, th_1, 255, cv2.THRESH_BINARY)
		_, mask_s = cv2.threshold(diff_short, th_short, 255, cv2.THRESH_BINARY)
		_, mask_l = cv2.threshold(np.maximum(diff_long, diff_bg), th_long, 255, cv2.THRESH_BINARY)

		mask_1 = cv2.morphologyEx(mask_1, cv2.MORPH_OPEN, self.kernel_open)
		mask_s = cv2.morphologyEx(mask_s, cv2.MORPH_OPEN, self.kernel_open)
		mask_l = cv2.morphologyEx(mask_l, cv2.MORPH_OPEN, self.kernel_open)

		# Intersect short-term motion with (long-term | background) difference:
		# isolates only the moving object's CURRENT position and eliminates trailing ghosts
		motion_mask = cv2.bitwise_and(mask_s, mask_l)

		total_area = float(DETECTION_WIDTH * DETECTION_HEIGHT)
		live_step_px = cv2.countNonZero(mask_1)
		motion_px = cv2.countNonZero(motion_mask)

		if live_step_px < (MIN_MOTION_PIXELS // 2) or motion_px < MIN_MOTION_PIXELS or motion_px > total_area * 0.70:
			if motion_px > total_area * 0.70:
				# Full-frame camera bump or lighting switch: reset background model
				self.bg_float = blur.astype(np.float32)
			else:
				# Absorb stationary scene quickly when nothing is moving
				cv2.accumulateWeighted(blur, self.bg_float, 0.25)
			return self._decay_and_none()

		# Update background only on non-moving pixels so moving object is never absorbed into background
		static_mask = cv2.bitwise_not(cv2.dilate(mask_s, self.kernel_open))
		cv2.accumulateWeighted(blur, self.bg_float, 0.12, mask=static_mask)

		# If custom YOLOv8 robot model (best.pt) is present, run GPU inference on the active moving frame
		if self.yolo_model is not None and torch is not None:
			try:
				with torch.inference_mode():
					res = self.yolo_model.predict(
						source=table_frame,
						device=self.yolo_device,
						conf=0.55,
						iou=0.45,
						imgsz=640,
						half=self.yolo_device.startswith("cuda"),
						verbose=False,
					)
				if res and len(res) > 0 and res[0].boxes is not None and len(res[0].boxes) > 0:
					boxes = res[0].boxes
					xyxy = boxes.xyxy.detach().cpu().numpy()
					confs = boxes.conf.detach().cpu().numpy()
					best_idx = int(np.argmax(confs))
					x1, y1, x2, y2 = [float(v) for v in xyxy[best_idx]]
					raw_w = max(16.0, x2 - x1)
					raw_h = max(16.0, y2 - y1)
					raw_cx = x1 + raw_w * 0.5
					raw_cy = y1 + raw_h * 0.5
					self.miss_streak = 0
					self.confirm_streak = CONFIRM_FRAMES
					if self.smooth_bbox is None:
						self.smooth_bbox = (raw_cx, raw_cy, raw_w, raw_h)
					else:
						scx, scy, sw, sh = self.smooth_bbox
						scx += (raw_cx - scx) * 0.68
						scy += (raw_cy - scy) * 0.68
						sw += (raw_w - sw) * 0.35
						sh += (raw_h - sh) * 0.35
						self.smooth_bbox = (scx, scy, sw, sh)
					scx, scy, sw, sh = self.smooth_bbox
					fx = max(0, int(round(scx - sw * 0.5)))
					fy = max(0, int(round(scy - sh * 0.5)))
					fw_box = max(16, min(orig_w - fx, int(round(sw))))
					fh_box = max(16, min(orig_h - fy, int(round(sh))))
					return (fx, fy, fw_box, fh_box)
				return self._decay_and_none()
			except Exception:
				pass

		mask = cv2.morphologyEx(motion_mask, cv2.MORPH_CLOSE, self.kernel_close)

		contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
		if not contours:
			return self._decay_and_none()

		min_contour_motion = max(16, int(MIN_MOTION_PIXELS * 0.45))
		candidates = []
		for c in contours:
			area = cv2.contourArea(c)
			if area < total_area * MIN_AREA_RATIO or area > total_area * MAX_AREA_RATIO:
				continue
			bx, by, bw, bh = cv2.boundingRect(c)
			if bw < 6 or bh < 6:
				continue
			if bw > DETECTION_WIDTH * MAX_BBOX_W_RATIO or bh > DETECTION_HEIGHT * MAX_BBOX_H_RATIO:
				continue
			active_px = int(cv2.countNonZero(motion_mask[by : by + bh, bx : bx + bw]))
			if active_px < min_contour_motion:
				continue
			candidates.append((bx, by, bw, bh, bx + bw * 0.5, by + bh * 0.5, active_px))

		if not candidates:
			return self._decay_and_none()

		self.miss_streak = 0
		max_step = max(DETECTION_WIDTH, DETECTION_HEIGHT) * MAX_STEP_RATIO

		def _score_candidate(cand):
			active_px = float(cand[6])
			if self.last_center is not None:
				dist = math.hypot(cand[4] - self.last_center[0], cand[5] - self.last_center[1])
				if dist <= max_step:
					return active_px * 1.5
			return active_px

		primary = max(candidates, key=_score_candidate)

		# Merge nearby moving contour parts (e.g. leading & trailing edges of the same moving object)
		px1, py1 = primary[0], primary[1]
		px2, py2 = px1 + primary[2], py1 + primary[3]
		merge_pad = 24
		for cand in candidates:
			cx1, cy1 = cand[0], cand[1]
			cx2, cy2 = cx1 + cand[2], cy1 + cand[3]
			if (
				cx1 <= px2 + merge_pad
				and cx2 >= px1 - merge_pad
				and cy1 <= py2 + merge_pad
				and cy2 >= py1 - merge_pad
			):
				px1 = min(px1, cx1)
				py1 = min(py1, cy1)
				px2 = max(px2, cx2)
				py2 = max(py2, cy2)

		bw_merged = px2 - px1
		bh_merged = py2 - py1
		if bw_merged > DETECTION_WIDTH * MAX_BBOX_W_RATIO or bh_merged > DETECTION_HEIGHT * MAX_BBOX_H_RATIO:
			px1, py1, bw_merged, bh_merged = primary[0], primary[1], primary[2], primary[3]

		mcx = px1 + bw_merged * 0.5
		mcy = py1 + bh_merged * 0.5
		self.last_center = (mcx, mcy)
		self.confirm_streak = min(CONFIRM_FRAMES + 2, self.confirm_streak + 1)

		if self.confirm_streak < CONFIRM_FRAMES:
			return None

		scale_x = orig_w / float(DETECTION_WIDTH)
		scale_y = orig_h / float(DETECTION_HEIGHT)
		raw_cx = mcx * scale_x
		raw_cy = mcy * scale_y
		raw_w = bw_merged * scale_x
		raw_h = bh_merged * scale_y

		if self.smooth_bbox is None:
			self.smooth_bbox = (raw_cx, raw_cy, raw_w, raw_h)
		else:
			scx, scy, sw, sh = self.smooth_bbox
			jump = math.hypot(raw_cx - scx, raw_cy - scy)
			if jump > max(orig_w, orig_h) * 0.35:
				self.smooth_bbox = (raw_cx, raw_cy, raw_w, raw_h)
			else:
				if jump > 2.0:
					scx += (raw_cx - scx) * 0.68
					scy += (raw_cy - scy) * 0.68
				sw += (raw_w - sw) * 0.35
				sh += (raw_h - sh) * 0.35
				self.smooth_bbox = (scx, scy, sw, sh)

		scx, scy, sw, sh = self.smooth_bbox
		fx = max(0, int(round(scx - sw * 0.5)))
		fy = max(0, int(round(scy - sh * 0.5)))
		fw_box = max(16, min(orig_w - fx, int(round(sw))))
		fh_box = max(16, min(orig_h - fy, int(round(sh))))
		return (fx, fy, fw_box, fh_box)
