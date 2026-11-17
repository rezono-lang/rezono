// The decision table on a derived value (docs/reckon/tables.md), where the conformance cases T01 to T07 do not
// show it: what its check reports (src/table.ts), the two proofs and `total` held to the evaluation piece by
// piece and over a fixed grid of elements, the value in each of the four states of an input per hit policy, the row condition against the data of S1
// (docs/semantics/value-cases.yaml), the witness, and the step budget (src/evaluate.ts, `tabulate`). Every kind
// and value here is made up for the test.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import { parse as yaml } from 'yaml';
import { canonicalJson } from '../../viewer/src/lib/canon.ts';
import { answer, check, declare, isError, load, outputSchema, OverBudget, tabulate, type Cell, type Data, type Declared, type Schema, type StateName, type V } from '../src/index.ts';

const read = (file: string) => readFileSync(new URL(file, import.meta.url), 'utf8');
const fixture = JSON.parse(read('fixture.schema.json')) as Schema;
const appendixB = load(fixture, (JSON.parse(read('appendix-b.json')) as { rows: Record<string, unknown>[] }).rows);

const ALL: StateName[] = ['known', 'not_applicable', 'unknown', 'invalid'];
const KNOWN: StateName[] = ['known'];
/** A schema of one kind whose slots take every state (`x`, `a`, `b`) or are always known (the others). */
const lab: Schema = {
	reckon: '1.0',
	pack: 'lab',
	base: 'https://rezono.example/lab/',
	types: { Count: { of: 'Integer' }, Level: { of: 'Enum' }, Mood: { of: 'Enum' }, Eur: { of: 'Money', currency: 'EUR', scale: '2' } },
	enums: { Level: ['high', 'low', 'rest'], Mood: { world: 'open', values: ['up', 'down'] } },
	kinds: {
		Thing: {
			world: 'closed',
			id: { type: 'Text' },
			slots: {
				x: { type: 'Count', card: '?', states: ALL },
				a: { type: 'Bool', card: '?', states: ALL },
				b: { type: 'Bool', card: '?', states: ALL },
				n: { type: 'Count', card: '1', states: KNOWN },
				lv: { type: 'Level', card: '1', states: KNOWN },
				mood: { type: 'Mood', card: '1', states: KNOWN },
				day: { type: 'Date', card: '1', states: KNOWN },
				stamp: { type: 'DateTime', card: '1', states: KNOWN },
				ratio: { type: 'Ratio', card: '1', states: KNOWN },
				price: { type: 'Eur', card: '1', states: KNOWN },
				label: { type: 'Text', card: '1', states: KNOWN },
				flag: { type: 'Bool', card: '1', states: KNOWN },
				parts: { type: 'Count', card: '*', states: KNOWN },
				tags: { type: 'Text', card: '*', states: KNOWN, world: 'open' }
			}
		}
	},
	symbols: { '€': 'EUR' }
};
/** One element for each state of `x`. */
const things = load(lab, [
	{ $kind: 'Thing', $id: 't-known', x: 5 },
	{ $kind: 'Thing', $id: 't-na', x: { $na: '' } },
	{ $kind: 'Thing', $id: 't-unknown', x: { $unknown: 'not_counted' } },
	{ $kind: 'Thing', $id: 't-invalid', x: { $invalid: 'below_zero' } }
]);

/** A table under `extend <kind>`: the derived value's line, the policy, the header and the rows. */
const tableOf = (kind: string, derived: string, policy: string, ...rows: string[]) => [`extend ${kind}`, `  ${derived}`, `    table ${policy}`, ...rows.map((r) => `      ${r}`)].join('\n') + '\n';
/** What the check of declarations reports: each code, the text at its span and its values. */
const found = (text: string, schema: Schema = lab): string[] =>
	declare(text, schema).diagnostics.map((d) => `${d.code} at ${d.span.text}${d.args.length ? `: ${d.args.join(' | ')}` : ''}${d.suggest?.length ? ` (${d.suggest.join(', ')})` : ''}`);
const valid = (text: string, schema: Schema = lab): Declared => {
	const d = declare(text, schema);
	assert.deepEqual(d.diagnostics.filter(isError), [], text);
	return d;
};

/** A value in one line: a known value as it is, a state with its reason and its cause. */
function show(cell: Cell): string {
	const one = (v: V): string => {
		if (v.s !== 'known') return `${v.s === 'not_applicable' ? 'n/a' : v.s} ${v.reason}${v.cause ? ` @ ${v.cause.relation} ${JSON.stringify(v.cause.key)}` : ''}`;
		const k = v.v as unknown;
		return typeof k === 'object' && k !== null && 'id' in k ? String(k.id) : typeof k === 'object' && k !== null && 'n' in k ? String(k.n) : String(k);
	};
	if (!Array.isArray(cell)) return one(cell);
	return `[${cell.map((m) => `${one(m)}${'maybe' in m && m.maybe ? ` ? ${one(m.maybe as V)}` : ''}`).join(', ')}]`;
}
/** The value of the last table of some declarations, for every element of its kind. */
function decide(text: string, data: Data, schema: Schema = lab): Record<string, string> {
	const d = valid(text, schema);
	const { kind, slot } = d.tables.at(-1)!;
	return Object.fromEntries([...tabulate(d, data).data.kinds.get(kind)!].map(([id, row]) => [id, show(row.get(slot)!)]));
}

// ---- the check: names and types (tables.md §2) ----

test('the check takes an enum and an extend with tables, and refuses the rest by name', () => {
	const d = valid(`enum Size = small | large\nenum Wish world open = more\n${tableOf('Thing', 'derived size: Size', 'first', '| n | -> size |', '| ..<10 | small |', '| - | large |')}`);
	assert.deepEqual(d.schema!.types!.Size, { of: 'Enum' });
	assert.deepEqual(d.schema!.enums!.Size, ['small', 'large']);
	assert.deepEqual(d.schema!.enums!.Wish, { world: 'open', values: ['more'] });
	// Every row of `first` ends in a `-`, and `n` is always known: so is the value.
	assert.deepEqual(d.schema!.kinds.Thing.slots.size, { type: 'Size', card: '1', states: ['known'], derived: true });
	// The schema handed in is not changed.
	assert.equal(lab.kinds.Thing.slots.size, undefined);
	assert.equal(lab.types!.Size, undefined);
	// What this check does not take yet is refused at its span, never passed over.
	const other = 'an `enum`, or an `extend` whose derived values have a decision table';
	assert.deepEqual(found('unit Mile = 1609 m\nparam p: Count = 3\nkind Other\n  a: Count\ncheck thing.n > 0\nfact Thing\n  | id | n |\n'), [`R000 at Mile: ${other}`, `R000 at p: ${other}`, `R000 at Other: ${other}`, `R000 at check thing.n > 0: ${other}`, `R000 at Thing: ${other}`]);
	assert.deepEqual(found('extend Thing\n  derived twice: Count = n * 2\n'), ['R000 at twice: a derived value with a decision table']);
	// A header line is no declaration, and a name that is there already is not declared again.
	assert.deepEqual(found('pack lab\nenum Size = small\n'), ['R000 at pack: a declaration']);
	assert.deepEqual(found('enum Level = a | b\nenum Thing = a\nenum Date = a\n'), ['R000 at Level: a type name that is not declared yet', 'R000 at Thing: a type name that is not declared yet', 'R000 at Date: a type name that is not declared yet']);
	assert.deepEqual(found(tableOf('Thing', 'derived n: Count', 'first', '| x | -> n |', '| - | 1 |')), ['R000 at n: a name that `Thing` does not have yet']);
	// With an error there is no schema and no table to evaluate.
	const refused = declare('extend Thing\n  derived twice: Count = n * 2\n', lab);
	assert.equal(refused.schema, undefined);
	assert.deepEqual(refused.tables, []);
	assert.throws(() => tabulate(refused, things), /never evaluated/);
});

