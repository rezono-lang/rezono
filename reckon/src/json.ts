// The JSON form of a question (docs/reckon/expressions.md §4a). The tree is the JSON form, so reading it is a
// check and writing it is canonical JSON (RFC 8785, Rede's one canonical form: viewer/src/lib/canon.ts). The
// question hash is taken from the normal form of the checked tree (normal.ts, decision Q21), so the text of a
// question and its JSON form have one hash (E52).
import { canonicalJson } from '../../viewer/src/lib/canon.ts';
import { grammar } from './grammar.ts';
import { parse } from './parse.ts';
import { print } from './print.ts';
import type { Question } from './tree.ts';

/** A JSON value that is not the JSON form of a question. */
export class JsonFormError extends Error {}

/** The canonical JSON of a question: `to_json` of §4a. */
export const toJson = (q: Question): string => canonicalJson(q);

/**
 * A JSON value as the parser would have built it, where §4a allows two spellings of one tree: a chain of `and`
 * or `or` inside the same chain is flat, and an id that is spelled like a name (`cherry`) is a one-name path,
 * as the parser reads it; which of the two it is, is for name resolution.
 */
function normal(v: unknown): unknown {
	if (Array.isArray(v)) return v.map(normal);
	if (typeof v === 'string') return v;
	if (typeof v !== 'object' || v === null) throw new JsonFormError(`not the JSON form of a question: ${JSON.stringify(v)} is not a string, an array or an object`);
	const o = Object.fromEntries(Object.entries(v).map(([k, x]) => [k, normal(x)]));
	for (const op of ['and', 'or'])
		if (Array.isArray(o[op])) o[op] = (o[op] as unknown[]).flatMap((x) => (typeof x === 'object' && x !== null && Object.keys(x).length === 1 && Array.isArray((x as Record<string, unknown>)[op]) ? ((x as Record<string, unknown>)[op] as unknown[]) : [x]));
	if (typeof o.lit === 'string' && Object.keys(o).length === 1 && grammar.match(o.lit, 'name').succeeded()) return { path: [o.lit] };
	return o;
}

/**
 * Reads a question from its JSON form. A value is the JSON form of a question exactly when it is the tree of
 * its own printed text: printing it and parsing that text gives the same canonical JSON back. That one test
 * refuses every member, name and literal the grammar does not know, with no second description of the tree to
 * keep in step with the grammar. A reserved construct reads like any other (§1); it is reported when the
 * question is checked.
 */
export function fromJson(value: unknown): Question {
	let text: string;
	let canonical: string;
	try {
		const tree = normal(value);
		canonical = canonicalJson(tree);
		text = print(tree as Question);
	} catch (e) {
		if (e instanceof JsonFormError) throw e;
		throw new JsonFormError(`not the JSON form of a question: ${e instanceof Error ? e.message : String(e)}`);
	}
	const { tree } = parse(text);
	if (!tree || canonicalJson(tree) !== canonical) throw new JsonFormError('not the JSON form of a question: it is not the tree of its own text');
	return tree;
}
