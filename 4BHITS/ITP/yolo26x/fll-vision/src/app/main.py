import os
from typing import List, Optional

from fastapi import Body, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel

from .calibration import (
	DEFAULT_TABLE_ROIS,
	detect_table_rois,
	encode_raw_frame_jpeg,
	render_calibration_preview_jpeg,
)
from .config import LEFT_GPU, RIGHT_GPU, VIDEO_SOURCE
from .state import MatchStateManager
from .stream import FrameBroadcaster, mjpeg_stream
from .worker import VisionPipeline

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
CONTROLLER_HTML_PATH = os.path.join(STATIC_DIR, "controller.html")

app = FastAPI(title="FLL Vision & Match Control")

app.add_middleware(
	CORSMiddleware,
	allow_origins=["*"],
	allow_credentials=True,
	allow_methods=["*"],
	allow_headers=["*"],
)

state_manager = MatchStateManager()
left_broadcaster = FrameBroadcaster()
right_broadcaster = FrameBroadcaster()
left_control_broadcaster = FrameBroadcaster(on_viewer_change=lambda d: pipeline.adjust_control_viewers(d))
right_control_broadcaster = FrameBroadcaster(on_viewer_change=lambda d: pipeline.adjust_control_viewers(d))

pipeline = VisionPipeline(
	VIDEO_SOURCE,
	LEFT_GPU,
	RIGHT_GPU,
	left_broadcaster,
	right_broadcaster,
	left_control_broadcaster,
	right_control_broadcaster,
	initial_rois=state_manager.get_table_rois(),
)


class TeamsUpdateRequest(BaseModel):
	red: str
	blue: str


class TeamListUpdateRequest(BaseModel):
	teams: Optional[List[str]] = None
	text: Optional[str] = None


class TimerStartRequest(BaseModel):
	preCountEnabled: Optional[bool] = None


class TimerSettingsRequest(BaseModel):
	preCountEnabled: bool


class TableBoxModel(BaseModel):
	x1: float
	y1: float
	x2: float
	y2: float


class ManualCalibrationRequest(BaseModel):
	left: TableBoxModel
	right: TableBoxModel


@app.on_event("startup")
def startup_event():
	pipeline.start()


@app.on_event("shutdown")
def shutdown_event():
	pipeline.stop()


@app.get("/", response_class=HTMLResponse)
@app.get("/control", response_class=HTMLResponse)
async def remote_controller_ui():
	with open(CONTROLLER_HTML_PATH, "r", encoding="utf-8") as f:
		html = f.read()
	return HTMLResponse(
		content=html,
		headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"},
	)


@app.get("/api/state")
async def get_match_state():
	return state_manager.get_snapshot()


@app.post("/api/teams")
async def update_teams(payload: TeamsUpdateRequest):
	snapshot = state_manager.set_teams(payload.red, payload.blue)
	await state_manager.broadcast()
	return snapshot


@app.post("/api/teams/swap")
async def swap_teams():
	snapshot = state_manager.swap_teams()
	await state_manager.broadcast()
	return snapshot


@app.post("/api/team-list")
async def update_team_list(payload: TeamListUpdateRequest):
	raw_items: List[str] = []
	if payload.teams is not None:
		raw_items = payload.teams
	elif payload.text is not None:
		raw_items = payload.text.splitlines()

	try:
		snapshot = state_manager.set_team_list(raw_items)
	except ValueError as exc:
		raise HTTPException(status_code=400, detail=str(exc)) from exc

	await state_manager.broadcast()
	return snapshot


@app.post("/api/timer/start")
async def start_timer(payload: Optional[TimerStartRequest] = Body(default=None)):
	prev_version = state_manager.get_snapshot()["version"]
	pre_count = payload.preCountEnabled if payload is not None else None
	snapshot = state_manager.start_timer(pre_count_enabled=pre_count)
	if snapshot["version"] != prev_version:
		await state_manager.broadcast()
	return snapshot


@app.post("/api/timer/reset")
async def reset_timer():
	pipeline.reset_tracking()
	snapshot = state_manager.reset_timer()
	await state_manager.broadcast()
	return snapshot


@app.post("/api/tracking/reset")
async def reset_tracking():
	pipeline.reset_tracking()
	return {"ok": True}


@app.post("/api/timer/settings")
async def update_timer_settings(payload: TimerSettingsRequest):
	prev_version = state_manager.get_snapshot()["version"]
	snapshot = state_manager.set_timer_settings(payload.preCountEnabled)
	if snapshot["version"] != prev_version:
		await state_manager.broadcast()
	return snapshot


@app.post("/api/calibrate-tables")
async def calibrate_tables():
	frame = pipeline.get_latest_frame()
	if frame is None:
		raise HTTPException(status_code=503, detail="Camera feed is not ready yet.")
	detected_rois = detect_table_rois(frame)
	clean_rois = pipeline.set_table_rois(detected_rois)
	snapshot = state_manager.set_calibration(clean_rois, calibrated=True)
	await state_manager.broadcast()
	return snapshot


@app.post("/api/calibrate-tables/manual")
async def manual_calibrate_tables(payload: ManualCalibrationRequest):
	manual_rois = {
		"left": {"x1": payload.left.x1, "y1": payload.left.y1, "x2": payload.left.x2, "y2": payload.left.y2},
		"right": {"x1": payload.right.x1, "y1": payload.right.y1, "x2": payload.right.x2, "y2": payload.right.y2},
	}
	clean_rois = pipeline.set_table_rois(manual_rois)
	snapshot = state_manager.set_calibration(clean_rois, calibrated=True)
	await state_manager.broadcast()
	return snapshot


@app.post("/api/calibrate-tables/reset")
async def reset_table_calibration():
	clean_rois = pipeline.set_table_rois(DEFAULT_TABLE_ROIS)
	snapshot = state_manager.set_calibration(clean_rois, calibrated=False)
	await state_manager.broadcast()
	return snapshot


@app.get("/api/raw-frame")
async def raw_camera_frame():
	frame = pipeline.get_latest_frame()
	if frame is None:
		raise HTTPException(status_code=503, detail="Camera feed is not ready yet.")
	jpeg_bytes = encode_raw_frame_jpeg(frame)
	return Response(
		content=jpeg_bytes,
		media_type="image/jpeg",
		headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"},
	)


@app.get("/api/calibration-preview")
async def calibration_preview():
	frame = pipeline.get_latest_frame()
	if frame is None:
		raise HTTPException(status_code=503, detail="Camera feed is not ready yet.")
	jpeg_bytes = render_calibration_preview_jpeg(frame, state_manager.get_table_rois())
	return Response(
		content=jpeg_bytes,
		media_type="image/jpeg",
		headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"},
	)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
	await state_manager.connect(websocket)
	try:
		while True:
			message = await websocket.receive_text()
			if message == "ping":
				await websocket.send_json(state_manager.get_snapshot())
	except WebSocketDisconnect:
		pass
	except Exception:
		pass
	finally:
		state_manager.disconnect(websocket)


@app.get("/left")
@app.get("/video-stream/red-team")
def left():
	return mjpeg_stream(left_broadcaster)


@app.get("/right")
@app.get("/video-stream/blue-team")
def right():
	return mjpeg_stream(right_broadcaster)


@app.get("/video-stream/red-team/control")
def left_control():
	return mjpeg_stream(left_control_broadcaster)


@app.get("/video-stream/blue-team/control")
def right_control():
	return mjpeg_stream(right_control_broadcaster)
