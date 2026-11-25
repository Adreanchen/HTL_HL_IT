from fastapi import APIRouter

from .raw_recorder import RawVideoRecorder


def create_raw_recording_router(recorder: RawVideoRecorder) -> APIRouter:
	router = APIRouter(prefix="/api/raw-recording", tags=["raw-recording"])

	@router.get("/status")
	def get_raw_recording_status():
		return recorder.status()

	@router.post("/start")
	def start_raw_recording():
		return {"ok": True, **recorder.start()}

	@router.post("/stop")
	def stop_raw_recording():
		return {"ok": True, **recorder.stop()}

	@router.post("/toggle")
	def toggle_raw_recording():
		return {"ok": True, **recorder.toggle()}

	return router
