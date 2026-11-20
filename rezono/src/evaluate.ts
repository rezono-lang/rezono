// The answer of a checked question over the rows a role reads (docs/rezono/expressions.md §7, §7a, §8a and
// Appendix A, which is normative).
//
// The rows are the publication (docs/publication/l0.md §3): the role's own form of a publication, so a row the
// role does not read is not there, and what is missing is read by the slot's cardinality and world, and by
// whether the role reads the slot's relation in full (§7a rule 1). Nothing outside those rows is read, so two
// publications whose role views are equal give the same bytes (§7a rule 5).
//
// Every expression has one of four states: known with a value, or `n/a`, unknown or invalid with a reason and
// the row that caused it. Strict operators take the highest state of their operands (A.3); `and`, `or`, `not`,
// `=>` and `when` follow A.1 and A.2; `is` is always true or false (A.3b); of several operands in the deciding
// state the least reason wins, then the cause that sorts first (A.4). At the top of an `ask` a true condition
// gives a row, false leaves it out, `n/a` leaves it out and counts it, unknown and invalid give an undecided
// row (A.5).
//
// Numbers are exact: a fraction of two integers in the storage unit of its dimension, so `0.5 TiB = 512 GiB`
// holds and nothing is rounded but by `round`. No floating point, no clock, no randomness; rows come in the
// canonical order of their key.
//
// Evaluation counts its steps: one for each expression it evaluates on each row, for each slot it reads, for
// each member a read gives (a hop over a set, an inverse slot), and for each member of a set it counts or
// searches. So the work of an evaluation is bounded by its steps, whatever the fan-out of the rows. With a limit it stops when the count passes it
// (`OverBudget`), so a question is never answered in part. The count follows from the question and the rows
// handed in, and from nothing else. Where only some kinds and slots were loaded, a read of another is refused
// (`NotLoaded`): absence there would be read as a fact.
import { canonicalJson } from '../../viewer/src/lib/canon.ts';
import { outputSchema, schemaId, type AnswerSchema } from './answer-schema.ts';
import { isError, type Checked } from './check.ts';
import { inPart, NOT_READ_IN_FULL, sameDim, slotType, snake, typeOf, type Schema, type SlotDef, type Ty, type TypeDef } from './schema.ts';
import type { Declared } from './table.ts';
import { isAsk, isCheck, type Expr } from './tree.ts';

/** A question that passed the check and still cannot be answered: what it uses has no evaluation yet. */
export class NotEvaluated extends Error {}
/** The evaluation passed its step limit: the question costs more than it may, and gets no answer. */
export class OverBudget extends Error {
	limit: number;
	constructor(limit: number) {
		super(`the evaluation takes more than ${limit} steps`);
		this.limit = limit;
	}
}
/** A kind or a slot is read that was not loaded: a defect of whoever loaded the rows, never an answer. */
export class NotLoaded extends Error {}

/** A row of a relation: the relation and the key of the row (contracts/proof.yaml, RowRef). */
export interface RowRef {
	relation: string;
	key: string[];
}
/** An exact number: `n/d` in lowest terms, `d` above zero. */
export interface Frac {
	n: bigint;
	d: bigint;
}
export interface Ref {
	id: string;
}
interface Bounds {
	lo: V;
	hi: V;
	/** `..<`: the upper bound is outside. */
	open: boolean;
}
type Held = 'not_applicable' | 'unknown' | 'invalid';
interface Stated {
	s: Held;
	reason: string;
	cause?: RowRef;
}
/** A known value: a truth value, a number, a text (also a date), an element, a range, or a set of members. */
type Known = boolean | Frac | string | Ref | Bounds | Member[];
/** The value of an expression: known, or in a state with its reason and cause (A.4). */
export type V = { s: 'known'; v: Known } | Stated;
/**
 * A member of a set. `maybe` is the state that leaves its membership undecided: of a filter's condition, or of
 * the forward value of an inverse slot (§7, "Sets").
 */
type Member = V & { maybe?: Stated };
/** Why "no member found" over an open relation, and a value of an element nobody listed, are unknown (§7). */
const OPEN_WORLD = 'open_world';
/**
 * Why a call of a partial rule is unknown when no row holds its key: the rule declares `outcome` and a state
 * beyond `known`, and neither an outcome row nor a success row has the key. That holds whether or not any
 * outcome row of the rule was loaded.
 */
const NO_OUTCOME = 'no_outcome';
/** Why a shown amount that no decimal of its type holds is unknown (§8a). */
const NOT_EXACT = 'not_exact';
/** What a row gives for a slot: one value, or the members of a many-valued slot (a state stands for the whole set). */
export type Cell = V | V[];

/** The checked outcome of one invocation of a rule: a truth value, or a state with its reason and cause. */
export interface Outcome {
	key: string[];
	state: 'known' | Held;
	value?: boolean;
	reason?: string;
	cause?: RowRef;
}

/** The rows a role reads, as evaluation reads them. */
export interface Data {
	/** Per kind, per element, the cell of each slot its row gives. */
	kinds: Map<string, Map<string, Map<string, Cell>>>;
	/** Per rule, the canonical JSON of each list of ids it holds for. */
	rules: Map<string, Set<string>>;
	/** Per rule that publishes one, the checked outcome of each invocation by the canonical JSON of its key. */
	outcomes: Map<string, Map<string, V>>;
	params: Map<string, V>;
	/** When not every kind and slot was loaded: the kinds that were, and of each its slots that were. A read of another is refused. */
	only?: Map<string, Set<string>>;
}

const RANK: Record<Held, number> = { not_applicable: 1, unknown: 2, invalid: 3 };
const T: V = { s: 'known', v: true };
const F: V = { s: 'known', v: false };
const known = (v: Known): V => ({ s: 'known', v });
const bool = (b: boolean): V => (b ? T : F);

// ---- exact numbers ----

const gcd = (a: bigint, b: bigint): bigint => {
	if (a < 0n) a = -a;
	while (b) [a, b] = [b, a % b];
	return a;
};
function frac(n: bigint, d = 1n): Frac {
	if (d < 0n) [n, d] = [-n, -d];
	const g = gcd(n, d) || 1n;
	return { n: n / g, d: d / g };
}
const times = (a: Frac, b: Frac): Frac => frac(a.n * b.n, a.d * b.d);
const over = (a: Frac, b: Frac): Frac => frac(a.n * b.d, a.d * b.n);
const plus = (a: Frac, b: Frac, sign = 1n): Frac => frac(a.n * b.d + sign * b.n * a.d, a.d * b.d);
const sign = (x: bigint): number => (x < 0n ? -1 : x > 0n ? 1 : 0);

