// The check of declarations against a schema, as far as it is built: an enum, and a derived value by a decision
// table (docs/rezono/tables.md §2 and §4). `declare` reads declarations that stand on top of a schema, types
// each table and proves what the text says the compiler proves, and gives the schema with the enums and the
// derived values in it, so that a question is checked against it as against any other. The value of a table
// is evaluate.ts (`tabulate`).
//
// The diagnostics, beside those of the reader (module.ts) and of names and types (check.ts):
//   R000  a declaration this check does not take yet: anything but an `enum` and an `extend` whose derived
//         values have a table; and a name that is declared already
//   R001  a kind, a type or a value of an enum that is not there
//   R003  a test whose value does not go with its input; a range over a type without an order (a number and
//         a date have one); `table priority` whose output is not an enum; an output that is not of the type,
//         or that is of its dimension and no value of it (`1.5` for an integer, `€ 1.005` at scale 2)
//   R005  an input that is a set; `collect` on anything but `T*`, another policy on a set
//   R012  a date in a test or an output that is no day of the calendar; a number that has no value (`1/0`)
//   R031  two rows of a `unique` table that one input passes, at the cell of the later row in the first column
//         where both test, with an example
//   W112  rows that leave a gap, at `table <policy>`, with an example; R024 instead when the value is `total`,
//         and R024 at each input of a `total` value that can be `n/a`, unknown or invalid
//
// The proofs read no row (tables.md §4). The values of each column split into pieces: the values of a Bool or
// a closed enum; for a number or a date each end of a range, each value tested and the intervals between them;
// for any other type each value tested and "any other". A row takes a piece when its cell is `-` or one of its
// tests passes every value of it. Two rows overlap when in every column some piece is taken by both; a
// combination of pieces that no row takes is a gap.
//
// A proof uses of an input only what holds for every row: the type of a value that is stored, and the states
// its typing lists. A type that holds whole numbers of a step (an integer, a quantity in its storage unit, money
// at its scale, a date in days) has no value between two neighbours, so `..17` and `18..` leave no gap there.
// That is used for a path only: a slot or a parameter, which the publication holds to its type (§3.2), and a derived
// value above, whose outputs R003 holds to it. Anything computed is any number of its dimension, whatever name
// its type has: `n + 0.5` is no whole number. So the proofs are exact over stored values; over a computed one
// they may name an overlap or a gap that the arithmetic never gives, and never miss one.
import { isError, near, typing, type Head, type Typed } from './check.ts';
import { amount, factor, reader, utcInstant, type Frac } from './evaluate.ts';
import { parseDeclarations, type Decl, type DerivedDecl, type Table, type TableTest, type TableValue } from './module.ts';
import { inOrder, type Diagnostic, type Span } from './parse.ts';
import { printExpr } from './print.ts';
import { baseTypeOf, isOrdered, knownType, slotType, STATES, type Schema, type SlotDef, type StateName, type Ty } from './schema.ts';
import type { Expr } from './tree.ts';

/** A decision table as evaluation reads it. */
export interface DecisionTable {
	kind: string;
	slot: string;
	policy: Table['table'];
	/** The rows in the order written: the condition of each cell that tests (Appendix A), and the output. */
	rows: { when: Expr[]; value: TableValue }[];
	/** For `priority`: the values of the output enum, in its order. */
	order?: string[];
}
export interface Declared {
	/** Absent when a parse-level check failed. */
	decls?: Decl[];
	/** The schema with what the text declares in it; absent when the text has an error. */
	schema?: Schema;
	/** Every diagnostic, the reader's own included, in source order. */
	diagnostics: Diagnostic[];
	/** The tables in the order of the text; none when the text has an error. */
	tables: DecisionTable[];
	/** The types and the heads of the expressions of the tables, by their node: evaluation reads them. */
	typed: Map<object, Typed>;
	heads: Map<object, Head>;
}

/** One piece of the values of a column: how an example names it (absent: any value), and whether a test passes all of it. */
interface Piece {
	show?: string;
	has(test: TableTest): boolean;
}

