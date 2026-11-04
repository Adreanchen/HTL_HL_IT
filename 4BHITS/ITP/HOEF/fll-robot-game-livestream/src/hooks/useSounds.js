import { useCallback, useEffect, useMemo } from "react";

const useSounds = (soundMap) => {
	const audios = useMemo(
		() =>
			Object.fromEntries(
				Object.entries(soundMap).map(([key, src]) => {
					const audio = new Audio(src);
					audio.preload = "auto";
					return [key, audio];
				})
			),
		[soundMap]
	);

	useEffect(() => {
		let unlocked = false;
		const unlockAudio = () => {
			if (unlocked) {
				return;
			}
			unlocked = true;
			Object.values(audios).forEach((audio) => {
				audio.load();
			});
			window.removeEventListener("pointerdown", unlockAudio);
			window.removeEventListener("keydown", unlockAudio);
		};

		window.addEventListener("pointerdown", unlockAudio, { once: true });
		window.addEventListener("keydown", unlockAudio, { once: true });

		return () => {
			window.removeEventListener("pointerdown", unlockAudio);
			window.removeEventListener("keydown", unlockAudio);
			Object.values(audios).forEach((audio) => {
				audio.pause();
				audio.currentTime = 0;
			});
		};
	}, [audios]);

	const play = useCallback(
		(key) => {
			const audio = audios[key];

			if (!audio) {
				return;
			}

			audio.currentTime = 0;
			audio.play().catch((reason) => console.warn("Audio playback blocked or failed:", reason));
		},
		[audios]
	);

	const stop = useCallback(
		(key) => {
			const audio = audios[key];

			if (!audio) {
				return;
			}

			audio.pause();
			audio.currentTime = 0;
		},
		[audios]
	);

	const stopAll = useCallback(() => {
		Object.values(audios).forEach((audio) => {
			audio.pause();
			audio.currentTime = 0;
		});
	}, [audios]);

	return { play, stop, stopAll };
};

export { useSounds };