/** `12`, `0.5`, `1/3`, `-2.50`: a number as it is written. */
function exact(text: string): Frac | undefined {
	const m = /^(-?)([0-9]+)(?:\.([0-9]+))?(?:\/([0-9]+))?$/.exec(text);
	if (!m) return undefined;
	const [, minus, whole, part = '', under = '1'] = m;
	if (BigInt(under) === 0n) return undefined;
	const f = frac(BigInt(whole + part), 10n ** BigInt(part.length) * BigInt(under));
	return minus ? frac(-f.n, f.d) : f;
}
/** The factor of a type as a number; one when it has none. A factor that is no number above zero is a defect of the schema. */
function factorOf(text: string | undefined): Frac {
	const f = exact(text ?? '1');
	if (!f || f.n <= 0n) throw new TypeError(`${JSON.stringify(text)} is not a factor of a type: a number above zero`);
	return f;
}
/** How many storage units one of a unit word is (`GiB`: 1073741824 `B`); a word without a factor counts once. */
export function factor(schema: Schema, word: string): Frac {
	const types = schema.types ?? {};
	const name = Object.keys(types).sort().find((n) => types[n].unit === word) ?? word;
	return factorOf(types[name]?.factor);
}
const NUM = String.raw`(-?[0-9][0-9.]*(?:\/[0-9]+)?)`;
const PERCENT = new RegExp(`^${NUM}[ \\t]*%$`);
const QUANTITY = new RegExp(`^${NUM}(?:[ \\t]+([A-Za-z]\\w*))?$`);
const MONEY = new RegExp(`^[^\\s0-9-]+[ \\t]*${NUM}(?:\\/([A-Za-z]\\w*))?$`, 'u');
/**
 * A number as text, in the storage unit of its dimension: a literal of a question or a value of Row JSON
 * (`384 GiB`, `0.5 TiB`, `€ 0.20/h`, `12 %`, `3`). Units convert exactly (§6).
 */
export function amount(schema: Schema, text: string): Frac | undefined {
	const t = text.trim();
	let m = PERCENT.exec(t);
	if (m) {
		// A percent whose number is none (`1/0 %`) has no value, as `1/0` has none.
		const f = exact(m[1]);
		return f && over(f, frac(100n));
	}
	m = QUANTITY.exec(t);
	if (m) {
		const f = exact(m[1]);
		return f && (m[2] === undefined ? f : times(f, factor(schema, m[2])));
	}
	m = MONEY.exec(t);
	if (!m) return undefined;
	const f = exact(m[1]);
	return f && (m[2] === undefined ? f : over(f, factor(schema, m[2])));
}
/** A number as a decimal with at least `scale` places; undefined when no decimal is exact (`1/3`). */
function decimal(f: Frac, scale = 0): string | undefined {
	let places = 0;
	let rest = f.d;
	for (const p of [2n, 5n]) {
		let k = 0;
		while (rest % p === 0n) [rest, k] = [rest / p, k + 1];
		places = Math.max(places, k);
	}
	if (rest !== 1n) return undefined;
	places = Math.max(places, scale);
	const digits = ((f.n < 0n ? -f.n : f.n) * 10n ** BigInt(places)) / f.d;
	const text = digits.toString().padStart(places + 1, '0');
	return `${f.n < 0n ? '-' : ''}${places ? `${text.slice(0, -places)}.${text.slice(-places)}` : text}`;
}

// ---- order ----

const utf8 = new TextEncoder();
/** The order of two texts by their UTF-8 bytes (A.4; publication §6.2). */
export function byteOrder(a: string, b: string): number {
	const [x, y] = [utf8.encode(a), utf8.encode(b)];
	for (let i = 0; i < Math.min(x.length, y.length); i++) if (x[i] !== y[i]) return x[i] - y[i];
	return x.length - y.length;
}
const isFrac = (v: Known): v is Frac => typeof v === 'object' && 'n' in v;
const isRef = (v: Known): v is Ref => typeof v === 'object' && 'id' in v;
const isBounds = (v: Known): v is Bounds => typeof v === 'object' && 'lo' in v;
/** Two known values of one type, in order: below zero, zero when they are the same, above zero. */
function order(a: Known, b: Known): number {
	if (isFrac(a) && isFrac(b)) return sign(a.n * b.d - b.n * a.d);
	if (isRef(a) && isRef(b)) return byteOrder(a.id, b.id);
	if (typeof a === 'boolean' && typeof b === 'boolean') return Number(a) - Number(b);
	if (typeof a === 'string' && typeof b === 'string') return byteOrder(a, b);
	throw new NotEvaluated('two values of different types are compared');
}

// ---- states (Appendix A) ----

/** Of two operands in one state: the least reason, then a constant before any cause, then the cause that sorts first (A.4). */
function least(a: Stated, b: Stated): Stated {
	const by = byteOrder(a.reason, b.reason) || Number(a.cause !== undefined) - Number(b.cause !== undefined);
	if (by || !a.cause || !b.cause) return by <= 0 ? a : b;
	return (byteOrder(a.cause.relation, b.cause.relation) || byteOrder(canonicalJson(a.cause.key), canonicalJson(b.cause.key))) <= 0 ? a : b;
}
/** The highest state among some values, with the reason A.4 gives it; undefined when all are known. */
function worst(values: V[]): Stated | undefined {
	let out: Stated | undefined;
	for (const v of values) {
		if (v.s === 'known') continue;
		out = !out || RANK[v.s] > RANK[out.s] ? v : RANK[v.s] === RANK[out.s] ? least(out, v) : out;
	}
	// A member's `maybe` is not part of a state.
	return out && { s: out.s, reason: out.reason, ...(out.cause ? { cause: out.cause } : {}) };
}
/** A.1: false if any operand is false; otherwise the highest state among the others; otherwise true. */
const and = (parts: V[]): V => (parts.some((p) => p.s === 'known' && p.v === false) ? F : (worst(parts) ?? T));
const or = (parts: V[]): V => (parts.some((p) => p.s === 'known' && p.v === true) ? T : (worst(parts) ?? F));
/** A.2: `not` keeps a state. */
const not = (a: V): V => (a.s === 'known' ? bool(a.v !== true) : a);

// ---- rows ----

const STATE_MEMBER: Record<string, Held> = { $na: 'not_applicable', $unknown: 'unknown', $invalid: 'invalid' };
/** The id a `$ref` names: the text itself, or what follows the kind in a reference into another pack (publication §3.4). */
const refId = (ref: string): string => /^[^:/]+@s-[0-9a-f]{64}(?:@[^:]+)?:[^/]+\/(.*)$/s.exec(ref)?.[1] ?? ref;

/** One value of Row JSON (publication §3.2 to §3.4) as evaluation reads it; a state names the row it stands in as its cause. */
function fromJson(schema: Schema, ty: Ty, json: unknown, cause: RowRef): V {
	if (typeof json === 'object' && json !== null && !Array.isArray(json)) {
		const [member, text] = Object.entries(json)[0] ?? ['', ''];
		if (member in STATE_MEMBER) return { s: STATE_MEMBER[member], reason: String(text), cause };
		if (member === '$ref') return known({ id: refId(String(text)) });
	} else if (ty.t === 'bool' && typeof json === 'boolean') return known(json);
	else if (ty.t === 'num' && (typeof json === 'string' || typeof json === 'number')) {
		const f = amount(schema, String(json));
		if (f) return known(f);
	} else if (ty.t === 'ref' && typeof json === 'string') return known({ id: json });
	else if (ty.t === 'val' && typeof json === 'string') return known(json);
	throw new TypeError(`${cause.relation} ${canonicalJson(cause.key)}: ${JSON.stringify(json)} is not a value of its slot`);
}
const relationOf = (kind: string, slot: string): string => `${snake(kind)}__${slot}`;
/** Whether two values a row gives for one slot are the same value, or the same state with the same reason. */
const sameValue = (a: V, b: V): boolean =>
	a.s === 'known' && b.s === 'known' ? order(a.v, b.v) === 0 : a.s === b.s && (a as Stated).reason === (b as Stated).reason;
