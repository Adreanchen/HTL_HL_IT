from collections import deque
from datetime import datetime
import os
import queue
import threading
import time
from typing import Any, Callable, Dict, Optional

import cv2
from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.responses import FileResponse
import numpy as np

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
RAW_RECORDER_JS_PATH = os.path.join(STATIC_DIR, "raw-recorder.js")
RECORDINGS_DIR = os.path.abspath(
	os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "recordings")
)

MIN_FPS = 1.0
MAX_FPS = 120.0
DEFAULT_FPS = 30.0
QUEUE_MAXSIZE = 120


class RawVideoRecorder:
	"""Thread-safe, non-blocking raw BGR video recorder backed by cv2.VideoWriter."""

	def __init__(self, recordings_dir: str = RECORDINGS_DIR) -> None:
		self._recordings_dir = os.path.abspath(recordings_dir)
		self._lock = threading.Lock()
		self._frame_times: deque[float] = deque(maxlen=30)

		self._recording = False
		self._started_at: Optional[str] = None
		self._start_mono: Optional[float] = None
		self._frame_count = 0
		self._dropped_frames = 0
		self._writer_fps: Optional[float] = None
		self._resolution: Optional[str] = None
		self._filename: Optional[str] = None
		self._path: Optional[str] = None

		self._last_filename: Optional[str] = None
		self._last_path: Optional[str] = None
		self._last_frame_count = 0
		self._error: Optional[str] = None

		self._queue: Optional[queue.Queue] = None
		self._stop_event: Optional[threading.Event] = None
		self._writer_thread: Optional[threading.Thread] = None

	def _estimate_fps_locked(self) -> float:
		if len(self._frame_times) < 2:
			return DEFAULT_FPS
		dt = self._frame_times[-1] - self._frame_times[0]
		if dt <= 0.0:
			return DEFAULT_FPS
		fps = (len(self._frame_times) - 1) / dt
		return max(MIN_FPS, min(MAX_FPS, fps))

	def _build_status_locked(self) -> Dict[str, Any]:
		elapsed = 0.0
		if self._recording and self._start_mono is not None:
			elapsed = round(max(0.0, time.monotonic() - self._start_mono), 2)

		fps = self._writer_fps if (self._recording and self._writer_fps is not None) else self._estimate_fps_locked()
		return {
			"recording": self._recording,
			"startedAt": self._started_at,
			"elapsedSec": elapsed,
			"frameCount": self._frame_count,
			"droppedFrames": self._dropped_frames,
			"fps": round(fps, 2),
			"resolution": self._resolution,
			"filename": self._filename,
			"path": self._path,
			"lastFilename": self._last_filename,
			"lastPath": self._last_path,
			"lastFrameCount": self._last_frame_count,
			"error": self._error,
		}

	def _next_recording_file_locked(self) -> tuple[str, str]:
		stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
		base = f"raw_{stamp}"
		candidate = f"{base}.avi"
		full_path = os.path.join(self._recordings_dir, candidate)
		counter = 1
		while os.path.exists(full_path):
			candidate = f"{base}_{counter}.avi"
			full_path = os.path.join(self._recordings_dir, candidate)
			counter += 1
		return candidate, full_path

	def on_raw_frame(self, frame: np.ndarray, frame_id: int) -> None:
		"""Capture hook called on the camera thread before any pipeline processing."""
		now = time.monotonic()
		with self._lock:
			self._frame_times.append(now)
			if not self._recording or self._queue is None:
				return
			q = self._queue

		if frame is None or not hasattr(frame, "shape") or frame.size == 0:
			return

		frame_copy = frame.copy()
		try:
			q.put_nowait(frame_copy)
		except queue.Full:
			with self._lock:
				self._dropped_frames += 1

	def _writer_loop(
		self,
		q: queue.Queue,
		stop_event: threading.Event,
		filepath: str,
		filename: str,
	) -> None:
		writer: Optional[cv2.VideoWriter] = None
		expected_w = 0
		expected_h = 0
		frames_written = 0

		try:
			while True:
				try:
					item = q.get(timeout=0.1)
				except queue.Empty:
					if stop_event.is_set():
						break
					continue

				if item is None:
					break

				h, w = item.shape[:2]
				if writer is None:
					with self._lock:
						fps = self._estimate_fps_locked()
					fourcc = cv2.VideoWriter_fourcc(*"MJPG")
					writer = cv2.VideoWriter(filepath, fourcc, fps, (w, h))
					if not writer.isOpened():
						writer.release()
						writer = None
						with self._lock:
							self._error = f"Failed to open VideoWriter for {filename}"
							self._recording = False
						break
					expected_w, expected_h = w, h
					with self._lock:
						self._writer_fps = fps
						self._resolution = f"{w}x{h}"

				if w != expected_w or h != expected_h:
					continue

				writer.write(item)
				frames_written += 1
				with self._lock:
					self._frame_count = frames_written
		except Exception as exc:
			with self._lock:
				self._error = f"Writer error: {exc}"
				self._recording = False
		finally:
			if writer is not None:
				writer.release()

			if frames_written == 0 and os.path.isfile(filepath):
				try:
					os.remove(filepath)
				except OSError:
					pass

			with self._lock:
				self._frame_count = frames_written
				if frames_written > 0 and os.path.isfile(filepath):
					self._last_filename = filename
					self._last_path = filepath
					self._last_frame_count = frames_written

	def start(self) -> Dict[str, Any]:
		"""Start a raw video recording session (idempotent if already active)."""
		with self._lock:
			if self._recording:
				return self._build_status_locked()

			os.makedirs(self._recordings_dir, exist_ok=True)
			filename, filepath = self._next_recording_file_locked()

			q: queue.Queue = queue.Queue(maxsize=QUEUE_MAXSIZE)
			stop_event = threading.Event()
			thread = threading.Thread(
				target=self._writer_loop,
				args=(q, stop_event, filepath, filename),
				daemon=True,
				name="raw-video-writer",
			)

			self._recording = True
			self._started_at = datetime.now().astimezone().isoformat(timespec="seconds")
			self._start_mono = time.monotonic()
			self._frame_count = 0
			self._dropped_frames = 0
			self._writer_fps = None
			self._resolution = None
			self._filename = filename
			self._path = filepath
			self._error = None
			self._queue = q
			self._stop_event = stop_event
			self._writer_thread = thread

			thread.start()
			return self._build_status_locked()

	def stop(self) -> Dict[str, Any]:
		"""Stop active recording, drain queue, release VideoWriter, and update last* fields."""
		with self._lock:
			if not self._recording and self._writer_thread is None:
				return self._build_status_locked()

			self._recording = False
			q = self._queue
			stop_event = self._stop_event
			thread = self._writer_thread

		if stop_event is not None:
			stop_event.set()

		if q is not None:
			while thread is not None and thread.is_alive():
				try:
					q.put(None, timeout=0.1)
					break
				except queue.Full:
					continue

		if thread is not None:
			thread.join(timeout=10.0)

		with self._lock:
			self._queue = None
			self._stop_event = None
			self._writer_thread = None
			self._started_at = None
			self._start_mono = None
			self._frame_count = 0
			self._writer_fps = None
			self._resolution = None
			self._filename = None
			self._path = None
			return self._build_status_locked()

	def get_status(self) -> Dict[str, Any]:
		with self._lock:
			return self._build_status_locked()


