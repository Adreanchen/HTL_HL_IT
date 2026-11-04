"""
run.py — Single-Command Launcher for FLL Vision & Livestream
------------------------------------------------------------
Run the entire project (Vision Backend on :8002 + Video Wall Livestream on :3000)
with one command:

    python run.py

Optional subcommands for YOLOv8 training & standalone tracking:
    python run.py extract --video match.mp4   # 1. Extract frames to dataset/raw/
    python run.py train                       # 2. Train YOLOv8n for 50 epochs on cuda:0
    python run.py track                       # 3. Run standalone OpenCV live tracker window
"""

from multiprocessing import freeze_support
import os
import socket
import subprocess
import sys
import time

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
VISION_DIR = os.path.join(ROOT_DIR, "fll-vision")
FRONTEND_DIR = os.path.join(ROOT_DIR, "fll-robot-game-livestream")


def get_lan_ip() -> str:
	try:
		with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
			s.connect(("8.8.8.8", 80))
			return s.getsockname()[0]
	except Exception:
		return "localhost"


def run_vision_backend() -> None:
	"""Runs the FLL Vision & Match Control FastAPI server on port 8002."""
	sys.path.insert(0, VISION_DIR)
	os.chdir(VISION_DIR)
	import uvicorn
	from src.app.logging import setup_logging
	from src.app.main import app, pipeline

	setup_logging()
	try:
		uvicorn.run(app, host="0.0.0.0", port=8002, log_level="info", timeout_graceful_shutdown=1)
	finally:
		pipeline.stop()


def run_full_stack() -> None:
	"""Starts both the FLL Vision Backend (:8002) and React Video Wall (:3000) in one terminal."""
	npm_cmd = "npm.cmd" if sys.platform.startswith("win") else "npm"

	# Automatically install frontend node_modules once if missing
	node_modules = os.path.join(FRONTEND_DIR, "node_modules")
	if os.path.isdir(FRONTEND_DIR) and not os.path.isdir(node_modules):
		print("[SETUP] Installing frontend packages (first-time setup)...")
		subprocess.run([npm_cmd, "install"], cwd=FRONTEND_DIR, check=True)

	lan_ip = get_lan_ip()
	print("=" * 68)
	print("  FLL ROBOT GAME LIVESTREAM & VISION TRACKER")
	print("=" * 68)
	print(f"  Video Wall / OBS Display : http://localhost:3000")
	print(f"  Phone / PC Control Panel : http://{lan_ip}:8002")
	print("  Press Ctrl+C at any time to stop everything.")
	print("=" * 68)

	procs = []
	try:
		# 1. Start Vision Backend (Port 8002)
		vision_proc = subprocess.Popen(
			[sys.executable, os.path.abspath(__file__), "--backend"],
			cwd=ROOT_DIR,
		)
		procs.append(vision_proc)

		# 2. Start Frontend Video Wall (Port 3000)
		if os.path.isdir(FRONTEND_DIR):
			env = os.environ.copy()
			env.setdefault("BROWSER", "none")
			frontend_proc = subprocess.Popen(
				[npm_cmd, "start"],
				cwd=FRONTEND_DIR,
				env=env,
			)
			procs.append(frontend_proc)

		# Monitor child processes until interrupted
		while True:
			for p in procs:
				if p.poll() is not None:
					raise RuntimeError(f"Process (PID {p.pid}) exited with code {p.returncode}.")
			time.sleep(0.5)

	except KeyboardInterrupt:
		print("\n[INFO] Stopping FLL Vision and Video Wall...")
	except Exception as exc:
		print(f"\n[INFO] Shutting down ({exc})...")
	finally:
		for p in procs:
			if p.poll() is None:
				try:
					if sys.platform.startswith("win"):
						subprocess.run(
							["taskkill", "/F", "/T", "/PID", str(p.pid)],
							stdout=subprocess.DEVNULL,
							stderr=subprocess.DEVNULL,
						)
					else:
						p.terminate()
				except Exception:
					pass
		print("[INFO] All services stopped cleanly.")


def main() -> None:
	freeze_support()
	if len(sys.argv) > 1:
		cmd = sys.argv[1].lower()
		rest = sys.argv[2:]
		if cmd == "--backend":
			run_vision_backend()
			return
		elif cmd == "extract":
			sys.exit(subprocess.call([sys.executable, os.path.join(ROOT_DIR, "1_extract_frames.py"), *rest]))
		elif cmd == "train":
			sys.exit(subprocess.call([sys.executable, os.path.join(ROOT_DIR, "2_train_model.py"), *rest]))
		elif cmd == "track":
			sys.exit(subprocess.call([sys.executable, os.path.join(ROOT_DIR, "3_live_tracking.py"), *rest]))
		elif cmd in ("-h", "--help", "help"):
			print(__doc__.strip())
			return

	run_full_stack()


if __name__ == "__main__":
	main()
