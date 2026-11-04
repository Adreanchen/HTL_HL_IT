import { TeamColor } from "constants";
import { useKeyHold } from "hooks";
import Topbar from "./components/topbar";
import VideoStream from "./components/video-stream";
import "./MatchStreamPage.css";

const MatchStreamPage = ({ teamNames, timerState, onRequestStart, onRequestReset, goToTeamSelect }) => {
	useKeyHold("E", goToTeamSelect);

	return (
		<div className="match-stream-page__container">
			<Topbar
				teamNames={teamNames}
				timerState={timerState}
				onRequestStart={onRequestStart}
				onRequestReset={onRequestReset}
			/>
			<VideoStream teamColor={TeamColor.RED} />
			<VideoStream teamColor={TeamColor.BLUE} />
		</div>
	);
};

export default MatchStreamPage;