test('R001: a kind, a type, an input or a value that is not there', () => {
	assert.deepEqual(found(tableOf('Thin', 'derived v: Level', 'first', '| n | -> v |', '| - | low |')), ['R001 at Thin: Thin (Thing)']);
	assert.deepEqual(found(tableOf('Thing', 'derived v: Levle', 'first', '| n | -> v |', '| - | low |')), ['R001 at Levle: Levle (Level)']);
	assert.deepEqual(found(tableOf('Thing', 'derived v: Level', 'first', '| m | -> v |', '| 1 | low |')), ['R001 at m: m']);
	assert.deepEqual(found(tableOf('Thing', 'derived v: Level', 'first', '| lable | -> v |', '| "a" | low |')), ['R001 at lable: lable (label)']);
	assert.deepEqual(found(tableOf('Thing', 'derived v: Level', 'first', '| lv | -> v |', '| hihg | lo |')), ['R001 at hihg: hihg (high)', 'R001 at lo: lo (low)']);
	// The name after `->` is the derived value's own (the reader reports it).
	assert.deepEqual(found(tableOf('Thing', 'derived v: Level', 'first', '| n | -> w |', '| - | low |')), ['R001 at w: w (v)']);
	// A value is a literal, an id or a bare word, never a name in scope: `n` here is no slot.
	assert.deepEqual(found(tableOf('Thing', 'derived v: Level', 'first', '| n | -> v |', '| x | low |')), ['R001 at x: x']);
	// A table reads the schema handed in and what stands above it: not itself, and nothing below it.
	assert.deepEqual(found(tableOf('Thing', 'derived v: Level', 'first', '| v | -> v |', '| low | low |')), ['R001 at v: v (lv)']);
	const chain = `${tableOf('Thing', 'derived one: Level', 'first', '| two | -> one |', '| - | low |')}${tableOf('Thing', 'derived two: Level', 'first', '| n | -> two |', '| - | low |')}`;
	assert.deepEqual(found(chain), ['R001 at two: two']);
});

test('a value that is a keyword is a bare word in a cell: an enum of the schema may say `valid` or `open`', () => {
	const grant: Schema = {
		...lab,
		types: { ...lab.types, Grant: { of: 'Enum' } },
		enums: { ...lab.enums, Grant: ['valid', 'open', 'revoked'] },
		kinds: { Thing: { ...lab.kinds.Thing, slots: { ...lab.kinds.Thing.slots, g: { type: 'Grant', card: '1', states: KNOWN } } } }
	};
	const data = load(grant, [
		{ $kind: 'Thing', $id: 't-valid', n: 1, g: 'valid' },
		{ $kind: 'Thing', $id: 't-open', n: 1, g: 'open' },
		{ $kind: 'Thing', $id: 't-revoked', n: 1, g: 'revoked' }
	]);
	const text = `enum Standing = good | withdrawn
${tableOf('Thing', 'derived standing: Standing', 'unique', '| g | -> standing |', '| valid, open | good |', '| revoked | withdrawn |')}`;
	assert.deepEqual(decide(text, data, grant), { 't-valid': 'good', 't-open': 'good', 't-revoked': 'withdrawn' });
	// It is read by the type of its input as any bare word: a keyword that is no value of the enum is R001.
	assert.deepEqual(found(tableOf('Thing', 'derived v: Level', 'unique', '| g | -> v |', '| known | low |'), grant), ['R001 at known: known']);
	// `true` and `false` stay the literals of Bool, and a state stays no value (tables.md §7 point 1).
	assert.deepEqual(found(tableOf('Thing', 'derived v: Level', 'unique', '| g | -> v |', '| true | low |'), grant).map((f) => f.slice(0, 4)), ['R003']);
});

test('R003: a test that does not go with its input, a range without an order, an output of another type', () => {
	const of = (input: string, test: string) => found(tableOf('Thing', 'derived v: Level', 'first', `| ${input} | -> v |`, `| ${test} | low |`, '| - | rest |'));
	assert.deepEqual(of('n', '€ 3.00'), ['R003 at € 3.00: Count | money EUR']);
	assert.deepEqual(of('price', '3'), ['R003 at 3: Eur | number']);
	assert.deepEqual(of('flag', '1, true'), ['R003 at 1: Bool | number']);
	assert.deepEqual(of('day', '3..'), ['R003 at 3..: Date | number']);
	// Each test of a cell on its own, and both ends of a range.
	assert.deepEqual(of('n', '1, true..2, € 1.00'), ['R003 at true..2: Count | Bool', 'R003 at € 1.00: Count | money EUR']);
	// A range needs an order: a number and a date have one, an enum, a truth value, a text and a moment have not.
	assert.deepEqual(of('lv', 'high..low'), ['R003 at high..low: Level | ..']);
	assert.deepEqual(of('flag', '..<true'), ['R003 at ..<true: Bool | ..<']);
	assert.deepEqual(of('label', '"a".."b"'), ['R003 at "a".."b": Text | ..']);
	assert.deepEqual(of('stamp', '2026-01-01T00:00.., 2026-01-01T00:00'), ['R003 at 2026-01-01T00:00..: DateTime | ..']);
	assert.deepEqual(of('day', '2026-01-01..<2026-02-01, 2026-03-01'), []);
	assert.deepEqual(of('ratio', '..<12 %, 0.5, 1/3..'), []);
	// A date that is no day of the calendar has no place in the order.
	assert.deepEqual(of('day', '2026-02-30..'), ['R012 at 2026-02-30: 2026-02-30 | Date']);
	assert.deepEqual(of('day', '2023-02-29'), ['R012 at 2023-02-29: 2023-02-29 | Date']);
	assert.deepEqual(of('day', '2024-02-29'), []);
	// The output is a value of the derived value's type; `priority` orders by an enum.
	assert.deepEqual(found(tableOf('Thing', 'derived v: Count', 'first', '| n | -> v |', '| - | low |', '| - | 2 GiB |', '| - | 3 |'), fixtureWith()), ['R001 at low: low', 'R003 at 2 GiB: GiB | Count']);
	assert.deepEqual(found(tableOf('Thing', 'derived v: Count', 'priority', '| n | -> v |', '| - | 3 |')), ['R003 at table priority: table priority | Count']);
	assert.deepEqual(found(tableOf('Thing', 'derived v: Level', 'priority', '| n | -> v |', '| - | low |')), []);
});
/** The lab schema with the units of the fixture, for a literal of another dimension. */
function fixtureWith(): Schema {
	const s = structuredClone(lab);
	s.types = { ...s.types, ...fixture.types };
	return s;
}

test('R005: a set as an input, `collect` on anything but `T*`, another policy on a set', () => {
	assert.deepEqual(found(tableOf('Thing', 'derived v: Level', 'first', '| parts | -> v |', '| 1 | low |')), ['R005 at parts']);
	assert.deepEqual(found(tableOf('Thing', 'derived v: Level', 'first', '| parts.count() | -> v |', '| 1 | low |', '| - | rest |')), []);
	for (const card of ['', '?', '+']) assert.deepEqual(found(tableOf('Thing', `derived v: Level${card}`, 'collect', '| n | -> v |', '| 1 | low |')), ['R005 at table collect']);
	assert.deepEqual(found(tableOf('Thing', 'derived v: Level*', 'collect', '| n | -> v |', '| 1 | low |')), []);
	for (const policy of ['unique', 'first', 'priority']) {
		assert.deepEqual(found(tableOf('Thing', 'derived v: Level*', policy, '| n | -> v |', '| - | low |')), [`R005 at table ${policy}`]);
		assert.deepEqual(found(tableOf('Thing', 'derived v: Level+', policy, '| n | -> v |', '| - | low |')), [`R005 at table ${policy}`]);
		assert.deepEqual(found(tableOf('Thing', 'derived v: Level?', policy, '| n | -> v |', '| - | low |')), []);
	}
});

