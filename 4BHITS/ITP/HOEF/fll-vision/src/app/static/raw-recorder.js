(() => {
	"use strict";

	const API_STATUS = "/api/recording/status";
	const API_START = "/api/recording/start";
	const API_STOP = "/api/recording/stop";
	const API_DOWNLOAD_BASE = "/api/recording/download/";

	const POLL_RECORDING_MS = 1000;
	const POLL_IDLE_MS = 3000;

	const STYLE_ID = "rawRecordStyles";
	const BTN_ID = "rawRecordBtn";
	const STATUS_ID = "rawRecordStatus";

	function injectStyles() {
		if (document.getElementById(STYLE_ID)) return;

		const style = document.createElement("style");
		style.id = STYLE_ID;
		style.textContent = `
			#${BTN_ID} {
				display: inline-flex;
				align-items: center;
				justify-content: center;
				gap: 8px;
			}
			#${BTN_ID}.raw-rec-btn--recording {
				background: var(--red, #dc2626);
				border-color: var(--red, #dc2626);
				color: #ffffff;
			}
			#${BTN_ID}.raw-rec-btn--recording:hover:not(:disabled) {
				background: #b91c1c;
				border-color: #b91c1c;
			}
			.raw-rec-dot {
				width: 8px;
				height: 8px;
				border-radius: 999px;
				background: var(--red, #dc2626);
				flex-shrink: 0;
			}
			#${BTN_ID}.raw-rec-btn--recording .raw-rec-dot {
				background: #ffffff;
				animation: raw-rec-pulse 1.1s ease-in-out infinite;
			}
			@keyframes raw-rec-pulse {
				0%, 100% { opacity: 1; transform: scale(1); }
				50% { opacity: 0.4; transform: scale(0.82); }
			}
			#${STATUS_ID} {
				margin-top: 10px;
				padding: 10px 14px;
				background: var(--surface-subtle, #f1f5f9);
				border: 1px solid var(--border, #e2e8f0);
				border-radius: var(--radius-md, 12px);
				font-size: 12.5px;
				color: var(--text-secondary, #475569);
				display: flex;
				flex-direction: column;
				gap: 6px;
			}
			#${STATUS_ID}.raw-rec-status--recording {
				background: var(--red-soft, #fef2f2);
				border-color: var(--red-border, #fecaca);
			}
			#${STATUS_ID}.raw-rec-status--error {
				border-color: var(--red-border, #fecaca);
			}
			.raw-rec-row {
				display: flex;
				flex-wrap: wrap;
				align-items: center;
				justify-content: space-between;
				gap: 8px 12px;
			}
			.raw-rec-main {
				display: flex;
				flex-wrap: wrap;
				align-items: center;
				gap: 8px;
				min-width: 0;
			}
			.raw-rec-badge {
				display: inline-flex;
				align-items: center;
				gap: 6px;
				padding: 2px 8px;
				border-radius: 999px;
				font-size: 11px;
				font-weight: 700;
				letter-spacing: 0.02em;
				text-transform: uppercase;
				background: var(--surface, #ffffff);
				border: 1px solid var(--border-strong, #cbd5e1);
				color: var(--text-secondary, #475569);
			}
			.raw-rec-badge--live {
				background: var(--red, #dc2626);
				border-color: var(--red, #dc2626);
				color: #ffffff;
			}
			.raw-rec-badge--live .raw-rec-dot {
				width: 6px;
				height: 6px;
				background: #ffffff;
				animation: raw-rec-pulse 1.1s ease-in-out infinite;
			}
			.raw-rec-meta {
				font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
				font-size: 11.5px;
				color: var(--text, #0f172a);
				word-break: break-word;
			}
			.raw-rec-dropped {
				color: var(--amber, #d97706);
				font-weight: 600;
			}
			.raw-rec-download {
				display: inline-flex;
				align-items: center;
				padding: 4px 10px;
				border-radius: var(--radius-sm, 8px);
				background: var(--surface, #ffffff);
				border: 1px solid var(--border-strong, #cbd5e1);
				color: var(--primary, #2563eb);
				font-size: 12px;
				font-weight: 600;
				text-decoration: none;
				white-space: nowrap;
				transition: background 0.15s ease, border-color 0.15s ease;
			}
			.raw-rec-download:hover {
				background: var(--primary-soft, rgba(37, 99, 235, 0.08));
				border-color: var(--primary, #2563eb);
			}
			.raw-rec-error {
				font-size: 12px;
				font-weight: 500;
				color: var(--red, #dc2626);
				word-break: break-word;
			}
		`;
		document.head.appendChild(style);
	}

	function formatDuration(seconds) {
		const total = Math.max(0, Math.floor(Number(seconds) || 0));
		const hrs = Math.floor(total / 3600);
		const mins = Math.floor((total % 3600) / 60);
		const secs = total % 60;
		const mm = String(mins).padStart(2, "0");
		const ss = String(secs).padStart(2, "0");
		if (hrs > 0) {
			return `${String(hrs).padStart(2, "0")}:${mm}:${ss}`;
		}
		return `${mm}:${ss}`;
	}

	function formatResolution(resolution) {
		if (!resolution) return "";
		if (typeof resolution === "string") return resolution.trim();
		if (Array.isArray(resolution) && resolution.length >= 2) {
			return `${resolution[0]}x${resolution[1]}`;
		}
		if (typeof resolution === "object" && resolution.width && resolution.height) {
			return `${resolution.width}x${resolution.height}`;
		}
		return "";
	}

	function formatFps(fps) {
		const num = Number(fps);
		if (!Number.isFinite(num) || num <= 0) return "";
		return Number.isInteger(num) ? `${num} fps` : `${num.toFixed(1)} fps`;
	}

	async function parseErrorMessage(response) {
		try {
			const data = await response.json();
			if (data && typeof data.error === "string" && data.error) return data.error;
			if (data && typeof data.detail === "string" && data.detail) return data.detail;
		} catch (_) {
			// Ignore JSON parse errors on non-JSON error responses
		}
		return `Request failed (${response.status})`;
	}

	function init() {
		const calibButtons = document.querySelector("#vision-section .calib-buttons");
		if (!calibButtons) return;
		if (document.getElementById(BTN_ID)) return;

		injectStyles();

		const recordBtn = document.createElement("button");
		recordBtn.id = BTN_ID;
		recordBtn.type = "button";

		const statusBar = document.createElement("div");
		statusBar.id = STATUS_ID;
		statusBar.setAttribute("role", "status");
		statusBar.setAttribute("aria-live", "polite");

		calibButtons.appendChild(recordBtn);
		calibButtons.insertAdjacentElement("afterend", statusBar);

		let currentState = {
			recording: false,
			startedAt: null,
			elapsedSec: 0,
			frameCount: 0,
			droppedFrames: 0,
			fps: null,
			resolution: null,
			filename: null,
			path: null,
			lastFilename: null,
			lastPath: null,
			lastFrameCount: null,
			error: null
		};
		let fetchError = null;
		let inFlight = false;
		let pollTimer = null;
		let pollInProgress = false;

		function isAppVisible() {
			const shell = document.getElementById("appShell");
			if (!shell) return true;
			return !shell.classList.contains("hidden");
		}

		function render() {
			const isRec = Boolean(currentState.recording);

			recordBtn.disabled = inFlight;
			recordBtn.classList.toggle("raw-rec-btn--recording", isRec);
			recordBtn.setAttribute("aria-pressed", isRec ? "true" : "false");

			recordBtn.textContent = "";
			const btnDot = document.createElement("span");
			btnDot.className = "raw-rec-dot";
			btnDot.setAttribute("aria-hidden", "true");
			recordBtn.appendChild(btnDot);

			const btnLabel = document.createElement("span");
			btnLabel.textContent = isRec
				? `Stop Raw Recording (${formatDuration(currentState.elapsedSec)})`
				: "Record Raw Video";
			recordBtn.appendChild(btnLabel);

			const activeError = fetchError || currentState.error;
			statusBar.className = "";
			if (isRec) statusBar.classList.add("raw-rec-status--recording");
			if (activeError) statusBar.classList.add("raw-rec-status--error");

			statusBar.textContent = "";

			const topRow = document.createElement("div");
			topRow.className = "raw-rec-row";

			const main = document.createElement("div");
			main.className = "raw-rec-main";

			const badge = document.createElement("span");
			badge.className = isRec ? "raw-rec-badge raw-rec-badge--live" : "raw-rec-badge";
			if (isRec) {
				const dot = document.createElement("span");
				dot.className = "raw-rec-dot";
				dot.setAttribute("aria-hidden", "true");
				badge.appendChild(dot);
				badge.appendChild(document.createTextNode("Recording"));
			} else {
				badge.textContent = "Idle";
			}
			main.appendChild(badge);

			const meta = document.createElement("span");
			meta.className = "raw-rec-meta";

			if (isRec) {
				const parts = [];
				const frames = Number(currentState.frameCount);
				parts.push(`${Number.isFinite(frames) ? frames : 0} frames`);
				const resText = formatResolution(currentState.resolution);
				if (resText) parts.push(resText);
				const fpsText = formatFps(currentState.fps);
				if (fpsText) parts.push(fpsText);
				if (currentState.filename) parts.push(currentState.filename);
				meta.textContent = parts.join(" • ");
				main.appendChild(meta);

				const dropped = Number(currentState.droppedFrames);
				if (Number.isFinite(dropped) && dropped > 0) {
					const dropSpan = document.createElement("span");
					dropSpan.className = "raw-rec-dropped";
					dropSpan.textContent = `(${dropped} dropped)`;
					main.appendChild(dropSpan);
				}
			} else if (currentState.lastFilename) {
				const parts = [`Last: ${currentState.lastFilename}`];
				const lastFrames = Number(currentState.lastFrameCount);
				if (Number.isFinite(lastFrames) && lastFrames > 0) {
					parts.push(`${lastFrames} frames`);
				}
				meta.textContent = parts.join(" • ");
				main.appendChild(meta);
			} else {
				meta.textContent = "Raw camera capture ready";
				main.appendChild(meta);
			}

			topRow.appendChild(main);

			if (!isRec && currentState.lastFilename) {
				const link = document.createElement("a");
				link.className = "raw-rec-download";
				link.href = `${API_DOWNLOAD_BASE}${encodeURIComponent(currentState.lastFilename)}`;
				link.setAttribute("download", currentState.lastFilename);
				link.textContent = "Download";
				topRow.appendChild(link);
			}

			statusBar.appendChild(topRow);

			if (activeError) {
				const errEl = document.createElement("div");
				errEl.className = "raw-rec-error";
				errEl.textContent = `Recording error: ${activeError}`;
				statusBar.appendChild(errEl);
			}
		}

		function clearPollTimer() {
			if (pollTimer !== null) {
				clearTimeout(pollTimer);
				pollTimer = null;
			}
		}

		function schedulePoll() {
			clearPollTimer();
			if (!isAppVisible()) return;
			const delay = currentState.recording ? POLL_RECORDING_MS : POLL_IDLE_MS;
			pollTimer = setTimeout(pollStatus, delay);
		}

		async function fetchStatus() {
			const response = await fetch(API_STATUS, { cache: "no-store" });
			if (!response.ok) {
				throw new Error(await parseErrorMessage(response));
			}
			const data = await response.json();
			if (data && typeof data === "object") {
				currentState = Object.assign({}, currentState, data);
			}
			fetchError = null;
		}

		async function pollStatus() {
			if (!isAppVisible() || pollInProgress) {
				schedulePoll();
				return;
			}
			pollInProgress = true;
			try {
				await fetchStatus();
			} catch (err) {
				fetchError = err && err.message ? err.message : "Unable to reach recording service";
			} finally {
				pollInProgress = false;
				if (isAppVisible()) {
					render();
					schedulePoll();
				}
			}
		}

		async function toggleRecording() {
			if (inFlight) return;
			inFlight = true;
			fetchError = null;
			render();

			const endpoint = currentState.recording ? API_STOP : API_START;
			try {
				const response = await fetch(endpoint, { method: "POST" });
				if (!response.ok) {
					throw new Error(await parseErrorMessage(response));
				}
				const data = await response.json();
				if (data && typeof data === "object" && "recording" in data) {
					currentState = Object.assign({}, currentState, data);
				} else {
					await fetchStatus();
				}
			} catch (err) {
				fetchError = err && err.message ? err.message : "Recording request failed";
			} finally {
				inFlight = false;
				render();
				schedulePoll();
			}
		}

		recordBtn.addEventListener("click", toggleRecording);

		const appShell = document.getElementById("appShell");
		if (appShell && typeof MutationObserver === "function") {
			let wasVisible = isAppVisible();
			const observer = new MutationObserver(() => {
				const nowVisible = isAppVisible();
				if (nowVisible === wasVisible) return;
				wasVisible = nowVisible;
				if (nowVisible) {
					pollStatus();
				} else {
					clearPollTimer();
				}
			});
			observer.observe(appShell, { attributes: true, attributeFilter: ["class"] });
		}

		render();
		if (isAppVisible()) {
			pollStatus();
		}
	}

	if (document.readyState === "loading") {
		document.addEventListener("DOMContentLoaded", init, { once: true });
	} else {
		init();
	}
})();
