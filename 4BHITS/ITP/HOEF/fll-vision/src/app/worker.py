import ctypes
import math
from multiprocessing import Process
from multiprocessing.shared_memory import SharedMemory
import os
import struct
import sys
import threading
import time
import traceback
from typing import Optional
import cv2
import numpy as np

from src.tools.video_source import VideoSource, enable_high_res_timer

from .calibration import DEFAULT_TABLE_ROIS, sanitize_table_rois
from .config import (
	DETECTION_FPS,
	JPEG_QUALITY,
	MAX_OUTPUT_HEIGHT,
	PAN_DEADZONE_RATIO,
	PAN_SPEED,
	ROBOT_ZOOM_ASPECT,
	ROBOT_ZOOM_H_MAX,
	ROBOT_ZOOM_W,
	STOPPED_HOLD_SEC,
	TARGET_FPS,
	TARGET_SMOOTH_SPEED,
	ZOOM_SPEED,
)
from .detector import AutoEnhancer, DetectorHybrid
from .stream import HEADER_STRUCT, JPEG_SLOT_BYTES

MAX_FRAME_W = 1920
MAX_FRAME_H = 1080
FRAME_SHM_BYTES = MAX_FRAME_W * MAX_FRAME_H * 3
OUT_SHM_BYTES = 16 + 2 * JPEG_SLOT_BYTES

# Control block: stop_flag(i), ctrl_viewers(i), reset_seq(i), frame_seq(q), frame_w(i), frame_h(i), 8 ROI doubles
CTRL_STRUCT = struct.Struct("<iiiqii8d")
CTRL_SHM_BYTES = 128


def _is_parent_alive(parent_pid: int) -> bool:
	if sys.platform.startswith("win"):
		try:
			handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, parent_pid)
			if not handle:
				return False
			exit_code = ctypes.c_ulong()
			ok = ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
			ctypes.windll.kernel32.CloseHandle(handle)
			return bool(ok and exit_code.value == 259)
		except Exception:
			return True
	return os.getppid() == parent_pid


def _get_safe_window(cx: float, cy: float, frame_w: int, frame_h: int, view_w: int, view_h: int):
	left = max(0, int(round(cx - view_w * 0.5)))
	top = max(0, int(round(cy - view_h * 0.5)))
	if left + view_w > frame_w:
		left = max(0, frame_w - view_w)
	if top + view_h > frame_h:
		top = max(0, frame_h - view_h)
	return left, top


def _write_jpeg_slot(shm: SharedMemory, seq: int, jpeg_bytes: bytes) -> int:
	n = len(jpeg_bytes)
	if 0 < n <= JPEG_SLOT_BYTES:
		next_seq = seq + 1
		slot_offset = 16 + (next_seq & 1) * JPEG_SLOT_BYTES
		shm.buf[slot_offset : slot_offset + n] = jpeg_bytes
		HEADER_STRUCT.pack_into(shm.buf, 0, next_seq, n)
		return next_seq
	return seq


def _render_views(
	table_img: np.ndarray,
	cam_x: float,
	cam_y: float,
	cur_win_w: float,
	cur_win_h: float,
	bbox,
	need_control_view: bool,
	enhancer: Optional[AutoEnhancer] = None,
):
	"""
	Returns (wall_img, ctrl_img):
	- wall_img: Clean zoomed-in broadcast view for the Video Wall (auto-enhanced, no tracking rectangle).
	- ctrl_img: Full-table Control Panel monitor view with bright green rectangle on the tracked robot.
	"""
	t_h, t_w = table_img.shape[:2]

	win_w = max(64, min(t_w, int(round(cur_win_w))))
	win_h = max(64, min(t_h, int(round(cur_win_h))))

	if win_w >= t_w - 2 and win_h >= t_h - 2:
		wx, wy, win_w, win_h = 0, 0, t_w, t_h
		cropped = table_img
	else:
		wx, wy = _get_safe_window(cam_x, cam_y, t_w, t_h, win_w, win_h)
		cropped = table_img[wy : wy + win_h, wx : wx + win_w]

	target_h = min(t_h, MAX_OUTPUT_HEIGHT)
	target_w = max(64, int(round(target_h * (win_w / float(max(1, win_h))))))

	if cropped.shape[1] != target_w or cropped.shape[0] != target_h:
		wall_img = cv2.resize(cropped, (target_w, target_h), interpolation=cv2.INTER_LINEAR)
	else:
		wall_img = cropped.copy()

	if enhancer is not None:
		wall_img = enhancer.apply(wall_img)

	if not need_control_view:
		return wall_img, None

	ctrl_h = min(t_h, 560)
	ctrl_w = max(64, int(round(ctrl_h * (t_w / float(max(1, t_h))))))
	if t_w != ctrl_w or t_h != ctrl_h:
		ctrl_img = cv2.resize(table_img, (ctrl_w, ctrl_h), interpolation=cv2.INTER_LINEAR)
	else:
		ctrl_img = table_img.copy()

	if enhancer is not None:
		ctrl_img = enhancer.apply(ctrl_img)

	if bbox is not None:
		bx, by, bw, bh = bbox
		sx = ctrl_w / float(max(1, t_w))
		sy = ctrl_h / float(max(1, t_h))
		rx1 = max(2, int(round(bx * sx)))
		ry1 = max(2, int(round(by * sy)))
		rx2 = min(ctrl_w - 3, int(round((bx + bw) * sx)))
		ry2 = min(ctrl_h - 3, int(round((by + bh) * sy)))

		# High-contrast dark outline + bright green rectangle around the tracked/stopped LEGO robot
		cv2.rectangle(ctrl_img, (rx1 - 1, ry1 - 1), (rx2 + 1, ry2 + 1), (10, 15, 10), 5)
		cv2.rectangle(ctrl_img, (rx1, ry1), (rx2, ry2), (0, 240, 75), 3)

	return wall_img, ctrl_img


