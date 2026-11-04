"""
1_extract_frames.py
-------------------
Extracts frames from an FLL match recording (.mp4) at a fixed frame interval
(default: every 10th frame) and saves them to `dataset/raw/` for bounding-box
annotation in Roboflow.

Usage:
    python 1_extract_frames.py --video match.mp4 --interval 10 --output dataset/raw
"""

import argparse
import os
import sys
from pathlib import Path
import cv2

DEFAULT_VIDEO_PATH = "match.mp4"
DEFAULT_OUTPUT_DIR = os.path.join("dataset", "raw")
DEFAULT_FRAME_INTERVAL = 10
DEFAULT_JPEG_QUALITY = 95


def find_default_video(preferred_path: str) -> str:
	"""Returns the preferred video path if it exists, or searches the workspace for an .mp4 file."""
	if os.path.isfile(preferred_path):
		return preferred_path

	for root_dir in (".", "fll-vision"):
		if not os.path.isdir(root_dir):
			continue
		for fname in os.listdir(root_dir):
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
				# Handle end-of-stream or isolated corrupt frames gracefully
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
	print(
		"[NEXT STEP] Upload the images in 'dataset/raw/' to Roboflow, label ONLY the LEGO robot "
		"as class 'robot' (leave hands/arms unlabeled as background), and export in YOLOv8 format."
	)
	return saved_count


def parse_args():
	parser = argparse.ArgumentParser(
		description="Extract frames from an FLL robot video (.mp4) for Roboflow YOLOv8 labeling."
	)
	parser.add_argument(
		"--video",
		"-v",
		type=str,
		default=DEFAULT_VIDEO_PATH,
		help=f"Path to input .mp4 video file (default: {DEFAULT_VIDEO_PATH})",
	)
	parser.add_argument(
		"--output",
		"-o",
		type=str,
		default=DEFAULT_OUTPUT_DIR,
		help=f"Directory to save extracted frames (default: {DEFAULT_OUTPUT_DIR})",
	)
	parser.add_argument(
		"--interval",
		"-i",
		type=int,
		default=DEFAULT_FRAME_INTERVAL,
		help=f"Save every Nth frame (default: {DEFAULT_FRAME_INTERVAL})",
	)
	parser.add_argument(
		"--prefix",
		type=str,
		default="fll_frame",
		help="Filename prefix for saved JPG images (default: fll_frame)",
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
	resolved_video = find_default_video(args.video)
	try:
		extract_frames(
			video_path=resolved_video,
			output_dir=args.output,
			frame_interval=args.interval,
			prefix=args.prefix,
			jpeg_quality=args.quality,
		)
	except Exception as exc:
		print(f"[ERROR] {exc}", file=sys.stderr)
		sys.exit(1)