// ---- the proofs (tables.md §4) ----

test('R031: two rows of a `unique` table that one input passes, at the cell of the later row, with an example', () => {
	const unique = (...rows: string[]) => found(tableOf('Thing', 'derived v: Level', 'unique', ...rows)).filter((d) => !d.startsWith('W112'));
	assert.deepEqual(unique('| n | -> v |', '| ..<10 | low |', '| 5.. | high |'), ['R031 at 5..: v | 1 | 2 | n = 5']);
	// Row order does not make rows disjoint: the same two rows the other way round overlap too.
	assert.deepEqual(unique('| n | -> v |', '| 5.. | high |', '| ..<10 | low |'), ['R031 at ..<10: v | 1 | 2 | n = 5']);
	// Also when both give the same output (v0 §5b rule 3: a silent pick hides an error).
	assert.deepEqual(unique('| n | -> v |', '| 1 | low |', '| 1, 2 | low |'), ['R031 at 1, 2: v | 1 | 2 | n = 1']);
	// Disjoint in one column is disjoint, whatever the others say.
	assert.deepEqual(unique('| n | flag | -> v |', '| ..<10 | true | low |', '| 5.. | false | high |'), []);
	assert.deepEqual(unique('| n | flag | -> v |', '| ..<10 | - | low |', '| 10.. | - | high |'), []);
	// The first column where both test names the cell; the example gives every column either row tests.
	assert.deepEqual(unique('| flag | n | lv | -> v |', '| - | ..<10 | high | low |', '| true | 5.. | high, low | high |'), ['R031 at 5..: v | 1 | 2 | flag = true and n = 5 and lv = high']);
	// Without a column where both test, the later row itself is the place: it applies wherever the other does.
	assert.deepEqual(unique('| n | flag | -> v |', '| 1 | - | low |', '| - | true | high |'), ['R031 at | - | true | high |: v | 1 | 2 | n = 1 and flag = true']);
	assert.deepEqual(unique('| n | -> v |', '| - | low |', '| - | high |'), ['R031 at | - | high |: v | 1 | 2 | true']);
	// Every pair, in the order of the later row.
	assert.deepEqual(unique('| n | -> v |', '| 1..3 | low |', '| 3..5 | high |', '| 2..4 | rest |'), ['R031 at 3..5: v | 1 | 2 | n = 3', 'R031 at 2..4: v | 1 | 3 | n = 2', 'R031 at 2..4: v | 2 | 3 | n = 3']);
	// Ends that touch: `..<` leaves its end out, `..` takes it in.
	assert.deepEqual(unique('| n | -> v |', '| 1..<3 | low |', '| 3..5 | high |'), []);
	assert.deepEqual(unique('| n | -> v |', '| 1..3 | low |', '| 3..<5 | high |'), ['R031 at 3..<5: v | 1 | 2 | n = 3']);
	// A cell no value passes (its range is empty) overlaps nothing.
	assert.deepEqual(unique('| n | -> v |', '| 5..3 | low |', '| - | high |'), []);
	// The other policies say what several applying rows mean: no R031.
	for (const policy of ['first', 'priority']) assert.deepEqual(found(tableOf('Thing', 'derived v: Level', policy, '| n | -> v |', '| - | low |', '| - | high |')), []);
	assert.deepEqual(found(tableOf('Thing', 'derived v: Level*', 'collect', '| n | -> v |', '| - | low |', '| - | high |')), []);
});

test('W112: the rows leave a gap, with an example; the pieces follow the type of the input', () => {
	const gap = (input: string, ...tests: string[]) =>
		found(tableOf('Thing', 'derived v: Level', 'first', `| ${input} | -> v |`, ...tests.map((x) => `| ${x} | low |`)), fixtureWith()).map((d) => d.replace(/^W112 at table first: first \| v \| /, 'gap: '));
	// A number: the ends, and the intervals between them.
	assert.deepEqual(gap('ratio', '..0.5', '0.6..'), ['gap: ratio > 0.5 and ratio < 0.6']);
	assert.deepEqual(gap('ratio', '..<0.5', '0.5..'), []);
	assert.deepEqual(gap('ratio', '..<0.5', '0.5'), ['gap: ratio > 0.5']);
	assert.deepEqual(gap('ratio', '0.5..'), ['gap: ratio < 0.5']);
	assert.deepEqual(gap('ratio', '..<0.5', '0.6..'), ['gap: ratio = 0.5']);
	assert.deepEqual(gap('ratio'), ['gap: true']);
	// A type of whole numbers has no value between two neighbours; so has money at its scale, and a date in days.
	assert.deepEqual(gap('n', '..17', '18..'), []);
	assert.deepEqual(gap('n', '..<17', '18..'), ['gap: n = 17']);
	assert.deepEqual(gap('n', '..16', '18..'), ['gap: n > 16 and n < 18']);
	assert.deepEqual(gap('n', '..<17.5', '17.5..'), []);
	assert.deepEqual(gap('price', '..€ 99.99', '€ 100.00..'), []);
	assert.deepEqual(gap('price', '..€ 99.98', '€ 100.00..'), ['gap: price > € 99.98 and price < € 100.00']);
	assert.deepEqual(gap('day', '..2026-01-31', '2026-02-01..'), []);
	assert.deepEqual(gap('day', '..2026-02-28', '2026-03-02..'), ['gap: day > 2026-02-28 and day < 2026-03-02']);
	assert.deepEqual(gap('day', '..2024-02-28', '2024-03-01..'), ['gap: day > 2024-02-28 and day < 2024-03-01']);
	assert.deepEqual(gap('day', '..2023-02-28', '2023-03-01..'), []);
	// What a division made need not be a whole number, whatever its type says.
	assert.deepEqual(gap('n / 2', '..17', '18..'), ['gap: (n / 2) > 17 and (n / 2) < 18']);
	assert.deepEqual(gap('n * 2', '..17', '18..'), ['gap: (n * 2) > 17 and (n * 2) < 18']);
	// A Bool and a closed enum have the values they have; an open enum and any other type may hold another.
	assert.deepEqual(gap('flag', 'true'), ['gap: flag = false']);
	assert.deepEqual(gap('flag', 'true, false'), []);
	assert.deepEqual(gap('lv', 'high', 'low'), ['gap: lv = rest']);
	assert.deepEqual(gap('lv', 'high', 'rest, low'), []);
	assert.deepEqual(gap('mood', 'up', 'down'), ['gap: mood != up and mood != down']);
	assert.deepEqual(gap('label', '"a"'), ['gap: label != "a"']);
	assert.deepEqual(gap('stamp', '2026-01-01T00:00'), ['gap: stamp != 2026-01-01T00:00']);
	// Column by column: the first combination of pieces that no row takes.
	const two = (...rows: string[]) => found(tableOf('Thing', 'derived v: Level', 'unique', '| flag | n | -> v |', ...rows));
	assert.deepEqual(two('| true | ..<10 | low |', '| true | 10.. | high |', '| false | ..<10 | rest |'), ['W112 at table unique: unique | v | flag = false and n = 10']);
	assert.deepEqual(two('| true | ..<10 | low |', '| true | 10.. | high |', '| false | - | rest |'), []);
	assert.deepEqual(two('| true | ..<10 | low |', '| false | - | rest |'), ['W112 at table unique: unique | v | flag = true and n = 10']);
	// `collect` gives the empty set where no row applies: that is a value, not a gap.
	assert.deepEqual(found(tableOf('Thing', 'derived v: Level*', 'collect', '| flag | -> v |', '| true | low |')), []);
});