def side_worker_process(
	side: str,
	parent_pid: int,
	gpu_id: int,
	ctrl_shm_name: str,
	frame_shm_name: str,
	wall_out_shm_name: str,
	ctrl_out_shm_name: str,
):
	"""
	Dedicated OS process for one FLL table ("left" = Red, "right" = Blue).
	"""
	enable_high_res_timer()
	cv2.setNumThreads(2)

	ctrl_shm = SharedMemory(name=ctrl_shm_name)
	frame_shm = SharedMemory(name=frame_shm_name)
	wall_out_shm = SharedMemory(name=wall_out_shm_name)
	ctrl_out_shm = SharedMemory(name=ctrl_out_shm_name)

	raw_buffer = np.ndarray((MAX_FRAME_H, MAX_FRAME_W, 3), dtype=np.uint8, buffer=frame_shm.buf)

	state_lock = threading.Lock()
	shared_det = {
		"bbox": None,
		"last_seen": 0.0,
		"running": True,
	}

	def read_ctrl():
		vals = CTRL_STRUCT.unpack_from(ctrl_shm.buf, 0)
		stop_flag, ctrl_viewers, reset_seq, seq, fw, fh = (
			vals[0],
			vals[1],
			vals[2],
			vals[3],
			vals[4],
			vals[5],
		)
		roi = vals[6:10] if side == "left" else vals[10:14]
		return stop_flag, ctrl_viewers, reset_seq, seq, fw, fh, roi

	def slice_table(fw: int, fh: int, roi):
		x1 = max(0, min(fw - 4, int(fw * roi[0])))
		y1 = max(0, min(fh - 4, int(fh * roi[1])))
		x2 = max(x1 + 4, min(fw, int(fw * roi[2])))
		y2 = max(y1 + 4, min(fh, int(fh * roi[3])))
		return raw_buffer[y1:y2, x1:x2]

	def detection_loop():
		detector = DetectorHybrid()
		det_interval = 1.0 / DETECTION_FPS
		last_seq = -1
		active_roi = None
		active_reset_seq = None
		logged_error = False

		while shared_det["running"]:
			t0 = time.perf_counter()
			try:
				stop_flag, _, reset_seq, seq, fw, fh, roi = read_ctrl()
				if stop_flag != 0:
					break
				if seq <= 0 or fw <= 0 or fh <= 0:
					time.sleep(0.005)
					continue

				if active_roi != roi or active_reset_seq != reset_seq:
					is_reset_only = active_roi == roi and active_reset_seq is not None
					active_roi = roi
					active_reset_seq = reset_seq
					if not is_reset_only:
						detector = DetectorHybrid()
					else:
						detector.reset()
					with state_lock:
						shared_det["bbox"] = None
						shared_det["last_seen"] = 0.0

				if seq == last_seq:
					time.sleep(0.004)
					continue

				last_seq = seq
				table_copy = slice_table(fw, fh, roi).copy()
				bbox = detector.detect(table_copy)

				now = time.perf_counter()
				with state_lock:
					if bbox is not None:
						shared_det["bbox"] = bbox
						shared_det["last_seen"] = now
					elif shared_det["bbox"] is not None and (now - shared_det["last_seen"]) > STOPPED_HOLD_SEC:
						shared_det["bbox"] = None
			except Exception:
				if not logged_error:
					logged_error = True
					traceback.print_exc()
				time.sleep(0.01)

			elapsed = time.perf_counter() - t0
			if elapsed < det_interval:
				time.sleep(det_interval - elapsed)

	det_thread = threading.Thread(target=detection_loop, daemon=True)
	det_thread.start()

	try:
		frame_interval = 1.0 / TARGET_FPS
		encode_params = [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY]
		stream_enhancer = AutoEnhancer()

		cam_x: Optional[float] = None
		cam_y: Optional[float] = None
		cur_win_w: Optional[float] = None
		cur_win_h: Optional[float] = None
		smooth_tx: Optional[float] = None
		smooth_ty: Optional[float] = None
		anchor_tx: Optional[float] = None
		anchor_ty: Optional[float] = None

		last_rendered_seq: int = -1
		last_enhance_seq: int = -1
		last_ctrl_viewers: int = 0
		last_bbox = None
		wall_seq: int = 0
		ctrl_seq: int = 0
		active_roi = None
		prev_t = time.perf_counter()
		last_parent_check = prev_t

		while True:
			t0 = time.perf_counter()
			dt = max(0.001, min(0.1, t0 - prev_t))
			prev_t = t0

			if (t0 - last_parent_check) > 0.5:
				last_parent_check = t0
				if not _is_parent_alive(parent_pid):
					break

			stop_flag, ctrl_viewers, _, seq, fw, fh, roi = read_ctrl()
			if stop_flag != 0:
				break
			if seq <= 0 or fw <= 0 or fh <= 0:
				time.sleep(0.01)
				continue

			table_view = slice_table(fw, fh, roi)
			t_h, t_w = table_view.shape[:2]

			if cam_x is None or cur_win_w is None or active_roi != roi:
				active_roi = roi
				cam_x, cam_y = t_w * 0.5, t_h * 0.5
				smooth_tx, smooth_ty = cam_x, cam_y
				anchor_tx, anchor_ty = cam_x, cam_y
				cur_win_w, cur_win_h = float(t_w), float(t_h)
				last_rendered_seq = -1

			# Update automatic brightness/contrast/white-balance LUT every 3rd camera frame
			if seq != last_enhance_seq and (seq % 3 == 1 or last_enhance_seq == -1):
				last_enhance_seq = seq
				stream_enhancer.update_from_sample(table_view)

			with state_lock:
				bbox = (
					shared_det["bbox"]
					if (shared_det["bbox"] is not None and (t0 - shared_det["last_seen"]) <= STOPPED_HOLD_SEC)
					else None
				)

			if bbox is not None:
				bx, by, bw, bh = bbox
				raw_tx = bx + bw * 0.5
				raw_ty = by + bh * 0.5

				# Spatial deadzone eliminates micro-twitch when robot is stopped or driving straight
				deadzone_px = max(5.0, min(t_w, t_h) * PAN_DEADZONE_RATIO)
				if anchor_tx is None or math.hypot(raw_tx - anchor_tx, raw_ty - anchor_ty) > deadzone_px:
					anchor_tx, anchor_ty = raw_tx, raw_ty

				# Constant-size zoom window prevents contour-size zoom breathing/pumping
				target_win_w = float(max(64.0, min(float(t_w), t_w * ROBOT_ZOOM_W)))
				desired_h = min(t_h * ROBOT_ZOOM_H_MAX, target_win_w * ROBOT_ZOOM_ASPECT)
				target_win_h = float(max(64.0, min(float(t_h), desired_h)))
			else:
				anchor_tx = t_w * 0.5
				anchor_ty = t_h * 0.5
				target_win_w = float(t_w)
				target_win_h = float(t_h)

			# Stage 1: Smooth target trajectory at 60 FPS (removes 20Hz stepping)
			t_alpha = 1.0 - math.exp(-TARGET_SMOOTH_SPEED * dt)
			smooth_tx += (anchor_tx - smooth_tx) * t_alpha
			smooth_ty += (anchor_ty - smooth_ty) * t_alpha

			# Stage 2: Fluid-head camera pan & optical zoom
			pan_alpha = 1.0 - math.exp(-PAN_SPEED * dt)
			zoom_alpha = 1.0 - math.exp(-ZOOM_SPEED * dt)
			cam_x += (smooth_tx - cam_x) * pan_alpha
			cam_y += (smooth_ty - cam_y) * pan_alpha
			cur_win_w += (target_win_w - cur_win_w) * zoom_alpha
			cur_win_h += (target_win_h - cur_win_h) * zoom_alpha

			is_animating = (
				abs(smooth_tx - cam_x) > 0.4
				or abs(smooth_ty - cam_y) > 0.4
				or abs(target_win_w - cur_win_w) > 0.6
				or abs(target_win_h - cur_win_h) > 0.6
			)

			need_ctrl = ctrl_viewers > 0
			ctrl_just_opened = need_ctrl and last_ctrl_viewers == 0
			bbox_changed = bbox != last_bbox
			last_ctrl_viewers = ctrl_viewers
			last_bbox = bbox

			if seq != last_rendered_seq or is_animating or wall_seq == 0 or ctrl_just_opened or bbox_changed:
				last_rendered_seq = seq
				wall_img, ctrl_img = _render_views(
					table_view,
					cam_x,
					cam_y,
					cur_win_w,
					cur_win_h,
					bbox,
					need_control_view=need_ctrl,
					enhancer=stream_enhancer,
				)

				ok_w, jpeg_w = cv2.imencode(".jpg", wall_img, encode_params)
				if ok_w:
					wall_bytes = jpeg_w.tobytes()
					wall_seq = _write_jpeg_slot(wall_out_shm, wall_seq, wall_bytes)

					if need_ctrl and ctrl_img is not None:
						ok_c, jpeg_c = cv2.imencode(".jpg", ctrl_img, encode_params)
						if ok_c:
							ctrl_seq = _write_jpeg_slot(ctrl_out_shm, ctrl_seq, jpeg_c.tobytes())

			elapsed = time.perf_counter() - t0
			if elapsed < frame_interval:
				time.sleep(frame_interval - elapsed)
	finally:
		shared_det["running"] = False
		for shm in (ctrl_shm, frame_shm, wall_out_shm, ctrl_out_shm):
			try:
				shm.close()
			except Exception:
				pass