const defined = <T>(x: T | undefined): x is T => x !== undefined;
const compare = (a: Frac, b: Frac): number => {
	const by = a.n * b.d - b.n * a.d;
	return by < 0n ? -1 : by > 0n ? 1 : 0;
};
/** The whole number at or below `a / b`, for `b` above zero. */
const floorOf = (a: Frac, b: Frac): bigint => {
	const [n, d] = [a.n * b.d, a.d * b.n];
	return n >= 0n ? n / d : -((-n + d - 1n) / d);
};
/** A date as the number of its day, or undefined when it is no day of the calendar. */
function dayOf(date: string): Frac | undefined {
	const [y, m, d] = date.split('-').map(Number);
	const at = new Date(Date.UTC(y, m - 1, d));
	at.setUTCFullYear(y);
	return at.getUTCMonth() === m - 1 && at.getUTCDate() === d ? { n: BigInt(at.getTime() / 86400000), d: 1n } : undefined;
}
/** A DateTime as its UTC nanosecond instant, or undefined when it is not a valid calendar date-time. */
function instantOf(dateTime: string): Frac | undefined {
	const ns = utcInstant(dateTime);
	return ns === undefined ? undefined : { n: ns, d: 1n };
}

/** Checks declarations that stand on top of a schema. The schema handed in is not changed. */
export function declare(text: string, schema: Schema): Declared {
	const parsed = parseDeclarations(text);
	const { decls, spans } = parsed;
	if (!decls) return { diagnostics: parsed.diagnostics, tables: [], typed: new Map(), heads: new Map() };
	const next = structuredClone(schema);
	const t = typing(text, next, spans);
	const { typed, heads, found, spanOf } = t;
	const tables: DecisionTable[] = [];
	const points = [...text];
	const refuse = (node: object, expected: string): void => void found.push({ code: 'R000', span: spanOf(node), args: [expected] });
	// The literals of a table have a value without any row: the proofs compare them as evaluation does.
	const literals = reader({ typed, heads }, next, { kinds: new Map(), rules: new Map(), params: new Map() });
	const valueOf = (v: TableValue) => (literals.ex(v) as { v: boolean | Frac | string | { id: string } }).v;

	/** The place of a derived value's type: the first word of it after the name. */
	function typeAt(d: DerivedDecl): Span {
		const word = /^[A-Za-z0-9]+/.exec(d.type)![0];
		const from = spanOf(d).end;
		const at = points.slice(from).join('').indexOf(word);
		if (at < 0) return spanOf(d);
		const start = from + [...points.slice(from).join('').slice(0, at)].length;
		return { text: word, start, end: start + [...word].length };
	}

	/**
	 * A literal that reads as its type and has no value: a date/instant that is no day of the calendar,
	 * or a number that divides by zero (`1/0`). R012.
	 */
	function valueless(ty: Ty, v: TableValue): boolean {
		const base = ty.t === 'val' ? baseTypeOf(next, ty.name) : undefined;
		const none = base === 'Date' ? !dayOf(v.lit) : base === 'DateTime' ? !instantOf(v.lit) : ty.t === 'num' && !amount(next, v.lit);
		if (none) t.report('R012', spanOf(v), [v.lit, t.describe(ty)]);
		return none;
	}

	/** The condition of one test over its input (tables.md §3), typed; undefined when it has an error. */
	function condition(input: Expr, a: Typed, test: TableTest): Expr | undefined {
		const span = spanOf(test);
		const placed = <T extends object>(node: T): T => (spans.set(node, span), node);
		let good = true;
		for (const v of 'lit' in test ? [test] : [test.between.from, test.between.to].filter(defined)) {
			const b = t.ex(v);
			if (!t.meet(a, input, b, v)) t.report('R003', span, [t.describe(a.ty), t.describe(b.ty)]);
			else if (b.ty.t !== 'err' && !valueless(b.ty, v)) continue;
			good = false;
		}
		if (!('lit' in test) && good && !isOrdered(next, a.ty)) {
			t.report('R003', span, [t.describe(a.ty), test.between.op]);
			good = false;
		}
		if (!good) return undefined;
		if ('lit' in test) return placed({ cmp: ['=', input, test] });
		const { from, op, to } = test.between;
		if (from && to) return placed({ in: [input, placed({ range: [from, op, to] })] });
		return placed(from ? { cmp: ['>=', input, from] } : { cmp: [op === '..' ? '<=' : '<', input, to!] });
	}

	/**
	 * The distance between two neighbouring values of a type: a day for a date, the step of a type of whole
	 * numbers; undefined when any number is a value of it. It says what the type holds, not what an expression
	 * of that type gives: `stepAt` decides where it may be used.
	 */
	function stepOf(ty: Ty): Frac | undefined {
		if (ty.t === 'val' && baseTypeOf(next, ty.name) === 'Date') return { n: 1n, d: 1n };
		if (ty.t !== 'num' || ty.name === undefined) return undefined;
		const def = next.types?.[ty.name];
		const scale = 10n ** BigInt(def?.scale ?? '0');
		const of = def?.of ?? ty.name;
		if (of === 'Integer') return { n: 1n, d: 1n };
		if (of === 'Quantity') return { n: 1n, d: scale };
		if (of !== 'Money') return undefined;
		const per = def!.per === undefined ? { n: 1n, d: 1n } : factor(next, def!.per);
		return { n: per.d, d: scale * per.n };
	}
	/** Whether a number is a whole number of a step; any number is one of no step. */
	const onStep = (k: Frac, step: Frac | undefined): boolean => !step || (k.n * step.d) % (k.d * step.n) === 0n;
	/**
	 * The step an input is held to. A path gives a value as it is stored: a slot or a parameter, which Rezono
	 * Data holds to its type (§3.2), or a derived value above, whose outputs `derived` holds to it. Every other
	 * expression computes, and the type it is named after does not hold its value: `n + 0.5` has the type of `n`.
	 */
	const stepAt = (input: Expr, a: Typed): Frac | undefined => ('path' in input ? stepOf(a.ty) : undefined);
	/**
	 * Whether an input can be in a state: one its typing lists, and unknown when it reads the missing rows of an
	 * open relation. "None found" is unknown there (`any`, `in`, a rule; expressions.md §6), and the typing
	 * keeps that as `opens`, not as a state.
	 */
	const may = (a: Typed, state: StateName): boolean => a.states.has(state) || (state === 'unknown' && a.opens.length > 0);

	/** The pieces of one column, in a fixed order (tables.md §4). */
	function pieces(input: Expr, a: Typed, cells: ('-' | TableTest[])[]): Piece[] {
		const tests = cells.flatMap((c) => (c === '-' ? [] : c));
		// A column nobody tests is one piece: any value.
		if (!tests.length) return [{ has: () => false }];
		const name = 'path' in input ? printExpr(input) : `(${printExpr(input)})`;
		const values = tests.flatMap((x) => ('lit' in x ? [x] : [x.between.from, x.between.to].filter(defined)));
		if (isOrdered(next, a.ty)) {
			const base = a.ty.t === 'val' ? baseTypeOf(next, a.ty.name) : undefined;
			const key = (v: TableValue): Frac => (base === 'Date' ? dayOf(v.lit)! : base === 'DateTime' ? instantOf(v.lit)! : (valueOf(v) as Frac));
			const ends = values
				.map((v) => ({ k: key(v), text: v.lit }))
				.sort((x, y) => compare(x.k, y.k))
				.filter((e, i, all) => i === 0 || compare(all[i - 1].k, e.k) !== 0);
			const step = stepAt(input, a);
			const whole = (k: Frac): boolean => onStep(k, step);
			/** Whether a value the input can have lies strictly between two ends. */
			const room = (lo: Frac, hi: Frac): boolean => !step || compare({ n: floorOf(lo, step) + 1n, d: 1n }, { n: hi.n * step.d, d: hi.d * step.n }) < 0;
			const out: Piece[] = [];
			for (let i = 0; i <= ends.length; i++) {
				const [lo, hi] = [ends[i - 1], ends[i]];
				if (!lo || !hi || room(lo.k, hi.k))
					out.push({
						show: [...(lo ? [`${name} > ${lo.text}`] : []), ...(hi ? [`${name} < ${hi.text}`] : [])].join(' and '),
						has: (x) => !('lit' in x) && (!x.between.from || (lo !== undefined && compare(key(x.between.from), lo.k) <= 0)) && (!x.between.to || (hi !== undefined && compare(hi.k, key(x.between.to)) <= 0))
					});
				if (hi && whole(hi.k))
					out.push({
						show: `${name} = ${hi.text}`,
						has: (x) => {
							if ('lit' in x) return compare(key(x), hi.k) === 0;
							const { from, op, to } = x.between;
							return (!from || compare(key(from), hi.k) <= 0) && (!to || compare(hi.k, key(to)) < (op === '..' ? 1 : 0));
						}
					});
			}
			return out;
		}
		const key = (v: TableValue): string => {
			const k = valueOf(v);
			return typeof k === 'object' && 'id' in k ? k.id : String(k);
		};
		const listed = values.map((v) => ({ k: key(v), text: v.lit })).filter((e, i, all) => all.findIndex((o) => o.k === e.k) === i);
		// A Bool and a closed enum have the values they have; any other type may hold a value nobody tests.
		const def = a.ty.t === 'val' ? next.types?.[a.ty.name] : undefined;
		const members = def?.of === 'Enum' ? next.enums?.[def.enum ?? (a.ty as { name: string }).name] : undefined;
		const all = a.ty.t === 'bool' ? ['false', 'true'] : Array.isArray(members) ? members : undefined;
		const out: Piece[] = (all?.map((k) => ({ k, text: k })) ?? listed).map(({ k, text }) => ({ show: `${name} = ${text}`, has: (x) => 'lit' in x && key(x) === k }));
		if (!all) out.push({ show: listed.map((e) => `${name} != ${e.text}`).join(' and '), has: () => false });
		return out;
	}

	function derived(kind: string, d: DerivedDecl): void {
		const table = d.table;
		// `=`, `unless` and versions are read (module.ts) and not checked yet.
		if (!table) return refuse(d, 'a derived value with a decision table');
		const slots = next.kinds[kind].slots;
		if (slots[d.derived]) return refuse(d, `a name that \`${kind}\` does not have yet`);
		const slot: SlotDef = { ...(next.kinds[d.type] ? { ref: d.type } : { type: d.type }), card: d.card ?? '1', states: ['known', 'unknown'], derived: true };
		const before = found.length;
		if (!knownType(next, d.type)) {
			found.push({ code: 'R001', span: typeAt(d), args: [d.type], suggest: near(d.type, [...Object.keys(next.types ?? {}), ...Object.keys(next.kinds)]) });
			slots[d.derived] = slot;
			return;
		}
		const at = spanOf(table);
		const out = slotType(next, slot);
		// `collect` gives a set, which may be empty; every other policy one value (tables.md §2).
		if (table.table === 'collect' ? d.card !== '*' : d.card === '*' || d.card === '+') t.report('R005', at, []);
		const order = out.t === 'val' ? t.enumValues(out.name) : undefined;
		if (table.table === 'priority' && !order) t.report('R003', at, [`table ${table.table}`, d.type]);
		const want = t.value(out);
		const inputs: (Typed | undefined)[] = [];
		const rows = t.element(kind, () => {
			for (const e of table.inputs) {
				const a = t.settled(e);
				if (a.set && a.ty.t !== 'err') t.report('R005', spanOf(e), []);
				inputs.push(a.set || a.ty.t === 'err' ? undefined : a);
			}
			return table.rows.map((row) => {
				const when: Expr[] = [];
				row.tests.forEach((cell, j) => {
					const a = inputs[j];
					if (cell === '-' || !a) return;
					// The tests of a cell are alternatives: `t1 or t2`.
					const conds = cell.map((test) => condition(table.inputs[j], a, test)).filter(defined);
					if (conds.length) when.push(conds.length === 1 ? conds[0] : { or: conds });
				});
				const v = t.ex(row.value);
				if (!t.meet(v, row.value, want, row.value)) t.report('R003', spanOf(row.value), [t.describe(v.ty), t.describe(out)]);
				// A value of the type, not only of its dimension: a table below reads this slot by its type.
				else if (v.ty.t !== 'err' && !valueless(v.ty, row.value) && v.ty.t === 'num' && !onStep(valueOf(row.value) as Frac, stepOf(out))) t.report('R003', spanOf(row.value), [row.value.lit, t.describe(out)]);
				return { when, value: row.value };
			});
		});
		// The name is there for what follows it, whatever was found, and not for the table itself: a table reads
		// the schema handed in and what stands above it, so no table reads its own value.
		slots[d.derived] = slot;
		if (found.length > before) return;

		// ---- the proofs (tables.md §4) ----
		const columns = table.inputs.map((e, j) => pieces(e, inputs[j]!, table.rows.map((row) => row.tests[j])));
		const takes = (cell: '-' | TableTest[], piece: Piece): boolean => cell === '-' || cell.some((x) => piece.has(x));
		const example = (shows: (string | undefined)[]): string => shows.filter(defined).join(' and ') || 'true';
		if (table.table === 'unique')
			table.rows.forEach((later, j) => {
				for (const [i, earlier] of table.rows.slice(0, j).entries()) {
					const shared = columns.map((ps, c) => ps.filter((p) => takes(earlier.tests[c], p) && takes(later.tests[c], p)));
					// Disjoint: a column in which no value passes both.
					if (shared.some((ps) => !ps.length)) continue;
					const both = columns.findIndex((_ps, c) => earlier.tests[c] !== '-' && later.tests[c] !== '-');
					const shows = shared.map((ps, c) => (earlier.tests[c] === '-' && later.tests[c] === '-' ? undefined : ps[0].show));
					found.push({ code: 'R031', span: spanOf(both < 0 ? later : later.tests[both]), args: [d.derived, String(i + 1), String(j + 1), example(shows)] });
				}
			});
		// A gap: the first combination of pieces, column by column, that no row takes.
		const full = new Set<string>();
		const gap = (c: number, alive: number[]): string[] | undefined => {
			if (!alive.length) return [];
			const key = `${c}:${alive.join()}`;
			if (c === columns.length || full.has(key)) return undefined;
			for (const piece of columns[c]) {
				const rest = gap(c + 1, alive.filter((r) => takes(table.rows[r].tests[c], piece)));
				if (rest) return [...(piece.show ? [piece.show] : []), ...rest];
			}
			full.add(key);
			return undefined;
		};
		const open = table.table === 'collect' ? undefined : gap(0, table.rows.map((_row, r) => r));
		const tested = (j: number): boolean => table.rows.some((row) => row.tests[j] !== '-');
		const can = (state: StateName): boolean => inputs.some((a, j) => tested(j) && may(a!, state));
		if (open) found.push(d.totality ? { code: 'R024', span: at, args: [d.derived, example(open)] } : { code: 'W112', span: at, args: [table.table, d.derived, example(open)] });
		// `total` promises a known value (v0 §5d): no gap, and no input that leaves a row undecided or out.
		if (d.totality)
			table.inputs.forEach((e, j) => {
				const states = (['not_applicable', 'unknown', 'invalid'] as const).filter((s) => tested(j) && may(inputs[j]!, s));
				const name = 'path' in e ? printExpr(e) : `(${printExpr(e)})`;
				if (states.length) found.push({ code: 'R024', span: spanOf(e), args: [d.derived, states.map((s) => `${name} is ${s === 'not_applicable' ? 'n/a' : s}`).join(' or ')] });
			});
		// The states of the value (tables.md §3). A row over an input that is `n/a` does not apply, so no row may;
		// one over an unknown or invalid input is undecided, and the value, or a membership, takes that state.
		const unknown = can('unknown') || (table.table !== 'collect' && (open !== undefined || can('not_applicable')));
		slot.states = STATES.filter((s) => s === 'known' || (s === 'unknown' && unknown) || (s === 'invalid' && can('invalid')));
		if (!found.slice(before).some(isError)) tables.push({ kind, slot: d.derived, policy: table.table, rows, ...(table.table === 'priority' ? { order } : {}) });
	}

	for (const decl of decls) {
		if ('enum' in decl) {
			if (knownType(next, decl.enum)) refuse(decl, 'a type name that is not declared yet');
			else {
				(next.types ??= {})[decl.enum] = { of: 'Enum' };
				(next.enums ??= {})[decl.enum] = decl.world === 'open' ? { world: 'open', values: decl.values } : decl.values;
			}
		} else if ('extend' in decl) {
			if (!next.kinds[decl.extend]) found.push({ code: 'R001', span: spanOf(decl), args: [decl.extend], suggest: near(decl.extend, Object.keys(next.kinds)) });
			else for (const d of decl.derived) derived(decl.extend, d);
		} else refuse(decl, 'an `enum`, or an `extend` whose derived values have a decision table');
	}
	const diagnostics = [...parsed.diagnostics, ...found].sort(inOrder);
	const valid = !diagnostics.some(isError);
	return { decls, ...(valid ? { schema: next } : {}), diagnostics, tables: valid ? tables : [], typed, heads };
}