class RawRecorderInjectionMiddleware:
	"""Pure ASGI middleware injecting <script src="/raw-recorder.js"></script> on / and /control."""

	INJECT_TAG = b'<script src="/raw-recorder.js"></script>'

	def __init__(self, app: Callable[..., Any]) -> None:
		self.app = app

	async def __call__(self, scope: Dict[str, Any], receive: Callable[..., Any], send: Callable[..., Any]) -> None:
		if (
			scope.get("type") != "http"
			or scope.get("path") not in ("/", "/control")
			or scope.get("method", "GET") != "GET"
		):
			await self.app(scope, receive, send)
			return

		initial_message: Optional[Dict[str, Any]] = None
		body_chunks: list[bytes] = []

		async def send_wrapper(message: Dict[str, Any]) -> None:
			nonlocal initial_message
			msg_type = message.get("type")
			if msg_type == "http.response.start":
				initial_message = message
				return
			if msg_type == "http.response.body":
				body_chunks.append(message.get("body", b""))
				if message.get("more_body", False):
					return

				assert initial_message is not None
				full_body = b"".join(body_chunks)
				headers = list(initial_message.get("headers", []))
				status = initial_message.get("status", 200)

				content_type = ""
				for k, v in headers:
					if k.lower() == b"content-type":
						content_type = v.decode("latin-1").lower()
						break

				if status == 200 and "text/html" in content_type and self.INJECT_TAG not in full_body:
					idx = full_body.rfind(b"</body>")
					if idx == -1:
						idx = full_body.rfind(b"</BODY>")
					if idx != -1:
						full_body = full_body[:idx] + self.INJECT_TAG + b"\n" + full_body[idx:]
					else:
						full_body = full_body + self.INJECT_TAG

					new_headers = [(k, v) for k, v in headers if k.lower() != b"content-length"]
					new_headers.append((b"content-length", str(len(full_body)).encode("ascii")))
					initial_message = {**initial_message, "headers": new_headers}

				await send(initial_message)
				await send(
					{
						"type": "http.response.body",
						"body": full_body,
						"more_body": False,
					}
				)
				return

			await send(message)

		await self.app(scope, receive, send_wrapper)


