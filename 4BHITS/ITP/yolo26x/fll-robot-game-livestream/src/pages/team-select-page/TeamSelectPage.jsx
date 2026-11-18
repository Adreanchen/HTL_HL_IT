import { BACKEND_HTTP_URL, TeamColor } from "constants";
import { useEffect, useRef } from "react";
import Select from "react-select";
import { capitalizeFirstLetter } from "utils";
import "./TeamSelectPage.css";

const selectStyles = {
	control: (base, state) => ({
		...base,
		minHeight: "44px",
		borderRadius: "10px",
		borderColor: state.isFocused ? "#2563eb" : "#cbd5e1",
		boxShadow: state.isFocused ? "0 0 0 3px rgba(37, 99, 235, 0.18)" : "none",
		"&:hover": {
			borderColor: "#94a3b8",
		},
	}),
	option: (base, state) => ({
		...base,
		backgroundColor: state.isSelected
			? "#2563eb"
			: state.isFocused
			? "rgba(37, 99, 235, 0.08)"
			: "#ffffff",
		color: state.isSelected ? "#ffffff" : state.isDisabled ? "#94a3b8" : "#0f172a",
	}),
};

const TeamSelectPage = ({
	teamNames,
	resetTeamNames,
	updateTeamName,
	teamNameList,
	setTeamNameList,
	goToMatchStream,
}) => {
	const { [TeamColor.RED]: redTeamName, [TeamColor.BLUE]: blueTeamName } = teamNames;
	const isTeamNameUploadRequired = teamNameList.length < 2;

	const fileInputRef = useRef(null);

	useEffect(resetTeamNames, [resetTeamNames]);

	const createTeamNameSelectOptions = (disabledTeamName) =>
		teamNameList?.map((teamName) => ({
			value: teamName,
			label: teamName,
			isDisabled: teamName === disabledTeamName,
		}));

	const onTeamNameSelectChange = (teamColor) => (selectedOption) =>
		updateTeamName(teamColor, selectedOption ? selectedOption.value : "");

	const renderTeamNameSelect = (teamColor, disabledTeamName) => (
		<div className="team-select-field">
			<label className={`team-select-label team-select-label--${teamColor}`}>
				{capitalizeFirstLetter(teamColor)} Table Team
			</label>
			<Select
				className="team-name-select"
				styles={selectStyles}
				placeholder={`Select ${capitalizeFirstLetter(teamColor)} Team...`}
				options={createTeamNameSelectOptions(disabledTeamName)}
				onChange={onTeamNameSelectChange(teamColor)}
				isSearchable
				isClearable
			/>
		</div>
	);

	const triggerFileInputClick = () => fileInputRef.current?.click();

	const updateTeamNameList = (text) => {
		const newTeamNameList = text
			.split("\n")
			.map((teamName) => teamName.trim())
			.filter((teamName) => teamName.length > 0);

		setTeamNameList(newTeamNameList);
	};

	const onFileInputChange = async (e) => {
		const file = e.target.files[0];

		if (!file) {
			return;
		}

		const text = await file.text();

		updateTeamNameList(text);
	};

	return (
		<div className="team-select-page__wrapper">
			<header className="team-select-page__navbar">
				<div className="team-select-page__brand">
					<span className="team-select-page__badge">FLL</span>
					<span>Robot Game Livestream</span>
				</div>
				<a href={BACKEND_HTTP_URL} className="team-select-page__navlink">
					Open Remote Control Panel &rarr;
				</a>
			</header>

			<main className="team-select-page__hero">
				<div className="team-select-page__container">
					<span className="team-select-page__pill">Match Setup</span>
					<h1>{isTeamNameUploadRequired ? "Upload Team Roster" : "Select Competing Teams"}</h1>
					<p>
						{isTeamNameUploadRequired
							? "Upload a plain text file (.txt) containing at least two team names (one per line) to initialize the tournament roster."
							: "Choose the Red Table and Blue Table teams below to launch the live dual-table broadcast view."}
					</p>

					{!isTeamNameUploadRequired && (
						<div className="team-select-page__grid">
							{renderTeamNameSelect(TeamColor.RED, blueTeamName)}
							{renderTeamNameSelect(TeamColor.BLUE, redTeamName)}
						</div>
					)}

					<div className="team-select-page__actions">
						{isTeamNameUploadRequired ? (
							<button type="button" className="team-select-page__cta" onClick={triggerFileInputClick}>
								Upload Team Roster (.txt)
							</button>
						) : (
							<>
								<button
									type="button"
									className="team-select-page__secondary"
									onClick={triggerFileInputClick}
								>
									Replace .txt Roster
								</button>
								<button
									type="button"
									className="team-select-page__cta"
									onClick={goToMatchStream}
									disabled={!redTeamName || !blueTeamName}
								>
									Launch Match Stream
								</button>
							</>
						)}
					</div>
					<input ref={fileInputRef} type="file" accept=".txt" className="hidden" onChange={onFileInputChange} />
				</div>
			</main>
		</div>
	);
};

export default TeamSelectPage;