test('R024: a `total` value whose table leaves a gap, or whose input can be in a state', () => {
	const total = (input: string, ...rows: string[]) => found(tableOf('Thing', 'total derived v: Level', 'unique', `| ${input} | -> v |`, ...rows));
	assert.deepEqual(total('n', '| ..<10 | low |'), ['R024 at table unique: v | n = 10']);
	assert.deepEqual(total('x', '| ..<10 | low |', '| 10.. | high |'), ['R024 at x: v | x is n/a or x is unknown or x is invalid']);
	assert.deepEqual(total('x + 1', '| - | low |'), []);
	const d = valid(tableOf('Thing', 'total derived v: Level', 'unique', '| n | flag | -> v |', '| ..<10 | - | low |', '| 10.. | true | high |', '| 10.. | false | rest |'));
	assert.deepEqual(d.schema!.kinds.Thing.slots.v.states, ['known']);
	// Without `total` the same table is valid, and its value lists the states its inputs give it.
	const states = (text: string) => valid(text).schema!.kinds.Thing.slots.v.states;
	assert.deepEqual(states(tableOf('Thing', 'derived v: Level', 'unique', '| x | -> v |', '| ..<10 | low |', '| 10.. | high |')), ['known', 'unknown', 'invalid']);
	assert.deepEqual(states(tableOf('Thing', 'derived v: Level', 'unique', '| n | -> v |', '| ..<10 | low |')), ['known', 'unknown']);
	assert.deepEqual(states(tableOf('Thing', 'derived v: Level*', 'collect', '| x | -> v |', '| ..<10 | low |')), ['known', 'unknown', 'invalid']);
	assert.deepEqual(states(tableOf('Thing', 'derived v: Level*', 'collect', '| n | -> v |', '| ..<10 | low |')), ['known']);
	// An input in a column of `-` only is never read: its states are not the value's.
	assert.deepEqual(states(tableOf('Thing', 'derived v: Level', 'first', '| x | n | -> v |', '| - | ..<10 | low |', '| - | - | high |')), ['known']);
});

test('the proofs agree with the evaluation, piece by piece (tables.md §4)', () => {
	const text = `enum Size = small | medium | large\n${tableOf('Host', 'derived size: Size', 'unique', '| memory_need | owner | -> size |', '| ..<300 GiB | - | small |', '| 300 GiB..<500 GiB | team-platform | medium |', '| 500 GiB.. | - | large |')}`;
	// The gap the proof names: the first piece of each column, in order, that no row takes.
	assert.deepEqual(found(text, fixture), ['W112 at table unique: unique | size | memory_need = 300 GiB and owner != team-platform']);
	// One element in each piece of each column: below, at and between the ends; the owner tested and another.
	const memory = ['299 GiB', '300 GiB', '400 GiB', '500 GiB', '600 GiB'];
	const owners = ['team-platform', 'team-other'];
	const rows = memory.flatMap((m, i) => owners.map((o, j) => ({ $kind: 'Host', $id: `h${i}${j}`, memory_need: m, owner: { $ref: o } })));
	const no = (id: string) => `unknown no_row_applies @ host__size ["${id}"]`;
	assert.deepEqual(decide(text, load(fixture, rows), fixture), {
		h00: 'small',
		h01: 'small',
		h10: 'medium',
		h11: no('h11'),
		h20: 'medium',
		h21: no('h21'),
		h30: 'large',
		h31: 'large',
		h40: 'large',
		h41: 'large'
	});
	// Rows the proof calls disjoint: no element has two of them applying, so `exception_conflict` is never given.
	// Where two rows do apply, the value is invalid, whatever their order: the check refuses such a table
	// (R031), so this is a table as no text can declare it.
	const d = valid(text, fixture);
	const [table] = d.tables;
	const twice: Declared = { ...d, tables: [{ ...table, rows: [table.rows[2], table.rows[0], { ...table.rows[0], value: table.rows[1].value }] }] };
	const cell = (id: string) => show(tabulate(twice, load(fixture, rows)).data.kinds.get('Host')!.get(id)!.get('size')!);
	assert.equal(cell('h00'), 'invalid exception_conflict @ host__size ["h00"]');
	assert.equal(cell('h40'), 'large');
	assert.equal(cell('h21'), no('h21'));
});

test('a computed input is held to no step: a sum takes the name of a type and need not be a value of it', () => {
	const of = (derived: string, policy: string, input: string, ...rows: string[]) => found(tableOf('Thing', derived, policy, `| ${input} | -> z |`, ...rows));
	const one = load(lab, [{ $kind: 'Thing', $id: 't', n: 1, price: '€ 0.99' }]);
	// `n` is a whole number and `n + 0.5` is not: between `..1` and `2..` there is a value, and one element has it.
	for (const input of ['n + 0.5', '0.5 + n', 'n - 0.5', 'when flag then n else n + 0.5']) {
		const shown = `(${input})`;
		assert.deepEqual(of('total derived z: Level', 'first', input, '| ..1 | high |', '| 2.. | low |'), [`R024 at table first: z | ${shown} > 1 and ${shown} < 2`], input);
		assert.deepEqual(of('derived z: Level', 'first', input, '| ..1 | high |', '| 2.. | low |'), [`W112 at table first: first | z | ${shown} > 1 and ${shown} < 2`], input);
	}
	assert.deepEqual(decide(tableOf('Thing', 'derived z: Level', 'first', '| n + 0.5 | -> z |', '| ..1 | high |', '| 2.. | low |'), one), { t: 'unknown no_row_applies @ thing__z ["t"]' });
	// The same value is in `1..2` and is `1.5`: two rows of `unique` apply.
	assert.deepEqual(of('derived z: Level', 'unique', 'n + 0.5', '| 1..2 | high |', '| 1.5 | low |').filter((d) => d.startsWith('R')), ['R031 at 1.5: z | 1 | 2 | (n + 0.5) = 1.5']);
	// Money at two places plus half a cent is no amount at two places.
	assert.deepEqual(of('total derived z: Level', 'first', 'price + € 0.005', '| ..€ 0.99 | high |', '| € 1.00.. | low |'), ['R024 at table first: z | (price + € 0.005) > € 0.99 and (price + € 0.005) < € 1.00']);
	assert.deepEqual(decide(tableOf('Thing', 'derived z: Level', 'first', '| price + € 0.005 | -> z |', '| ..€ 0.99 | high |', '| € 1.00.. | low |'), one), { t: 'unknown no_row_applies @ thing__z ["t"]' });
	// A product with a whole number keeps the step by arithmetic; the proof does not reason about it and names a
	// gap no value has: it refuses where it cannot prove, and never the other way round.
	assert.deepEqual(of('total derived z: Level', 'first', 'n * 2', '| ..1 | high |', '| 2.. | low |'), ['R024 at table first: z | (n * 2) > 1 and (n * 2) < 2']);
	// The slot itself is held to its type: no value between two neighbours.
	assert.deepEqual(of('total derived z: Level', 'first', 'n', '| ..1 | high |', '| 2.. | low |'), []);
	assert.deepEqual(of('derived z: Level', 'unique', 'n', '| 1..2 | high |', '| 1.5 | low |').filter((d) => d.startsWith('R')), []);
});