/**
 * What two rows of one element give together for a slot: the members of both for a set, and one value when they
 * agree. Two different values of a single-valued slot are invalid, with no reason (§7, conflicting scalar rows).
 */
function merged(before: Cell, cell: Cell): Cell {
	if (Array.isArray(before) && Array.isArray(cell)) return [...before, ...cell.filter((v) => !before.some((w) => sameValue(v, w)))];
	if (!Array.isArray(before) && !Array.isArray(cell) && sameValue(before, cell)) return before;
	return { s: 'invalid', reason: '' };
}

/**
 * Reads rows of Row JSON (`$kind`, `$id` and the slots) into what evaluation reads. A slot a row does not give
 * is absent, and absence is read by the slot's cardinality (§7a rule 1). An inverse slot is no data of its own
 * (publication §3.4): it is read from its forward slot. `rules` gives, per rule, the lists of ids it holds for;
 * `params` the value of each parameter, as Row JSON. `only` says which kinds, and which slots of each, the
 * rows were read for, when that is not all of them: evaluation then refuses to read any other (`NotLoaded`),
 * because a slot that was never read would look like a value that is not there.
 */
export function load(
	schema: Schema,
	rows: Record<string, unknown>[],
	more: { rules?: Record<string, string[][]>; outcomes?: Record<string, Outcome[]>; params?: Record<string, unknown>; only?: Map<string, Set<string>> } = {}
): Data {
	const data: Data = { kinds: new Map(), rules: new Map(), outcomes: new Map(), params: new Map(), ...(more.only ? { only: more.only } : {}) };
	for (const row of rows) {
		const [kind, id] = [String(row.$kind), String(row.$id)];
		const def = schema.kinds[kind];
		// A kind the role's schema does not have is not the role's to read.
		if (!def) continue;
		if (!data.kinds.has(kind)) data.kinds.set(kind, new Map());
		const elements = data.kinds.get(kind)!;
		// Rows with the same id give values of one element: they are read together, not one over the other.
		const cells = elements.get(id) ?? new Map<string, Cell>();
		for (const [name, slot] of Object.entries(def.slots)) {
			const json = row[name];
			if (json === undefined || slot.inverse !== undefined) continue;
			const one = (j: unknown) => fromJson(schema, slotType(schema, slot), j, { relation: relationOf(kind, name), key: [id] });
			const cell = Array.isArray(json) ? json.map(one) : one(json);
			const before = cells.get(name);
			cells.set(name, before === undefined ? cell : merged(before, cell));
		}
		elements.set(id, cells);
	}
	for (const [rule, lists] of Object.entries(more.rules ?? {})) data.rules.set(rule, new Set(lists.map((ids) => canonicalJson(ids))));
	for (const [rule, list] of Object.entries(more.outcomes ?? {})) {
		const byKey = new Map<string, V>();
		for (const o of list) {
			const held = o.state === 'known' ? bool(o.value === true) : ({ s: o.state, reason: o.reason ?? '', ...(o.cause ? { cause: o.cause } : {}) } as V);
			byKey.set(canonicalJson(o.key), held);
		}
		data.outcomes.set(rule, byKey);
	}
	for (const [name, json] of Object.entries(more.params ?? {})) {
		const param = schema.params?.[name];
		if (param) data.params.set(name, fromJson(schema, slotType(schema, param), json, { relation: 'param', key: [name] }));
	}
	return data;
}

/** The ids of a kind's elements, in the canonical order of their key (publication §6.2). */
function idsOf(data: Data, kind: string): string[] {
	return [...(data.kinds.get(kind)?.keys() ?? [])].sort((a, b) => byteOrder(canonicalJson([a]), canonicalJson([b])));
}

// ---- expressions ----

interface Reader {
	ex(e: Expr): V;
	within<R>(row: V, ty: Ty, body: () => R): R;
	/** The element a path leads to before its last slot, and that slot: where a suppose line writes. */
	target(path: { path: string[] }): { kind: string; id: string; slot: string } | undefined;
	/** The steps counted so far. */
	spent(): number;
}

/**
 * Reads expressions over the rows. `more.note` is told each fact a read takes (a slot of an element, a
 * parameter, a row of a rule): the witness of a decision table names them. `more.steps` is what was spent
 * before this reader started, so that several readers share one budget.
 */
