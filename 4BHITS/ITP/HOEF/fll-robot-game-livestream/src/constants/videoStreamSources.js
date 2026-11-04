import { TeamColor } from "./teamColor";

export const getBackendHostname = () =>
	typeof window !== "undefined" && window.location.hostname ? window.location.hostname : "localhost";

export const BACKEND_PORT = 8002;
export const BACKEND_HTTP_URL = `http://${getBackendHostname()}:${BACKEND_PORT}`;
export const BACKEND_WS_URL = `${
	typeof window !== "undefined" && window.location.protocol === "https:" ? "wss" : "ws"
}://${getBackendHostname()}:${BACKEND_PORT}/ws`;

export const VIDEO_STREAM_SOURCES = Object.freeze({
	[TeamColor.RED]: `${BACKEND_HTTP_URL}/video-stream/red-team`,
	[TeamColor.BLUE]: `${BACKEND_HTTP_URL}/video-stream/blue-team`,
});
