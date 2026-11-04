import ctypes
import sys
import threading
import time
import cv2

from src.app.config import TARGET_FPS


def enable_high_res_timer():
	if sys.platform.startswith("win"):
		try:
			ctypes.windll.winmm.timeBeginPeriod(1)
		except Exception:
			pass


def _try_open_camera(index: int):
	if sys.platform.startswith("win"):
		# Prefer DirectShow + MJPG so USB 2.0 cameras deliver 30-60 FPS instead of 10 FPS YUY2
		cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)
		if cap.isOpened():
			cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
			cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
			cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
			cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
			cap.set(cv2.CAP_PROP_FPS, TARGET_FPS)
			try:
				cap.set(cv2.CAP_PROP_AUTO_WB, 1)
				cap.set(cv2.CAP_PROP_AUTOFOCUS, 1)
			except Exception:
				pass
			ret, frame = cap.read()
			if ret and frame is not None:
				return cap, frame
			cap.release()

	# Fallback to default backend (MSMF / V4L2) without forcing FOURCC
	cap = cv2.VideoCapture(index)
	if cap.isOpened():
		cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
		cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
		cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
		cap.set(cv2.CAP_PROP_FPS, TARGET_FPS)
		ret, frame = cap.read()
		if ret and frame is not None:
			return cap, frame
		cap.release()

	return None, None


class VideoSource:
	def __init__(self, source, on_frame=None):
		enable_high_res_timer()
		self.source = source
		self.on_frame = on_frame
		self.cap = None
		first_frame = None

		if isinstance(source, int):
			self.cap, first_frame = _try_open_camera(source)
			if self.cap is None:
				alt = 0 if source != 0 else 1
				self.cap, first_frame = _try_open_camera(alt)
				if self.cap is not None:
					self.source = alt
		else:
			cap = cv2.VideoCapture(source)
			if cap.isOpened():
				ret, frame = cap.read()
				if ret and frame is not None:
					self.cap = cap
					first_frame = frame
				else:
					cap.release()

		if self.cap is None or first_frame is None:
			raise RuntimeError(f"Source Error: {source}")

		self._latest_frame = first_frame
		self._frame_id = 1
		self._running = True
		self._lock = threading.Lock()

		if self.on_frame is not None:
			try:
				self.on_frame(first_frame, 1)
			except Exception:
				pass

		self._thread = threading.Thread(target=self._capture_loop, daemon=True)
		self._thread.start()

	def _capture_loop(self):
		is_file = isinstance(self.source, str)
		frame_interval = 1.0 / TARGET_FPS
		while self._running:
			t0 = time.perf_counter()
			try:
				ret, frame = self.cap.read()
			except Exception:
				if not self._running:
					break
				time.sleep(0.01)
				continue
			if not ret or frame is None:
				if is_file:
					self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
					continue
				time.sleep(0.004)
				continue

			with self._lock:
				self._latest_frame = frame
				self._frame_id += 1
				fid = self._frame_id

			if self.on_frame is not None:
				try:
					self.on_frame(frame, fid)
				except Exception:
					pass

			if is_file:
				elapsed = time.perf_counter() - t0
				if elapsed < frame_interval:
					time.sleep(frame_interval - elapsed)

	def read(self):
		with self._lock:
			return self._latest_frame

	def read_with_id(self):
		with self._lock:
			return self._frame_id, self._latest_frame

	def release(self):
		self._running = False
		if hasattr(self, "_thread") and self._thread is not None and self._thread.is_alive():
			self._thread.join(timeout=0.4)
		if self.cap is not None and self.cap.isOpened():
			try:
				self.cap.release()
			except Exception:
				pass
