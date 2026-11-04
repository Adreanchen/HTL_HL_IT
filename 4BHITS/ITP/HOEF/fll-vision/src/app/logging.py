import logging
import sys


def setup_logging():
	"""
	Configures root logger for console output (stdout) for Docker/production.
	"""
	logger = logging.getLogger()
	logger.setLevel(logging.INFO)

	# Remove any existing handlers
	if logger.hasHandlers():
		logger.handlers.clear()

	# Create console handler
	ch = logging.StreamHandler(sys.stdout)
	ch.setLevel(logging.INFO)

	# Create formatter
	formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
	ch.setFormatter(formatter)

	# Add handler to root logger
	logger.addHandler(ch)

	return logger
