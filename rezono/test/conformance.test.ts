// The conformance cases of docs/rezono/cases/ run against this implementation (docs/rezono/expressions.md §11).
//
// A key of a case's `expect` is asserted exactly when this implementation can produce it. What it cannot
// produce yet is listed per case in `not-yet.json`, and that list is itself asserted: a key that starts to be
// asserted must leave the list in the same change, and nothing can join it unnoticed. So the file says, case by
// case, how far the implementation is, and it can only shrink.
//
// A `settled` case must give its `expect`. An `open` case must give its `expect` or one of its `alternatives`;
// the reading it follows is in `not-yet.json` under `readings` (§11: neither reading fails the run, but giving
// neither does). A `pending` case is not run.
//
// The cases of a decision table (T01 to T07, docs/rezono/tables.md §6) declare an enum and a table on top of
// the fixture schema. An evaluation case gives them in `declare`: they are checked (`declare`), the question is
// checked against the schema with the derived value in it, and the table is decided over the role's view
// (`tabulate`) before the question is answered. A check-only case gives them as its `source`.
import assert from 'node:assert/strict';
import { readdirSync, readFileSync } from 'node:fs';
import { test } from 'node:test';
import { parse as yaml } from 'yaml';
import { canonicalJson } from '../../viewer/src/lib/canon.ts';
import { answer, check, classOf, declare, fromJson, grouping, isAsk, isCheck, isError, load, outputSchema, page, parse, parseDeclarations, print, printDeclarations, publish, questionHash, schemaId, STATES, suppose, tabulate, toJson, type Answer, type AnswerSchema, type Cursor, type Data, type Declared, type Diagnostic, type Schema } from '../src/index.ts';

interface Expect {
	[key: string]: unknown;
	diagnostics?: { code: string; span: Diagnostic['span']; hint?: string; suggest?: string[] }[];
	output_schema?: 'returned' | Record<string, unknown>;
	answer?: { rows: string[]; undecided: Record<string, unknown>[]; not_applicable: number };
	absent_reasons?: string[];
}
/** The data of one world of a case: Appendix B, changed by suppose lines, without what the role does not read. */
interface World {
	given?: string[];
	hidden?: string[];
}
interface Case extends World {
	id: string;
	status: 'settled' | 'open' | 'pending';
	mode: 'parse' | 'evaluate' | 'check-only' | 'publish';
	source?: string;
	/** Declarations that extend the fixture schema before the question is checked (docs/rezono/tables.md §6). */
	declare?: string;
	json?: unknown;
	limit?: number;
	reads_in_part?: string[];
	worlds?: World[];
	expect: Expect;
	alternatives?: { by: string; expect: Expect }[];
}

const dir = new URL('../../docs/rezono/cases/', import.meta.url);
const cases: Case[] = readdirSync(dir)
	.filter((f) => /^[EPT][0-9]{2}\.yaml$/.test(f))
	.sort()
	.map((f) => yaml(readFileSync(new URL(f, dir), 'utf8')) as Case);
const byId = new Map(cases.map((c) => [c.id, c]));
const recorded = JSON.parse(readFileSync(new URL('not-yet.json', import.meta.url), 'utf8')) as {
	not_yet: Record<string, string[]>;
	readings: Record<string, string>;
	pending: string[];
};

/** The codes the parse itself reports; the others come from names and types. */
const PARSE_LEVEL = new Set(['R000', 'R014', 'R015', 'R016', 'R018']);
/** A source that is declarations, not a question: it starts with the word of one (T06, T07). */
const DECLARATIONS = /^(?:enum|extend)\b/;

/** The fixture schema of §2, as the schema document a question is checked against. */
const fixture = JSON.parse(readFileSync(new URL('fixture.schema.json', import.meta.url), 'utf8')) as Schema;
const sentences = JSON.parse(readFileSync(new URL('../messages/en.json', import.meta.url), 'utf8')) as Record<string, string>;
const sentence = (id: string, args: string[]) => sentences[id].replace(/\{(\d)\}/g, (_m, i: string) => args[Number(i)]);

/**
 * An output schema as the cases write it: per kind its key and its slots, with the types by their name in the
 * pack. The document itself names them through its import and carries the states of each slot, which a case
 * leaves to typing (E51).
 */