test('R003, R012: an output that is no value of the derived value\'s type, so that a table below reads a value of it', () => {
	const out = (type: string, value: string, schema: Schema = lab) => found(tableOf('Thing', `derived c: ${type}`, 'first', '| n | -> c |', `| - | ${value} |`), schema);
	assert.deepEqual(out('Count', '1.5'), ['R003 at 1.5: 1.5 | Count']);
	assert.deepEqual(out('Integer', '3/2'), ['R003 at 3/2: 3/2 | Integer']);
	assert.deepEqual(out('Count', '50 %'), ['R003 at 50 %: 50 % | Count']);
	assert.deepEqual(out('Eur', '€ 1.005'), ['R003 at € 1.005: € 1.005 | Eur']);
	assert.deepEqual(out('B', '0.5 B', fixtureWith()), ['R003 at 0.5 B: 0.5 B | B']);
	assert.deepEqual(out('EurPerHour', '€ 0.00005/h', fixtureWith()), ['R003 at € 0.00005/h: € 0.00005/h | EurPerHour']);
	assert.deepEqual(out('Date', '2026-02-30'), ['R012 at 2026-02-30: 2026-02-30 | Date']);
	// A value of the type in any spelling, and any number where the type holds any.
	for (const [type, value] of [['Count', '2'], ['Count', '4/2'], ['Count', '200 %'], ['Eur', '€ 1.00'], ['Eur', '€ 1.5'], ['GiB', '0.5 GiB'], ['B', '0.5 GiB'], ['EurPerHour', '€ 0.0001/h'], ['Ratio', '1/3'], ['Date', '2024-02-29']])
		assert.deepEqual(out(type, value, fixtureWith()), [], `${type} ${value}`);
	// What the hole gave: `c` was `3/2`, and a `total` table over it had no value for it.
	const below = `${tableOf('Thing', 'derived c: Count', 'first', '| n | -> c |', '| ..1 | 1 |', '| - | 2 |')}${tableOf('Thing', 'total derived z: Level', 'unique', '| c | -> z |', '| ..1 | high |', '| 2.. | low |')}`;
	assert.deepEqual(found(below), []);
	assert.deepEqual(decide(below, load(lab, [{ $kind: 'Thing', $id: 't1', n: 1 }, { $kind: 'Thing', $id: 't2', n: 2 }])), { t1: 'high', t2: 'low' });
	// A number that has no value is no test and no output (it was an exception of the evaluation).
	assert.deepEqual(found(tableOf('Thing', 'derived c: Count', 'first', '| n | -> c |', '| 1/0.. | 1 |', '| 2, 3/0 | 2 |', '| - | 1/0 |')), ['R012 at 1/0: 1/0 | number', 'R012 at 3/0: 3/0 | number', 'R012 at 1/0: 1/0 | number']);
});

test('R024: an input that reads the missing rows of an open relation can be unknown, whatever its typing lists', () => {
	// `tags` is an open relation: "none found" is unknown there, never false (expressions.md §6).
	const text = (derived: string) => tableOf('Thing', derived, 'unique', '| tags.any(it = "a") | -> z |', '| true | high |', '| false | low |');
	assert.deepEqual(found(text('total derived z: Level')), ['R024 at tags.any(it = "a"): z | (tags.any(it = "a")) is unknown']);
	assert.deepEqual(valid(text('derived z: Level')).schema!.kinds.Thing.slots.z.states, ['known', 'unknown']);
	assert.deepEqual(decide(text('derived z: Level'), load(lab, [{ $kind: 'Thing', $id: 'with', tags: ['a'] }, { $kind: 'Thing', $id: 'without', tags: ['b'] }])), { with: 'high', without: 'unknown open_world' });
});

// ---- the proofs against the evaluation (tables.md §4) ----

/**
 * The values each slot takes in the elements the proofs are held to: every end the tables below test, a value
 * on each side of it, a value strictly between two neighbouring ends where the type has one, a value nobody
 * tests, and for `x` the three states. A fixed list: the same elements on every run.
 */
const GRID: Record<string, unknown[]> = {
	n: [0, 1, 2, 3, 4, 5, 6],
	ratio: ['0', '0.25', '0.5', '0.75', '1', '1.25', '1.5', '1.75', '2', '2.25', '2.5', '2.75', '3'],
	price: ['€ 0.97', '€ 0.98', '€ 0.99', '€ 1.00', '€ 1.01', '€ 1.02', '€ 1.03'],
	day: ['2024-02-26', '2024-02-27', '2024-02-28', '2024-02-29', '2024-03-01', '2024-03-02', '2024-03-03'],
	flag: [true, false],
	lv: ['high', 'low', 'rest'],
	mood: ['up', 'down', 'sideways'],
	label: ['a', 'b', 'c'],
	tags: [['a'], ['b'], []],
	x: [1, 2, 3, { $na: '' }, { $unknown: 'u' }, { $invalid: 'i' }]
};
interface Held {
	/** Declarations above the table. */
	above?: string;
	/** The header inputs, the slots they read, and each row's cells as written between the outer bars. */
	inputs: string[];
	slots: string[];
	rows: string[];
	/**
	 * Whether the proof is exact over these inputs: every overlap and every gap it names has an element. It is
	 * for stored values; over a computed input it may name a value the arithmetic never gives.
	 */
	exact: boolean;
}
const HELD: Held[] = [
	// A stored value of each type that has a step: no value between two neighbours.
	{ inputs: ['n'], slots: ['n'], rows: ['..1', '2..'], exact: true },
	{ inputs: ['n'], slots: ['n'], rows: ['..<2', '3..'], exact: true },
	{ inputs: ['n'], slots: ['n'], rows: ['..<2.5', '2.5..'], exact: true },
	{ inputs: ['n'], slots: ['n'], rows: ['1..2', '1.5', '3..'], exact: true },
	{ inputs: ['n'], slots: ['n'], rows: ['1..3', '3..5', '2..4'], exact: true },
	{ inputs: ['n'], slots: ['n'], rows: ['1, 3', '2, 3..<5', '5..3'], exact: true },
	{ inputs: ['price'], slots: ['price'], rows: ['..€ 0.99', '€ 1.00..'], exact: true },
	{ inputs: ['price'], slots: ['price'], rows: ['..€ 0.99', '€ 1.01..'], exact: true },
	{ inputs: ['price'], slots: ['price'], rows: ['..€ 1.00', '€ 0.995', '€ 1.00..<€ 1.02'], exact: true },
	{ inputs: ['day'], slots: ['day'], rows: ['..2024-02-28', '2024-02-29..'], exact: true },
	{ inputs: ['day'], slots: ['day'], rows: ['..2024-02-28', '2024-03-01..'], exact: true },
	{ inputs: ['day'], slots: ['day'], rows: ['2024-02-28..2024-03-01', '2024-02-29', '..<2024-02-28'], exact: true },
	// A stored value of a type that holds any number: a value between any two ends.
	{ inputs: ['ratio'], slots: ['ratio'], rows: ['..1', '2..'], exact: true },
	{ inputs: ['ratio'], slots: ['ratio'], rows: ['..<1', '1..'], exact: true },
	{ inputs: ['ratio'], slots: ['ratio'], rows: ['0.5..1.5', '1..2', '1.25', '2.5'], exact: true },
	// The values of a Bool and of a closed enum; any other value of an open enum and of a text.
	{ inputs: ['flag', 'lv'], slots: ['flag', 'lv'], rows: ['true | high, low', 'false | -', '- | rest'], exact: true },
	{ inputs: ['mood'], slots: ['mood'], rows: ['up', 'down'], exact: true },
	{ inputs: ['label', 'flag'], slots: ['label', 'flag'], rows: ['"a" | -', '"a", "b" | true', '- | false'], exact: true },
	// Two ordered columns.
	{ inputs: ['n', 'ratio'], slots: ['n', 'ratio'], rows: ['..3 | ..<1', '2.. | 1..', '- | 1.5', '4.. | ..<1'], exact: true },
	// A slot in each state: a test on it is `n/a`, unknown or invalid; `-` takes it in any state.
	{ inputs: ['x'], slots: ['x'], rows: ['..<2', '2..'], exact: true },
	{ inputs: ['x', 'flag'], slots: ['x', 'flag'], rows: ['- | true', '- | false'], exact: true },
	{ inputs: ['x', 'flag'], slots: ['x', 'flag'], rows: ['..2 | true', '- | false', '3.. | true'], exact: true },
	// A derived value above: its outputs are values of its type.
	{ above: tableOf('Thing', 'derived c: Count', 'first', '| n | -> c |', '| ..1 | 1 |', '| 2..3 | 2 |', '| - | 3 |'), inputs: ['c'], slots: ['n'], rows: ['..1', '2', '3..'], exact: true },
	// A computed value: any number, whatever the type of what it reads. Each of these has a value between two
	// neighbours of that type, which one element of the grid gives.
	{ inputs: ['n + 0.5'], slots: ['n'], rows: ['..1', '2..'], exact: true },
	{ inputs: ['n + 0.5'], slots: ['n'], rows: ['1..2', '1.5', '3..'], exact: true },
	{ inputs: ['0.5 + n'], slots: ['n'], rows: ['..1', '2..'], exact: true },
	{ inputs: ['n - 0.5'], slots: ['n'], rows: ['..<2', '2', '3..'], exact: true },
	{ inputs: ['n / 2'], slots: ['n'], rows: ['..1', '2..'], exact: true },
	{ inputs: ['n * 0.5'], slots: ['n'], rows: ['..1', '1.5', '1..2', '2..'], exact: true },
	{ inputs: ['price + € 0.005'], slots: ['price'], rows: ['..€ 0.99', '€ 1.00..'], exact: true },
	{ inputs: ['price * 0.5'], slots: ['price'], rows: ['..€ 0.49', '€ 0.50..'], exact: true },
	{ inputs: ['when flag then n else n + 0.5'], slots: ['n', 'flag'], rows: ['..1', '2..'], exact: true },
	{ inputs: ['x + 0.5', 'n + x'], slots: ['x', 'n'], rows: ['..2 | -', '3.. | ..4', '- | 5..'], exact: true },
	{ inputs: ['ratio + n'], slots: ['ratio', 'n'], rows: ['..2', '2.5..'], exact: true },
	// Over these the proof names a value the arithmetic never gives: it refuses, and no element contradicts it.
	{ inputs: ['n * 2'], slots: ['n'], rows: ['..2', '3..'], exact: false },
	{ inputs: ['n + n'], slots: ['n'], rows: ['..2', '2.5', '3..'], exact: false },
	// "None found" over an open relation is unknown: both rows are undecided.
	{ inputs: ['tags.any(it = "a")'], slots: ['tags'], rows: ['true', 'false'], exact: true },
	{ inputs: ['tags.any(it = "a")', 'flag'], slots: ['tags', 'flag'], rows: ['true | -', '- | true', 'false | false'], exact: true }
];

