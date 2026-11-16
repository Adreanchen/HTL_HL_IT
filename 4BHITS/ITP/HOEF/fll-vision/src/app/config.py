import os

LEFT_GPU = int(os.environ.get("LEFT_GPU", 0))
RIGHT_GPU = int(os.environ.get("RIGHT_GPU", 0))

# Can be an integer (camera index 0 or 1) or a string (e.g. "match.mp4")
raw_video_source = os.environ.get("VIDEO_SOURCE")
if raw_video_source is not None:
	VIDEO_SOURCE = int(raw_video_source) if raw_video_source.isdigit() else raw_video_source
elif os.path.exists("match.mp4"):
	VIDEO_SOURCE = "match.mp4"
else:
	VIDEO_SOURCE = 1

# Frame rates & encoding
TARGET_FPS = 60
DETECTION_FPS = 20           # 20 Hz robot detection keeps CPU usage low while render pans at 60 FPS
JPEG_QUALITY = 78            # Clean MJPEG encoding with low latency
MAX_OUTPUT_HEIGHT = 720      # Cap output height without upscaling smaller table crops

# Portrait downscaled detection grid matching FLL table aspect ratio (~1 : 1.8)
DETECTION_WIDTH = 180
DETECTION_HEIGHT = 320
MIN_MOTION_PIXELS = 45       # Minimum active motion pixels to trigger tracking (ignores static camera noise)

# Moving object filter settings (evaluated on 180x320 cropped table region)
MIN_AREA_RATIO = 0.0012      # Minimum moving contour area fraction (~70 px on 180x320)
MAX_AREA_RATIO = 0.65        # Rejects full-frame camera bumps / global lighting flashes
MAX_BBOX_W_RATIO = 0.85      # Max width fraction of table region
MAX_BBOX_H_RATIO = 0.85      # Max height fraction of table region
MIN_SOLIDITY = 0.15
MIN_EXTENT = 0.10
MIN_COMPACTNESS = 0.02
MIN_ASPECT_RATIO = 0.12
MAX_ASPECT_RATIO = 8.0
MAX_SKIN_RATIO = 1.0
BORDER_MAX_SKIN_RATIO = 1.0
CONFIRM_FRAMES = 2           # Consecutive detection ticks to confirm movement
MAX_STEP_RATIO = 0.45        # Continuity preference radius ratio

# Hold focus briefly when a moving robot pauses, while releasing cleanly when removed
STOPPED_HOLD_SEC = 1.2       # Grace window to hold lock across brief pauses before unfocusing
TARGET_SMOOTH_SPEED = 8.0    # Stage-1 60Hz target trajectory smoothing (removes 20Hz stepping)
PAN_SPEED = 6.5              # Stage-2 fluid-head camera pan speed
ZOOM_SPEED = 4.5             # Stage-2 smooth optical zoom speed
PAN_DEADZONE_RATIO = 0.012   # Ignore sub-1.2% contour micro-wobble

# Automatic Brightness / Contrast / White-Balance settings
AUTO_ENHANCE_ENABLED = True
TARGET_BRIGHTNESS = 132.0    # Target mean luminance (0..255) for clear broadcast visibility

# Video Wall Zoom Framing (constant-size zoom window -> zero zoom breathing/pumping):
ROBOT_ZOOM_W = 0.64          # Fraction of table width when zoomed in on active/stopped robot
ROBOT_ZOOM_ASPECT = 1.08     # Height/Width ratio of zoomed window (matches Video Wall pane)
ROBOT_ZOOM_H_MAX = 0.64      # Maximum height fraction when zoomed in
