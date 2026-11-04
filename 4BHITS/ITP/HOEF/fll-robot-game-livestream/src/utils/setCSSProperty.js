export const setCSSProperty = (property, value) => {
	if (typeof property !== "string") {
		throw new TypeError(`Expected parameter 'property' to be a string, but received: ${typeof property}.`);
	}

	if (typeof value !== "string") {
		throw new TypeError(`Expected parameter 'value' to be a string, but received: ${typeof value}.`);
	}

	document.documentElement.style.setProperty(property, value);
};