function outline(doc: AnswerSchema): Record<string, unknown> {
	const type = (name: string) => (name === 'UndecidedState' ? { enum: doc.enums.UndecidedState } : name === 'Reason' ? 'reason' : name.replace(/^p\./, ''));
	return Object.fromEntries(
		Object.entries(doc.kinds).map(([kind, def]) => [
			kind,
			{
				key: 'binder',
				slots: Object.entries(def.slots).map(([name, s]) => ({
					name,
					type: s.ref !== undefined ? { ref: s.ref.replace(/^p\./, '') } : type(s.type!),
					...(s.expr !== undefined ? { expr: s.expr } : {})
				}))
			}
		])
	);
}

/** The rows of Appendix B, as Row JSON. It gives no provider: a host's provider is read as missing. */
const appendixB = (JSON.parse(readFileSync(new URL('appendix-b.json', import.meta.url), 'utf8')) as { rows: Record<string, unknown>[] }).rows;

/** What a role does not read is not in its view (§7a rule 1): a row (`host-e`) or one value (`host-a.owner`). */
function hide(data: Data, what: string): Data {
	const [id, slot] = what.split('.');
	const kinds = new Map([...data.kinds].map(([kind, rows]) => [kind, new Map(rows)]));
	for (const rows of kinds.values()) {
		if (!rows.has(id)) continue;
		if (slot === undefined) rows.delete(id);
		else rows.set(id, new Map([...rows.get(id)!].filter(([name]) => name !== slot)));
	}
	return { ...data, kinds };
}
/**
 * The schema of the role of a case: the fixture, and for each slot whose relation the role reads in part what
 * the role's publication form says of it (publication §3.3): the slot is open and takes `unknown`. It follows
 * from the case, never from a world's rows.
 */
function schemaOf(c: Case): Schema {
	if (!c.reads_in_part) return fixture;
	const schema = structuredClone(fixture);
	for (const [kind, name] of c.reads_in_part.map((s) => s.split('.'))) {
		const slot = schema.kinds[kind].slots[name];
		slot.world = 'open';
		if (!slot.states.includes('unknown')) slot.states = STATES.filter((s) => s === 'unknown' || slot.states.includes(s));
		((schema.in_part ??= {})[kind] ??= []).push(name);
	}
	return schema;
}
/**
 * The role's view of one world: Appendix B, each `given` line applied in order, then what is hidden taken out.
 * The tables a case declares are decided last, over that view: a derived value reads nothing the role does not.
 */
function viewOf(world: World, schema: Schema, declared?: Declared): Data {
	let data = load(schema, appendixB);
	for (const line of world.given ?? []) data = suppose(data, check(line, schema), schema);
	for (const what of world.hidden ?? []) data = hide(data, what);
	return declared ? tabulate(declared, data).data : data;
}
/** Everything a client can get of an answer, as bytes: the dataset, the counts, and every page with its cursor. */
function bytesOf(a: Answer, limit: number | undefined): string {
	const pages = [];
	for (let after: Cursor | undefined = {}; limit !== undefined && after; ) {
		const p = page(a, limit, after);
		pages.push(p);
		after = p.next;
	}
	return canonicalJson({ $schema: a.$schema, $rows: [...a.rows, ...a.undecided], counts: a.counts, pages });
}

