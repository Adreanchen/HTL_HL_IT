import useResizeObserver from "@react-hook/resize-observer";
import { MATCH_DURATION_SECONDS, TeamColor } from "constants";
import { useCallback, useEffect, useRef } from "react";
import { isHorizontallyOverflowing, setCSSProperty } from "utils";
import Timer from "../timer";
import "./Topbar.css";

const Topbar = ({ teamNames, timerState, onRequestStart, onRequestReset }) => {
	const { [TeamColor.RED]: redTeamName, [TeamColor.BLUE]: blueTeamName } = teamNames;

	const topbarRef = useRef(null);
	const redTeamNameRef = useRef(null);
	const blueTeamNameRef = useRef(null);

	const updateTopbarHeight = useCallback(() => {
		const topbar = topbarRef.current;

		if (!topbar) {
			return;
		}

		setCSSProperty("--team-name-background-cutout-width", `${topbar.clientHeight}px`);
	}, []);

	const updateTeamNameWidth = useCallback((teamNameRef, teamColor) => {
		const teamName = teamNameRef.current;

		if (!teamName || !teamName.parentElement) {
			return;
		}

		teamName.classList.remove("marquee");
		setCSSProperty("--team-name-background-width", `${teamName.parentElement.clientWidth}px`);

		if (isHorizontallyOverflowing(teamName)) {
			teamName.classList.add("marquee");
			setCSSProperty(`--${teamColor}-team-name-width`, `${teamName.scrollWidth}px`);
		} else {
			setCSSProperty(`--${teamColor}-team-name-width`, `${teamName.clientWidth}px`);
		}
	}, []);

	useResizeObserver(topbarRef, updateTopbarHeight);
	useResizeObserver(redTeamNameRef, () => updateTeamNameWidth(redTeamNameRef, TeamColor.RED));
	useResizeObserver(blueTeamNameRef, () => updateTeamNameWidth(blueTeamNameRef, TeamColor.BLUE));

	useEffect(() => {
		updateTeamNameWidth(redTeamNameRef, TeamColor.RED);
		updateTeamNameWidth(blueTeamNameRef, TeamColor.BLUE);
	}, [redTeamName, blueTeamName, updateTeamNameWidth]);

	const renderTeamName = (teamNameRef, teamColor, teamName) => (
		<div className={`team-name__wrapper team-name__wrapper--${teamColor} children-center`}>
			<div ref={teamNameRef} className={`team-name team-name--${teamColor} cardot bold`}>
				{teamName}
			</div>
		</div>
	);

	const renderCountdownTimer = () => (
		<div className="countdown-timer__wrapper children-center">
			<div className="countdown-timer__container seven-segment-display">
				<div className="countdown-timer__background">8:88</div>
				<div className="countdown-timer">
					<Timer
						duration={MATCH_DURATION_SECONDS}
						timerState={timerState}
						onRequestStart={onRequestStart}
						onRequestReset={onRequestReset}
					/>
				</div>
			</div>
		</div>
	);

	return (
		<div ref={topbarRef} className="topbar">
			{renderTeamName(redTeamNameRef, TeamColor.RED, redTeamName)}
			{renderCountdownTimer()}
			{renderTeamName(blueTeamNameRef, TeamColor.BLUE, blueTeamName)}
		</div>
	);
};

export default Topbar;
