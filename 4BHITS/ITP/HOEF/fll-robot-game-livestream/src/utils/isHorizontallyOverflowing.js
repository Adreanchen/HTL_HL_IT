export const isHorizontallyOverflowing = (element) => {
	if (!(element instanceof HTMLElement)) {
		throw new TypeError(
			`Expected parameter 'element' to be an instance of HTMLElement, but received: ${typeof element}.`
		);
	}

	return element.scrollWidth > element.clientWidth;
};