/** What this implementation gives for a case, by `expect` key; a key it cannot give is absent. */
async function observe(c: Case): Promise<Record<string, unknown>> {
	// Checking reads the question and the schema, and nothing else: it is handed no row (§8b, E54).
	const base = schemaOf(c);
	// Declarations as the source itself: what their check reports, and their normal form.
	if (c.source !== undefined && DECLARATIONS.test(c.source)) {
		const d = declare(c.source, base);
		return { diagnostics: d.diagnostics, reads_rows: false, ...(d.decls ? { print: printDeclarations(d.decls) } : {}) };
	}
	// Declarations before the question: it is checked against the schema with what they declare in it.
	const declared = c.declare === undefined ? undefined : declare(c.declare, base);
	const fixture = declared?.schema ?? base;
	const checked = check(c.json !== undefined ? print(fromJson(c.json)) : c.source!, fixture);
	const { tree } = checked;
	// An error in the declarations is an error of the case; their warnings (W112) stand beside the question's.
	const seen: Record<string, unknown> = { diagnostics: [...(declared?.diagnostics.filter(isError) ?? []), ...checked.diagnostics], reads_rows: false };
	if (!tree) return seen;
	seen.print = print(tree);
	seen.resolve = checked.resolve;
	seen.class = c.mode === 'check-only' ? 'computes' : classOf(tree);
	seen.hash = await questionHash(checked, fixture);
	// A check statement decides at publication, over the role's view of the case's data (v0 §7b).
	if (isCheck(tree)) {
		const p = publish(checked, fixture, viewOf(c, fixture, declared));
		if (p) seen.publication = { outcome: p.outcome, violations: p.violations, undecided: p.undecided.map((u) => ({ binder: u.id, state: u.state, reason: u.reason })), blocking: p.blocking };
		return seen;
	}
	if (!isAsk(tree)) return seen;
	seen.grouping = grouping(tree.where);
	const schema = await outputSchema(tree, checked, fixture);
	if (schema) {
		assert.match(await schemaId(schema), /^s-[0-9a-f]{64}$/);
		seen.output_schema = outline(schema);
	}
	// An answer, where a case asks for one: in every world of the case, over the role's view of it.
	const wantsId = [c.expect, ...(c.alternatives ?? []).map((a) => a.expect)].some((e) => typeof e.output_schema === 'object' && 'answer_schema_is_id' in e.output_schema);
	if (!schema || (c.mode !== 'evaluate' && !wantsId)) return seen;
	const answers = await Promise.all((c.worlds ?? [c]).map(async (world) => (await answer(checked, fixture, viewOf(world, fixture, declared)))!));
	const [first] = answers;
	seen.answer = {
		rows: first.rows.map((r) => r.$id),
		undecided: first.undecided.map((u) => ({ binder: u.$id, state: u.state, reason: u.reason, ...(u.cause_relation ? { cause: { relation: u.cause_relation, key: JSON.parse(u.cause_key) } } : {}) })),
		not_applicable: first.counts.not_applicable
	};
	assert.deepEqual(first.counts, { rows: first.rows.length, undecided: first.undecided.length, not_applicable: first.counts.not_applicable });
	seen.answer_schema_is_id = first.$schema === (await schemaId(schema));
	seen.bytes = answers.map((a) => bytesOf(a, c.limit));
	seen.identical_worlds = answers.length > 1 && (seen.bytes as string[]).every((b) => b === (seen.bytes as string[])[0]);
	return seen;
}

/** The keys of an expectation that are asserted now, and those that are not yet. */
function split(c: Case, e: Expect): { now: string[]; later: string[] } {
	const now: string[] = [];
	const later: string[] = [];
	for (const key of Object.keys(e)) {
		if (['publication', 'print', 'grouping', 'same_hash_as', 'class', 'diagnostics', 'resolve', 'reads_rows', 'output_schema', 'answer', 'identical_worlds', 'absent_reasons'].includes(key)) now.push(key);
		else later.push(key);
	}
	return { now, later };
}

/** Why what was seen is not what an expectation asks, on the keys asserted now; undefined when it is. */
async function differs(c: Case, e: Expect, seen: Record<string, unknown>): Promise<string | undefined> {
	for (const key of split(c, e).now) {
		let want: unknown = e[key];
		let got = seen[key];
		if (key === 'diagnostics') {
			// A hint is its sentence; a hint or a list of suggestions that a case does not give is not asserted.
			got = (seen.diagnostics as Diagnostic[]).map((d, i) => ({
				code: d.code,
				span: d.span,
				...(e.diagnostics![i]?.hint !== undefined && d.hint ? { hint: sentence(d.hint.id, d.hint.args) } : {}),
				...(e.diagnostics![i]?.suggest !== undefined && d.suggest ? { suggest: d.suggest } : {})
			}));
		}
		if (key === 'output_schema') {
			if (want === 'returned') got = got === undefined ? undefined : 'returned';
			// The `$schema` of the answer is the id of this schema (§8a).
			else if ('answer_schema_is_id' in (want as object)) got = { ...(got as object), answer_schema_is_id: seen.answer_schema_is_id };
		}
		if (key === 'answer' && got !== undefined) {
			// An undecided row is asserted on the members the case gives: a cause only where the case names one.
			const given = e.answer!.undecided;
			const mine = got as NonNullable<Expect['answer']>;
			got = { ...mine, undecided: mine.undecided.map((u, i) => Object.fromEntries(Object.entries(u).filter(([k]) => !given[i] || k in given[i]))) };
		}
		// A reason that must not show: in no byte of the answer, in any world (E50).
		if (key === 'absent_reasons') got = seen.bytes === undefined ? undefined : e.absent_reasons!.filter((reason) => (seen.bytes as string[]).every((b) => !b.includes(reason)));
		if (key === 'same_hash_as') {
			want = (await observe(byId.get(e.same_hash_as as string)!)).hash;
			got = seen.hash;
		}
		try {
			assert.deepEqual(got, want);
		} catch (err) {
			return `${key}: ${(err as Error).message}`;
		}
	}
	return undefined;
}

