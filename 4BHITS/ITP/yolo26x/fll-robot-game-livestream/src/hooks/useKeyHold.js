import { useEffect, useRef } from "react";

const useKeyHold = (key, callback, ms = 2000, enabled = true) => {
	const callbackRef = useRef(callback);
	const timeoutRef = useRef(null);

	const isKey = (event, key) => event.key.toLowerCase() === key.toLowerCase();

	const isTextInputFocused = () =>
		["INPUT", "TEXTAREA"].includes(document.activeElement.tagName) || document.activeElement.isContentEditable;

	const clearTimeoutRef = (ref) => {
		if (ref.current) {
			clearTimeout(ref.current);
			ref.current = null;
		}
	};

	useEffect(() => {
		callbackRef.current = callback;
	}, [callback]);

	useEffect(() => {
		if (!enabled) {
			return;
		}

		const onKeyDown = (e) => {
			if (!isKey(e, key) || e.repeat || isTextInputFocused()) {
				return;
			}

			timeoutRef.current = setTimeout(() => callbackRef.current?.(), ms);
		};

		const onKeyUp = (e) => {
			if (!isKey(e, key)) {
				return;
			}

			clearTimeoutRef(timeoutRef);
		};

		const controller = new AbortController();
		const signal = controller.signal;

		document.addEventListener("keydown", onKeyDown, { signal });
		document.addEventListener("keyup", onKeyUp, { signal });

		return () => {
			controller.abort();
			clearTimeoutRef(timeoutRef);
		};
	}, [key, ms, enabled]);
};

export { useKeyHold };
