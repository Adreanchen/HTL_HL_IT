import asyncio
from multiprocessing.shared_memory import SharedMemory
import struct
import threading
from typing import Callable, Optional, Tuple
from fastapi.responses import StreamingResponse

JPEG_SLOT_BYTES = 524288
HEADER_STRUCT = struct.Struct("<qi")


class FrameBroadcaster:
	def __init__(self, on_viewer_change: Optional[Callable[[int], None]] = None):
		self.latest_jpeg: Optional[bytes] = None
		self.frame_id: int = 0
		self.running: bool = True
		self._shm: Optional[SharedMemory] = None
		self._on_viewer_change = on_viewer_change
		self._viewers: int = 0
		self._lock = threading.Lock()

	def attach_shared_memory(self, shm: SharedMemory) -> None:
		self._shm = shm

	def update_jpeg(self, jpeg_bytes: bytes) -> None:
		self.latest_jpeg = jpeg_bytes
		self.frame_id += 1

	def add_viewer(self) -> None:
		with self._lock:
			self._viewers += 1
		if self._on_viewer_change is not None:
			self._on_viewer_change(1)

	def remove_viewer(self) -> None:
		with self._lock:
			self._viewers = max(0, self._viewers - 1)
		if self._on_viewer_change is not None:
			self._on_viewer_change(-1)

	def get_latest(self) -> Tuple[int, Optional[bytes]]:
		if self._shm is not None:
			try:
				buf = self._shm.buf
				seq, length = HEADER_STRUCT.unpack_from(buf, 0)
				if seq > 0 and 0 < length <= JPEG_SLOT_BYTES:
					offset = 16 + (seq & 1) * JPEG_SLOT_BYTES
					data = bytes(buf[offset : offset + length])
					seq_after, _ = HEADER_STRUCT.unpack_from(buf, 0)
					if seq_after == seq:
						return seq, data
			except Exception:
				pass
		return self.frame_id, self.latest_jpeg

	def start(self) -> None:
		self.running = True

	def stop(self) -> None:
		self.running = False
		self._shm = None


def mjpeg_stream(broadcaster: FrameBroadcaster):
	broadcaster.start()

	async def gen():
		broadcaster.add_viewer()
		last_id = -1
		try:
			while broadcaster.running:
				current_id, jpeg_bytes = broadcaster.get_latest()
				if jpeg_bytes is not None and current_id != last_id:
					last_id = current_id
					yield (
						b"--frame\r\nContent-Type: image/jpeg\r\n\r\n"
						+ jpeg_bytes
						+ b"\r\n"
					)
				await asyncio.sleep(0.008)
		finally:
			broadcaster.remove_viewer()

	return StreamingResponse(
		gen(),
		media_type="multipart/x-mixed-replace; boundary=frame",
		headers={
			"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
			"Pragma": "no-cache",
			"Connection": "keep-alive",
		},
	)