const notYet: Record<string, string[]> = {};
const readings: Record<string, string> = {};

for (const c of cases) {
	test(`${c.id} (${c.status}, ${c.mode})`, { skip: c.status === 'pending' }, async () => {
		const seen = await observe(c);
		const candidates = [{ by: 'expect', expect: c.expect }, ...(c.status === 'open' ? (c.alternatives ?? []) : [])];
		const failures: string[] = [];
		const met: number[] = [];
		for (const [i, candidate] of candidates.entries()) {
			const failure = await differs(c, candidate.expect, seen);
			if (failure === undefined) met.push(i);
			else failures.push(`${candidate.by}: ${failure}`);
		}
		if (!met.length) assert.fail(failures.join('; '));
		// The reading of an open case is known once what is asserted tells its readings apart.
		if (c.status === 'open') readings[c.id] = met.length === candidates.length ? 'not told apart yet' : met[0] === 0 ? 'expect' : `alternative ${met[0]}`;
		const chosen = candidates[met[0]].expect;
		const { later } = split(c, chosen);
		if (later.length) notYet[c.id] = later;
		// A case that waits for a later check still has to parse, unless the parse itself is what it reports.
		const parseLevel = (chosen.diagnostics ?? []).some((d) => PARSE_LEVEL.has(d.code) && d.code !== 'R015');
		if (!parseLevel) assert.ok(seen.print !== undefined, 'the source parses');
		// A case that lists no diagnostics is a valid question: the check finds no error in it.
		if (chosen.diagnostics === undefined) assert.deepEqual((seen.diagnostics as Diagnostic[]).filter(isError), [], 'a valid question checks without an error');
	});
}

test('every source that parses prints stably, and its JSON form reads back to the same tree', () => {
	for (const c of cases) {
		if (c.source === undefined || c.status === 'pending') continue;
		// Declarations, as a source or before one, print and read back as the same declarations.
		for (const text of [c.declare, ...(DECLARATIONS.test(c.source) ? [c.source] : [])]) {
			if (text === undefined) continue;
			const { decls } = parseDeclarations(text);
			assert.ok(decls, `${c.id}: the declarations parse`);
			const printed = printDeclarations(decls);
			assert.deepEqual(parseDeclarations(printed).decls, decls, `${c.id}: parse(print(declarations))`);
			assert.equal(printDeclarations(parseDeclarations(printed).decls!), printed, `${c.id}: the printed declarations are stable`);
		}
		const { tree, diagnostics } = parse(c.source);
		if (!tree) continue;
		const text = print(tree);
		const again = parse(text);
		assert.equal(toJson(again.tree!), toJson(tree), `${c.id}: parse(print(tree)) is the tree`);
		assert.equal(print(again.tree!), text, `${c.id}: print(parse(print(tree))) is stable`);
		assert.deepEqual(
			again.diagnostics.map((d) => d.code),
			diagnostics.map((d) => d.code),
			`${c.id}: the same diagnostics after printing`
		);
		assert.equal(toJson(fromJson(JSON.parse(toJson(tree)))), toJson(tree), `${c.id}: from_json(to_json(tree))`);
	}
});

test('every case is here and every span is the text it names', () => {
	const ids = cases.map((c) => c.id);
	const expected = [...Array.from({ length: 64 }, (_, i) => `E${String(i + 1).padStart(2, '0')}`), ...Array.from({ length: 7 }, (_, i) => `P0${i + 1}`), ...Array.from({ length: 7 }, (_, i) => `T0${i + 1}`)];
	assert.deepEqual(ids, expected);
	for (const c of cases)
		for (const e of [c.expect, ...(c.alternatives ?? []).map((a) => a.expect)])
			for (const d of e.diagnostics ?? []) assert.equal([...c.source!].slice(d.span.start, d.span.end).join(''), d.span.text, c.id);
});

test('not-yet.json lists exactly what is not asserted yet, and the reading of every open case', () => {
	const pending = cases.filter((c) => c.status === 'pending').map((c) => c.id);
	assert.deepEqual({ not_yet: notYet, readings, pending }, recorded);
});