export function reader(checked: Pick<Checked, 'typed' | 'heads'>, schema: Schema, data: Data, limit = Infinity, more: { note?: (fact: RowRef) => void; steps?: number } = {}): Reader {
	const { typed, heads } = checked;
	const { note } = more;
	const scopes: { v: V; ty: Ty }[] = [];
	const literals = new Map<object, V>();
	const inverses = new Map<string, { named: Map<string, Member[]>; maybe: Member[] }>();
	const kindSets = new Map<string, V>();
	let steps = more.steps ?? 0;
	/** Counts work done; past the limit the evaluation stops, whatever it had found. */
	const tick = (n = 1): void => {
		steps += n;
		if (steps > limit) throw new OverBudget(limit);
	};
	/** Refuses a read of a kind, or of a slot of it, that was not loaded. */
	const need = (kind: string, slot?: string): void => {
		if (!data.only) return;
		const slots = data.only.get(kind);
		if (!slots || (slot !== undefined && !slots.has(slot))) throw new NotLoaded(`${kind}${slot === undefined ? '' : `.${slot}`} is read and was not loaded`);
	};
	const tyOf = (e: object): Ty => typed.get(e)?.ty ?? { t: 'err' };
	const opens = (e: object): boolean => (typed.get(e)?.opens.length ?? 0) > 0;
	const kindOf = (ty: Ty): string => {
		if (ty.t !== 'ref') throw new NotEvaluated('a slot is read of something that is not an element');
		return ty.kind;
	};
	const members = (v: V): Member[] | undefined => (v.s === 'known' && Array.isArray(v.v) ? v.v : undefined);
	const plain = ({ maybe: _maybe, ...v }: Member): V => v as V;

	function within<R>(row: V, ty: Ty, body: () => R): R {
		scopes.push({ v: row, ty });
		try {
			return body();
		} finally {
			scopes.pop();
		}
	}

	/** Two memberships that both must hold ("in the one and in the other"): the highest state, by A.4. */
	const both = (a: Stated | undefined, b: Stated | undefined): Stated | undefined => (a && b ? worst([a, b]) : (a ?? b));
	/**
	 * The members of an inverse slot: the elements whose forward slot names this one. An element whose forward
	 * value is unknown or invalid may name any element, so it is a member of every such set with that state,
	 * reason and cause on its membership: the one relation gives one answer from either end (publication §3.4).
	 * A forward value that is `n/a` names none. A forward value that the row does not give is unknown when the
	 * slot is required or the role reads its relation in part, and names none otherwise (§7a rule 1).
	 */
	function inverse(slot: SlotDef, id: string): Member[] {
		const [kind, name] = [slot.ref!, slot.inverse!];
		const key = `${kind}.${name}`;
		need(kind, name);
		let index = inverses.get(key);
		if (!index) {
			index = { named: new Map(), maybe: [] };
			const reason = inPart(schema, kind, name) ? NOT_READ_IN_FULL : schema.kinds[kind].slots[name].card === '1' ? '' : undefined;
			for (const other of idsOf(data, kind)) {
				const cell = data.kinds.get(kind)!.get(other)!.get(name);
				const missing: V[] = reason === undefined ? [] : [{ s: 'unknown', reason, cause: { relation: relationOf(kind, name), key: [other] } }];
				for (const v of cell === undefined ? missing : Array.isArray(cell) ? cell : [cell]) {
					if (v.s === 'not_applicable') continue;
					if (v.s !== 'known') index.maybe.push({ ...known({ id: other }), maybe: v });
					else if (isRef(v.v)) {
						if (!index.named.has(v.v.id)) index.named.set(v.v.id, []);
						index.named.get(v.v.id)!.push(known({ id: other }));
					}
				}
			}
			// The index is made once, over every element of the kind.
			tick(data.kinds.get(kind)?.size ?? 0);
			inverses.set(key, index);
		}
		// Every member it gives is a step: an element's sources, and every source whose forward value is undecided.
		const out = [...(index.named.get(id) ?? []), ...index.maybe];
		tick(out.length);
		return out;
	}
	/** One slot further (a strict operator, A.3): of one element, or of every member of a set. */
	function step(from: V, ty: Ty, name: string): [V, Ty] {
		const kind = kindOf(ty);
		const slot = schema.kinds[kind].slots[name];
		const many = slot.card === '*' || slot.card === '+';
		const read = (of: V): V => {
			if (of.s !== 'known') return of;
			const { id } = of.v as Ref;
			need(kind, name);
			tick();
			if (slot.inverse !== undefined) {
				const sources = inverse(slot, id);
				// A member of an inverse set is read from the forward row of its source.
				if (note) for (const m of sources) note({ relation: relationOf(slot.ref!, slot.inverse), key: [((m as { v: Ref }).v).id] });
				return known(sources);
			}
			note?.({ relation: relationOf(kind, name), key: [id] });
			const row = data.kinds.get(kind)?.get(id);
			// An element of an open kind that has no row: nothing is known of it, also not that an optional value
			// is absent. So every slot of it is unknown, whatever its cardinality.
			if (!row && schema.kinds[kind].world === 'open') return { s: 'unknown', reason: OPEN_WORLD, cause: { relation: relationOf(kind, name), key: [id] } };
			const cell = row?.get(name);
			if (cell !== undefined) return Array.isArray(cell) ? known(cell) : cell;
			// No value in the role's view: an absent member of a set is absent, a missing `T?` is `n/a`, a
			// missing `T` is unknown; the cause is the row that would hold it (§7a rule 1, §8a).
			if (many) return known([]);
			const cause = { relation: relationOf(kind, name), key: [id] };
			// Of a relation the role reads in part, the missing value may be one it does not read: unknown,
			// also for a `T?`, and the same bytes whether a value is withheld or there is none.
			if (inPart(schema, kind, name)) return { s: 'unknown', reason: NOT_READ_IN_FULL, cause };
			return { s: slot.card === '?' ? 'not_applicable' : 'unknown', reason: '', cause };
		};
		const set = members(from);
		if (!set) return [read(from), slotType(schema, slot)];
		const out: Member[] = [];
		for (const m of set) {
			const v = read(plain(m));
			// Every member a read gives is a step, before it is copied: a hop over a set costs its fan-out.
			const xs = (members(v) ?? [v]) as Member[];
			tick(xs.length);
			for (const x of xs) {
				const maybe = both(m.maybe, x.maybe);
				out.push(maybe ? { ...plain(x), maybe } : x);
			}
		}
		return [known(out), slotType(schema, slot)];
	}

	function literal(e: { lit: string }): V {
		const ty = tyOf(e);
		const text = e.lit;
		if (ty.t === 'state') {
			if (text === 'n/a') return { s: 'not_applicable', reason: '' };
			const [, word, reason] = /^(unknown|invalid)[ \t]+(.*)$/s.exec(text)!;
			return { s: word as Held, reason: reason.startsWith('"') ? unquote(reason) : reason };
		}
		if (ty.t === 'bool') return bool(text === 'true');
		if (ty.t === 'num') {
			const f = amount(schema, text);
			if (f) return known(f);
		}
		if (ty.t === 'ref') return known({ id: /^[A-Z][A-Za-z0-9]*:\x60(.*)\x60$/s.exec(text)?.[1] ?? text });
		if (ty.t === 'val') return known(/^(?:[A-Z][A-Za-z0-9]*)?"/.test(text) ? unquote(text.slice(text.indexOf('"'))) : text);
		throw new NotEvaluated(`the literal ${text} has no value here`);
	}
	const unquote = (text: string): string => text.slice(1, -1).replace(/\\(.)/gs, '$1');

	function path(e: { path: string[] }, upTo = e.path.length): [V, Ty] {
		const [first, ...rest] = e.path.slice(0, upTo);
		const head = heads.get(e);
		let at: [V, Ty];
		if (!head) {
			// A lone id: its context gave it its kind (§3).
			const ty = tyOf(e);
			// A bare word that its context read as a value of an enum (`tier = high`) is that value.
			if (ty.t === 'val') at = [known(first), ty];
			else if (ty.t !== 'ref') throw new NotEvaluated(`the name ${first} has no value here`);
			else at = [known({ id: first }), ty];
		} else if (head.as === 'id') at = [known({ id: first }), { t: 'ref', kind: head.kind }];
		else if (head.as === 'param') {
			const param = schema.params![first];
			note?.({ relation: 'param', key: [first] });
			at = [data.params.get(first) ?? { s: 'unknown', reason: '', cause: { relation: 'param', key: [first] } }, slotType(schema, param)];
		} else {
			const scope = scopes[head.level];
			at = head.as === 'row' ? [scope.v, scope.ty] : step(scope.v, scope.ty, first);
		}
		for (const name of rest) at = step(at[0], at[1], name);
		return at;
	}

	/** A strict operator (A.3): with an operand in a state, the highest state; otherwise what `compute` gives. */
	const strict = (operands: V[], compute: (...known: Known[]) => V): V => worst(operands) ?? compute(...operands.map((o) => (o as { v: Known }).v));
	const number = (v: Known): Frac => {
		if (!isFrac(v)) throw new NotEvaluated('arithmetic on dates and periods is not evaluated yet');
		return v;
	};

	function aggregate(e: { agg: [string, Expr] | [string, Expr, Expr] }): V {
		const [name, of, arg] = e.agg;
		const base = ex(of);
		const set = members(base);
		if (set) tick(set.length);
		// An aggregate over a set in a state takes that state (A.3).
		if (base.s !== 'known') return base;
		if (!set) throw new NotEvaluated(`${name}(…) of a range or of a single value is not evaluated yet`);
		const ty = tyOf(of);
		const each = (m: Member): V => within(plain(m), ty, () => ex(arg!));
		if (name === 'any' || name === 'all' || name === 'none') {
			// `any` folds `or` from false, `all` folds `and` from true (A.3); a member whose own membership is
			// undecided counts when that is decided: `any` reads it as "in and p", `all` as "in => p".
			const parts = set.map((m) => {
				const p = arg === undefined ? T : each(m);
				return !m.maybe ? p : name === 'all' ? or([m.maybe, p]) : and([m.maybe, p]);
			});
			if (name === 'all') return and(parts);
			const some = or(parts);
			// Over an open relation "no member found" proves nothing: unknown, never false (§6).
			if (name === 'any') return some.s === 'known' && some.v === false && opens(of) ? { s: 'unknown', reason: OPEN_WORLD } : some;
			return not(some);
		}
		// `count`, `sum`, `min` and `max` are strict in the members (A.3), and in whether each one is a member: a
		// count does not reason about bounds, so it stays undecided where a membership or a member is.
		const undecided = set.flatMap((m) => (m.maybe ? [m.maybe as V] : []));
		const values = arg === undefined ? set.map(plain) : set.map(each);
		if (name === 'count') return strict([...undecided, ...values], () => known(frac(BigInt(arg === undefined ? set.length : values.filter((v) => (v as { v: Known }).v === true).length))));
		return strict([...undecided, ...values], () => {
			const all = values.map((v) => (v as { v: Known }).v);
			if (name === 'sum') return known(all.reduce<Frac>((sum, x) => plus(sum, number(x)), frac(0n)));
			if (!all.length) return { s: 'not_applicable', reason: 'empty' };
			return known(all.reduce((best, x) => ((name === 'min' ? order(x, best) < 0 : order(x, best) > 0) ? x : best)));
		});
	}
	function isIn(e: { in: [Expr, Expr] }): V {
		const [x, of] = [ex(e.in[0]), ex(e.in[1])];
		if (of.s !== 'known') return worst([x, of])!;
		if (isBounds(of.v)) {
			const { lo, hi, open } = of.v;
			return strict([x, lo, hi], (a, b, c) => bool(order(a, b) >= 0 && (open ? order(a, c) < 0 : order(a, c) <= 0)));
		}
		if (x.s !== 'known') return x;
		const set: Member[] = members(of) ?? [of];
		tick(set.length);
		const same = set.filter((m) => m.s === 'known' && order(m.v, x.v) === 0);
		if (same.some((m) => !m.maybe)) return T;
		// Not found for sure: a member in a state, or one whose membership is undecided, may be the one.
		return worst([...same.map((m) => m.maybe as V), ...set.filter((m) => m.s !== 'known').map(plain)]) ?? (opens(e.in[1]) ? { s: 'unknown', reason: OPEN_WORLD } : F);
	}

	function round(e: { call: [string, Expr[]] }): V {
		const [x, mode] = e.call[1];
		const ty = tyOf(x);
		return strict([ex(x)], (v) => {
			if (ty.t !== 'num') throw new NotEvaluated('round of something that is not a number');
			const named = mode && 'path' in mode ? mode.path[0] : schema.rounding?.money;
			if (named === undefined) throw new NotEvaluated('round(x) needs the rounding of the pack; write round(x, half_even), or declare it');
			// The places of the value's type: its own type, or the pack's first type of its dimension.
			const types = schema.types ?? {};
			const type = ty.name ?? Object.keys(types).sort().find((n) => ((t: Ty) => t.t === 'num' && sameDim(t.dim, ty.dim))(typeOf(schema, n)));
			const def: TypeDef | undefined = type === undefined ? undefined : types[type];
			const unit = unitFactor(def);
			const scaled = times(over(number(v), unit), frac(10n ** BigInt(def?.scale ?? '0')));
			return known(over(times(frac(roundTo(scaled, named)), unit), frac(10n ** BigInt(def?.scale ?? '0'))));
		});
	}
	/** How many storage units one unit of a type is: its factor, or for money per unit one over that unit's factor. */
	const unitFactor = (def: TypeDef | undefined): Frac => (def?.of === 'Money' ? (def.per ? over(frac(1n), factor(schema, def.per)) : frac(1n)) : factorOf(def?.factor));

	function ex(e: Expr): V {
		tick();
		if ('lit' in e) {
			if (!literals.has(e)) literals.set(e, literal(e));
			return literals.get(e)!;
		}
		if ('path' in e) return path(e)[0];
		if ('kind' in e) {
			need(e.kind);
			if (!kindSets.has(e.kind)) kindSets.set(e.kind, known(idsOf(data, e.kind).map((id) => known({ id }))));
			return kindSets.get(e.kind)!;
		}
		if ('dot' in e) return step(ex(e.dot[0]), tyOf(e.dot[0]), e.dot[1])[0];
		if ('timesel' in e) throw new NotEvaluated('a time selection is reserved');
		if ('agg' in e) return aggregate(e);
		if ('filter' in e) {
			const base = ex(e.filter[0]);
			const set = members(base);
			if (!set) return base;
			const ty = tyOf(e.filter[0]);
			// A filter decides as an `ask` does (A.5): true is in, false and `n/a` are out; with an unknown or
			// invalid condition the member stays, with that state on its membership.
			return known(
				set.flatMap((m): Member[] => {
					const c = within(plain(m), ty, () => ex(e.filter[1]));
					const decided = m.maybe ? and([m.maybe, c]) : c;
					if (decided.s === 'known') return decided.v === true ? [plain(m)] : [];
					return decided.s === 'not_applicable' ? [] : [{ ...plain(m), maybe: decided }];
				})
			);
		}
		if ('cmp' in e) {
			const [op, a, b] = e.cmp;
			return strict([ex(a), ex(b)], (x, y) => {
				const by = order(x, y);
				return bool(op === '=' ? by === 0 : op === '!=' ? by !== 0 : op === '<' ? by < 0 : op === '<=' ? by <= 0 : op === '>' ? by > 0 : by >= 0);
			});
		}
		if ('in' in e) return isIn(e);
		if ('range' in e) return known({ lo: ex(e.range[0]), hi: ex(e.range[2]), open: e.range[1] === '..<' });
		if ('is' in e) {
			// A.3b: always true or false.
			const { s } = ex(e.is[0]);
			return bool((s === 'not_applicable' ? 'n/a' : s) === e.is[1]);
		}
		if ('and' in e) return and(e.and.map(ex));
		if ('or' in e) return or(e.or.map(ex));
		if ('not' in e) return not(ex(e.not));
		// `a => b` is `not a or b` (§7); its operands keep their places.
		if ('imply' in e) return or([not(ex(e.imply[0])), ex(e.imply[1])]);
		if ('neg' in e) return strict([ex(e.neg)], (x) => known(frac(-number(x).n, number(x).d)));
		if ('arith' in e) {
			const [op, a, b] = e.arith;
			return strict([ex(a), ex(b)], (x, y) => {
				const [p, q] = [number(x), number(y)];
				if (op === '+' || op === '-') return known(plus(p, q, op === '+' ? 1n : -1n));
				if (op === '*') return known(times(p, q));
				// A division by zero is invalid (S1 §2); no row caused it.
				return q.n === 0n ? { s: 'invalid', reason: '' } : known(over(p, q));
			});
		}
		if ('when' in e) {
			const c = ex(e.when[0]);
			return c.s !== 'known' ? c : ex(e.when[c.v === true ? 1 : 2]);
		}
		const [name, args] = e.call;
		if (name === 'round') return round(e);
		const rule = schema.rules![name];
		return strict(args.map(ex), (...ids) => {
			const key = ids.map((v) => (v as Ref).id);
			note?.({ relation: name, key });
			const outcome = data.outcomes.get(name)?.get(canonicalJson(key));
			if (outcome) return outcome;
			if (data.rules.get(name)?.has(canonicalJson(key))) return T;
			// A partial rule that publishes outcomes decides a key only by its outcome row (§2): without one the call
			// is unknown, with the missing outcome row as cause, and never false by absence.
			if (rule.outcome && rule.states?.some((s) => s !== 'known')) return { s: 'unknown', reason: NO_OUTCOME, cause: { relation: name, key } };
			// No row: false for a closed rule; for an open one unknown, with the row that would hold it as cause.
			return rule.world === 'open' ? { s: 'unknown', reason: OPEN_WORLD, cause: { relation: name, key } } : F;
		});
	}

	function target(p: { path: string[] }) {
		const [at, ty] = path(p, p.path.length - 1);
		return at.s === 'known' && isRef(at.v) && ty.t === 'ref' ? { kind: ty.kind, id: at.v.id, slot: p.path[p.path.length - 1] } : undefined;
	}
	return { ex, within, target, spent: () => steps };
}

/** A whole number from a fraction, by a named rounding (v0 §5f). */
function roundTo(f: Frac, mode: string): bigint {
	const down = f.n >= 0n ? f.n / f.d : -((-f.n + f.d - 1n) / f.d);
	const rest = plus(f, frac(down), -1n);
	if (rest.n === 0n) return down;
	const half = sign(rest.n * 2n - rest.d);
	if (mode === 'down') return f.n >= 0n ? down : down + 1n;
	if (mode === 'up') return f.n >= 0n ? down + 1n : down;
	if (mode === 'half_up') return half > 0 || (half === 0 && f.n >= 0n) ? down + 1n : down;
	if (mode === 'half_even') return half > 0 || (half === 0 && down % 2n !== 0n) ? down + 1n : down;
	throw new NotEvaluated(`the rounding ${mode} is not one of half_even, half_up, down, up`);
}

// ---- suppose lines ----

/** Places an evaluated value into a cell, attributing any state to the row that holds it. */
function cellValue(v: V, relation: string, key: string): Cell {
	const cause: RowRef = { relation, key: [key] };
	// A state written in the line stands in the row it is set on, like a state the data gives.
	const placed = (x: V): V => (x.s === 'known' ? x : { ...x, cause });
	return v.s === 'known' && Array.isArray(v.v) ? v.v.map(placed) : placed(v);
}

/**
 * The rows with one suppose line applied (§8): `+ path = value` sets a value, and makes the element when it is
 * not there; `+ Kind id {slot = value, ...}` inserts a fresh whole record; `- path` takes a value away, so that
 * it is read as absent; `- Kind id` takes a row away. The rows handed in are not changed: a delta lasts for the
 * question only.
 */
export function suppose(data: Data, line: Checked, schema: Schema): Data {
	const { tree } = line;
	if (!tree || isAsk(tree) || line.diagnostics.some(isError)) throw new TypeError('not a suppose line that checks');
	const kinds = new Map([...data.kinds].map(([kind, rows]) => [kind, new Map(rows)]));
	const out: Data = { ...data, kinds };
	if ('retract_row' in tree) {
		kinds.get(tree.retract_row[0])?.delete(tree.retract_row[1]);
		return out;
	}
	const read = reader(line, schema, data);
	if ('insert_row' in tree) {
		const { kind, key, slots } = tree.insert_row;
		const def = schema.kinds[kind];
		if (!def) throw new TypeError(`unknown kind ${kind}`);
		if (data.only && !data.only.has(kind)) throw new NotLoaded(`${kind} is inserted and was not loaded`);
		if (kinds.get(kind)?.has(key)) throw new TypeError(`${kind} ${key} already exists`);
		const cells = new Map<string, Cell>();
		for (const entry of slots) {
			const slotDef = def.slots[entry.name];
			if (!slotDef || slotDef.inverse !== undefined || slotDef.derived) {
				throw new TypeError(`${kind}.${entry.name} cannot be written by a whole-record insertion`);
			}
			cells.set(entry.name, cellValue(read.ex(entry.value), relationOf(kind, entry.name), key));
		}
		if (!kinds.has(kind)) kinds.set(kind, new Map());
		kinds.get(kind)!.set(key, cells);
		return out;
	}
	const at = read.target('set' in tree ? tree.set[0] : tree.retract);
	// A path through a value that is not there names no row: nothing to change.
	if (!at) return out;
	// An inverse slot is no data of its own (publication §3.4): a line writes the forward slot.
	if (schema.kinds[at.kind]?.slots[at.slot]?.inverse !== undefined) throw new TypeError(`${at.kind}.${at.slot} is an inverse slot: a suppose line writes its forward slot`);
	if (!kinds.has(at.kind)) kinds.set(at.kind, new Map());
	const cells = new Map(kinds.get(at.kind)!.get(at.id));
	if ('set' in tree) cells.set(at.slot, cellValue(read.ex(tree.set[1]), relationOf(at.kind, at.slot), at.id));
	else cells.delete(at.slot);
	kinds.get(at.kind)!.set(at.id, cells);
	return out;
}

// ---- the answer ----

/** A row of an answer, as Row JSON of its output schema (§8a). */
export type AnswerRow = { $kind: 'Answer'; $id: string; binder: { $ref: string } } & Record<string, unknown>;
export interface UndecidedRow {
	$kind: 'Undecided';
	$id: string;
	binder: { $ref: string };
	state: 'unknown' | 'invalid';
	reason: string;
	/** The typed RowRef of the cause: its relation, and the canonical JSON of its key; both `""` for a state written as a constant. */
	cause_relation: string;
	cause_key: string;
}
/** The answer of an `ask`: a dataset of its output schema, with its counts (§8a). */
export interface Answer {
	/** The id of the output schema: the `$schema` of the dataset. */
	$schema: string;
	schema: AnswerSchema;
	/** The rows where the condition is true, and those where it is unknown or invalid: each in the canonical order of its key. */
	rows: AnswerRow[];
	undecided: UndecidedRow[];
	counts: { rows: number; undecided: number; not_applicable: number };
}

/** A value as Row JSON of an output slot (publication §3.2, §3.3). */
function toJson(v: V, slot: SlotDef, doc: AnswerSchema, schema: Schema): unknown {
	if (v.s !== 'known') return { [v.s === 'not_applicable' ? '$na' : `$${v.s}`]: v.reason };
	const value = v.v;
	if (isRef(value)) return { $ref: `${doc.imports.p.pack}@${doc.imports.p.schema}:${(slot.ref ?? '').replace(/^p\./, '')}/${value.id}` };
	if (typeof value === 'boolean' || typeof value === 'string') return value;
	if (!isFrac(value)) throw new NotEvaluated('a set or a range is shown');
	const name = slot.type ?? '';
	const def: TypeDef | undefined = name.startsWith('p.') ? schema.types?.[name.slice(2)] : doc.types[name];
	const whole = (f: Frac) => (f.d === 1n ? f.n.toString() : `${f.n}/${f.d}`);
	// A quantity and an amount of money are stored as an integer at the scale of their type (publication §3.2).
	// A value whose stored integer is not whole is no value of the type: it exists and the type cannot hold it,
	// so it is shown as unknown, in this column of this row only. Inside a condition it stays exact.
	const scale = 10n ** BigInt(def?.scale ?? '0');
	const held = (stored: Frac): boolean => times(stored, frac(scale)).d === 1n;
	if (def?.of === 'Quantity') {
		if (!held(value)) return { $unknown: NOT_EXACT };
		const inUnit = over(value, factorOf(def.factor));
		return `${decimal(inUnit) ?? whole(inUnit)} ${def.unit}`;
	}
	if (def?.of === 'Money') {
		const inUnit = def.per ? times(value, factor(schema, def.per)) : value;
		if (!held(inUnit)) return { $unknown: NOT_EXACT };
		const symbol = Object.keys(schema.symbols ?? {}).sort().find((s) => schema.symbols![s] === def.currency) ?? def.currency;
		return `${symbol} ${decimal(inUnit, Number(def.scale ?? '0'))}${def.per ? `/${def.per}` : ''}`;
	}
	// A plain number is a ratio: `1/3` as it stands.
	return whole(value);
}

/**
 * Answers a checked `ask` over the rows a role reads. Undefined when the text is not an `ask` or the check
 * found an error: a question that does not check is never evaluated. With `budget.steps` the evaluation
 * stops when it passes that many steps (`OverBudget`): no row and no count, never a part as the whole. `pack`
 * is the pack's whole schema, which the question hash of the output schema's `base` is taken against.
 */
export async function answer(checked: Checked, schema: Schema, data: Data, budget: { steps?: number } = {}, pack: Schema = schema): Promise<Answer | undefined> {
	const { tree, answer: shape } = checked;
	if (!tree || !isAsk(tree) || !shape) return undefined;
	if (data.only && !data.only.has(shape.kind)) throw new NotLoaded(`${shape.kind} is asked and was not loaded`);
	const doc = (await outputSchema(tree, checked, schema, pack))!;
	const read = reader(checked, schema, data, budget.steps);
	const ty: Ty = { t: 'ref', kind: shape.kind };
	const out: Answer = { $schema: await schemaId(doc), schema: doc, rows: [], undecided: [], counts: { rows: 0, undecided: 0, not_applicable: 0 } };
	for (const id of idsOf(data, shape.kind)) {
		const row = known({ id });
		const binder = { $ref: `${doc.imports.p.pack}@${doc.imports.p.schema}:${shape.kind}/${id}` };
		const c = read.within(row, ty, () => read.ex(tree.where));
		if (c.s === 'known') {
			if (c.v !== true) continue;
			const shown = shape.shown.map((s, i) => [`c${i + 1}`, toJson(read.within(row, ty, () => read.ex(s.expr)), doc.kinds.Answer.slots[`c${i + 1}`], doc, schema)]);
			out.rows.push({ $kind: 'Answer', $id: id, binder, ...Object.fromEntries(shown) });
		} else if (c.s === 'not_applicable') out.counts.not_applicable++;
		else out.undecided.push({ $kind: 'Undecided', $id: id, binder, state: c.s, reason: c.reason, cause_relation: c.cause?.relation ?? '', cause_key: c.cause ? canonicalJson(c.cause.key) : '' });
	}
	out.counts.rows = out.rows.length;
	out.counts.undecided = out.undecided.length;
	return out;
}

// ---- a decision table ----

/** Why a table gives no value: no row applies; and two rows of a `unique` table apply (v0 §5, core reason codes). */
const NO_ROW_APPLIES = 'no_row_applies';
const EXCEPTION_CONFLICT = 'exception_conflict';

/** One row of a table in the witness of a value: its number in the order written, from 1, and the facts its tests read. */
export interface RowWitness {
	row: number;
	/** Each once, by relation and then by key. */
	facts: RowRef[];
}
export interface Tabulated {
	/** The rows handed in, with the value of each table for every element of its kind as the cell of its slot. */
	data: Data;
	/**
	 * The witness of each value (tables.md §3), by the relation of its slot (`<kind>__<slot>`) and the element:
	 * the rows that gave it, in the order written. For a known value that is the row whose output it is; for
	 * `collect` every row that gives a member; for a state taken from undecided rows those rows; for
	 * `exception_conflict` the rows that apply; for `no_row_applies` none.
	 */
	why: Map<string, Map<string, RowWitness[]>>;
}

/**
 * The value of every decision table of checked declarations, for every element of its kind, by tables.md §3. A
 * cell is a condition of Appendix A and a row the `and` of its cells: it applies when that is true, does not
 * when it is false or `n/a`, and is undecided when it is unknown or invalid. The tables are decided in the
 * order of the text, each over the rows with the tables before it, so a table reads what stands above it. The
 * rows handed in are not changed. Every expression evaluated counts as a step, as in an answer; past
 * `budget.steps` nothing is given (`OverBudget`).
 */
export function tabulate(declared: Declared, data: Data, budget: { steps?: number } = {}): Tabulated {
	const { schema } = declared;
	if (!schema) throw new TypeError('declarations that do not check are never evaluated');
	const why: Tabulated['why'] = new Map();
	let out = data;
	let steps = 0;
	for (const table of declared.tables) {
		let facts: RowRef[] = [];
		const read = reader(declared, schema, out, budget.steps, { note: (fact) => facts.push(fact), steps });
		const ty: Ty = { t: 'ref', kind: table.kind };
		const relation = relationOf(table.kind, table.slot);
		const outputs = table.rows.map((row) => read.ex(row.value) as V & { s: 'known' });
		const same = (i: number, j: number): boolean => order(outputs[i].v, outputs[j].v) === 0;
		// `priority`: the place of a row's output in the order of the output enum.
		const rank = (i: number): number => table.order!.indexOf(outputs[i].v as string);
		const cells = new Map<string, Cell>();
		const rows = new Map<string, RowWitness[]>();
		for (const id of idsOf(out, table.kind)) {
			// `no_row_applies` and `exception_conflict` have the row that holds the derived value as cause.
			const cause: RowRef = { relation, key: [id] };
			const decided = table.rows.map((row, i) => {
				facts = [];
				const v = read.within(known({ id }), ty, () => and(row.when.map((cell) => read.ex(cell))));
				const seen = new Map(facts.map((f) => [canonicalJson([f.relation, f.key]), f]));
				return { i, v, facts: [...seen.values()].sort((a, b) => byteOrder(a.relation, b.relation) || byteOrder(canonicalJson(a.key), canonicalJson(b.key))) };
			});
			const applying = decided.filter((d) => d.v.s === 'known' && d.v.v === true);
			const undecided = decided.filter((d) => d.v.s === 'unknown' || d.v.s === 'invalid');
			let value: Cell;
			let from = applying;
			if (table.policy === 'collect') {
				// Every output an applying row gives is a member; an output only undecided rows give is a member
				// whose membership is undecided, with the highest state among those rows.
				const open = undecided.filter((d) => !applying.some((a) => same(a.i, d.i)));
				from = [...applying, ...open].sort((a, b) => a.i - b.i);
				value = from
					.filter((d, n) => !from.slice(0, n).some((o) => same(o.i, d.i)))
					.map((d): Member => (applying.includes(d) ? outputs[d.i] : { ...outputs[d.i], maybe: worst(open.filter((o) => same(o.i, d.i)).map((o) => o.v))! }));
			} else if (!applying.length) {
				value = worst(undecided.map((d) => d.v)) ?? { s: 'unknown', reason: NO_ROW_APPLIES, cause };
				from = undecided;
			} else if (table.policy === 'unique') value = applying.length > 1 ? { s: 'invalid', reason: EXCEPTION_CONFLICT, cause } : outputs[applying[0].i];
			else {
				// `first`: the first row that applies; `priority`: the one whose output comes first in the enum's
				// order. An undecided row that would win if it applied, with another output, leaves the value undecided.
				const r = table.policy === 'first' ? applying[0] : applying.reduce((best, d) => (rank(d.i) < rank(best.i) ? d : best));
				const wins = undecided.filter((d) => (table.policy === 'first' ? d.i < r.i && !same(d.i, r.i) : rank(d.i) < rank(r.i)));
				value = wins.length ? worst(wins.map((d) => d.v))! : outputs[r.i];
				from = wins.length ? wins : [r];
			}
			cells.set(id, value);
			rows.set(id, from.map((d) => ({ row: d.i + 1, facts: d.facts })));
		}
		steps = read.spent();
		why.set(relation, rows);
		const filled = new Map([...(out.kinds.get(table.kind) ?? [])].map(([id, row]) => [id, new Map(row).set(table.slot, cells.get(id)!)]));
		// Where only some slots were loaded, the slot just computed is one of them.
		const only = out.only?.has(table.kind) ? new Map(out.only).set(table.kind, new Set([...out.only.get(table.kind)!, table.slot])) : out.only;
		out = { ...out, kinds: new Map(out.kinds).set(table.kind, filled), ...(only ? { only } : {}) };
	}
	return { data: out, why };
}

// ---- a check statement at publication ----

/** An element whose condition is undecided (v0 §7b): an undecided violation, with the reason and cause of its state. */
export interface UndecidedViolation {
	id: string;
	state: 'unknown' | 'invalid';
	reason: string;
	cause?: RowRef;
}
/** What one check statement decides at publication (v0 §5, §7b). */
export interface Publication {
	verb: 'check' | 'require' | 'warn';
	name?: string;
	outcome: 'publishes' | 'blocked';
	/** The elements whose condition is false, in key order. */
	violations: string[];
	/** The elements whose condition is unknown or invalid, in key order. */
	undecided: UndecidedViolation[];
	/** The elements that block publication, in key order. */
	blocking: string[];
}

/**
 * Decides a checked check statement over the rows a role reads (v0 §7b). A condition that is true or `n/a`
 * passes, false is a violation, unknown or invalid an undecided violation. `check` and `require` are about the
 * model and block on a violation; `check` publishes an unknown one and blocks on an invalid one, because the
 * model then contradicts itself; `require` is fail-closed and blocks on both; `warn` never blocks. Undefined
 * when the text is not a check statement or the check found an error.
 */
export function publish(checked: Checked, schema: Schema, data: Data): Publication | undefined {
	const { tree, publication: shape } = checked;
	if (!tree || !isCheck(tree) || !shape) return undefined;
	if (shape.kind === undefined || shape.binder === undefined) throw new NotEvaluated('a check statement whose condition names no kind is not evaluated yet');
	const read = reader(checked, schema, data);
	const ty: Ty = { t: 'ref', kind: shape.kind };
	const out: Publication = { verb: shape.verb, ...(shape.name !== undefined ? { name: shape.name } : {}), outcome: 'publishes', violations: [], undecided: [], blocking: [] };
	for (const id of idsOf(data, shape.kind)) {
		const c = read.within(known({ id }), ty, () => read.ex(tree.cond));
		if (c.s === 'known') {
			if (c.v === true) continue;
			out.violations.push(id);
			if (shape.verb !== 'warn') out.blocking.push(id);
		} else if (c.s !== 'not_applicable') {
			out.undecided.push({ id, state: c.s, reason: c.reason, ...(c.cause ? { cause: c.cause } : {}) });
			if (shape.verb === 'require' || (shape.verb === 'check' && c.s === 'invalid')) out.blocking.push(id);
		}
	}
	if (out.blocking.length) out.outcome = 'blocked';
	return out;
}

/** The last key of each kind of row on a page: where the next page starts (§8a). */
export interface Cursor {
	rows?: string;
	undecided?: string;
}
/**
 * One page of an answer: at most `limit` rows and `limit` undecided rows after the cursor, each in key order,
 * and the cursor of the next page while one of the two has more. Every page is a slice of the one answer.
 */
export function page(a: Answer, limit: number, after: Cursor = {}): { rows: AnswerRow[]; undecided: UndecidedRow[]; next?: Cursor } {
	const slice = <R extends { $id: string }>(all: R[], last: string | undefined): [R[], boolean] => {
		const from = last === undefined ? 0 : all.findIndex((r) => byteOrder(canonicalJson([r.$id]), canonicalJson([last])) > 0);
		const rest = from < 0 ? [] : all.slice(from);
		return [rest.slice(0, limit), rest.length > limit];
	};
	const [rows, moreRows] = slice(a.rows, after.rows);
	const [undecided, moreUndecided] = slice(a.undecided, after.undecided);
	const last = <R extends { $id: string }>(on: R[], before: string | undefined) => (on.length ? on[on.length - 1].$id : before);
	const next: Cursor = {};
	const [r, u] = [last(rows, after.rows), last(undecided, after.undecided)];
	if (r !== undefined) next.rows = r;
	if (u !== undefined) next.undecided = u;
	return { rows, undecided, ...(moreRows || moreUndecided ? { next } : {}) };
}
