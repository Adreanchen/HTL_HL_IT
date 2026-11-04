export const capitalizeFirstLetter = (string) => {
	if (typeof string !== "string") {
		throw new TypeError(`Expected a string, but received: ${typeof string}.`);
	}

	return string.charAt(0).toUpperCase() + string.slice(1);
};
