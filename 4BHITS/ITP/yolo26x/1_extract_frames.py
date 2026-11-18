"""
1_extract_frames.py
-------------------
Extracts frames from a single FLL match recording (`--video`) or a directory of
recordings (`--video-dir videos`), with optional automated LEGO robot bounding-box
labeling (`--auto-label`) to build a complete YOLO26x training & validation dataset
in `dataset/train/` and `dataset/valid/`.

Usage:
    # Batch extract & auto-label all videos in videos/ into dataset/train & dataset/valid:
    python 1_extract_frames.py --video-dir videos --auto-label

    # Single video raw frame extraction to dataset/raw/:
    python 1_extract_frames.py --video match.mp4 --interval 10 --output dataset/raw
"""

import argparse
import glob
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import cv2
import numpy as np

DEFAULT_VIDEO_PATH = "match.mp4"
DEFAULT_VIDEO_DIR = "videos"
DEFAULT_OUTPUT_DIR = os.path.join("dataset", "raw")
DEFAULT_DATASET_DIR = "dataset"
DEFAULT_FRAME_INTERVAL = 10
DEFAULT_AUTO_LABEL_INTERVAL = 40
DEFAULT_JPEG_QUALITY = 95

# Playable inner FLL table regions in 1280x720 dual-table overhead view
LEFT_TABLE_INNER = (330, 108, 646, 678)
RIGHT_TABLE_INNER = (682, 108, 1016, 686)
WATER_BOTTLE_EXCLUSION = (330, 195, 385, 265)

# Single-table crop regions (for training YOLO26x on both dual-table and single-table views)
LEFT_TABLE_CROP = (320, 50, 656, 695)
RIGHT_TABLE_CROP = (672, 50, 1026, 695)


def find_default_video(preferred_path: str) -> str:
	"""Returns the preferred video path if it exists, or searches the workspace for an .mp4 file."""
	if os.path.isfile(preferred_path):
		return preferred_path

	for root_dir in (".", "videos", "fll-vision"):
		if not os.path.isdir(root_dir):
			continue
		for fname in sorted(os.listdir(root_dir)):
			if fname.lower().endswith(".mp4"):
				candidate = os.path.join(root_dir, fname)
				if os.path.isfile(candidate):
					return candidate
	return preferred_path


def extract_frames(
	video_path: str,
	output_dir: str = DEFAULT_OUTPUT_DIR,
	frame_interval: int = DEFAULT_FRAME_INTERVAL,
	prefix: str = "fll_frame",
	jpeg_quality: int = DEFAULT_JPEG_QUALITY,
) -> int:
	"""
	Reads an input video (.mp4) and saves every Nth frame to `output_dir`.
	Returns the total number of saved frames.
	"""
	if frame_interval < 1:
		raise ValueError(f"Frame interval must be >= 1 (got {frame_interval}).")

	out_path = Path(output_dir)
	out_path.mkdir(parents=True, exist_ok=True)

	if not os.path.isfile(video_path):
		raise FileNotFoundError(
			f"Input video not found at '{video_path}'.\n"
			f"Place your video file at '{video_path}' or run:\n"
			f"  python 1_extract_frames.py --video path/to/your_video.mp4"
		)

	cap = cv2.VideoCapture(video_path)
	if not cap.isOpened():
		raise RuntimeError(f"OpenCV could not open video file: '{video_path}'. Check codec/file integrity.")

	total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
	fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
	width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
	height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)

	print(f"[INFO] Opened video : {video_path}")
	print(f"[INFO] Resolution   : {width}x{height} @ {fps:.2f} FPS ({total_frames} total frames)")
	print(f"[INFO] Output folder: {out_path.resolve()}")
	print(f"[INFO] Extracting every {frame_interval}th frame...")

	encode_params = [int(cv2.IMWRITE_JPEG_QUALITY), int(max(50, min(100, jpeg_quality)))]
	frame_idx = 0
	saved_count = 0
	consecutive_read_failures = 0

	try:
		while True:
			ret, frame = cap.read()
			if not ret or frame is None:
				consecutive_read_failures += 1
				if total_frames > 0 and frame_idx < total_frames - 1 and consecutive_read_failures <= 5:
					frame_idx += 1
					continue
				break

			consecutive_read_failures = 0

			if frame_idx % frame_interval == 0:
				filename = f"{prefix}_{frame_idx:06d}.jpg"
				file_dest = out_path / filename
				ok = cv2.imwrite(str(file_dest), frame, encode_params)
				if not ok:
					print(f"[WARN] Failed to write frame {frame_idx} to {file_dest}", file=sys.stderr)
				else:
					saved_count += 1
					if saved_count % 25 == 0:
						progress = (
							f" ({(frame_idx / total_frames) * 100:.1f}%)"
							if total_frames > 0
							else ""
						)
						print(f"[INFO] Saved {saved_count} frames (at frame #{frame_idx}{progress})...")

			frame_idx += 1

	except KeyboardInterrupt:
		print("\n[INFO] Frame extraction interrupted by user. Closing video safely...")
	finally:
		cap.release()

	print(f"[SUCCESS] Extracted {saved_count} frames into '{out_path.resolve()}'.")
	return saved_count


