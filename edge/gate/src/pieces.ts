export type Key = (string | number)[];

export function compareText(a: string, b: string): number {
	for (let i = 0, j = 0; i < a.length && j < b.length; ) {
		const x = a.codePointAt(i)!;
		const y = b.codePointAt(j)!;
		if (x !== y) return x < y ? -1 : 1;
		i += x > 0xffff ? 2 : 1;
		j += y > 0xffff ? 2 : 1;
	}
	return a.length === b.length ? 0 : a.length < b.length ? -1 : 1;
}

/** Keys element by element: text by its UTF-8 bytes, a number by its value; a key before every longer key it begins. */
export function compareKey(a: Key, b: Key): number {
	for (let i = 0; i < a.length && i < b.length; i++) {
		const [x, y] = [a[i], b[i]];
		const c = typeof x === 'number' && typeof y === 'number' ? Math.sign(x - y) : typeof x === 'string' && typeof y === 'string' ? compareText(x, y) : typeof x === 'number' ? -1 : 1;
		if (c) return c;
	}
	return Math.sign(a.length - b.length);
}

export type KeyRange = { prefix: Key; after?: Key; limit: number; starts?: string };

export function pageByKey<T extends {key: string[]}>(ordered: T[], { prefix, after, limit, starts }: KeyRange) {
	const matching = ordered.filter(({ key }) =>
		prefix.every((part, i) => key[i] === part) && (starts === undefined || key[0].startsWith(starts))
		&& (!after || compareKey(key, after) > 0));
	const rows = matching.slice(0, limit);
	return { rows, ...(matching.length > rows.length && { next: rows.at(-1)!.key }) };
}
