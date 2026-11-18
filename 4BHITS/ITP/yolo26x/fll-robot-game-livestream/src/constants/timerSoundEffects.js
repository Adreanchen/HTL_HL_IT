import { SoundEffect } from "./soundEffect";
import { TimerPhase } from "./timerPhase";

export const TIMER_SOUND_EFFECTS = Object.freeze({
	[TimerPhase.PRE]: [
		Object.freeze({
			condition: (totalSeconds) => totalSeconds <= 3 && totalSeconds > 0,
			sound: SoundEffect.PRE_COUNT,
		}),
	],
	[TimerPhase.MAIN]: [
		Object.freeze({
			condition: (totalSeconds, duration) => totalSeconds === duration,
			sound: SoundEffect.MATCH_START,
		}),
		Object.freeze({
			condition: (totalSeconds) => totalSeconds <= 5 && totalSeconds > 0,
			sound: SoundEffect.MAIN_COUNT,
		}),
		Object.freeze({ condition: (totalSeconds) => totalSeconds === 0, sound: SoundEffect.MATCH_END }),
	],
});