test('the proofs are held to the evaluation: no overlap, no gap and `total` over every element of the grid', () => {
	let elements = 0;
	for (const spec of HELD) {
		const name = `| ${spec.inputs.join(' | ')} |: ${spec.rows.join(' / ')}`;
		const rowEnum = `enum Row = ${spec.rows.map((_r, i) => `r${i + 1}`).join(' | ')}\n`;
		const text = (derived: string, policy: string) =>
			`${spec.above ?? ''}${rowEnum}${tableOf('Thing', derived, policy, `| ${spec.inputs.join(' | ')} | -> v |`, ...spec.rows.map((cells, i) => `| ${cells} | r${i + 1} |`))}`;
		// One element for each combination of the values of the slots the inputs read.
		const combos = spec.slots.reduce<unknown[][]>((all, slot) => all.flatMap((c) => GRID[slot].map((v) => [...c, v])), [[]]);
		const data = load(lab, combos.map((c, i) => ({ $kind: 'Thing', $id: `e${String(i).padStart(3, '0')}`, ...Object.fromEntries(spec.slots.map((s, k) => [s, c[k]])) })));
		const inState = (i: number) => combos[i].some((v) => typeof v === 'object' && v !== null && !Array.isArray(v));
		elements += combos.length;

		// What the evaluation says, row by row: under `collect` each row gives its own member, known when the row
		// applies and with a state on its membership when the row is undecided.
		const twin = valid(text('derived v: Row*', 'collect'));
		const decided = [...tabulate(twin, data).data.kinds.get('Thing')!.values()].map((row) => {
			const members = row.get('v') as (V & { v: string; maybe?: object })[];
			return { applies: members.filter((m) => !m.maybe).map((m) => m.v), undecided: members.filter((m) => m.maybe).length };
		});
		// What the proofs say.
		const unique = declare(text('derived v: Row', 'unique'), lab);
		assert.deepEqual(unique.diagnostics.filter((d) => !['R031', 'W112'].includes(d.code)), [], name);
		const overlaps = unique.diagnostics.filter((d) => d.code === 'R031').map((d) => `r${d.args[1]} r${d.args[2]}`);
		const gap = unique.diagnostics.some((d) => d.code === 'W112');
		const total = declare(text('total derived v: Row', 'unique'), lab);

		// No overlap named: no element has two rows that apply. No gap named: every element whose inputs are known
		// values has a row. The other way round where the proof is exact: what it names, an element has.
		const seen = new Set<string>();
		let none = false;
		for (const [i, d] of decided.entries()) {
			for (const [k, later] of d.applies.entries()) for (const earlier of d.applies.slice(0, k)) seen.add(`${earlier} ${later}`);
			if (!inState(i) && !d.applies.length && !d.undecided) none = true;
		}
		for (const pair of seen) assert.ok(overlaps.includes(pair), `${name}: ${pair} both apply to an element and R031 does not name them`);
		assert.ok(gap || !none, `${name}: no row applies to an element and W112 names no gap`);
		if (spec.exact) {
			assert.deepEqual([...overlaps].sort(), [...seen].sort(), `${name}: R031 names rows that no element has both of`);
			assert.equal(gap, none, `${name}: W112 names a gap that no element is in`);
		}
		// The table as the check takes it: never `exception_conflict`, and `no_row_applies` only where W112 said so
		// or an input is in a state.
		if (!unique.diagnostics.some(isError)) {
			const values = [...tabulate(unique, data).data.kinds.get('Thing')!.values()].map((row) => show(row.get('v')!));
			for (const [i, v] of values.entries()) {
				assert.doesNotMatch(v, /exception_conflict/, `${name}: element ${i}`);
				if (!gap && !inState(i)) assert.doesNotMatch(v, /no_row_applies/, `${name}: element ${i}`);
			}
		}
		// `total` as the check takes it: a known value for every element, the ones in a state included.
		if (!total.diagnostics.some(isError)) {
			const values = [...tabulate(total, data).data.kinds.get('Thing')!.values()].map((row) => row.get('v') as V);
			for (const [i, v] of values.entries()) assert.equal(v.s, 'known', `${name}: element ${i} of a \`total\` value is ${show(v)}`);
		} else if (spec.exact && !overlaps.length) assert.ok(decided.some((d) => d.applies.length !== 1 || d.undecided), `${name}: R024, and every element has its one row`);
	}
	assert.deepEqual([HELD.length, elements], [38, 492]);
});

