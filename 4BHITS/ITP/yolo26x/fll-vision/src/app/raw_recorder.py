from datetime import datetime
from pathlib import Path
import queue
import threading
import time
from typing import Dict, List, Optional, Tuple
import cv2
import numpy as np

DEFAULT_QUEUE_MAXSIZE = 120
DEFAULT_FALLBACK_FPS = 25.0
MIN_FPS = 5.0
MAX_FPS = 60.0
INITIAL_BUFFER_MAX_FRAMES = 10
INITIAL_BUFFER_MAX_SEC = 0.45


def _clamp_fps(fps: float) -> float:
	return max(MIN_FPS, min(MAX_FPS, float(fps)))


def _estimate_fps(timestamps: List[float], fallback: float = DEFAULT_FALLBACK_FPS) -> float:
	if len(timestamps) < 2:
		return fallback
	dt = timestamps[-1] - timestamps[0]
	if dt <= 1e-4:
		return fallback
	return round(_clamp_fps((len(timestamps) - 1) / dt), 2)


class RawVideoRecorder:
	"""Thread-safe raw camera video recorder fed via a non-blocking frame hook."""

	def __init__(self, videos_dir: Path, max_queue_size: int = DEFAULT_QUEUE_MAXSIZE):
		self._videos_dir = Path(videos_dir)
		self._max_queue_size = max(1, int(max_queue_size))

		self._lock = threading.Lock()
		self._op_lock = threading.Lock()

		self._recording = False
		self._queue: Optional[queue.Queue] = None
		self._stop_event: Optional[threading.Event] = None
		self._writer_thread: Optional[threading.Thread] = None

		self._file_path: Optional[Path] = None
		self._frames_written = 0
		self._dropped_frames = 0
		self._started_at: Optional[float] = None
		self._stopped_at: Optional[float] = None
		self._fps: Optional[float] = None
		self._resolution: Optional[List[int]] = None
		self._error: Optional[str] = None

	def _next_output_path(self) -> Path:
		stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
		candidate = self._videos_dir / f"raw_{stamp}.mp4"
		if not candidate.exists():
			return candidate
		suffix = 1
		while True:
			candidate = self._videos_dir / f"raw_{stamp}_{suffix}.mp4"
			if not candidate.exists():
				return candidate
			suffix += 1

	def on_frame(self, frame: np.ndarray) -> None:
		if not self._recording:
			return
		q = self._queue
		if q is None or frame is None:
			return
		try:
			q.put_nowait((time.monotonic(), frame.copy()))
		except queue.Full:
			with self._lock:
				self._dropped_frames += 1

	def start(self) -> Dict[str, object]:
		with self._op_lock:
			return self._start_unlocked()

	def _start_unlocked(self) -> Dict[str, object]:
		with self._lock:
			if self._recording:
				return self._status_locked()

			self._videos_dir.mkdir(parents=True, exist_ok=True)
			output_path = self._next_output_path()

			frame_queue: queue.Queue = queue.Queue(maxsize=self._max_queue_size)
			stop_event = threading.Event()

			self._queue = frame_queue
			self._stop_event = stop_event
			self._file_path = output_path
			self._frames_written = 0
			self._dropped_frames = 0
			self._started_at = time.monotonic()
			self._stopped_at = None
			self._fps = None
			self._resolution = None
			self._error = None
			self._recording = True

			thread = threading.Thread(
				target=self._writer_loop,
				args=(output_path, frame_queue, stop_event),
				name="RawVideoRecorderWriter",
				daemon=True,
			)
			self._writer_thread = thread
			thread.start()
			return self._status_locked()

	def stop(self) -> Dict[str, object]:
		with self._op_lock:
			return self._stop_unlocked()

	def _stop_unlocked(self) -> Dict[str, object]:
		with self._lock:
			if not self._recording:
				thread = self._writer_thread
			else:
				self._recording = False
				self._stopped_at = time.monotonic()
				stop_event = self._stop_event
				frame_queue = self._queue
				thread = self._writer_thread
				if stop_event is not None:
					stop_event.set()
				if frame_queue is not None:
					try:
						frame_queue.put_nowait(None)
					except queue.Full:
						pass

		if thread is not None and thread.is_alive():
			thread.join(timeout=10.0)

		with self._lock:
			if self._writer_thread is thread:
				self._writer_thread = None
				self._queue = None
				self._stop_event = None
			return self._status_locked()

	def toggle(self) -> Dict[str, object]:
		with self._op_lock:
			if self._recording:
				return self._stop_unlocked()
			return self._start_unlocked()

	def status(self) -> Dict[str, object]:
		with self._lock:
			return self._status_locked()

	def _status_locked(self) -> Dict[str, object]:
		if self._started_at is None:
			duration = 0.0
		elif self._recording or self._stopped_at is None:
			duration = max(0.0, time.monotonic() - self._started_at)
		else:
			duration = max(0.0, self._stopped_at - self._started_at)

		return {
			"recording": bool(self._recording),
			"file": str(self._file_path) if self._file_path is not None else None,
			"frames_written": int(self._frames_written),
			"dropped_frames": int(self._dropped_frames),
			"duration_seconds": round(duration, 2),
			"fps": self._fps,
			"resolution": list(self._resolution) if self._resolution is not None else None,
			"error": self._error,
		}

	@staticmethod
	def _normalize_frame_for_writer(frame: np.ndarray, expected_size: Tuple[int, int]) -> np.ndarray:
		if frame.ndim == 2:
			frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
		exp_w, exp_h = expected_size
		h, w = frame.shape[:2]
		if w != exp_w or h != exp_h:
			frame = cv2.resize(frame, (exp_w, exp_h), interpolation=cv2.INTER_AREA)
		return frame

	def _writer_loop(
		self,
		output_path: Path,
		frame_queue: queue.Queue,
		stop_event: threading.Event,
	) -> None:
		buffered: List[Tuple[float, np.ndarray]] = []
		writer: Optional[cv2.VideoWriter] = None
		expected_size: Optional[Tuple[int, int]] = None

		try:
			# Phase 1: buffer initial frames briefly to measure true frame arrival FPS
			while True:
				if len(buffered) >= INITIAL_BUFFER_MAX_FRAMES:
					break
				if len(buffered) >= 2 and (time.monotonic() - buffered[0][0]) >= INITIAL_BUFFER_MAX_SEC:
					break
				if stop_event.is_set() and frame_queue.empty():
					break

				try:
					item = frame_queue.get(timeout=0.05)
				except queue.Empty:
					continue

				if item is None:
					if stop_event.is_set() and frame_queue.empty():
						break
					continue

				buffered.append(item)

			if not buffered:
				with self._lock:
					if self._file_path == output_path:
						self._file_path = None
				return

			timestamps = [ts for ts, _ in buffered]
			fps = _estimate_fps(timestamps, fallback=DEFAULT_FALLBACK_FPS)
			first_frame = buffered[0][1]
			h, w = first_frame.shape[:2]
			expected_size = (w, h)

			fourcc = cv2.VideoWriter_fourcc(*"mp4v")
			writer = cv2.VideoWriter(str(output_path), fourcc, fps, expected_size)
			if not writer.isOpened():
				with self._lock:
					self._error = f"Failed to open VideoWriter for {output_path.name}"
					self._recording = False
				return

			with self._lock:
				self._fps = fps
				self._resolution = [w, h]

			for _, frame in buffered:
				writer.write(self._normalize_frame_for_writer(frame, expected_size))
				with self._lock:
					self._frames_written += 1
			buffered.clear()

			# Phase 2: stream remaining frames until stop_event is set and queue is drained
			while True:
				if stop_event.is_set() and frame_queue.empty():
					break
				try:
					item = frame_queue.get(timeout=0.05)
				except queue.Empty:
					continue
				if item is None:
					if stop_event.is_set() and frame_queue.empty():
						break
					continue

				_, frame = item
				writer.write(self._normalize_frame_for_writer(frame, expected_size))
				with self._lock:
					self._frames_written += 1

		except Exception as exc:
			with self._lock:
				self._error = str(exc)
				self._recording = False
		finally:
			if writer is not None:
				writer.release()
