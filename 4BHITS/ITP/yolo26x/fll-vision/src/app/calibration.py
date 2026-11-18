from copy import deepcopy
import cv2
import numpy as np


DEFAULT_TABLE_ROIS = {
	"left": {"x1": 0.0, "y1": 0.0, "x2": 0.5, "y2": 1.0},
	"right": {"x1": 0.5, "y1": 0.0, "x2": 1.0, "y2": 1.0},
}


def _clamp_box(box: dict, fallback: dict) -> dict:
	try:
		x1 = max(0.0, min(0.96, float(box.get("x1", fallback["x1"]))))
		y1 = max(0.0, min(0.96, float(box.get("y1", fallback["y1"]))))
		x2 = max(0.04, min(1.0, float(box.get("x2", fallback["x2"]))))
		y2 = max(0.04, min(1.0, float(box.get("y2", fallback["y2"]))))
	except Exception:
		return deepcopy(fallback)

	if x1 > x2:
		x1, x2 = x2, x1
	if y1 > y2:
		y1, y2 = y2, y1

	if (x2 - x1) < 0.08 or (y2 - y1) < 0.12:
		return deepcopy(fallback)

	return {
		"x1": round(x1, 4),
		"y1": round(y1, 4),
		"x2": round(x2, 4),
		"y2": round(y2, 4),
	}


def sanitize_table_rois(rois: dict) -> dict:
	if not isinstance(rois, dict):
		return deepcopy(DEFAULT_TABLE_ROIS)
	return {
		"left": _clamp_box(rois.get("left") or {}, DEFAULT_TABLE_ROIS["left"]),
		"right": _clamp_box(rois.get("right") or {}, DEFAULT_TABLE_ROIS["right"]),
	}


def _find_runs(profile: np.ndarray, thresh: float, max_gap: int = 3, min_len: int = 2):
	indices = np.where(profile >= thresh)[0]
	runs = []
	for idx in indices:
		i = int(idx)
		if not runs or i > runs[-1][1] + max_gap:
			runs.append([i, i])
		else:
			runs[-1][1] = i
	return [r for r in runs if (r[1] - r[0] + 1) >= min_len]


def detect_table_rois(frame: np.ndarray) -> dict:
	"""
	Detects the inner playable bounds of the Left (Red) and Right (Blue) FLL tables
	from a single camera frame. Handles off-screen corners and partial occlusions cleanly.
	"""
	if frame is None or frame.size == 0:
		return deepcopy(DEFAULT_TABLE_ROIS)

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
	v_runs = _find_runs(col_wood, 0.40, max_gap=4, min_len=min_rail_w)

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
		h_runs = _find_runs(smooth_wood, 0.40, max_gap=3, min_len=min_rail_h)

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

	# For automatic detection, fall back cleanly if either detected region is implausibly small
	if (lx2 - lx1) < 0.20 or (rx2 - rx1) < 0.20 or (ly2 - ly1) < 0.40 or (ry2 - ry1) < 0.40:
		return deepcopy(DEFAULT_TABLE_ROIS)

	return sanitize_table_rois(
		{
			"left": {"x1": lx1, "y1": ly1, "x2": lx2, "y2": ly2},
			"right": {"x1": rx1, "y1": ry1, "x2": rx2, "y2": ry2},
		}
	)


def encode_raw_frame_jpeg(frame: np.ndarray, max_width: int = 960) -> bytes:
	"""Encodes a single clean uncropped camera frame for the interactive manual table editor."""
	h, w = frame.shape[:2]
	if w > max_width:
		scale = max_width / float(w)
		vis = cv2.resize(frame, (max_width, max(64, int(h * scale))), interpolation=cv2.INTER_AREA)
	else:
		vis = frame
	ok, jpeg = cv2.imencode(".jpg", vis, [int(cv2.IMWRITE_JPEG_QUALITY), 82])
	return jpeg.tobytes() if ok else b""


def render_calibration_preview_jpeg(frame: np.ndarray, rois: dict) -> bytes:
	"""Draws the locked Left (Red) and Right (Blue) table regions onto a single preview JPEG."""
	h, w = frame.shape[:2]
	scale = min(1.0, 800.0 / max(1, w))
	pw, ph = max(64, int(w * scale)), max(64, int(h * scale))
	vis = cv2.resize(frame, (pw, ph), interpolation=cv2.INTER_AREA)

	dimmed = (vis.astype(np.float32) * 0.35).astype(np.uint8)

	clean = sanitize_table_rois(rois)
	for side, color, label in [
		("left", (36, 28, 237), "RED TABLE"),
		("right", (206, 114, 0), "BLUE TABLE"),
	]:
		b = clean[side]
		x1, y1 = int(b["x1"] * pw), int(b["y1"] * ph)
		x2, y2 = int(b["x2"] * pw), int(b["y2"] * ph)
		dimmed[y1:y2, x1:x2] = vis[y1:y2, x1:x2]
		cv2.rectangle(dimmed, (x1, y1), (max(x1 + 1, x2 - 1), max(y1 + 1, y2 - 1)), color, 2)
		cv2.rectangle(dimmed, (x1, y1), (min(pw, x1 + 118), min(ph, y1 + 24)), color, -1)
		cv2.putText(
			dimmed,
			label,
			(x1 + 7, y1 + 17),
			cv2.FONT_HERSHEY_SIMPLEX,
			0.5,
			(255, 255, 255),
			1,
			cv2.LINE_AA,
		)

	ok, jpeg = cv2.imencode(".jpg", dimmed, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
	return jpeg.tobytes() if ok else b""
