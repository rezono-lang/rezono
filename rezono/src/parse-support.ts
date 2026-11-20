import type { Node } from 'ohm-js';

/** A place in the source: the text and its 0-based code-point offsets, end exclusive (§11). */
export interface Span {
	text: string;
	start: number;
	end: number;
}
/** A diagnostic: its code, its place and the values its sentence needs (the sentences are in `messages/`). */
export interface Diagnostic {
	code: string;
	span: Span;
	args: string[];
	/** What to write instead: a sentence of `messages/` by its id, with its values. */
	hint?: { id: string; args: string[] };
	/** The names it may have meant, nearest first. */
	suggest?: string[];
}
/** What one parse collects; the semantics below are built once and read it through this. */
interface Run {
	text: string;
	/** Code-point offset per UTF-16 offset, or undefined when the two are equal (no astral character). */
	points?: number[];
	spans: WeakMap<object, Span>;
	/** Nodes that are an id token, so that `host-b.owner` reads as one path. */
	ids: WeakSet<object>;
	errors: Diagnostic[];
	reserved: Diagnostic[];
	/** Time selections on a literal: the writer meant the question's context (§4, E30). */
	misplaced: [Diagnostic, 'at' | 'as_known'][];
	/** Language version when reading a module; undefined for standalone questions. */
	version?: '0' | '1';
}
export let run: Run;

/** Code-point offset per UTF-16 offset, or undefined when the two are equal (no astral character). */
export function points(text: string): number[] | undefined {
	if (!/[\uD800-\uDBFF]/.test(text)) return undefined;
	const at: number[] = [];
	let n = 0;
	for (let i = 0; i < text.length; i++) {
		at.push(n);
		const c = text.charCodeAt(i);
		if (!(c >= 0xd800 && c <= 0xdbff)) n++;
	}
	at.push(n);
	return at;
}

export function spanAt(from: number, to: number): Span {
	const p = run.points;
	return { text: run.text.slice(from, to), start: p ? p[from] : from, end: p ? p[to] : to };
}
/** The span of a parse node, without the white space and comments around it. */
export function spanOf(node: Node): Span {
	let { startIdx: from, endIdx: to } = node.source;
	const lead = /^(?:\s|--[^\n]*)*/.exec(run.text.slice(from, to))![0].length;
	from += lead;
	while (to > from && /\s/.test(run.text[to - 1])) to--;
	return spanAt(from, to);
}
/** Records the place of a tree node; a node keeps its first, innermost place. */
export function placed<T extends object>(node: Node, tree: T): T {
	if (!run.spans.has(tree)) run.spans.set(tree, spanOf(node));
	return tree;
}
export function reserved(node: Node, what: string): Diagnostic {
	const d: Diagnostic = { code: 'R015', span: spanOf(node), args: [what] };
	run.reserved.push(d);
	return d;
}

/** A parse-level error at a node: with one, the text has no tree. */
export function refused(node: Node, code: string, args: string[]): void {
	run.errors.push({ code, span: spanOf(node), args });
}

export function startRun(text: string, spans: WeakMap<object, Span>, at: number[] | undefined, version?: '0' | '1'): void {
	run = { text, points: at, spans, ids: new WeakSet(), errors: [], reserved: [], misplaced: [], version };
}
