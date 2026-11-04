from copy import deepcopy
import json
import logging
import os
import threading
import time
from typing import List, Optional, Set

from fastapi import WebSocket

from .calibration import DEFAULT_TABLE_ROIS, sanitize_table_rois

logger = logging.getLogger("fll-vision.state")

FLL_VISION_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
WORKSPACE_ROOT = os.path.abspath(os.path.join(FLL_VISION_DIR, ".."))
ROOT_TEAMS_TXT = os.path.join(WORKSPACE_ROOT, "teams.txt")
LOCAL_TEAMS_TXT = os.path.join(FLL_VISION_DIR, "teams.txt")
STATE_JSON_PATH = os.path.join(FLL_VISION_DIR, "match_state.json")

DEFAULT_MATCH_DURATION = 150
DEFAULT_PRE_COUNT_DURATION = 10


class MatchStateManager:
	def __init__(self):
		self._lock = threading.RLock()
		self._clients: Set[WebSocket] = set()

		self._version: int = 1
		self._team_list: List[str] = self._load_initial_team_list()

		default_red = self._team_list[0] if len(self._team_list) >= 1 else "Red Team"
		default_blue = self._team_list[1] if len(self._team_list) >= 2 else "Blue Team"

		saved = self._load_saved_state()
		self._red_team: str = str(saved.get("red") or "").strip() or default_red
		self._blue_team: str = str(saved.get("blue") or "").strip() or default_blue
		self._pre_count_enabled: bool = bool(saved.get("preCountEnabled", True))

		self._tables_calibrated: bool = bool(saved.get("tablesCalibrated", False))
		self._table_rois: dict = sanitize_table_rois(saved.get("tableRois") or DEFAULT_TABLE_ROIS)

		self._pre_count_duration: int = DEFAULT_PRE_COUNT_DURATION
		self._duration: int = DEFAULT_MATCH_DURATION
		self._timer_status: str = "idle"
		self._timer_action_id: int = 0
		self._timer_started_at: Optional[float] = None

	def _resolve_teams_txt_path(self) -> str:
		if os.path.exists(ROOT_TEAMS_TXT):
			return ROOT_TEAMS_TXT
		if os.path.exists(LOCAL_TEAMS_TXT):
			return LOCAL_TEAMS_TXT
		return ROOT_TEAMS_TXT

	def _load_initial_team_list(self) -> List[str]:
		path = self._resolve_teams_txt_path()
		if os.path.exists(path):
			try:
				with open(path, "r", encoding="utf-8") as f:
					teams = self._clean_team_list(f.read().splitlines())
				if teams:
					return teams
			except Exception as exc:
				logger.warning("Failed to read teams.txt from %s: %s", path, exc)
		return ["Red Team", "Blue Team"]

	def _load_saved_state(self) -> dict:
		if not os.path.exists(STATE_JSON_PATH):
			return {}
		try:
			with open(STATE_JSON_PATH, "r", encoding="utf-8") as f:
				data = json.load(f)
			return data if isinstance(data, dict) else {}
		except Exception as exc:
			logger.warning("Failed to read match_state.json: %s", exc)
			return {}

	def _save_state(self) -> None:
		payload = {
			"red": self._red_team,
			"blue": self._blue_team,
			"preCountEnabled": self._pre_count_enabled,
			"tablesCalibrated": self._tables_calibrated,
			"tableRois": self._table_rois,
		}
		try:
			with open(STATE_JSON_PATH, "w", encoding="utf-8") as f:
				json.dump(payload, f, indent=2, ensure_ascii=False)
		except Exception as exc:
			logger.warning("Failed to persist match_state.json: %s", exc)

	@staticmethod
	def _clean_team_list(raw_teams: List[str]) -> List[str]:
		seen = set()
		cleaned = []
		for item in raw_teams:
			if not isinstance(item, str):
				continue
			name = item.strip()
			if name and name not in seen:
				seen.add(name)
				cleaned.append(name)
		return cleaned

	def _total_countdown_seconds(self) -> int:
		pre = self._pre_count_duration if self._pre_count_enabled else 0
		return pre + self._duration

	def get_table_rois(self) -> dict:
		with self._lock:
			return deepcopy(self._table_rois)

	def set_calibration(self, rois: dict, calibrated: bool) -> dict:
		with self._lock:
			self._table_rois = sanitize_table_rois(rois)
			self._tables_calibrated = bool(calibrated)
			self._version += 1
			self._save_state()
			return self.get_snapshot()

	def get_snapshot(self) -> dict:
		with self._lock:
			now = time.time()
			elapsed = 0.0
			if self._timer_status == "running" and self._timer_started_at is not None:
				elapsed = max(0.0, now - self._timer_started_at)

			return {
				"version": self._version,
				"serverTime": now,
				"teams": {
					"red": self._red_team,
					"blue": self._blue_team,
				},
				"teamList": list(self._team_list),
				"timer": {
					"status": self._timer_status,
					"actionId": self._timer_action_id,
					"elapsed": round(elapsed, 3),
					"preCountEnabled": self._pre_count_enabled,
					"preCountDuration": self._pre_count_duration,
					"duration": self._duration,
				},
				"calibration": {
					"calibrated": self._tables_calibrated,
					"rois": deepcopy(self._table_rois),
				},
			}

	def set_teams(self, red: str, blue: str) -> dict:
		with self._lock:
			self._red_team = (red or "").strip() or "Red Team"
			self._blue_team = (blue or "").strip() or "Blue Team"
			self._version += 1
			self._save_state()
			return self.get_snapshot()

	def swap_teams(self) -> dict:
		with self._lock:
			self._red_team, self._blue_team = self._blue_team, self._red_team
			self._version += 1
			self._save_state()
			return self.get_snapshot()

	def set_team_list(self, teams: List[str]) -> dict:
		cleaned = self._clean_team_list(teams)
		if not cleaned:
			raise ValueError("Please provide at least one team name.")

		with self._lock:
			self._team_list = cleaned
			target_path = self._resolve_teams_txt_path()
			try:
				with open(target_path, "w", encoding="utf-8") as f:
					f.write("\n".join(cleaned) + "\n")
			except Exception as exc:
				logger.warning("Failed to write teams.txt to %s: %s", target_path, exc)

			if self._red_team == "Red Team" and len(cleaned) >= 1:
				self._red_team = cleaned[0]
			if self._blue_team == "Blue Team" and len(cleaned) >= 2:
				self._blue_team = cleaned[1]

			self._version += 1
			self._save_state()
			return self.get_snapshot()

	def start_timer(self, pre_count_enabled: Optional[bool] = None) -> dict:
		with self._lock:
			now = time.time()
			if self._timer_status == "running" and self._timer_started_at is not None:
				elapsed = max(0.0, now - self._timer_started_at)
				if elapsed < self._total_countdown_seconds():
					return self.get_snapshot()

			if pre_count_enabled is not None:
				self._pre_count_enabled = bool(pre_count_enabled)
				self._save_state()

			self._timer_status = "running"
			self._timer_started_at = now
			self._timer_action_id += 1
			self._version += 1
			return self.get_snapshot()

	def reset_timer(self) -> dict:
		with self._lock:
			self._timer_status = "idle"
			self._timer_started_at = None
			self._timer_action_id += 1
			self._version += 1
			return self.get_snapshot()

	def set_timer_settings(self, pre_count_enabled: bool) -> dict:
		with self._lock:
			if self._timer_status == "running" and self._timer_started_at is not None:
				elapsed = max(0.0, time.time() - self._timer_started_at)
				if elapsed < self._total_countdown_seconds():
					return self.get_snapshot()

			self._pre_count_enabled = bool(pre_count_enabled)
			self._version += 1
			self._save_state()
			return self.get_snapshot()

	async def connect(self, websocket: WebSocket) -> None:
		await websocket.accept()
		self._clients.add(websocket)
		try:
			await websocket.send_json(self.get_snapshot())
		except Exception:
			self._clients.discard(websocket)

	def disconnect(self, websocket: WebSocket) -> None:
		self._clients.discard(websocket)

	async def broadcast(self) -> None:
		snapshot = self.get_snapshot()
		stale: List[WebSocket] = []
		for client in list(self._clients):
			try:
				await client.send_json(snapshot)
			except Exception:
				stale.append(client)
		for client in stale:
			self._clients.discard(client)