// ---- the value (tables.md §3) ----

test('the four states of an input, for each hit policy', () => {
	const unknown = 'unknown not_counted @ thing__x ["t-unknown"]';
	const invalid = 'invalid below_zero @ thing__x ["t-invalid"]';
	// `unique`: a known input has its one row; `n/a` passes no test, so no row applies; an unknown or invalid
	// input leaves every row undecided, and the value takes that state with its reason and its cause.
	assert.deepEqual(decide(tableOf('Thing', 'derived u: Level', 'unique', '| x | -> u |', '| ..<10 | low |', '| 10.. | high |'), things), {
		't-known': 'low',
		't-na': 'unknown no_row_applies @ thing__u ["t-na"]',
		't-unknown': unknown,
		't-invalid': invalid
	});
	// `first`: `-` takes any value in any state, so `n/a` reaches the last row; an undecided row before it,
	// with another output, leaves the value undecided.
	assert.deepEqual(decide(tableOf('Thing', 'derived f: Level', 'first', '| x | -> f |', '| 10.. | high |', '| - | rest |'), things), { 't-known': 'rest', 't-na': 'rest', 't-unknown': unknown, 't-invalid': invalid });
	// An undecided row before it with the same output cannot change the value; nor can one after it.
	assert.deepEqual(decide(tableOf('Thing', 'derived f: Level', 'first', '| x | -> f |', '| 10.. | rest |', '| - | rest |', '| ..<3 | high |'), things), { 't-known': 'rest', 't-na': 'rest', 't-unknown': 'rest', 't-invalid': 'rest' });
	// Without a row that applies: the state of the undecided rows, else `no_row_applies`.
	assert.deepEqual(decide(tableOf('Thing', 'derived f: Level', 'first', '| x | -> f |', '| 10.. | high |', '| ..<3 | low |'), things), {
		't-known': 'unknown no_row_applies @ thing__f ["t-known"]',
		't-na': 'unknown no_row_applies @ thing__f ["t-na"]',
		't-unknown': unknown,
		't-invalid': invalid
	});
	// `priority`: the enum's order is high, low, rest, whatever the order of the rows. An undecided row whose
	// output comes before the applying one leaves the value undecided; one whose output comes after does not.
	assert.deepEqual(decide(tableOf('Thing', 'derived p: Level', 'priority', '| x | -> p |', '| ..<3 | rest |', '| - | low |', '| 10.. | high |'), things), { 't-known': 'low', 't-na': 'low', 't-unknown': unknown, 't-invalid': invalid });
	assert.deepEqual(decide(tableOf('Thing', 'derived p: Level', 'priority', '| x | -> p |', '| 10.. | rest |', '| ..<10 | low |', '| - | high |'), things), { 't-known': 'high', 't-na': 'high', 't-unknown': 'high', 't-invalid': 'high' });
	assert.deepEqual(decide(tableOf('Thing', 'derived p: Level', 'priority', '| x | -> p |', '| ..<10 | rest |', '| 5 | low |'), things), {
		't-known': 'low',
		't-na': 'unknown no_row_applies @ thing__p ["t-na"]',
		't-unknown': unknown,
		't-invalid': invalid
	});
	// `collect`: every applying row gives a member, once; an output only undecided rows give is a member whose
	// membership is undecided; the members stand in the order of the rows. No row: the empty set, known.
	const collect = tableOf('Thing', 'derived c: Level*', 'collect', '| x | -> c |', '| ..<10 | low |', '| - | rest |', '| 10.. | low |', '| 10.. | high |', '| 5 | rest |');
	assert.deepEqual(decide(collect, things), {
		't-known': '[low, rest]',
		't-na': '[rest]',
		't-unknown': `[low ? ${unknown}, rest, high ? ${unknown}]`,
		't-invalid': `[low ? ${invalid}, rest, high ? ${invalid}]`
	});
	assert.deepEqual(decide(tableOf('Thing', 'derived c: Level*', 'collect', '| x | -> c |', '| 10.. | low |'), things), { 't-known': '[]', 't-na': '[]', 't-unknown': `[low ? ${unknown}]`, 't-invalid': `[low ? ${invalid}]` });
});

const tables = (yaml(read('../../docs/semantics/value-cases.yaml')) as { tables: { order: string[]; and: Record<string, string[]>; or: Record<string, string[]> } }).tables;

test('a row is the `and` of its cells and a cell the `or` of its tests: the tables of S1, cell for cell', () => {
	// One element for each pair of the five values of a condition; `a = true` then has the value of `a`.
	const VALUE: Record<string, unknown> = { T: true, F: false, N: { $na: '' }, U: { $unknown: 'u' }, I: { $invalid: 'i' } };
	const data = load(
		lab,
		tables.order.flatMap((a) => tables.order.map((b) => ({ $kind: 'Thing', $id: `${a}${b}`, a: VALUE[a], b: VALUE[b] })))
	);
	// What a row in each state gives: under `collect` a member, none, or a member whose membership has the
	// state; under `unique` its output, `no_row_applies`, or the state.
	const member: Record<string, RegExp> = { T: /^\[high\]$/, F: /^\[\]$/, N: /^\[\]$/, U: /^\[high \? unknown u @ thing__[ab] \[".."\]\]$/, I: /^\[high \? invalid i @ thing__[ab] \[".."\]\]$/ };
	const value: Record<string, RegExp> = { T: /^high$/, F: /^unknown no_row_applies @ thing__one /, N: /^unknown no_row_applies @ thing__one /, U: /^unknown u @ thing__[ab] /, I: /^invalid i @ thing__[ab] / };
	const hit = decide(tableOf('Thing', 'derived hit: Level*', 'collect', '| a | b | -> hit |', '| true | true | high |'), data);
	const one = decide(tableOf('Thing', 'derived one: Level', 'unique', '| a | b | -> one |', '| true | true | high |'), data);
	// A cell of two tests over `a`: `a = true or a = false`.
	const alt = decide(tableOf('Thing', 'derived alt: Level*', 'collect', '| a | -> alt |', '| true, false | high |'), data);
	const NOT: Record<string, string> = { T: 'F', F: 'T', N: 'N', U: 'U', I: 'I' };
	for (const a of tables.order)
		for (const [j, b] of tables.order.entries()) {
			assert.match(hit[`${a}${b}`], member[tables.and[a][j]], `${a} and ${b}, collect`);
			assert.match(one[`${a}${b}`], value[tables.and[a][j]], `${a} and ${b}, unique`);
			assert.match(alt[`${a}${b}`], member[tables.or[a][tables.order.indexOf(NOT[a])]], `${a} or not ${a}`);
		}
	assert.equal(Object.keys(hit).length, 25);
});

test('two rows with one output under `collect`: an applying row decides, and undecided rows share one membership', () => {
	const data = load(lab, [
		{ $kind: 'Thing', $id: 'both', a: { $unknown: 'u' }, b: { $invalid: 'i' } },
		{ $kind: 'Thing', $id: 'one', a: true, b: { $invalid: 'i' } },
		{ $kind: 'Thing', $id: 'reasons', a: { $unknown: 'z' }, b: { $unknown: 'k' } }
	]);
	const text = tableOf('Thing', 'derived c: Level*', 'collect', '| a | b | -> c |', '| true | - | low |', '| - | true | low |');
	assert.deepEqual(decide(text, data), {
		// The highest state among the rows (A.4), and of two reasons the least.
		both: '[low ? invalid i @ thing__b ["both"]]',
		one: '[low]',
		reasons: '[low ? unknown k @ thing__b ["reasons"]]'
	});
});

