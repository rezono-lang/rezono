import type { Diagnostic } from './parse.ts';
import type { Line } from './module-support.ts';

/** A logical line: its text range in the file, its indent, and the lines of its block. */
export interface Logical {
	indent: number;
	start: number;
	end: number;
	/** The last physical line's code, or its full text within a verbatim block. */
	last: string;
	/** Delimiters left open, outside text literals, backtick-quoted identifiers, and comments. */
	depth: number;
	block: Logical[];
	read?: Line;
}

/** A line's code without its comment: `--` outside a text literal or backtick-quoted identifier ends it (§3). */
export function codeOf(line: string): string {
	let inText = false;
	let inTick = false;
	for (let i = 0; i < line.length; i++) {
		const c = line[i];
		if (inText) {
			if (c === '\\') i++;
			else if (c === '"') inText = false;
		} else if (inTick) {
			if (c === '`') inTick = false;
		} else if (c === '"') inText = true;
		else if (c === '`') inTick = true;
		else if (c === '-' && line[i + 1] === '-') return line.slice(0, i).trimEnd();
	}
	return line.trimEnd();
}
export function depthOf(code: string): number {
	let depth = 0;
	let inText = false;
	let inTick = false;
	for (let i = 0; i < code.length; i++) {
		const c = code[i];
		if (inText) {
			if (c === '\\') i++;
			else if (c === '"') inText = false;
		} else if (inTick) {
			if (c === '`') inTick = false;
		} else if (c === '"') inText = true;
		else if (c === '`') inTick = true;
		else if (c === '-' && code[i + 1] === '-') break;
		else if (c === '(' || c === '[' || c === '{') depth++;
		else if (c === ')' || c === ']' || c === '}') depth--;
	}
	return depth;
}
const OPEN_END = /(?:=>|=|(?:^|\s)[+\-*/]|[(,]|\b(?:when|then|else|and|or|not))$/;
const GOES_ON = /^(?:(?:then|else|and|or)\b|=>|[+*/).]|-(?!-))/;
const EFFECT_HEADER = /^effect\s+(?:[a-z][a-z0-9_]*|`[a-z][a-z0-9_]*`)$/;

/** Splits a file into logical lines and their blocks (§11); a tab in an indent is an R000. */
export function layout(
	text: string, errors: Diagnostic[], cp: (at: number) => number, isVerbatimHeader: (code: string) => boolean
): Logical[] {
	const top: Logical[] = [];
	const open: Logical[] = [];
	let at = 0;
	let current: Logical | undefined;
	let verbatimIndent: number | undefined;
	for (const raw of text.split('\n')) {
		const start = at;
		at += raw.length + 1;
		const line = raw.endsWith('\r') ? raw.slice(0, -1) : raw;
		const indent = /^ */.exec(line)![0].length;
		const verbatim = verbatimIndent !== undefined && indent > verbatimIndent;
		const code = verbatim ? line : codeOf(line);
		if (!code.trim()) continue;
		if (!verbatim) verbatimIndent = undefined;
		if (code[indent] === '\t') {
			errors.push({ code: 'R000', span: { text: '\t', start: cp(start + indent), end: cp(start + indent + 1) }, args: ['spaces'] });
			continue;
		}
		const body = code.slice(indent);
		const inEffectHeader = open.length >= 2 && EFFECT_HEADER.test(current?.last ?? '');
		if (!verbatim && current && indent > current.indent && !inEffectHeader && (current.depth > 0 || OPEN_END.test(current.last) || GOES_ON.test(body))) {
			current.end = start + code.length;
			current.last = body;
			current.depth += depthOf(body);
			continue;
		}
		current = { indent, start: start + indent, end: start + code.length, last: body, depth: verbatim ? 0 : depthOf(body), block: [] };
		while (open.length && open[open.length - 1].indent >= indent) open.pop();
		(open.length ? open[open.length - 1].block : top).push(current);
		open.push(current);
		if (!verbatim && isVerbatimHeader(body)) verbatimIndent = indent;
	}
	return top;
}
/** The text slice of one logical line and its UTF-16 base offset in the file. */
export function sliceOf(text: string, line: Logical): { text: string; offset: number } {
	return { text: text.slice(line.start, line.end), offset: line.start };
}