def attach_raw_recorder(app: FastAPI, pipeline: Any) -> RawVideoRecorder:
	"""Attach raw frame capture, API routes, shutdown hook, and script injection to app/pipeline."""
	existing = getattr(app.state, "raw_recorder", None)
	if existing is not None:
		return existing

	recorder = RawVideoRecorder()
	app.state.raw_recorder = recorder

	original_on_camera_frame = pipeline._on_camera_frame

	def _wrapped_on_camera_frame(frame: np.ndarray, frame_id: int) -> Any:
		try:
			recorder.on_raw_frame(frame, frame_id)
		except Exception:
			pass
		return original_on_camera_frame(frame, frame_id)

	pipeline._on_camera_frame = _wrapped_on_camera_frame

	router = APIRouter()

	@router.get("/raw-recorder.js")
	def get_raw_recorder_js():
		if not os.path.isfile(RAW_RECORDER_JS_PATH):
			raise HTTPException(status_code=404, detail="raw-recorder.js not found")
		return FileResponse(
			path=RAW_RECORDER_JS_PATH,
			media_type="application/javascript",
			headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"},
		)

	@router.get("/api/recording/status")
	def get_recording_status():
		return recorder.get_status()

	@router.post("/api/recording/start")
	def start_recording():
		return recorder.start()

	@router.post("/api/recording/stop")
	def stop_recording():
		return recorder.stop()

	@router.get("/api/recording/download/{filename}")
	def download_recording(filename: str):
		if (
			not filename
			or ".." in filename
			or "/" in filename
			or "\\" in filename
			or "\x00" in filename
			or os.path.basename(filename) != filename
		):
			raise HTTPException(status_code=400, detail="Invalid recording filename.")

		status = recorder.get_status()
		if status["recording"] and status["filename"] == filename:
			raise HTTPException(status_code=409, detail="Cannot download an active recording.")

		recordings_root = os.path.realpath(recorder._recordings_dir)
		target_path = os.path.realpath(os.path.join(recordings_root, filename))
		if not target_path.startswith(recordings_root + os.sep):
			raise HTTPException(status_code=400, detail="Invalid recording path.")

		if not os.path.isfile(target_path):
			raise HTTPException(status_code=404, detail="Recording not found.")

		return FileResponse(
			path=target_path,
			media_type="video/x-msvideo",
			filename=filename,
		)

	app.include_router(router)
	add_event_handler = getattr(app, "add_event_handler", app.router.add_event_handler)
	add_event_handler("shutdown", recorder.stop)
	app.add_middleware(RawRecorderInjectionMiddleware)

	return recorder
