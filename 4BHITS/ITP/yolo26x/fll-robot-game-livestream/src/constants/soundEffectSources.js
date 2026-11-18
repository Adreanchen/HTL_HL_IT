import beepSound from "assets/audio/sfx/beep.mp3";
import buzzSound from "assets/audio/sfx/buzz.mp3";
import highSound from "assets/audio/sfx/high.mp3";
import lowSound from "assets/audio/sfx/low.mp3";
import { SoundEffect } from "./soundEffect";

export const SOUND_EFFECT_SOURCES = Object.freeze({
	[SoundEffect.PRE_COUNT]: lowSound,
	[SoundEffect.MATCH_START]: highSound,
	[SoundEffect.MAIN_COUNT]: beepSound,
	[SoundEffect.MATCH_END]: buzzSound,
});