def clean_launch_corners_in_median(med: np.ndarray, frames: List[np.ndarray]) -> np.ndarray:
	"""
	Replaces the bottom-left and bottom-right white launch corners in a median background
	with the median of the cleanest empty-corner frames (maximizing white mat pixels and
	penalizing cyan robot pixels, dark tire pixels, and human skin pixels).
	"""
	if len(frames) < 3:
		return med
	cleaned = med.copy()
	for (x1, y1, x2, y2) in [(920, 500, 1020, 650), (295, 540, 405, 678)]:
		scored: List[Tuple[int, np.ndarray]] = []
		for f in frames:
			patch = f[y1:y2, x1:x2]
			hsv_p = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
			ycrcb_p = cv2.cvtColor(patch, cv2.COLOR_BGR2YCrCb)
			white_px = cv2.countNonZero(cv2.inRange(hsv_p, (0, 0, 155), (180, 42, 255)))
			vcyan_px = cv2.countNonZero(cv2.inRange(hsv_p, (85, 85, 45), (112, 255, 255)))
			dark_px = cv2.countNonZero(cv2.inRange(hsv_p, (0, 0, 0), (180, 255, 80)))
			skin_px = cv2.countNonZero(
				cv2.bitwise_and(
					cv2.inRange(ycrcb_p, (40, 133, 77), (255, 177, 127)),
					cv2.inRange(hsv_p, (0, 25, 50), (22, 180, 255)),
				)
			)
			score = white_px - 4 * vcyan_px - 2 * dark_px - 6 * skin_px
			scored.append((score, patch))
		scored.sort(key=lambda item: item[0], reverse=True)
		top_k = [p for _, p in scored[:3]]
		cleaned[y1:y2, x1:x2] = np.median(np.stack(top_k, axis=0), axis=0).astype(np.uint8)
	return cleaned


def compute_dual_exposure_backgrounds(video_paths: List[str]) -> Tuple[np.ndarray, np.ndarray]:
	"""
	Samples frames across all input videos matching the primary camera alignment and computes
	two reference median background images grouped by ambient room brightness (`frame.mean() < 122.5` vs `>= 122.5`).
	"""
	dark_samples: List[np.ndarray] = []
	bright_samples: List[np.ndarray] = []
	ref_first_frame: Optional[np.ndarray] = None

	print(f"[AUTO-LABEL] Computing dual-exposure reference backgrounds across {len(video_paths)} video(s)...")
	for vpath in video_paths:
		cap = cv2.VideoCapture(vpath)
		if not cap.isOpened():
			continue
		total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
		sample_indices = (
			[int(total * 0.10), int(total * 0.50), int(total * 0.85)]
			if total >= 10
			else [0]
		)
		for fidx in sample_indices:
			cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, fidx))
			ret, frame = cap.read()
			if ret and frame is not None:
				if ref_first_frame is None:
					ref_first_frame = frame.copy()
				else:
					# Compare static inner-right mat region (normalized for exposure) to detect shifted camera/mat framing
					f_roi = frame[120:340, 685:875].astype(np.float32)
					r_roi = ref_first_frame[120:340, 685:875].astype(np.float32)
					f_scaled = f_roi * (float(r_roi.mean()) / max(1.0, float(f_roi.mean())))
					align_diff = float(np.max(np.abs(f_scaled - r_roi), axis=2).mean())
					if align_diff > 28.0:
						break
				if float(frame.mean()) < 122.5:
					dark_samples.append(frame)
				else:
					bright_samples.append(frame)
		cap.release()

	if not dark_samples and not bright_samples:
		raise RuntimeError("Could not read any valid frames from the provided videos.")

	if dark_samples and bright_samples:
		med_dark = np.median(np.stack(dark_samples, axis=0), axis=0).astype(np.uint8)
		med_bright = np.median(np.stack(bright_samples, axis=0), axis=0).astype(np.uint8)
	elif dark_samples:
		med_dark = np.median(np.stack(dark_samples, axis=0), axis=0).astype(np.uint8)
		med_bright = med_dark.copy()
	else:
		med_bright = np.median(np.stack(bright_samples, axis=0), axis=0).astype(np.uint8)
		med_dark = med_bright.copy()

	print(
		f"[AUTO-LABEL] Primary background models ready "
		f"(dark samples: {len(dark_samples)}, bright samples: {len(bright_samples)})."
	)
	return med_dark, med_bright


