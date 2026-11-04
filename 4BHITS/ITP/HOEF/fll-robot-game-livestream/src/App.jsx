import { BACKEND_HTTP_URL, Page, TeamColor } from "constants";
import { useMatchState } from "hooks";
import MatchStreamPage from "pages/match-stream-page";
import TeamSelectPage from "pages/team-select-page";
import { useCallback, useEffect, useMemo, useState } from "react";
import "./App.css";

const App = () => {
	useEffect(() => {
		if (typeof window !== "undefined" && window.location.pathname.replace(/\/+$/, "") === "/control") {
			window.location.replace(BACKEND_HTTP_URL);
		}
	}, []);

	const {
		teamNames,
		teamNameList,
		timerState,
		updateTeamsRemote,
		updateTeamListRemote,
		startTimerRemote,
		resetTimerRemote,
	} = useMatchState();

	const emptyDraftTeamNames = useMemo(() => ({ [TeamColor.RED]: "", [TeamColor.BLUE]: "" }), []);
	const [page, setPage] = useState(Page.MATCH_STREAM);
	const [draftTeamNames, setDraftTeamNames] = useState(emptyDraftTeamNames);

	const resetDraftTeamNames = useCallback(
		() => setDraftTeamNames(emptyDraftTeamNames),
		[emptyDraftTeamNames]
	);

	const updateDraftTeamName = useCallback((teamColor, newTeamName) => {
		setDraftTeamNames((prev) => ({ ...prev, [teamColor]: newTeamName }));
	}, []);

	const handleConfirmTeamSelect = useCallback(() => {
		updateTeamsRemote(draftTeamNames[TeamColor.RED], draftTeamNames[TeamColor.BLUE]);
		setPage(Page.MATCH_STREAM);
	}, [draftTeamNames, updateTeamsRemote]);

	return (
		<div className="app__container">
			{page === Page.TEAM_SELECT && (
				<TeamSelectPage
					teamNames={draftTeamNames}
					resetTeamNames={resetDraftTeamNames}
					updateTeamName={updateDraftTeamName}
					teamNameList={teamNameList}
					setTeamNameList={updateTeamListRemote}
					goToMatchStream={handleConfirmTeamSelect}
				/>
			)}
			{page === Page.MATCH_STREAM && (
				<MatchStreamPage
					teamNames={teamNames}
					timerState={timerState}
					onRequestStart={startTimerRemote}
					onRequestReset={resetTimerRemote}
					goToTeamSelect={() => setPage(Page.TEAM_SELECT)}
				/>
			)}
		</div>
	);
};

export default App;
