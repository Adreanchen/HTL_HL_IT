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
	Hybrid LEGO Robot & Multi-Horizon Motion Detector optimized for FLL tables.
	Detects and tracks the LEGO robot both when moving across the field and when
	standing stationary (in the corner launch areas or on the mat), while ignoring
	human hands/arms reaching in and returning None when no robot is present.
	"""

	def __init__(self):
		self.kernel_open = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
		self.kernel_dilate = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))
		self.kernel_close = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 15))
		self.kernel_small = np.ones((2, 2), dtype=np.uint8)
		self.kernel_hub = np.ones((3, 3), dtype=np.uint8)
		self.kernel_cluster = np.ones((9, 9), dtype=np.uint8)

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
		if self.miss_streak >= 3:
			self.confirm_streak = 0
			self.last_center = None
			self.smooth_bbox = None
		return None

	def _update_smooth_bbox(self, raw_cx: float, raw_cy: float, raw_w: float, raw_h: float, orig_w: int, orig_h: int):
		self.miss_streak = 0
		self.confirm_streak = max(CONFIRM_FRAMES, self.confirm_streak + 1)
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

	def _detect_stationary_robot(self, table_frame: np.ndarray):
		"""
		Detects a LEGO SPIKE Prime / Technic robot standing on the mat or inside
		any of the white corner launch areas while ignoring printed mat graphics
		and mission models. Returns (x, y, w, h) in table_frame coordinates or None.
		"""
		th, tw = table_frame.shape[:2]
		if th < 32 or tw < 32:
			return None

		gray_full = cv2.cvtColor(table_frame, cv2.COLOR_BGR2GRAY)
		valid_cols = np.where(gray_full.mean(axis=0) > 38)[0]
		valid_rows = np.where(gray_full.mean(axis=1) > 38)[0]
		if len(valid_cols) < 16 or len(valid_rows) < 16:
			ox0, oy0, ox1, oy1 = 0, 0, tw, th
		else:
			ox0, ox1 = int(valid_cols[0]), int(valid_cols[-1] + 1)
			oy0, oy1 = int(valid_rows[0]), int(valid_rows[-1] + 1)

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

		# LEGO SPIKE Prime Medium Azure / Cyan wheel & motor signature
		teal_mask = (
			(H >= 64) & (H <= 108) & (S >= 42) & (V >= 60) & (V <= 215) & (B > R + 10) & (G > R + 8)
		).astype(np.uint8) * 255
		teal_mask = cv2.morphologyEx(teal_mask, cv2.MORPH_OPEN, self.kernel_small)

		# 1. Robot on the mat: solid bright rectangular hub top + adjacent cyan wheel/accents
		hub_mask = ((V >= 208) & (S <= 54) & (R >= 202) & (B >= 188)).astype(np.uint8) * 255
		hub_mask = cv2.morphologyEx(hub_mask, cv2.MORPH_OPEN, self.kernel_hub)

		contours, _ = cv2.findContours(hub_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
		best_box = None
		best_score = 0.0
		for c in contours:
			area = cv2.contourArea(c)
			if area < 150 or area > 1600:
				continue
			x, y, w, h = cv2.boundingRect(c)
			if w < 12 or h < 12 or w > 95 or h > 95:
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
				best_box = (rx0, ry0, rx1 - rx0, ry1 - ry0)

		if best_box is not None:
			bx, by, bw, bh = best_box
			fx = ox0 + int(round(bx * sw / float(W)))
			fy = oy0 + int(round(by * sh / float(H_grid)))
			fw = int(round(bw * sw / float(W)))
			fh = int(round(bh * sh / float(H_grid)))
			return (fx, fy, fw, fh)

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
				clustered = cv2.morphologyEx(teal_in_arc, cv2.MORPH_CLOSE, self.kernel_cluster)
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
				fw = int(round(bw * sw / float(W)))
				fh = int(round(bh * sh / float(H_grid)))
				return (fx, fy, fw, fh)

		return None

	def detect(self, table_frame: np.ndarray):
		orig_h, orig_w = table_frame.shape[:2]
		if orig_h < 16 or orig_w < 16:
			return None

		# 1. Check stationary/visual LEGO robot signature on the table
		stat_box = self._detect_stationary_robot(table_frame)

		# 2. Multi-horizon motion differencing on raw un-enhanced frame
		small = cv2.resize(table_frame, (DETECTION_WIDTH, DETECTION_HEIGHT), interpolation=cv2.INTER_AREA)
		blur = cv2.GaussianBlur(small, (5, 5), 0)

		if not self.history or self.bg_float is None:
			self.history.append(blur)
			self.bg_float = blur.astype(np.float32)
			if stat_box is not None:
				bx, by, bw, bh = stat_box
				rcx, rcy = bx + bw * 0.5, by + bh * 0.5
				self.last_center = (
					rcx * DETECTION_WIDTH / float(orig_w),
					rcy * DETECTION_HEIGHT / float(orig_h),
				)
				return self._update_smooth_bbox(rcx, rcy, float(bw), float(bh), orig_w, orig_h)
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

		motion_mask = cv2.bitwise_and(mask_s, mask_l)

		total_area = float(DETECTION_WIDTH * DETECTION_HEIGHT)
		live_step_px = cv2.countNonZero(mask_1)
		motion_px = cv2.countNonZero(motion_mask)

		if live_step_px < (MIN_MOTION_PIXELS // 2) or motion_px < MIN_MOTION_PIXELS or motion_px > total_area * 0.70:
			if motion_px > total_area * 0.70:
				self.bg_float = blur.astype(np.float32)
			else:
				cv2.accumulateWeighted(blur, self.bg_float, 0.25)

			if stat_box is not None:
				bx, by, bw, bh = stat_box
				rcx, rcy = bx + bw * 0.5, by + bh * 0.5
				self.last_center = (
					rcx * DETECTION_WIDTH / float(orig_w),
					rcy * DETECTION_HEIGHT / float(orig_h),
				)
				return self._update_smooth_bbox(rcx, rcy, float(bw), float(bh), orig_w, orig_h)
			return self._decay_and_none()

		static_mask = cv2.bitwise_not(cv2.dilate(mask_s, self.kernel_open))
		cv2.accumulateWeighted(blur, self.bg_float, 0.12, mask=static_mask)

		# 3. If custom YOLOv8 model is present during active motion, accept only boxes that are actually moving
		min_contour_motion = max(16, int(MIN_MOTION_PIXELS * 0.45))
		if self.yolo_model is not None and torch is not None:
			try:
				with torch.inference_mode():
					res = self.yolo_model.predict(
						source=table_frame,
						device=self.yolo_device,
						conf=0.55,
						iou=0.45,
						imgsz=640,
						verbose=False,
					)
				if res and len(res) > 0 and res[0].boxes is not None and len(res[0].boxes) > 0:
					boxes = res[0].boxes
					xyxy = boxes.xyxy.detach().cpu().numpy()
					confs = boxes.conf.detach().cpu().numpy()
					for idx in np.argsort(-confs):
						x1, y1, x2, y2 = [float(v) for v in xyxy[int(idx)]]
						mx1 = max(0, int(x1 * DETECTION_WIDTH / float(orig_w)))
						my1 = max(0, int(y1 * DETECTION_HEIGHT / float(orig_h)))
						mx2 = min(DETECTION_WIDTH, int(math.ceil(x2 * DETECTION_WIDTH / float(orig_w))))
						my2 = min(DETECTION_HEIGHT, int(math.ceil(y2 * DETECTION_HEIGHT / float(orig_h))))
						if mx2 > mx1 and my2 > my1:
							active_in_yolo = int(cv2.countNonZero(motion_mask[my1:my2, mx1:mx2]))
							if active_in_yolo >= min_contour_motion:
								raw_w = max(16.0, x2 - x1)
								raw_h = max(16.0, y2 - y1)
								raw_cx = x1 + raw_w * 0.5
								raw_cy = y1 + raw_h * 0.5
								self.last_center = (
									raw_cx * DETECTION_WIDTH / float(orig_w),
									raw_cy * DETECTION_HEIGHT / float(orig_h),
								)
								return self._update_smooth_bbox(raw_cx, raw_cy, raw_w, raw_h, orig_w, orig_h)
			except Exception:
				pass

		# Skin mask on downscaled frame to reject human hands/arms reaching in from border
		ycrcb = cv2.cvtColor(small, cv2.COLOR_BGR2YCrCb)
		skin_mask = cv2.inRange(ycrcb, (40, 135, 85), (255, 180, 135))

		mask = cv2.morphologyEx(motion_mask, cv2.MORPH_CLOSE, self.kernel_close)
		contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

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
			touches_border = (
				bx <= 3 or by <= 3 or (bx + bw) >= (DETECTION_WIDTH - 3) or (by + bh) >= (DETECTION_HEIGHT - 3)
			)
			if touches_border:
				skin_px = int(cv2.countNonZero(skin_mask[by : by + bh, bx : bx + bw]))
				if skin_px > (bw * bh) * 0.28 or area > total_area * 0.16:
					continue
			candidates.append((bx, by, bw, bh, bx + bw * 0.5, by + bh * 0.5, active_px))

		if not candidates:
			if stat_box is not None:
				bx, by, bw, bh = stat_box
				rcx, rcy = bx + bw * 0.5, by + bh * 0.5
				self.last_center = (
					rcx * DETECTION_WIDTH / float(orig_w),
					rcy * DETECTION_HEIGHT / float(orig_h),
				)
				return self._update_smooth_bbox(rcx, rcy, float(bw), float(bh), orig_w, orig_h)
			return self._decay_and_none()

		# If visual robot signature is also found, prefer its tight bounding box
		if stat_box is not None:
			bx, by, bw, bh = stat_box
			rcx, rcy = bx + bw * 0.5, by + bh * 0.5
			self.last_center = (
				rcx * DETECTION_WIDTH / float(orig_w),
				rcy * DETECTION_HEIGHT / float(orig_h),
			)
			return self._update_smooth_bbox(rcx, rcy, float(bw), float(bh), orig_w, orig_h)

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

		return self._update_smooth_bbox(raw_cx, raw_cy, raw_w, raw_h, orig_w, orig_h)