class VisionPipeline:
	"""
	Captures camera frames once into zero-copy SharedMemory and runs two independent
	OS worker processes (Left/Red Table & Right/Blue Table) across multiple CPU cores.
	"""

	def __init__(
		self,
		source_path,
		left_gpu,
		right_gpu,
		left_broadcaster,
		right_broadcaster,
		left_control_broadcaster,
		right_control_broadcaster,
		initial_rois=None,
	):
		self.source_path = source_path
		self.left_gpu = left_gpu
		self.right_gpu = right_gpu
		self.left_broadcaster = left_broadcaster
		self.right_broadcaster = right_broadcaster
		self.left_control_broadcaster = left_control_broadcaster
		self.right_control_broadcaster = right_control_broadcaster

		self._rois = sanitize_table_rois(initial_rois or DEFAULT_TABLE_ROIS)
		self._lock = threading.Lock()
		self._source: Optional[VideoSource] = None
		self._running = False
		self._ctrl_viewers = 0
		self._reset_seq = 0
		self._frame_seq = 0
		self._frame_w = 0
		self._frame_h = 0
		self._latest_frame: Optional[np.ndarray] = None

		self._ctrl_shm: Optional[SharedMemory] = None
		self._frame_shm: Optional[SharedMemory] = None
		self._left_out_shm: Optional[SharedMemory] = None
		self._right_out_shm: Optional[SharedMemory] = None
		self._left_ctrl_out_shm: Optional[SharedMemory] = None
		self._right_ctrl_out_shm: Optional[SharedMemory] = None
		self._frame_array: Optional[np.ndarray] = None
		self._processes = []

	def _write_ctrl(self, stop_flag: int = 0) -> None:
		if self._ctrl_shm is None:
			return
		l_box = self._rois["left"]
		r_box = self._rois["right"]
		CTRL_STRUCT.pack_into(
			self._ctrl_shm.buf,
			0,
			stop_flag,
			self._ctrl_viewers,
			self._reset_seq,
			self._frame_seq,
			self._frame_w,
			self._frame_h,
			l_box["x1"],
			l_box["y1"],
			l_box["x2"],
			l_box["y2"],
			r_box["x1"],
			r_box["y1"],
			r_box["x2"],
			r_box["y2"],
		)

	def adjust_control_viewers(self, delta: int) -> None:
		with self._lock:
			self._ctrl_viewers = max(0, self._ctrl_viewers + delta)
			if self._running:
				self._write_ctrl(stop_flag=0)

	def reset_tracking(self) -> None:
		with self._lock:
			self._reset_seq += 1
			if self._running:
				self._write_ctrl(stop_flag=0)

	def set_table_rois(self, rois: dict) -> dict:
		clean = sanitize_table_rois(rois)
		with self._lock:
			self._rois = clean
			self._reset_seq += 1
			self._write_ctrl(stop_flag=0 if self._running else 1)
		return clean

	def get_latest_frame(self) -> Optional[np.ndarray]:
		with self._lock:
			return self._latest_frame.copy() if self._latest_frame is not None else None

	def _on_camera_frame(self, frame: np.ndarray, frame_id: int) -> None:
		if not self._running or self._frame_array is None:
			return

		h, w = frame.shape[:2]
		if w > MAX_FRAME_W or h > MAX_FRAME_H:
			scale = min(MAX_FRAME_W / float(w), MAX_FRAME_H / float(h))
			w, h = int(w * scale), int(h * scale)
			frame = cv2.resize(frame, (w, h), interpolation=cv2.INTER_AREA)

		with self._lock:
			self._latest_frame = frame
			self._frame_array[:h, :w, :] = frame
			self._frame_w = w
			self._frame_h = h
			self._frame_seq = frame_id
			self._write_ctrl(stop_flag=0)

	def start(self) -> None:
		if self._running:
			return
		enable_high_res_timer()
		cv2.setNumThreads(2)
		self._running = True

		self._ctrl_shm = SharedMemory(create=True, size=CTRL_SHM_BYTES)
		self._frame_shm = SharedMemory(create=True, size=FRAME_SHM_BYTES)
		self._left_out_shm = SharedMemory(create=True, size=OUT_SHM_BYTES)
		self._right_out_shm = SharedMemory(create=True, size=OUT_SHM_BYTES)
		self._left_ctrl_out_shm = SharedMemory(create=True, size=OUT_SHM_BYTES)
		self._right_ctrl_out_shm = SharedMemory(create=True, size=OUT_SHM_BYTES)
		self._frame_array = np.ndarray((MAX_FRAME_H, MAX_FRAME_W, 3), dtype=np.uint8, buffer=self._frame_shm.buf)

		for out_s in (
			self._left_out_shm,
			self._right_out_shm,
			self._left_ctrl_out_shm,
			self._right_ctrl_out_shm,
		):
			HEADER_STRUCT.pack_into(out_s.buf, 0, 0, 0)

		self._write_ctrl(stop_flag=0)

		self.left_broadcaster.attach_shared_memory(self._left_out_shm)
		self.right_broadcaster.attach_shared_memory(self._right_out_shm)
		self.left_control_broadcaster.attach_shared_memory(self._left_ctrl_out_shm)
		self.right_control_broadcaster.attach_shared_memory(self._right_ctrl_out_shm)

		parent_pid = os.getpid()
		p_left = Process(
			target=side_worker_process,
			args=(
				"left",
				parent_pid,
				self.left_gpu,
				self._ctrl_shm.name,
				self._frame_shm.name,
				self._left_out_shm.name,
				self._left_ctrl_out_shm.name,
			),
			daemon=True,
		)
		p_right = Process(
			target=side_worker_process,
			args=(
				"right",
				parent_pid,
				self.right_gpu,
				self._ctrl_shm.name,
				self._frame_shm.name,
				self._right_out_shm.name,
				self._right_ctrl_out_shm.name,
			),
			daemon=True,
		)
		p_left.start()
		p_right.start()
		self._processes = [p_left, p_right]

		threading.Thread(target=self._init_source, daemon=True).start()

	def _init_source(self) -> None:
		while self._running:
			try:
				self._source = VideoSource(self.source_path, on_frame=self._on_camera_frame)
				break
			except Exception:
				time.sleep(1.0)

	def stop(self) -> None:
		self._running = False
		with self._lock:
			self._write_ctrl(stop_flag=1)

		self.left_broadcaster.stop()
		self.right_broadcaster.stop()
		self.left_control_broadcaster.stop()
		self.right_control_broadcaster.stop()

		if self._source is not None:
			try:
				self._source.release()
			except Exception:
				pass
			self._source = None

		for proc in self._processes:
			try:
				proc.join(timeout=0.5)
				if proc.is_alive():
					proc.terminate()
					proc.join(timeout=0.3)
			except Exception:
				pass
		self._processes = []

		self._frame_array = None
		for shm_attr in (
			"_ctrl_shm",
			"_frame_shm",
			"_left_out_shm",
			"_right_out_shm",
			"_left_ctrl_out_shm",
			"_right_ctrl_out_shm",
		):
			shm = getattr(self, shm_attr, None)
			setattr(self, shm_attr, None)
			if shm is not None:
				try:
					shm.close()
				except Exception:
					pass
				try:
					shm.unlink()
				except Exception:
					pass
