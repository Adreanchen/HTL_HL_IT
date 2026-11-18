import { BACKEND_HTTP_URL, BACKEND_WS_URL, TeamColor } from "constants";
import { useCallback, useEffect, useState } from "react";

const useMatchState = () => {
	const [teamNames, setTeamNames] = useState({
		[TeamColor.RED]: "Red Team",
		[TeamColor.BLUE]: "Blue Team",
	});
	const [teamNameList, setTeamNameList] = useState([]);
	const [timerState, setTimerState] = useState(null);

	const applySnapshot = useCallback((snapshot) => {
		if (!snapshot || typeof snapshot !== "object") {
			return;
		}

		if (snapshot.teams) {
			const nextRed = snapshot.teams.red || "Red Team";
			const nextBlue = snapshot.teams.blue || "Blue Team";
			setTeamNames((prev) => {
				if (prev[TeamColor.RED] === nextRed && prev[TeamColor.BLUE] === nextBlue) {
					return prev;
				}
				return {
					[TeamColor.RED]: nextRed,
					[TeamColor.BLUE]: nextBlue,
				};
			});
		}

		if (Array.isArray(snapshot.teamList)) {
			const nextList = snapshot.teamList;
			setTeamNameList((prev) => {
				if (prev.length === nextList.length && prev.every((item, idx) => item === nextList[idx])) {
					return prev;
				}
				return nextList;
			});
		}

		if (snapshot.timer) {
			const nextTimer = snapshot.timer;
			setTimerState((prev) => {
				if (
					prev &&
					prev.actionId === nextTimer.actionId &&
					prev.status === nextTimer.status &&
					Boolean(prev.preCountEnabled) === Boolean(nextTimer.preCountEnabled) &&
					prev.duration === nextTimer.duration &&
					prev.preCountDuration === nextTimer.preCountDuration
				) {
					return prev;
				}
				return nextTimer;
			});
		}
	}, []);

	useEffect(() => {
		let isUnmounted = false;
		let ws = null;
		let reconnectTimeout = null;

		const fetchState = async () => {
			try {
				const response = await fetch(`${BACKEND_HTTP_URL}/api/state`, { cache: "no-store" });
				if (!response.ok || isUnmounted) {
					return;
				}
				const data = await response.json();
				if (!isUnmounted) {
					applySnapshot(data);
				}
			} catch (_) {
				// Backend may still be booting; next poll or WebSocket reconnect will sync automatically
			}
		};

		const connectWebSocket = () => {
			if (isUnmounted) {
				return;
			}
			try {
				ws = new WebSocket(BACKEND_WS_URL);
				ws.onmessage = (event) => {
					if (isUnmounted) {
						return;
					}
					try {
						const data = JSON.parse(event.data);
						applySnapshot(data);
					} catch (_) {}
				};
				ws.onclose = () => {
					if (!isUnmounted) {
						reconnectTimeout = setTimeout(connectWebSocket, 1500);
					}
				};
				ws.onerror = () => {
					try {
						ws.close();
					} catch (_) {}
				};
			} catch (_) {
				if (!isUnmounted) {
					reconnectTimeout = setTimeout(connectWebSocket, 1500);
				}
			}
		};

		fetchState();
		connectWebSocket();

		// Continuous 1-second check as fallback alongside instant WebSocket updates
		const pollInterval = setInterval(fetchState, 1000);

		return () => {
			isUnmounted = true;
			clearInterval(pollInterval);
			if (reconnectTimeout) {
				clearTimeout(reconnectTimeout);
			}
			if (ws) {
				try {
					ws.close();
				} catch (_) {}
			}
		};
	}, [applySnapshot]);

	const postJson = useCallback(
		async (path, bodyObj) => {
			try {
				const response = await fetch(`${BACKEND_HTTP_URL}${path}`, {
					method: "POST",
					headers: { "Content-Type": "application/json" },
					body: JSON.stringify(bodyObj || {}),
				});
				if (response.ok) {
					const data = await response.json();
					applySnapshot(data);
				}
			} catch (err) {
				console.warn(`Failed to POST ${path}:`, err);
			}
		},
		[applySnapshot]
	);

	const updateTeamsRemote = useCallback(
		(redName, blueName) => {
			const cleanRed = (redName || "").trim() || "Red Team";
			const cleanBlue = (blueName || "").trim() || "Blue Team";
			setTeamNames({
				[TeamColor.RED]: cleanRed,
				[TeamColor.BLUE]: cleanBlue,
			});
			postJson("/api/teams", { red: cleanRed, blue: cleanBlue });
		},
		[postJson]
	);

	const updateTeamListRemote = useCallback(
		(newList) => {
			if (!Array.isArray(newList) || newList.length === 0) {
				return;
			}
			setTeamNameList(newList);
			postJson("/api/team-list", { teams: newList });
		},
		[postJson]
	);

	const startTimerRemote = useCallback(() => {
		postJson("/api/timer/start", {});
	}, [postJson]);

	const resetTimerRemote = useCallback(() => {
		postJson("/api/timer/reset", {});
	}, [postJson]);

	return {
		teamNames,
		setTeamNames,
		teamNameList,
		timerState,
		updateTeamsRemote,
		updateTeamListRemote,
		startTimerRemote,
		resetTimerRemote,
	};
};

export { useMatchState };