test('the witness names the rows that gave the value and the facts their tests read', () => {
	const text = `enum Tier = gold | silver | bronze\n${tableOf('Host', 'derived tier: Tier', 'priority', '| memory_need | owner | -> tier |', '| 500 GiB.. | - | gold |', '| 300 GiB.. | - | silver |', '| - | team-platform | bronze |')}`;
	const { why } = tabulate(valid(text, fixture), appendixB);
	const memory = (id: string) => ({ relation: 'host__memory_need', key: [id] });
	assert.deepEqual([...why.keys()], ['host__tier']);
	assert.deepEqual(Object.fromEntries(why.get('host__tier')!), {
		// The row whose output it is, and what its tests read: `-` reads nothing.
		'host-a': [{ row: 2, facts: [memory('host-a')] }],
		// No row applies: no row to name.
		'host-b': [],
		'host-c': [{ row: 1, facts: [memory('host-c')] }],
		// A state taken from undecided rows: those rows.
		'host-d': [
			{ row: 1, facts: [memory('host-d')] },
			{ row: 2, facts: [memory('host-d')] }
		]
	});
	// `collect`: every row that gives a member, in the order written; each fact once, by relation and key.
	const flags = `enum Flag = big | owned\n${tableOf('Host', 'derived flags: Flag*', 'collect', '| memory_need | owner | memory_need + host_reserve | -> flags |', '| 300 GiB.. | - | - | big |', '| - | team-platform | - | owned |', '| 300 GiB.. | team-platform | 300 GiB.. | big |')}`;
	const reserve = load(fixture, (JSON.parse(read('appendix-b.json')) as { rows: Record<string, unknown>[] }).rows, { params: { host_reserve: '16 GiB' } });
	const collected = tabulate(valid(flags, fixture), reserve);
	assert.deepEqual(collected.why.get('host__flags')!.get('host-c'), [
		{ row: 1, facts: [memory('host-c')] },
		{ row: 2, facts: [{ relation: 'host__owner', key: ['host-c'] }] },
		{ row: 3, facts: [memory('host-c'), { relation: 'host__owner', key: ['host-c'] }, { relation: 'param', key: ['host_reserve'] }] }
	]);
	assert.deepEqual(collected.why.get('host__flags')!.get('host-b'), []);
	assert.equal(show(collected.data.kinds.get('Host')!.get('host-a')!.get('flags')!), '[big, owned ? unknown not_assigned @ host__owner ["host-a"]]');
	assert.deepEqual(collected.why.get('host__flags')!.get('host-a')!.map((w) => w.row), [1, 2]);
});

test('a table reads the tables above it; the rows handed in are not changed; the same input gives the same bytes', () => {
	const text = `${tableOf('Thing', 'derived u: Level', 'unique', '| x | -> u |', '| ..<10 | low |', '| 10.. | high |')}${tableOf('Thing', 'derived again: Level*', 'collect', '| u | x | -> again |', '| low | - | rest |', '| - | 5 | high |')}`;
	const d = valid(text);
	assert.deepEqual(d.tables.map((t) => `${t.kind}.${t.slot} ${t.policy}`), ['Thing.u unique', 'Thing.again collect']);
	assert.deepEqual(decide(text, things), {
		't-known': '[rest, high]',
		// `u` is `unknown no_row_applies` there, and that is the state the membership takes.
		't-na': '[rest ? unknown no_row_applies @ thing__u ["t-na"]]',
		't-unknown': '[rest ? unknown not_counted @ thing__x ["t-unknown"], high ? unknown not_counted @ thing__x ["t-unknown"]]',
		't-invalid': '[rest ? invalid below_zero @ thing__x ["t-invalid"], high ? invalid below_zero @ thing__x ["t-invalid"]]'
	});
	const bytes = (t: ReturnType<typeof tabulate>) =>
		canonicalJson({ cells: [...t.data.kinds.get('Thing')!].map(([id, row]) => [id, show(row.get('u')!), show(row.get('again')!)]), why: [...t.why].map(([relation, rows]) => [relation, [...rows].map(([id, w]) => [id, w.map((r) => [String(r.row), r.facts])])]) });
	assert.equal(bytes(tabulate(d, things)), bytes(tabulate(declare(text, lab), things)));
	assert.equal(things.kinds.get('Thing')!.get('t-known')!.has('u'), false);
	// Where only some slots were loaded, the slots the tables fill are loaded too.
	const partly: Data = { ...things, only: new Map([['Thing', new Set(['x'])]]) };
	assert.deepEqual([...tabulate(d, partly).data.only!.get('Thing')!], ['x', 'u', 'again']);
});

test('the budget of steps: a table that costs more gets no value, and the count follows from the input alone', () => {
	const d = valid(`${tableOf('Thing', 'derived u: Level', 'unique', '| x | -> u |', '| ..<10 | low |', '| 10.. | high |')}${tableOf('Thing', 'derived f: Level', 'first', '| u | -> f |', '| low | high |', '| - | rest |')}`);
	const needs = (data: Data): number => {
		for (let steps = 1; steps < 500; steps++) {
			try {
				tabulate(d, data, { steps });
				return steps;
			} catch (e) {
				assert.ok(e instanceof OverBudget, String(e));
				assert.equal(e.limit, steps);
			}
		}
		return assert.fail('the tables take more than 500 steps');
	};
	const steps = needs(things);
	assert.equal(needs(things), steps);
	// Both tables count against the one budget: the second alone would fit in what the first leaves over.
	assert.ok(steps > 40, String(steps));
	assert.throws(() => tabulate(d, things, { steps: steps - 1 }), OverBudget);
	assert.deepEqual(tabulate(d, things, { steps }).data, tabulate(d, things).data);
});

test('a question over the declared schema reads the derived value as any other slot', async () => {
	const text = `enum Size = small | medium | large\n${tableOf('Host', 'derived size: Size', 'unique', '| memory_need | -> size |', '| ..<300 GiB | small |', '| 300 GiB..<500 GiB | medium |', '| 500 GiB.. | large |')}`;
	const d = valid(text, fixture);
	assert.deepEqual(d.diagnostics, []);
	const schema = d.schema!;
	// `memory_need` can be unknown or invalid: so can `size`.
	assert.deepEqual(schema.kinds.Host.slots.size, { type: 'Size', card: '1', states: ['known', 'unknown', 'invalid'], derived: true });
	const checked = check('ask Host where memory_need is known or owner is n/a show size', schema);
	assert.deepEqual(checked.diagnostics.map((x) => `${x.code} ${x.span.text}`), ['W105 size']);
	const a = (await answer(checked, schema, tabulate(d, appendixB).data))!;
	assert.deepEqual(a.rows.map((r) => [r.$id, r.c1]), [['host-a', 'medium'], ['host-b', 'small'], ['host-c', 'large'], ['host-d', { $unknown: 'no_spec' }]]);
	const doc = (await outputSchema(checked.tree as never, checked, schema))!;
	assert.deepEqual(doc.kinds.Answer.slots.c1, { type: 'p.Size', card: '1', states: ['known', 'unknown', 'invalid'], expr: 'size' });
	// Without the table's values the slot is read as any missing value: the question still never guesses.
	const bare = (await answer(check('ask Host where size = medium', schema), schema, appendixB))!;
	assert.deepEqual([bare.rows.length, bare.undecided.map((u) => `${u.$id} ${u.state} ${u.reason}`)], [0, ['host-a unknown ', 'host-b unknown ', 'host-c unknown ', 'host-d unknown ']]);
});
