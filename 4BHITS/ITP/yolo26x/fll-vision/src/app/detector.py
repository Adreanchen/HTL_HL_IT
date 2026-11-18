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
	YOLO_CONF,
	YOLO_IMGSZ,
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
		self.yolo_half = False
		if YOLO is not None and torch is not None:
			use_cuda = torch.cuda.is_available()
			self.yolo_device = "cuda:0" if use_cuda else "cpu"
			self.yolo_half = use_cuda
			repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
			candidates = []
			if use_cuda:
				candidates.extend(
					(
						os.path.join(repo_root, "best.engine"),
						os.path.join(repo_root, "models", "best.engine"),
						os.path.join(repo_root, "fll-vision", "best.engine"),
					)
				)
			candidates.extend(
				(
					os.path.join(repo_root, "best.pt"),
					os.path.join(repo_root, "models", "best.pt"),
					os.path.join(repo_root, "fll-vision", "best.pt"),
				)
			)
			for cand_path in candidates:
				if os.path.isfile(cand_path):
					try:
						self.yolo_model = YOLO(cand_path, task="detect")
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
			(H >= 85) & (H <= 108) & (S >= 65) & (V >= 60) & (V <= 215) & (B > R + 10) & (G > R + 8)
		).astype(np.uint8) * 255
		teal_mask = cv2.morphologyEx(teal_mask, cv2.MORPH_OPEN, self.kernel_small)
		teal_strong = (
			(H >= 85) & (H <= 108) & (S >= 115) & (V >= 60) & (V <= 215) & (B > R + 18) & (G > R + 15)
		).astype(np.uint8) * 255
		teal_strong = cv2.morphologyEx(teal_strong, cv2.MORPH_OPEN, self.kernel_small)

		# 1. Robot on the mat: solid bright rectangular hub top + adjacent cyan wheel/accents
		mean_v = float(V.mean())
		v_th_list = (228,) if mean_v > 192.0 else (228, 208)
		best_box = None
		best_score = 0.0
		for v_th in v_th_list:
			hub_mask = ((V >= v_th) & (S <= 54) & (R >= v_th - 6) & (B >= v_th - 20)).astype(np.uint8) * 255
			hub_mask = cv2.morphologyEx(hub_mask, cv2.MORPH_OPEN, self.kernel_hub)

			contours, _ = cv2.findContours(hub_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
			for c in contours:
				area = cv2.contourArea(c)
				if area < 95 or area > 1600:
					continue
				x, y, w, h = cv2.boundingRect(c)
				if w < 10 or h < 10 or w > 95 or h > 95:
					continue
				if x <= 18 or (x + w) >= (W - 18):
					continue
				if v_th == 228 and mean_v <= 192.0 and x < 120 and y < 140:
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
				if float(np.percentile(center_v, 15)) < max(175.0, float(v_th - 23)) or float(center_v.mean()) < float(
					v_th + (2 if v_th == 228 else 1)
				):
					continue
				x0, y0 = max(0, x - 18), max(0, y - 18)
				x1, y1 = min(W, x + w + 18), min(H_grid, y + h + 18)
				teal_near = int(np.count_nonzero(teal_mask[y0:y1, x0:x1]))
				teal_strong_near = int(np.count_nonzero(teal_strong[y0:y1, x0:x1]))
				has_strong_teal = teal_near >= 28 and teal_strong_near >= (145 if v_th == 228 else 130)
				has_large_hub_teal = (
					v_th == 228
					and 360 <= area <= 620
					and 22 <= w <= 36
					and 22 <= h <= 36
					and solidity >= 0.84
					and aspect <= 1.25
					and x > 25
					and (x + w) < (W - 25)
					and y > 155
					and teal_near >= 90
					and teal_strong_near >= 28
				)
				if not (has_strong_teal or has_large_hub_teal):
					continue
				rx0, ry0 = max(0, x - 12), max(0, y - 10)
				rx1, ry1 = min(W, x + w + 16), min(H_grid, y + h + 20)
				if rx1 - rx0 < 42:
					if rx1 >= W - 4:
						rx0 = max(0, rx1 - 42)
					else:
						rx1 = min(W, rx0 + 42)
				score = float(max(teal_strong_near, teal_near // 2)) * solidity
				if score > best_score:
					best_score = score
					best_box = (rx0, ry0, rx1 - rx0, ry1 - ry0)
			if best_box is not None:
				break

		if best_box is not None:
			bx, by, bw, bh = best_box
			fx = ox0 + int(round(bx * sw / float(W)))
			fy = oy0 + int(round(by * sh / float(H_grid)))
			fw = int(round(bw * sw / float(W)))
			fh = int(round(bh * sh / float(H_grid)))
			return (fx, fy, fw, fh)

		# 2. Robot inside the white quarter-circle corner launch areas (located on the outer side of the table)
		wf_left = (
			np.count_nonzero((V[0:150, 0:135] > 195) & (S[0:150, 0:135] < 42))
			+ np.count_nonzero((V[H_grid - 150 : H_grid, 0:135] > 195) & (S[H_grid - 150 : H_grid, 0:135] < 42))
		)
		wf_right = (
			np.count_nonzero((V[0:150, W - 135 : W] > 195) & (S[0:150, W - 135 : W] < 42))
			+ np.count_nonzero((V[H_grid - 150 : H_grid, W - 135 : W] > 195) & (S[H_grid - 150 : H_grid, W - 135 : W] < 42))
		)
		w_mat = (V > 185) & (S < 45)
		outer_w = w_mat[:, :120] if wf_left >= wf_right else w_mat[:, W - 120 :]
		w_rows = np.where(outer_w.sum(axis=1) > 15)[0]
		y_bot = int(w_rows[-1]) + 1 if len(w_rows) > 0 and w_rows[-1] > H_grid - 80 else H_grid
		if wf_left >= wf_right:
			corners = (
				(0, 135, 0, 150, 0, 0),
				(0, 135, max(0, y_bot - 150), y_bot, 0, y_bot),
			)
		else:
			corners = (
				(W - 135, W, 0, 150, W, 0),
				(W - 135, W, max(0, y_bot - 150), y_bot, W, y_bot),
			)
		best_corner = None
		best_corner_cnt = 0
		for x0, x1, y0, y1, cx_c, cy_c in corners:
			ch, cs, cv_ = H[y0:y1, x0:x1], S[y0:y1, x0:x1], V[y0:y1, x0:x1]
			white_frac = (
				np.count_nonzero((cv_ > 195) & (cs < 42)) / float(max(1, ch.size))
				if y0 == 0
				else np.count_nonzero((cv_ > 185) & (cs < 45)) / float(max(1, ch.size))
			)
			if white_frac < (0.28 if y0 == 0 else 0.25):
				continue
			yy, xx = np.mgrid[y0:y1, x0:x1]
			dist = np.hypot(xx - cx_c, yy - cy_c)
			max_arc_r = 118 if (x0 == 0 and y0 < 200) else 136
			in_arc = ((dist > 14) & (dist < max_arc_r)).astype(np.uint8) * 255
			teal_in_arc = cv2.bitwise_and(teal_strong[y0:y1, x0:x1], in_arc)
			teal_cnt = int(np.count_nonzero(teal_in_arc))
			if x0 == 0:
				min_corner_teal = 220 if y0 < 200 else 105
			else:
				min_corner_teal = 135 if y0 < 200 else 75
			if teal_cnt >= min_corner_teal and teal_cnt > best_corner_cnt:
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
				best_corner_cnt = teal_cnt
				best_corner = (fx, fy, fw, fh)

		return best_corner

	def detect(self, table_frame: np.ndarray):
		orig_h, orig_w = table_frame.shape[:2]
		if orig_h < 16 or orig_w < 16:
			return None

		# 1. Check stationary/visual LEGO robot signature on the table
		stat_box = self._detect_stationary_robot(table_frame)

		# 2. Multi-horizon motion differencing on raw un-enhanced frame
		small = cv2.resize(table_frame, (DETECTION_WIDTH, DETECTION_HEIGHT), interpolation=cv2.INTER_AREA)
		blur = cv2.GaussianBlur(small, (5, 5), 0)

		total_area = float(DETECTION_WIDTH * DETECTION_HEIGHT)
		first_frame = False
		if not self.history or self.bg_float is None:
			first_frame = True
			self.history.append(blur)
			self.bg_float = blur.astype(np.float32)
			motion_mask = np.zeros((DETECTION_HEIGHT, DETECTION_WIDTH), dtype=np.uint8)
			low_motion = True
		else:
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

			live_step_px = cv2.countNonZero(mask_1)
			motion_px = cv2.countNonZero(motion_mask)
			low_motion = (
				live_step_px < (MIN_MOTION_PIXELS // 2)
				or motion_px < MIN_MOTION_PIXELS
				or motion_px > total_area * 0.70
			)
			if low_motion:
				if motion_px > total_area * 0.70:
					self.bg_float = blur.astype(np.float32)
				else:
					cv2.accumulateWeighted(blur, self.bg_float, 0.25)
			else:
				static_mask = cv2.bitwise_not(cv2.dilate(mask_s, self.kernel_open))
				cv2.accumulateWeighted(blur, self.bg_float, 0.12, mask=static_mask)

		# 3. Primary YOLO26x detector (detects both moving and stationary LEGO robots while rejecting hands)
		if self.yolo_model is not None and torch is not None:
			try:
				with torch.inference_mode():
					res = self.yolo_model.predict(
						source=table_frame,
						device=self.yolo_device,
						conf=YOLO_CONF,
						nms=False,
						imgsz=YOLO_IMGSZ,
						half=self.yolo_half,
						verbose=False,
					)
				if res and len(res) > 0 and res[0].boxes is not None and len(res[0].boxes) > 0:
					boxes = res[0].boxes
					xyxy = boxes.xyxy.detach().cpu().numpy()
					confs = boxes.conf.detach().cpu().numpy()
					for idx in np.argsort(-confs):
						x1, y1, x2, y2 = [float(v) for v in xyxy[int(idx)]]
						ix1 = max(0, min(orig_w - 1, int(round(x1))))
						iy1 = max(0, min(orig_h - 1, int(round(y1))))
						ix2 = max(ix1 + 1, min(orig_w, int(round(x2))))
						iy2 = max(iy1 + 1, min(orig_h, int(round(y2))))
						area = float((ix2 - ix1) * (iy2 - iy1))
						if area < (orig_w * orig_h) * MIN_AREA_RATIO or area > (orig_w * orig_h) * MAX_AREA_RATIO:
							continue
						crop = table_frame[iy1:iy2, ix1:ix2]
						ycrcb_c = cv2.cvtColor(crop, cv2.COLOR_BGR2YCrCb)
						hsv_c = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
						skin_c = cv2.bitwise_and(
							cv2.inRange(ycrcb_c, (40, 133, 77), (255, 177, 127)),
							cv2.inRange(hsv_c, (0, 25, 50), (22, 180, 255)),
						)
						true_skin_c = cv2.bitwise_and(
							cv2.inRange(ycrcb_c, (40, 138, 77), (255, 177, 127)),
							cv2.inRange(hsv_c, (0, 30, 50), (17, 180, 255)),
						)
						skin_px = int(cv2.countNonZero(skin_c))
						skin_ratio = skin_px / area
						true_skin_ratio = int(cv2.countNonZero(true_skin_c)) / area
						cyan_strong = cv2.countNonZero(cv2.inRange(hsv_c, (85, 110, 55), (108, 255, 255)))
						cyan_med = cv2.countNonZero(cv2.inRange(hsv_c, (85, 65, 55), (108, 255, 255)))
						cyan_ratio = cyan_strong / area
						cyan_med_ratio = cyan_med / area
						white_px = cv2.countNonZero(cv2.inRange(hsv_c, (0, 0, 135), (180, 50, 255)))
						white_ratio = white_px / area
						near_border = (
							ix1 < int(orig_w * 0.08)
							or ix2 > int(orig_w * 0.92)
							or iy1 < int(orig_h * 0.06)
							or iy2 > int(orig_h * 0.92)
						)
						has_spike_robot_sig = (
							(cyan_ratio >= 0.02 or cyan_med_ratio >= 0.025)
							and white_ratio >= 0.25
							and (true_skin_ratio <= 0.26 or not near_border)
						)
						if skin_ratio > 0.22 and not has_spike_robot_sig:
							continue
						px1, py1 = max(0, ix1 - 25), max(0, iy1 - 25)
						px2, py2 = min(orig_w, ix2 + 25), min(orig_h, iy2 + 25)
						pad_crop = table_frame[py1:py2, px1:px2]
						pad_ycrcb = cv2.cvtColor(pad_crop, cv2.COLOR_BGR2YCrCb)
						pad_hsv = cv2.cvtColor(pad_crop, cv2.COLOR_BGR2HSV)
						pad_skin = cv2.bitwise_and(
							cv2.inRange(pad_ycrcb, (40, 133, 77), (255, 177, 127)),
							cv2.inRange(pad_hsv, (0, 25, 50), (22, 180, 255)),
						)
						pad_skin_ratio = cv2.countNonZero(pad_skin) / area
						if pad_skin_ratio > 0.06 and cyan_ratio < 0.025:
							continue
						on_left_border = ix1 < int(orig_w * 0.06)
						if near_border and cyan_ratio < 0.025 and (pad_skin_ratio > 0.05 or on_left_border):
							continue
						if not near_border and skin_ratio > 0.08 and cyan_ratio < 0.02 and white_ratio < 0.15:
							continue
						cyan_px = cv2.countNonZero(cv2.inRange(hsv_c, (82, 60, 55), (106, 255, 255)))
						if white_ratio < 0.08 and (cyan_px / area) < 0.03:
							continue
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

		if low_motion:
			if stat_box is not None:
				bx, by, bw, bh = stat_box
				rcx, rcy = bx + bw * 0.5, by + bh * 0.5
				self.last_center = (
					rcx * DETECTION_WIDTH / float(orig_w),
					rcy * DETECTION_HEIGHT / float(orig_h),
				)
				return self._update_smooth_bbox(rcx, rcy, float(bw), float(bh), orig_w, orig_h)
			if first_frame:
				return None
			return self._decay_and_none()

		min_contour_motion = max(16, int(MIN_MOTION_PIXELS * 0.45))

		# Skin mask on downscaled frame to reject human hands/arms reaching in from border
		ycrcb = cv2.cvtColor(small, cv2.COLOR_BGR2YCrCb)
		hsv_small = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
		skin_mask = cv2.bitwise_and(
			cv2.inRange(ycrcb, (40, 133, 77), (255, 177, 127)),
			cv2.inRange(hsv_small, (0, 25, 50), (22, 180, 255)),
		)
		true_skin_mask = cv2.bitwise_and(
			cv2.inRange(ycrcb, (40, 138, 77), (255, 177, 127)),
			cv2.inRange(hsv_small, (0, 30, 50), (17, 180, 255)),
		)
		cyan_small = cv2.inRange(hsv_small, (85, 115, 60), (108, 255, 255))
		wg_small = cv2.inRange(hsv_small, (0, 0, 145), (180, 45, 255))
		dk_small = cv2.inRange(hsv_small, (0, 0, 0), (180, 255, 75))

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
			if bw > DETECTION_WIDTH * 0.38 or bh > DETECTION_HEIGHT * 0.28:
				continue
			active_px = int(cv2.countNonZero(motion_mask[by : by + bh, bx : bx + bw]))
			if active_px < min_contour_motion:
				continue
			b_area = float(max(1, bw * bh))
			sx0, sy0 = max(0, bx - 22), max(0, by - 22)
			sx1, sy1 = min(DETECTION_WIDTH, bx + bw + 22), min(DETECTION_HEIGHT, by + bh + 22)
			skin_near = int(cv2.countNonZero(skin_mask[sy0:sy1, sx0:sx1]))
			true_skin_near = int(cv2.countNonZero(true_skin_mask[sy0:sy1, sx0:sx1]))
			cyan_px = int(cv2.countNonZero(cyan_small[by : by + bh, bx : bx + bw]))
			wg_px = int(cv2.countNonZero(wg_small[by : by + bh, bx : bx + bw]))
			dk_px = int(cv2.countNonZero(dk_small[by : by + bh, bx : bx + bw]))
			touches_border = (
				bx <= 18 or by <= 18 or (bx + bw) >= (DETECTION_WIDTH - 22) or (by + bh) >= (DETECTION_HEIGHT - 18)
			)
			if true_skin_near > b_area * 0.04 and cyan_px < b_area * 0.04:
				continue
			if touches_border and (skin_near > b_area * 0.02 or cyan_px < b_area * 0.035):
				continue
			if dk_px > b_area * 0.45 and cyan_px < b_area * 0.03:
				continue
			if cyan_px < b_area * 0.03 and (wg_px < b_area * 0.22 or dk_px < b_area * 0.04):
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
