import { VIDEO_STREAM_SOURCES } from "constants";
import { useEffect, useRef, useState } from "react";
import { BounceLoader } from "react-spinners";
import { capitalizeFirstLetter } from "utils";
import "./VideoStream.css";

const VideoStream = ({ teamColor }) => {
	const [isVideoStreamLoaded, setIsVideoStreamLoaded] = useState(false);
	const [retryCount, setRetryCount] = useState(0);
	const imgRef = useRef(null);

	useEffect(() => {
		if (isVideoStreamLoaded) {
			return;
		}
		const interval = setInterval(() => {
			if (imgRef.current && imgRef.current.naturalWidth > 0) {
				setIsVideoStreamLoaded(true);
			}
		}, 100);
		return () => clearInterval(interval);
	}, [isVideoStreamLoaded]);

	const handleStreamError = () => {
		setIsVideoStreamLoaded(false);
		setTimeout(() => {
			setRetryCount((prev) => prev + 1);
		}, 2000);
	};

	const baseSrc = VIDEO_STREAM_SOURCES[teamColor];
	const streamSrc = retryCount > 0 ? `${baseSrc}?retry=${retryCount}` : baseSrc;

	return (
		<div className={`video-stream__wrapper video-stream__wrapper--${teamColor} children-center`}>
			<img
				ref={imgRef}
				src={streamSrc}
				alt={`${capitalizeFirstLetter(teamColor)} Team Video`}
				className={`video-stream video-stream--${teamColor}`}
				style={!isVideoStreamLoaded ? { position: "absolute", width: 1, height: 1, opacity: 0 } : undefined}
				onLoad={() => setIsVideoStreamLoaded(true)}
				onError={handleStreamError}
			/>
			{!isVideoStreamLoaded && <BounceLoader size={100} color={`var(--color-${teamColor})`} />}
		</div>
	);
};

export default VideoStream;
