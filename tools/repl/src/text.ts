// Plain text of the REPL: its argument syntax, its tables and the value states (tools/repl/README.md).
// Deterministic: no locale, no terminal width, column widths from the content alone.
/** A failure the REPL prints as one line, `error: <message>`, leaving the session as it was. */
export class ReplError extends Error {}

/** The one text for every absent, hidden or unoffered name (role safety: absent and hidden look the same). */
export const NOT_FOUND = 'not found (or outside your view)';

/** A data value must occupy one line without issuing terminal control codes. */
export function terminalLine(line: string): string {
	return line.replace(/[\x00-\x1f\x7f-\x9f]/g, (character) => `\\u${character.charCodeAt(0).toString(16).padStart(4, '0')}`);
}

/**
 * The words of a line, separated by whitespace. A word that begins with `"` is a JSON string, so an
 * argument may hold spaces; it ends at its closing quote.
 */
export function words(line: string): string[] {
	const out: string[] = [];
	let i = 0;
	while (i < line.length) {
		if (/\s/.test(line[i])) {
			i++;
			continue;
		}
		if (line[i] === '"') {
			let j = i + 1;
			while (j < line.length && line[j] !== '"') j += line[j] === '\\' ? 2 : 1;
			if (j >= line.length) throw new ReplError('an argument in quotes is a JSON string; its closing quote is missing');
			try {
				out.push(JSON.parse(line.slice(i, j + 1)) as string);
			} catch {
				throw new ReplError('an argument in quotes is a JSON string');
			}
			i = j + 1;
			if (i < line.length && !/\s/.test(line[i])) throw new ReplError('an argument in quotes ends at whitespace');
			continue;
		}
		let j = i;
		while (j < line.length && !/\s/.test(line[j])) j++;
		out.push(line.slice(i, j));
		i = j;
	}
	return out;
}

/** Width in code points: the same for every terminal and locale. */
const width = (s: string) => [...s].length;

/** A table: a header line, then one line per row; columns two spaces apart, the last one never padded. */
export function table(header: string[], rows: string[][]): string[] {
	const all = [header, ...rows];
	const widths = header.map((_, c) => Math.max(...all.map((r) => width(r[c] ?? ''))));
	return all.map((r) => r.map((cell, c) => (c === r.length - 1 ? cell : cell + ' '.repeat(widths[c] - width(cell) + 2))).join(''));
}
