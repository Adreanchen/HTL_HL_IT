import { SOUND_EFFECT_SOURCES, TIMER_SOUND_EFFECTS, TimerPhase } from "constants";
import { useKeyHold, useSounds } from "hooks";
import { useCallback, useEffect, useRef, useState } from "react";
import { useTimer } from "react-timer-hook";
import "./Timer.css";

const calculateExpiryTimestamp = (seconds) => new Date(Date.now() + seconds * 1000);

const Timer = ({
	duration,
	preCountEnabled = true,
	preCountDuration = 10,
	timerState = null,
	onRequestStart = null,
	onRequestReset = null,
}) => {
	const effectivePreCountEnabled = timerState ? Boolean(timerState.preCountEnabled) : preCountEnabled;
	const effectivePreCountDuration = timerState
		? Number(timerState.preCountDuration) || preCountDuration
		: preCountDuration;
	const effectiveDuration = timerState ? Number(timerState.duration) || duration : duration;

	const [initialTimerPhase, initialDuration] = effectivePreCountEnabled
		? [TimerPhase.PRE, effectivePreCountDuration]
		: [TimerPhase.MAIN, effectiveDuration];

	const [hasTimerStarted, setHasTimerStarted] = useState(false);
	const [timerPhase, setTimerPhase] = useState(initialTimerPhase);

	const lastSyncKeyRef = useRef(null);
	const activeActionIdRef = useRef(0);
	const suppressEndSoundRef = useRef(false);
	const lastPlayedSoundKeyRef = useRef("");

	const onTimerExpire = useCallback(() => {
		if (timerPhase !== TimerPhase.PRE) {
			return;
		}

		setTimerPhase(TimerPhase.TRANSITION);
	}, [timerPhase]);

	const {
		totalSeconds,
		seconds,
		minutes,
		start: startTimer,
		restart: restartTimer,
	} = useTimer({
		expiryTimestamp: calculateExpiryTimestamp(initialDuration),
		autoStart: false,
		onExpire: onTimerExpire,
	});

	const { play: playSound, stopAll: stopAllSounds } = useSounds(SOUND_EFFECT_SOURCES);

	const onTimerStart = useCallback(() => {
		if (onRequestStart) {
			onRequestStart();
			return;
		}
		suppressEndSoundRef.current = false;
		lastPlayedSoundKeyRef.current = "";
		startTimer();
		setHasTimerStarted(true);
	}, [onRequestStart, startTimer]);

	const onTimerReset = useCallback(() => {
		if (onRequestReset) {
			onRequestReset();
			return;
		}
		suppressEndSoundRef.current = false;
		lastPlayedSoundKeyRef.current = "";
		stopAllSounds();
		restartTimer(calculateExpiryTimestamp(initialDuration), false);
		setHasTimerStarted(false);
		setTimerPhase(initialTimerPhase);
	}, [onRequestReset, stopAllSounds, restartTimer, initialDuration, initialTimerPhase]);

	useKeyHold("S", onTimerStart);
	useKeyHold("R", onTimerReset);

	// Sync countdown state with remote controller / backend
	useEffect(() => {
		if (!timerState) {
			return;
		}

		const usePre = Boolean(timerState.preCountEnabled);
		const preDur = Number(timerState.preCountDuration) || preCountDuration;
		const mainDur = Number(timerState.duration) || duration;
		const syncKey = `${timerState.actionId}:${timerState.status}:${usePre}:${preDur}:${mainDur}`;

		if (lastSyncKeyRef.current === syncKey) {
			return;
		}
		lastSyncKeyRef.current = syncKey;
		activeActionIdRef.current = timerState.actionId;
		lastPlayedSoundKeyRef.current = "";

		if (timerState.status !== "running") {
			suppressEndSoundRef.current = false;
			stopAllSounds();
			const nextInitPhase = usePre ? TimerPhase.PRE : TimerPhase.MAIN;
			const nextInitDur = usePre ? preDur : mainDur;
			setHasTimerStarted(false);
			setTimerPhase(nextInitPhase);
			restartTimer(calculateExpiryTimestamp(nextInitDur), false);
			return;
		}

		const elapsed = Math.max(0, Number(timerState.elapsed) || 0);

		if (usePre && elapsed < preDur) {
			suppressEndSoundRef.current = false;
			setTimerPhase(TimerPhase.PRE);
			setHasTimerStarted(true);
			restartTimer(calculateExpiryTimestamp(preDur - elapsed), true);
			return;
		}

		const mainElapsed = usePre ? elapsed - preDur : elapsed;
		if (mainElapsed < mainDur) {
			suppressEndSoundRef.current = false;
			setTimerPhase(TimerPhase.MAIN);
			setHasTimerStarted(true);
			restartTimer(calculateExpiryTimestamp(mainDur - mainElapsed), true);
			return;
		}

		// Already finished before this client connected / refreshed
		suppressEndSoundRef.current = true;
		setTimerPhase(TimerPhase.MAIN);
		setHasTimerStarted(true);
		restartTimer(new Date(Date.now()), false);
	}, [timerState, duration, preCountDuration, restartTimer, stopAllSounds]);

	useEffect(() => {
		if (timerPhase !== TimerPhase.TRANSITION) {
			return;
		}

		restartTimer(calculateExpiryTimestamp(effectiveDuration), true);
		setTimerPhase(TimerPhase.MAIN);
	}, [effectiveDuration, timerPhase, restartTimer]);

	useEffect(() => {
		if (!hasTimerStarted || suppressEndSoundRef.current) {
			return;
		}

		const soundKey = `${activeActionIdRef.current}:${timerPhase}:${totalSeconds}`;
		if (lastPlayedSoundKeyRef.current === soundKey) {
			return;
		}

		let didPlay = false;
		TIMER_SOUND_EFFECTS[timerPhase]?.forEach(({ condition, sound }) => {
			if (condition(totalSeconds, effectiveDuration)) {
				playSound(sound);
				didPlay = true;
			}
		});

		if (didPlay) {
			lastPlayedSoundKeyRef.current = soundKey;
		}
	}, [hasTimerStarted, effectiveDuration, timerPhase, totalSeconds, playSound]);

	const isTimerRed =
		hasTimerStarted &&
		(timerPhase === TimerPhase.PRE || (timerPhase === TimerPhase.MAIN && minutes === 0 && seconds <= 10));

	const renderDigit = (digit, forceVisible = false) => {
		const isInvisible = !forceVisible && timerPhase === TimerPhase.PRE && digit === 0;

		return <span className={`timer__digit ${isInvisible ? "timer__digit--invisible" : ""}`}>{digit}</span>;
	};

	const [displayMinutes, displaySeconds] = hasTimerStarted
		? [minutes, seconds]
		: [Math.floor(effectiveDuration / 60), effectiveDuration % 60];

	return (
		<div className={`timer ${isTimerRed ? "timer--red" : ""}`}>
			<span className="timer__minutes">{renderDigit(displayMinutes)}</span>
			<span className="timer__colon">:</span>
			<span className="timer__seconds">
				{renderDigit(Math.floor(displaySeconds / 10), displayMinutes > 0)}
				{renderDigit(displaySeconds % 10, true)}
			</span>
		</div>
	);
};

export default Timer;