def get_video_background_models(
	vpath: str,
	default_dark: np.ndarray,
	default_bright: np.ndarray,
) -> Tuple[np.ndarray, np.ndarray]:
	"""
	Returns `(default_dark, default_bright)` if `vpath` shares the primary camera/table
	alignment, or computes dedicated ghost-free dual-exposure median backgrounds for `vpath`
	when its camera/mat framing differs (such as `videobombe.mp4`).
	"""
	cap = cv2.VideoCapture(vpath)
	if not cap.isOpened():
		return default_dark, default_bright
	ret, first_frame = cap.read()
	if not ret or first_frame is None:
		cap.release()
		return default_dark, default_bright

	roi = slice(120, 340), slice(685, 875)
	diff_d = float(np.max(cv2.absdiff(first_frame[roi], default_dark[roi]), axis=2).mean())
	diff_b = float(np.max(cv2.absdiff(first_frame[roi], default_bright[roi]), axis=2).mean())
	if min(diff_d, diff_b) <= 25.0:
		cap.release()
		return default_dark, default_bright

	total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
	step = max(1, total // 60) if total > 60 else 1
	dark_frames: List[np.ndarray] = []
	bright_frames: List[np.ndarray] = []

	cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
	fidx = 0
	while True:
		ok = cap.grab()
		if not ok:
			break
		if fidx % step == 0:
			ret_f, f = cap.retrieve()
			if ret_f and f is not None:
				if float(f.mean()) < 122.5:
					dark_frames.append(f)
				else:
					bright_frames.append(f)
		fidx += 1
	cap.release()

	if dark_frames and bright_frames:
		v_dark = clean_launch_corners_in_median(
			np.median(np.stack(dark_frames, axis=0), axis=0).astype(np.uint8), dark_frames
		)
		v_bright = clean_launch_corners_in_median(
			np.median(np.stack(bright_frames, axis=0), axis=0).astype(np.uint8), bright_frames
		)
	elif dark_frames:
		v_dark = clean_launch_corners_in_median(
			np.median(np.stack(dark_frames, axis=0), axis=0).astype(np.uint8), dark_frames
		)
		v_bright = v_dark.copy()
	elif bright_frames:
		v_bright = clean_launch_corners_in_median(
			np.median(np.stack(bright_frames, axis=0), axis=0).astype(np.uint8), bright_frames
		)
		v_dark = v_bright.copy()
	else:
		return default_dark, default_bright

	print(
		f"[AUTO-LABEL] Dedicated dual-exposure background built for {Path(vpath).name} "
		f"(dark samples: {len(dark_frames)}, bright samples: {len(bright_frames)})."
	)
	return v_dark, v_bright


def build_playable_table_mask(height: int, width: int) -> np.ndarray:
	"""Builds the binary mask for the inner playable Left and Right FLL tables."""
	mask = np.zeros((height, width), dtype=np.uint8)
	lx1, ly1, lx2, ly2 = LEFT_TABLE_INNER
	rx1, ry1, rx2, ry2 = RIGHT_TABLE_INNER
	wx1, wy1, wx2, wy2 = WATER_BOTTLE_EXCLUSION

	mask[max(0, ly1):min(height, ly2), max(0, lx1):min(width, lx2)] = 255
	mask[max(0, ry1):min(height, ry2), max(0, rx1):min(width, rx2)] = 255
	mask[max(0, wy1):min(height, wy2), max(0, wx1):min(width, wx2)] = 0
	return mask


def detect_lego_robots_in_frame(
	frame: np.ndarray,
	med_dark: np.ndarray,
	med_bright: np.ndarray,
	med_dark_blur: np.ndarray,
	med_bright_blur: np.ndarray,
	med_dark_hsv: np.ndarray,
	med_bright_hsv: np.ndarray,
	table_mask: np.ndarray,
) -> Tuple[List[Tuple[int, int, int, int]], int]:
	"""
	Detects LEGO robots on the playable FLL tables using brightness-matched background
	subtraction, shadow suppression, skin-pixel subtraction, and LEGO visual signature
	verification.

	Returns:
		boxes: List of (x1, y1, x2, y2) bounding boxes in full-frame pixel coordinates.
		fg_skin_pixels: Count of foreground skin pixels on the table (used to select
		                hard-negative hand/arm frames when no robot is present).
	"""
	is_dark = float(frame.mean()) < 122.5
	med_blur = med_dark_blur if is_dark else med_bright_blur
	med_hsv = med_dark_hsv if is_dark else med_bright_hsv

	blur = cv2.GaussianBlur(frame, (5, 5), 0)
	diff = np.max(cv2.absdiff(blur, med_blur), axis=2)

	hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
	ycrcb = cv2.cvtColor(frame, cv2.COLOR_BGR2YCrCb)

	# Suppress cast shadows where brightness drops moderately without a hue change
	v_ratio = hsv[:, :, 2].astype(np.float32) / np.maximum(1.0, med_hsv[:, :, 2].astype(np.float32))
	h_abs = np.abs(hsv[:, :, 0].astype(np.int16) - med_hsv[:, :, 0].astype(np.int16))
	h_diff = np.minimum(h_abs, 180 - h_abs)
	is_shadow = (v_ratio >= 0.54) & (v_ratio < 0.88) & (h_diff < 14) & (diff < 52)

	_, fg = cv2.threshold(diff, 26, 255, cv2.THRESH_BINARY)
	fg[is_shadow] = 0
	fg = cv2.bitwise_and(fg, table_mask)

	# Subtract dilated human skin pixels so hands touching/launching a robot do not merge
	skin_broad = cv2.bitwise_and(
		cv2.inRange(ycrcb, (40, 133, 77), (255, 177, 127)),
		cv2.inRange(hsv, (0, 25, 50), (22, 180, 255)),
	)
	skin_fg = cv2.bitwise_and(
		cv2.inRange(ycrcb, (40, 135, 77), (255, 177, 127)),
		cv2.inRange(hsv, (0, 32, 50), (19, 180, 255)),
	)
	fg_skin_pixels = int(cv2.countNonZero(cv2.bitwise_and(skin_broad, fg)))
	skin_dilated = cv2.dilate(skin_fg, np.ones((5, 5), np.uint8))
	fg = cv2.bitwise_and(fg, cv2.bitwise_not(skin_dilated))

	fg = cv2.morphologyEx(fg, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)))
	fg = cv2.morphologyEx(fg, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (13, 13)))

	cnts, _ = cv2.findContours(fg, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
	scored_boxes: List[Tuple[float, Tuple[int, int, int, int]]] = []

	for c in cnts:
		area = float(cv2.contourArea(c))
		if area < 500.0 or area > 11500.0:
			continue
		x, y, w, h = cv2.boundingRect(c)
		if w < 26 or h < 26 or w > 135 or h > 135:
			continue
		if max(w, h) / float(min(w, h)) > 2.3:
			continue

		x1, y1, x2, y2 = x, y, x + w, y + h
		crop_diff = diff[y1:y2, x1:x2]
		if float(crop_diff.mean()) < 22.0:
			continue

		crop_hsv = hsv[y1:y2, x1:x2]
		crop_med_hsv = med_hsv[y1:y2, x1:x2]
		box_area = float(w * h)

		fg_crop_mask = (crop_diff > 24).astype(np.uint8) * 255
		bg_cyan_mask = cv2.inRange(crop_med_hsv, (80, 45, 40), (115, 255, 255))
		new_fg_mask = cv2.bitwise_and(fg_crop_mask, cv2.bitwise_not(bg_cyan_mask))

		cyan_px = cv2.countNonZero(
			cv2.bitwise_and(cv2.inRange(crop_hsv, (85, 55, 45), (112, 255, 255)), new_fg_mask)
		)
		vivid_cyan_px = cv2.countNonZero(
			cv2.bitwise_and(cv2.inRange(crop_hsv, (85, 85, 45), (112, 255, 255)), new_fg_mask)
		)
		white_grey_px = cv2.countNonZero(
			cv2.bitwise_and(cv2.inRange(crop_hsv, (0, 0, 145), (180, 55, 255)), fg_crop_mask)
		)
		dark_px = cv2.countNonZero(cv2.inRange(crop_hsv, (0, 0, 0), (180, 255, 80)))
		yellow_px = cv2.countNonZero(
			cv2.bitwise_and(cv2.inRange(crop_hsv, (18, 90, 90), (35, 255, 255)), fg_crop_mask)
		)

		# Reject small passive spare attachment resting in the bottom-left corner when lacking robot yellow/chassis
		if x1 < 355 and x2 <= 405 and y1 >= 575 and yellow_px < 15:
			continue

		near_border = (x1 < 360 or x2 > 985 or y1 < 140 or y2 > 650)
		if near_border:
			# Require vivid foreground SPIKE cyan + white/grey LEGO Technic chassis near table borders
			is_robot = (
				(vivid_cyan_px >= 25)
				and ((vivid_cyan_px / box_area) >= 0.025)
				and ((white_grey_px / box_area) >= 0.18)
			)
		else:
			# Inner field: accept either SPIKE cyan OR high-contrast white/grey LEGO attachment + dark wheels/shadow + zero adjacent skin
			pad = 25
			fh_img, fw_img = frame.shape[:2]
			adj_skin_px = cv2.countNonZero(
				skin_broad[max(0, y1 - pad):min(fh_img, y2 + pad), max(0, x1 - pad):min(fw_img, x2 + pad)]
			)
			has_cyan = ((cyan_px / box_area) >= 0.025) and ((white_grey_px / box_area) >= 0.15)
			has_grey_attachment = (
				((white_grey_px / box_area) >= 0.22)
				and ((dark_px / box_area) >= 0.04)
				and (adj_skin_px == 0)
			)
			is_robot = has_cyan or has_grey_attachment

		if is_robot:
			score = float(vivid_cyan_px) * 2.0 + float(white_grey_px) * 0.5
			scored_boxes.append((score, (x1, y1, x2, y2)))

	# Keep at most 1 highest-scoring robot per single-robot zone (Left table, Right top launch, Right main field)
	zone_best: Dict[int, Tuple[float, Tuple[int, int, int, int]]] = {}
	for score, b in scored_boxes:
		cx = (b[0] + b[2]) * 0.5
		cy = (b[1] + b[3]) * 0.5
		zone_id = 0 if cx < 660.0 else (1 if cy < 215.0 else 2)
		if zone_id not in zone_best or score > zone_best[zone_id][0]:
			zone_best[zone_id] = (score, b)

	boxes = [item[1] for item in zone_best.values()]
	return boxes, fg_skin_pixels


def format_yolo_labels(
	boxes: List[Tuple[int, int, int, int]],
	img_w: int,
	img_h: int,
	crop_rect: Optional[Tuple[int, int, int, int]] = None,
) -> List[str]:
	"""
	Formats a list of pixel bounding boxes `(x1, y1, x2, y2)` into normalized YOLO
	label lines (`0 cx cy w h`). If `crop_rect` is given, intersects and translates boxes
	into the crop coordinate space.
	"""
	lines: List[str] = []
	for x1, y1, x2, y2 in boxes:
		if crop_rect is not None:
			cx1, cy1, cx2, cy2 = crop_rect
			ix1 = max(x1, cx1)
			iy1 = max(y1, cy1)
			ix2 = min(x2, cx2)
			iy2 = min(y2, cy2)
			if (ix2 - ix1) < 18 or (iy2 - iy1) < 18:
				continue
			bx1 = ix1 - cx1
			by1 = iy1 - cy1
			bx2 = ix2 - cx1
			by2 = iy2 - cy1
			w_ref = float(cx2 - cx1)
			h_ref = float(cy2 - cy1)
		else:
			bx1, by1, bx2, by2 = x1, y1, x2, y2
			w_ref = float(img_w)
			h_ref = float(img_h)

		cx = min(1.0, max(0.0, ((bx1 + bx2) * 0.5) / w_ref))
		cy = min(1.0, max(0.0, ((by1 + by2) * 0.5) / h_ref))
		bw = min(1.0, max(0.0, (bx2 - bx1) / w_ref))
		bh = min(1.0, max(0.0, (by2 - by1) / h_ref))
		if bw > 0.005 and bh > 0.005:
			lines.append(f"0 {cx:.6f} {cy:.6f} {bw:.6f} {bh:.6f}")
	return lines


def clear_legacy_dataset(dataset_dir: Path) -> None:
	"""Removes legacy image and label files in train/ and valid/ while preserving .gitkeep."""
	for split in ("train", "valid"):
		for sub in ("images", "labels"):
			folder = dataset_dir / split / sub
			folder.mkdir(parents=True, exist_ok=True)
			for item in folder.iterdir():
				if item.is_file() and item.name != ".gitkeep":
					item.unlink()


def save_sample_pair(
	img: np.ndarray,
	label_lines: List[str],
	stem: str,
	split_dir: Path,
	encode_params: List[int],
) -> None:
	"""Writes an image `.jpg` and its corresponding YOLO `.txt` label file."""
	img_path = split_dir / "images" / f"{stem}.jpg"
	lbl_path = split_dir / "labels" / f"{stem}.txt"
	cv2.imwrite(str(img_path), img, encode_params)
	lbl_path.write_text("\n".join(label_lines) + ("\n" if label_lines else ""), encoding="utf-8")


def build_auto_labeled_dataset(
	video_paths: List[str],
	dataset_dir: str = DEFAULT_DATASET_DIR,
	frame_interval: int = DEFAULT_AUTO_LABEL_INTERVAL,
	jpeg_quality: int = DEFAULT_JPEG_QUALITY,
) -> Dict[str, int]:
	"""
	Extracts frames across all videos in `video_paths`, automatically detects and labels
	the LEGO robot, generates both full dual-table frames and single-table crops (plus
	~15% hard-negative hand/glare/empty frames), and splits 80/20 into train and valid.
	"""
	if not video_paths:
		raise FileNotFoundError("No .mp4 video files found to build dataset.")

	ds_path = Path(dataset_dir)
	clear_legacy_dataset(ds_path)

	med_dark, med_bright = compute_dual_exposure_backgrounds(video_paths)
	med_dark_blur = cv2.GaussianBlur(med_dark, (5, 5), 0)
	med_bright_blur = cv2.GaussianBlur(med_bright, (5, 5), 0)
	med_dark_hsv = cv2.cvtColor(med_dark, cv2.COLOR_BGR2HSV)
	med_bright_hsv = cv2.cvtColor(med_bright, cv2.COLOR_BGR2HSV)

	h_ref, w_ref = med_dark.shape[:2]
	table_mask = build_playable_table_mask(h_ref, w_ref)
	encode_params = [int(cv2.IMWRITE_JPEG_QUALITY), int(max(50, min(100, jpeg_quality)))]

	# Collect positive and negative candidate samples stratified by video
	positive_samples: List[Tuple[str, np.ndarray, List[str]]] = []
	negative_samples: List[Tuple[str, np.ndarray]] = []

	lx1, ly1, lx2, ly2 = LEFT_TABLE_CROP
	rx1, ry1, rx2, ry2 = RIGHT_TABLE_CROP

	for vpath in video_paths:
		vstem = Path(vpath).stem
		v_dark, v_bright = get_video_background_models(vpath, med_dark, med_bright)
		if v_dark is med_dark and v_bright is med_bright:
			v_dark_blur, v_bright_blur = med_dark_blur, med_bright_blur
			v_dark_hsv, v_bright_hsv = med_dark_hsv, med_bright_hsv
		else:
			v_dark_blur = cv2.GaussianBlur(v_dark, (5, 5), 0)
			v_bright_blur = cv2.GaussianBlur(v_bright, (5, 5), 0)
			v_dark_hsv = cv2.cvtColor(v_dark, cv2.COLOR_BGR2HSV)
			v_bright_hsv = cv2.cvtColor(v_bright, cv2.COLOR_BGR2HSV)

		cap = cv2.VideoCapture(vpath)
		if not cap.isOpened():
			print(f"[WARN] Could not open {vpath}, skipping.", file=sys.stderr)
			continue

		fidx = 0
		vid_pos_frames = 0
		vid_neg_frames = 0
		vid_boxes = 0

		while True:
			ret = cap.grab()
			if not ret:
				break
			if fidx % frame_interval == 0:
				ok, frame = cap.retrieve()
				if ok and frame is not None:
					boxes, fg_skin_px = detect_lego_robots_in_frame(
						frame=frame,
						med_dark=v_dark,
						med_bright=v_bright,
						med_dark_blur=v_dark_blur,
						med_bright_blur=v_bright_blur,
						med_dark_hsv=v_dark_hsv,
						med_bright_hsv=v_bright_hsv,
						table_mask=table_mask,
					)
					base_name = f"{vstem}_f{fidx:06d}"

					if boxes:
						vid_pos_frames += 1
						vid_boxes += len(boxes)
						full_labels = format_yolo_labels(boxes, w_ref, h_ref, crop_rect=None)
						positive_samples.append((f"{base_name}_full", frame, full_labels))

						# Single-table positive crops for fll-vision scale generalization
						left_labels = format_yolo_labels(boxes, w_ref, h_ref, crop_rect=LEFT_TABLE_CROP)
						if left_labels:
							left_crop = frame[ly1:ly2, lx1:lx2].copy()
							positive_samples.append((f"{base_name}_left", left_crop, left_labels))
						elif vid_pos_frames % 10 == 0:
							# Occasional empty left-table glare/hand crop as hard negative
							left_crop = frame[ly1:ly2, lx1:lx2].copy()
							negative_samples.append((f"{base_name}_left_neg", left_crop))

						right_labels = format_yolo_labels(boxes, w_ref, h_ref, crop_rect=RIGHT_TABLE_CROP)
						if right_labels:
							right_crop = frame[ry1:ry2, rx1:rx2].copy()
							positive_samples.append((f"{base_name}_right", right_crop, right_labels))
						elif vid_pos_frames % 10 == 5:
							# Occasional empty right-table glare/hand crop as hard negative
							right_crop = frame[ry1:ry2, rx1:rx2].copy()
							negative_samples.append((f"{base_name}_right_neg", right_crop))
					else:
						vid_neg_frames += 1
						# Prioritize frames with human hands/arms reaching across the table or periodic empty backgrounds
						if fg_skin_px >= 150 or vid_neg_frames % 2 == 1:
							negative_samples.append((f"{base_name}_neg_full", frame))
							if fg_skin_px >= 250:
								right_crop = frame[ry1:ry2, rx1:rx2].copy()
								negative_samples.append((f"{base_name}_neg_right", right_crop))

			fidx += 1

		cap.release()
		print(
			f"[AUTO-LABEL] {Path(vpath).name}: positive_frames={vid_pos_frames}, "
			f"negative_frames={vid_neg_frames}, robot_boxes={vid_boxes}"
		)

	# Target ~15% hard-negative images relative to total dataset size
	num_pos = len(positive_samples)
	target_neg = max(1, int(round(num_pos * (0.15 / 0.85))))
	if len(negative_samples) > target_neg:
		step = len(negative_samples) / float(target_neg)
		selected_negatives = [negative_samples[int(i * step)] for i in range(target_neg)]
	else:
		selected_negatives = negative_samples

	stats = {
		"train_images": 0,
		"train_positive": 0,
		"train_negative": 0,
		"train_boxes": 0,
		"valid_images": 0,
		"valid_positive": 0,
		"valid_negative": 0,
		"valid_boxes": 0,
	}

	# Stratified 80% train / 20% valid split across positive samples
	for idx, (stem, img, labels) in enumerate(positive_samples):
		is_valid = (idx % 5 == 4)
		split_name = "valid" if is_valid else "train"
		split_dir = ds_path / split_name
		save_sample_pair(img, labels, stem, split_dir, encode_params)
		stats[f"{split_name}_images"] += 1
		stats[f"{split_name}_positive"] += 1
		stats[f"{split_name}_boxes"] += len(labels)

	# Stratified 80% train / 20% valid split across hard-negative samples
	for idx, (stem, img) in enumerate(selected_negatives):
		is_valid = (idx % 5 == 4)
		split_name = "valid" if is_valid else "train"
		split_dir = ds_path / split_name
		save_sample_pair(img, [], stem, split_dir, encode_params)
		stats[f"{split_name}_images"] += 1
		stats[f"{split_name}_negative"] += 1

	total_imgs = stats["train_images"] + stats["valid_images"]
	total_neg = stats["train_negative"] + stats["valid_negative"]
	neg_pct = (total_neg / float(max(1, total_imgs))) * 100.0

	print("\n" + "=" * 68)
	print("[SUCCESS] Automated LEGO Robot YOLO26x Dataset Built Successfully!")
	print(f"  Train split : {stats['train_images']} images ({stats['train_positive']} pos, {stats['train_negative']} neg, {stats['train_boxes']} robot boxes)")
	print(f"  Valid split : {stats['valid_images']} images ({stats['valid_positive']} pos, {stats['valid_negative']} neg, {stats['valid_boxes']} robot boxes)")
	print(f"  Total       : {total_imgs} images ({neg_pct:.1f}% hard-negative frames)")
	print("=" * 68)
	return stats


def parse_args():
	parser = argparse.ArgumentParser(
		description="Extract frames and optionally auto-label FLL LEGO robot videos for YOLO26x training."
	)
	parser.add_argument(
		"--video",
		"-v",
		type=str,
		default=DEFAULT_VIDEO_PATH,
		help=f"Path to a single input .mp4 video file (default: {DEFAULT_VIDEO_PATH})",
	)
	parser.add_argument(
		"--video-dir",
		type=str,
		default=None,
		help="Directory containing .mp4 videos for batch extraction / auto-labeling (e.g., videos)",
	)
	parser.add_argument(
		"--auto-label",
		action="store_true",
		help="Automatically detect & label the LEGO robot into dataset/train and dataset/valid",
	)
	parser.add_argument(
		"--dataset-dir",
		type=str,
		default=DEFAULT_DATASET_DIR,
		help=f"Root dataset directory for --auto-label (default: {DEFAULT_DATASET_DIR})",
	)
	parser.add_argument(
		"--output",
		"-o",
		type=str,
		default=DEFAULT_OUTPUT_DIR,
		help=f"Directory to save raw extracted frames when not using --auto-label (default: {DEFAULT_OUTPUT_DIR})",
	)
	parser.add_argument(
		"--interval",
		"-i",
		type=int,
		default=None,
		help=f"Save every Nth frame (default: {DEFAULT_AUTO_LABEL_INTERVAL} with --auto-label, else {DEFAULT_FRAME_INTERVAL})",
	)
	parser.add_argument(
		"--prefix",
		type=str,
		default="fll_frame",
		help="Filename prefix for saved JPG images in single-video mode (default: fll_frame)",
	)
	parser.add_argument(
		"--quality",
		type=int,
		default=DEFAULT_JPEG_QUALITY,
		help=f"JPEG quality 50..100 (default: {DEFAULT_JPEG_QUALITY})",
	)
	return parser.parse_args()


if __name__ == "__main__":
	args = parse_args()
	try:
		if args.auto_label:
			interval = args.interval if args.interval is not None else DEFAULT_AUTO_LABEL_INTERVAL
			vdir = args.video_dir if args.video_dir is not None else (
				DEFAULT_VIDEO_DIR if os.path.isdir(DEFAULT_VIDEO_DIR) else None
			)
			if vdir is not None and os.path.isdir(vdir):
				videos = sorted(glob.glob(os.path.join(vdir, "*.mp4")))
			else:
				resolved = find_default_video(args.video)
				videos = [resolved] if os.path.isfile(resolved) else []
			build_auto_labeled_dataset(
				video_paths=videos,
				dataset_dir=args.dataset_dir,
				frame_interval=interval,
				jpeg_quality=args.quality,
			)
		elif args.video_dir is not None:
			interval = args.interval if args.interval is not None else DEFAULT_FRAME_INTERVAL
			videos = sorted(glob.glob(os.path.join(args.video_dir, "*.mp4")))
			if not videos:
				raise FileNotFoundError(f"No .mp4 files found in directory '{args.video_dir}'.")
			total_saved = 0
			for vpath in videos:
				vstem = Path(vpath).stem
				total_saved += extract_frames(
					video_path=vpath,
					output_dir=args.output,
					frame_interval=interval,
					prefix=vstem,
					jpeg_quality=args.quality,
				)
			print(f"[SUCCESS] Batch extracted {total_saved} total frames from {len(videos)} videos.")
		else:
			interval = args.interval if args.interval is not None else DEFAULT_FRAME_INTERVAL
			resolved_video = find_default_video(args.video)
			extract_frames(
				video_path=resolved_video,
				output_dir=args.output,
				frame_interval=interval,
				prefix=args.prefix,
				jpeg_quality=args.quality,
			)
	except Exception as exc:
		print(f"[ERROR] {exc}", file=sys.stderr)
		sys.exit(1)
