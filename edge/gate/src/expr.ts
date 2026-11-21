// Translate the role's schema and bounded snapshot reader to the Rezono question evaluator.
import { answer, byteOrder, check, isAsk, isError, load, NotEvaluated, outputSchema, page, print, printContext, questionHash, schemaId, type AnswerRow, type AnswerSchema, type Checked, type Context, type Cursor, type Diagnostic, type Expr, type Schema, type SlotDef, type TypeDef, type UndecidedRow, type World } from '../../../rezono/src/index.ts';
import { inPart, NOT_READ_IN_FULL, snake } from '../../../rezono/src/schema.ts';
import { canonicalJson } from '../../../viewer/src/lib/canon.ts';
import type { Bundle } from '../../../contracts/typescript/generated/bundle.ts';
import { ANSWER, AskError } from './ask.ts';
import { NotLoaded, OverBudget, type Data, type RowRef as EvalRowRef, type V } from '../../../rezono/src/evaluate.ts';
import type { CalcWitness, RowRef, Witness } from '../../../contracts/typescript/generated/proof.ts';
import type { Source } from '../../../contracts/typescript/generated/explain.ts';
import type { Key } from './pieces.ts';

/** The reason of a value missing from a relation the role does not read in full: one word, the role's Rezono Data form's and the evaluation's (O8). */
export { NOT_READ_IN_FULL };
/** The most rows one call of the reader gives (the row route's own limit). */
const PAGE = 1000;
/** Rezono's integer storage (docs/compiler.md, Tables): the bounds of an integer type that declares none. */
const BIGINT = ['-9223372036854775808', '9223372036854775807'];
const RULE_COLUMN_TYPES: Record<string, string> = { string: 'Text', integer: 'Integer', boolean: 'Bool' };
const ID_STORAGE: Record<string, string> = { text: 'string', integer: 'integer' };

type BundleKind = {
	id: string;
	class: string;
	parent?: string;
	iri?: string;
	world?: unknown;
	id_type?: unknown;
	plane?: unknown;
	owner?: string;
};
type BundleSlot = {
	id: string;
	kind: string;
	name: string;
	table: string;
	target?: string;
	type?: string;
	schema_type?: string;
	enum?: string;
	minimum?: string;
	maximum?: string;
	patterns?: string[];
	multivalued?: boolean;
	required?: boolean;
	world?: unknown;
};
type BundleSemantic = {
	case?: unknown;
	base?: unknown;
	target?: unknown;
};
type BundleColumn = {
	name: string;
	type?: unknown;
	semantic?: BundleSemantic | null;
};
type BundleRelation = {
	id: string;
	world?: unknown;
	columns: BundleColumn[];
};
const worldOf = (value: unknown): World | undefined => (value === 'open' || value === 'closed' ? value : undefined);

/** Rows of one relation of the role, in key order: at most `limit` after `after`, and the last key while there are more. */
export type Read = (relation: string, ask: { prefix: Key; after?: Key; limit: number }) => Promise<{ rows: unknown[]; next?: Key }>;

/** A snapshot entry of the role's manifest, as far as a question needs it. */
export interface Listed {
	relation?: string;
	complete?: boolean;
	full?: boolean;
}

/** What a role reads of a pack, as a question sees it. */
export interface View {
	schema: Schema;
	/** Per kind of the schema: the relation of its rows; for a derived relation also its columns, in key order. */
	kinds: Map<string, { relation: string; columns?: string[] }>;
	/** Per kind and slot: the relation of the slot's values, and whether the role reads all of it. */
	slots: Map<string, Map<string, { relation: string; partial: boolean }>>;
	/** The relations the role has a snapshot of: no other relation is ever asked of the reader. */
	reads: Set<string>;
	/** The kinds of a tree with a subkind (§2.1 `parent`): in the schema, and not yet read by a question. */
	trees: Set<string>;
	/** Optional explicit `place_slot` declared on a kind or derived relation in the bundle. */
	placeSlots?: Map<string, string>;
}

const pascal = (name: string): string =>
	name
		.split('_')
		.filter((p) => p)
		.map((p) => p[0].toUpperCase() + p.slice(1))
		.join('');
/**
 * A part of the pack that has no Rezono Data form yet: nothing is answered over a schema that leaves a part out.
 * A subkind has a form; a question that reads a kind of its tree is refused in `ask` instead (`View.trees`).
 */
const notYet = (what: string): AskError => new AskError(501, `${what}: no Rezono Data form yet, so no question is answered over this pack`);

/**
 * The schema of a role and where its rows are. A kind, a slot or a derived relation over a relation the role
 * does not read in full is open, and a single-valued slot over one also takes `unknown`.
 */
export function roleSchema(bundle: Bundle, snapshots: Listed[]): View {
	const reads = new Set<string>();
	const full = new Set<string>();
	for (const s of snapshots) {
		if (s.relation === undefined) continue;
		reads.add(s.relation);
		if (s.complete || s.full) full.add(s.relation);
	}
	const partial = (relation: string): boolean => !full.has(relation);
	// The pack's own base (§2.1), as the form takes it; a pack.yaml that declares no `iri:` gets the default.
	const base = bundle.pack.base || `https://rezono.example/${bundle.pack.id}/`;
	const view: View = { schema: { rezono: '1.0', pack: bundle.pack.id, base, kinds: {} }, kinds: new Map(), slots: new Map(), reads, trees: new Set(), placeSlots: new Map() };
	const { kinds } = view.schema;
	const types: Record<string, TypeDef> = {};
	const usedEnums = new Set<string>();
	const classOf = new Map<string, string>();
	const allKinds = (bundle.kinds ?? []) as unknown as BundleKind[];
	const byAll = new Map(allKinds.map((k) => [k.id, k]));
	/** The kind and the kinds above it, nearest first, by the bundle's `parent` (`_chain`). */
	const chain = (id: string): string[] => {
		const out: string[] = [];
		for (let at: string | null | undefined = id; at; at = byAll.get(at)!.parent) {
			if (!byAll.has(at) || out.includes(at)) throw notYet(`kind ${out[0] ?? at}: its parents do not end at a root kind`);
			out.push(at);
		}
		return out;
	};
	/** Per kind, by class: the kind and every kind below it, which restate each of its slots (§2.1 `parent`). */
	const family = new Map<string, string[]>();
	const visible = allKinds.filter((k) => reads.has(k.id));
	for (const k of visible) {
		// The world sits on the root kind: a subkind shares its parent's tables (docs/compiler.md, W6).
		const world = chain(k.id).map((c) => worldOf(byAll.get(c)!.world)).find((w) => w !== undefined) ?? 'closed';
		kinds[k.class] = { world: partial(k.id) ? 'open' : world, id: { type: 'Text' }, slots: {} };
		// A kind's own IRI, when it is not the default under the base (§2.1: the default is never written).
		if (k.iri !== undefined && k.iri !== `${base}${k.class}`) kinds[k.class].iri = k.iri;
		if (k.parent && reads.has(k.parent)) kinds[k.class].parent = byAll.get(k.parent)!.class;
		classOf.set(k.id, k.class);
		view.kinds.set(k.class, { relation: k.id });
		view.slots.set(k.class, new Map());
		const placeSlot = (k as { place_slot?: unknown }).place_slot;
		if (typeof placeSlot === 'string' && placeSlot.length > 0) view.placeSlots?.set(k.class, placeSlot);
		family.set(k.class, visible.filter((x) => chain(x.id).includes(k.id)).map((x) => x.class));
	}
	// Every kind of a tree that has a subkind: an element of a subkind is an element of each kind above it, which
	// the evaluation does not read yet, so a question that reads any kind of such a tree is not answered (`ask`).
	const roots = new Set(visible.filter((k) => chain(k.id).slice(1).some((c) => reads.has(c))).map((k) => chain(k.id).at(-1)));
	for (const k of visible) if (roots.has(chain(k.id).at(-1))) view.trees.add(k.class);
	const byId = (x: { id: string }, y: { id: string }): number => (x.id < y.id ? -1 : x.id > y.id ? 1 : 0);
	const allSlots = [...((bundle.attributes ?? []) as unknown as BundleSlot[]), ...((bundle.arrows ?? []) as unknown as BundleSlot[])];
	for (const a of [...allSlots].sort(byId)) {
		const declared = classOf.get(a.kind);
		if (!declared || !reads.has(a.table) || (a.target !== undefined && !classOf.has(a.target))) continue;
		const slot: SlotDef = { card: a.multivalued ? (a.required ? '+' : '*') : a.required ? '1' : '?', states: ['known'] };
		if (a.target !== undefined) slot.ref = classOf.get(a.target)!;
		else if (a.type === 'enum') {
			slot.type = pascal(a.enum!);
			types[slot.type] = { of: 'Enum', enum: a.enum };
			if (a.enum) usedEnums.add(a.enum);
		} else if (a.type === 'integer') {
			slot.type = a.schema_type && a.schema_type !== 'integer' ? pascal(a.schema_type) : `${declared}${pascal(a.name)}`;
			types[slot.type] = { of: 'Integer', min: a.minimum || BIGINT[0], max: a.maximum || BIGINT[1] };
		} else if (a.type === 'date') slot.type = 'Date';
		else if (a.type === 'boolean') slot.type = 'Bool';
		else if (a.type === 'text') {
			if (a.patterns?.length) {
				if (a.patterns.length !== 1) throw notYet(`${a.id} has more than one pattern`);
				if (!a.schema_type) throw notYet(`${a.id} has no schema_type`);
				const type: TypeDef = { of: 'Text', pattern: a.patterns[0] };
				let typeName = pascal(a.schema_type);
				if (Object.hasOwn(types, typeName) && canonicalJson(types[typeName]) !== canonicalJson(type)) {
					if (a.schema_type !== 'string') throw notYet(`${a.id}: a second type named ${typeName}`);
					typeName = `${declared}${pascal(a.name)}`;
					if (Object.hasOwn(types, typeName) && canonicalJson(types[typeName]) !== canonicalJson(type)) {
						throw notYet(`${a.id}: a second type named ${typeName}`);
					}
				}
				slot.type = typeName;
				types[slot.type] = type;
			} else slot.type = 'Text';
		} else throw notYet(`${a.id} has type ${a.type}`);
		// What the role cannot read in full is never closed over (O8); only a closed, optional slot read in full
		// can establish absence from a missing row (§3.3).
		const world = partial(a.table) ? 'open' : (worldOf(a.world) ?? 'closed');
		slot.states = ['known'];
		if (!a.multivalued) {
			if (!a.required) slot.states.push('not_applicable');
			if (a.required || world === 'open') slot.states.push('unknown');
		}
		// The kind that declares the slot, and each kind below it, restates it (each its own copy, as the form writes it).
		for (const kind of family.get(declared)!) {
			if (Object.hasOwn(kinds[kind].slots, a.name)) throw notYet(`${a.id}: ${kind} has two slots ${a.name}`);
			if (partial(a.table)) ((view.schema.in_part ??= {})[kind] ??= []).push(a.name);
			kinds[kind].slots[a.name] = { ...slot, states: [...slot.states], ...(world !== kinds[kind].world ? { world } : {}) };
			view.slots.get(kind)!.set(a.name, { relation: a.table, partial: partial(a.table) });
		}
	}
	// A kind of decided values (DV1, §3.7) carries its marker and owner; its decision is always known when read in full.
	for (const kind of visible.filter((k) => k.plane === 'control').sort(byId)) {
		const decision = kinds[kind.class].slots.decision;
		const table = allSlots.find((a) => a.kind === kind.id && a.name === 'decision')?.table;
		if (decision !== undefined && table !== undefined && !partial(kind.id) && !partial(table)) {
			if (typeof kind.owner !== 'string' || !kind.owner) throw notYet(`kind ${kind.id}: control kind declares no owner`);
			for (const name of family.get(kind.class)!) {
				kinds[name].slots.decision.states = ['known'];
				kinds[name].plane = 'control';
				kinds[name].owner = kind.owner;
			}
		}
	}
	const columnSlot = (relation: string, column: BundleColumn): Pick<SlotDef, 'type' | 'ref' | 'min' | 'max'> => {
		const where = `${relation}.${column.name}`;
		const physical = column.type;
		if (typeof physical !== 'string' || !Object.hasOwn(RULE_COLUMN_TYPES, physical)) {
			throw notYet(`${where}: unsupported rule column type ${JSON.stringify(physical)}`);
		}
		const scalar: Pick<SlotDef, 'type' | 'min' | 'max'> = physical === 'integer'
			? { type: RULE_COLUMN_TYPES[physical], min: BIGINT[0], max: BIGINT[1] }
			: { type: RULE_COLUMN_TYPES[physical] };
		const semantic = column.semantic;
		if (semantic === undefined || semantic === null) return scalar;
		if (typeof semantic !== 'object' || Array.isArray(semantic) || semantic.base !== physical) {
			throw notYet(`${where}: its semantic type does not store a ${physical}`);
		}
		if (semantic.case === 'scalar') return scalar;
		if (semantic.case === 'ref') {
			const target = semantic.target;
			if (typeof target !== 'string' || !classOf.has(target)) {
				throw notYet(`${where}: refers to ${JSON.stringify(target)}, which is not a kind of the bundle`);
			}
			const idType = byAll.get(chain(target).at(-1)!)?.id_type;
			if (typeof idType !== 'string' || !Object.hasOwn(ID_STORAGE, idType) || ID_STORAGE[idType] !== physical) {
				throw notYet(`${where}: the identifier of ${target} is not stored as a ${physical}`);
			}
			return { ref: classOf.get(target)! };
		}
		throw notYet(`${where}: a ${JSON.stringify(semantic.case)} column is not written as a publication yet`);
	};
	for (const r of (bundle.relations ?? []) as unknown as BundleRelation[]) {
		if (!reads.has(r.id)) continue;
		const name = pascal(r.id);
		if (Object.hasOwn(kinds, name)) throw notYet(`derived relation ${r.id} has the name of a kind`);
		const slots: Record<string, SlotDef> = {};
		const columns: string[] = [];
		for (const column of r.columns) {
			if (Object.hasOwn(slots, column.name)) throw notYet(`${r.id}: two columns \`${column.name}\``);
			slots[column.name] = { ...columnSlot(r.id, column), card: '1', states: ['known'], derived: true };
			columns.push(column.name);
		}
		kinds[name] = {
			world: partial(r.id) ? 'open' : (worldOf(r.world) ?? 'closed'),
			id: { type: 'Text' },
			slots,
			tuple_key: columns
		};
		view.kinds.set(name, { relation: r.id, columns });
		view.slots.set(name, new Map());
		const placeSlot = (r as { place_slot?: unknown }).place_slot;
		if (typeof placeSlot === 'string' && placeSlot.length > 0) view.placeSlots?.set(name, placeSlot);
	}
	if (Object.keys(types).length) view.schema.types = types;
	const enums = (bundle.enums ?? []).filter((e) => usedEnums.has(e.id) || reads.has(e.id));
	if (enums.length) view.schema.enums = Object.fromEntries(enums.map((e) => [e.id, e.values.map((v) => v.slice(v.indexOf('.') + 1))]));
	return view;
}

/**
 * The kinds and slots whose rows a checked text can read: the kind asked, every kind it names or whose
 * elements it reaches, and of each of them the slots whose name stands anywhere in the text. That is more than
 * the evaluation reads, never less: a slot is only ever read by its name, from an element of a kind reached so.
 */
export function wanted(checked: Checked, view: View): Map<string, Set<string>> {
	const names = new Set<string>();
	const walk = (x: unknown): void => {
		if (typeof x === 'string') names.add(x);
		else if (typeof x === 'object' && x !== null) Object.values(x).forEach(walk);
	};
	walk(checked.tree);
	const { kinds } = view.schema;
	const out = new Map<string, Set<string>>();
	const todo: string[] = [];
	const touch = (kind: string): void => {
		if (!kinds[kind] || out.has(kind)) return;
		out.set(kind, new Set());
		todo.push(kind);
	};
	if (checked.answer) touch(checked.answer.kind);
	names.forEach(touch);
	Object.values(checked.resolve).forEach(touch);
	for (const t of checked.typed.values()) if (t.ty.t === 'ref') touch(t.ty.kind);
	while (todo.length) {
		const kind = todo.pop()!;
		for (const [name, slot] of Object.entries(kinds[kind].slots)) {
			if (!names.has(name)) continue;
			out.get(kind)!.add(name);
			if (slot.ref === undefined) continue;
			touch(slot.ref);
			// An inverse slot is read from its forward slot, on the kind it points to.
			if (slot.inverse !== undefined) out.get(slot.ref)?.add(slot.inverse);
		}
	}
	return out;
}

/** The budget was passed: the question reads more rows than one request may. */
export class Cut extends Error {}

/** The largest integer a JSON number holds exactly (Rezono Data §3.2, LD2). */
const SAFE = 9007199254740991n;
const INT = /^(?:0|-?[1-9][0-9]*)$/;
type BoundedType = TypeDef & { min?: unknown; max?: unknown };

/**
 * Follows own `schema.types[cur].of` links to the base type name and visited definitions.
 * Returns `undefined` on any cycle, missing/non-string `of`, or prototype key (fail-closed).
 */
function resolveTypeChain(schema: Schema, name: string): { base: string; chain: BoundedType[] } | undefined {
	if (typeof name !== 'string' || !name) return undefined;
	const types = schema.types;
	if (types !== undefined && (types === null || typeof types !== 'object' || Array.isArray(types))) return undefined;
	const seen = new Set<string>();
	const chain: BoundedType[] = [];
	let cur = name;
	while (true) {
		if (cur === 'prototype' || cur in Object.prototype || seen.has(cur)) return undefined;
		seen.add(cur);
		if (!types || !Object.hasOwn(types, cur)) return { base: cur, chain };
		const def = types[cur] as BoundedType | undefined;
		if (!def || typeof def !== 'object' || Array.isArray(def)) return undefined;
		const of = Object.hasOwn(def, 'of') ? (def as { of?: unknown }).of : undefined;
		if (typeof of !== 'string' || !of) return undefined;
		chain.push(def);
		cur = of;
	}
}
/** LD2: a value of an integer type that declares both bounds within ±(2⁵³ − 1) is a JSON number; every other integer is a string. */
function asNumber(schema: Schema, slot: SlotDef): boolean {
	if (slot.ref !== undefined || slot.type === undefined) return false;
	const resolved = resolveTypeChain(schema, slot.type);
	if (!resolved || resolved.base !== 'Integer') return false;
	let lo: bigint | undefined;
	let hi: bigint | undefined;
	// Walk from the outermost parent down to the slot's type so every hop's bounds are validated and children cannot widen parents.
	for (let i = resolved.chain.length - 1; i >= 0; i--) {
		const def = resolved.chain[i];
		const rawMin = Object.hasOwn(def, 'min') ? def.min : undefined;
		const rawMax = Object.hasOwn(def, 'max') ? def.max : undefined;
		if (rawMin !== undefined) {
			if (typeof rawMin !== 'string' || !INT.test(rawMin)) return false;
			const nextLo = BigInt(rawMin);
			if (lo !== undefined && nextLo < lo) return false;
			lo = nextLo;
		}
		if (rawMax !== undefined) {
			if (typeof rawMax !== 'string' || !INT.test(rawMax)) return false;
			const nextHi = BigInt(rawMax);
			if (hi !== undefined && nextHi > hi) return false;
			hi = nextHi;
		}
		if (lo !== undefined && hi !== undefined && lo > hi) return false;
	}
	return lo !== undefined && hi !== undefined && -SAFE <= lo && lo <= hi && hi <= SAFE;
}
function asBoolean(schema: Schema, slot: SlotDef): boolean {
	if (slot.ref !== undefined || slot.type === undefined) return false;
	return resolveTypeChain(schema, slot.type)?.base === 'Bool';
}
function parseBooleanValue(where: string, raw: string): boolean {
	if (raw === 'true') return true;
	if (raw === 'false') return false;
	throw new AskError(500, `${where} holds an invalid boolean value`);
}
function parseBoolean(relation: string, parts: string[]): boolean {
	if (parts.length !== 2) throw new AskError(500, `${relation} holds a malformed boolean row`);
	return parseBooleanValue(relation, parts[1]);
}
function parseSafeInteger(relation: string, parts: string[]): number {
	if (parts.length !== 2) throw new AskError(500, `${relation} holds a malformed integer row`);
	if (!INT.test(parts[1])) throw new AskError(500, `${relation} holds an invalid integer value`);
	const n = Number(parts[1]);
	if (!Number.isSafeInteger(n)) throw new AskError(500, `${relation} holds an out-of-range integer value`);
	return n;
}

/**
 * The rows of the wanted kinds and slots as Row JSON (Rezono Data §3), read through `read` and counted against
 * `budget.left`. A slot's row for an element the role has no row of is not the role's to place and is left out.
 * Each wanted slot of each row is written as the role's Rezono Data form writes it, value for value
 * (rezono_data/publication.py, `row_json`): the answer names that form's schema.
 */
export async function rowsOf(view: View, want: Map<string, Set<string>>, read: Read, budget: { left: number }): Promise<Record<string, unknown>[]> {
	const all = async (relation: string): Promise<string[][]> => {
		const out: string[][] = [];
		if (!view.reads.has(relation)) return out;
		for (let after: Key | undefined; ; ) {
			const { rows, next } = await read(relation, { prefix: [], ...(after ? { after } : {}), limit: Math.min(PAGE, budget.left + 1) });
			budget.left -= rows.length;
			if (budget.left < 0) throw new Cut();
			for (const r of rows) out.push((r as { key: Key }).key.map(String));
			if (!next) return out;
			// A reader that names a next page and gives no row is a defect: never answer the rows so far as the whole.
			if (!rows.length) throw new AskError(500, `the reader of ${relation} names a next page and gives no row`);
			after = next;
		}
	};
	const out: Record<string, unknown>[] = [];
	for (const kind of [...want.keys()].sort()) {
		const { relation, columns } = view.kinds.get(kind)!;
		if (columns) {
			const slots = view.schema.kinds[kind].slots;
			for (const parts of await all(relation)) {
				if (parts.length !== columns.length) throw new AskError(500, `${relation} holds a malformed derived row`);
				out.push({
					$kind: kind,
					$id: canonicalJson(parts),
					...Object.fromEntries(columns.map((c, i) => [
						c,
						slots[c].ref !== undefined
							? { $ref: parts[i] }
							: asBoolean(view.schema, slots[c])
								? parseBooleanValue(`${relation}.${c}`, parts[i])
								: parts[i]
					]))
				});
			}
			continue;
		}
		const elements = new Map<string, Record<string, unknown>>();
		for (const [id] of await all(relation)) elements.set(id, { $kind: kind, $id: id });
		for (const name of [...want.get(kind)!].sort()) {
			const at = view.slots.get(kind)!.get(name);
			// An inverse slot has no rows of its own.
			if (!at) continue;
			const slot = view.schema.kinds[kind].slots[name];
			const many = slot.card === '*' || slot.card === '+';
			const number = asNumber(view.schema, slot);
			const bool = asBoolean(view.schema, slot);
			for (const parts of await all(at.relation)) {
				const [id, v] = parts;
				const row = elements.get(id);
				if (!row) continue;
				const value = slot.ref !== undefined ? { $ref: v } : bool ? parseBoolean(at.relation, parts) : number ? parseSafeInteger(at.relation, parts) : v;
				if (many) ((row[name] ??= []) as unknown[]).push(value);
				else if (name in row) throw new AskError(500, `${at.relation} holds two values for one element`);
				else row[name] = value;
			}
			// What the relation does not hold for an element is written out (Rezono Data §3.3). A set without a
			// member is `[]`. A single value the role's part of the relation does not hold may be one the role
			// does not read: unknown, whatever the slot's cardinality. Over a relation read in full, absence is
			// the state of its cardinality.
			const absent = many ? undefined : at.partial ? { $unknown: NOT_READ_IN_FULL } : slot.states.includes('unknown') ? { $unknown: '' } : { $na: '' };
			for (const row of elements.values()) if (!(name in row)) row[name] = absent ?? [];
		}
		out.push(...elements.values());
	}
	return out;
}

/** The active place, valid-time, and knowledge-time restriction of an `ask` answer. */
export interface AskRestriction {
	default: boolean;
	at: string | null;
	during: string | null;
	as_known: string | null;
	resolved_manifest: string | null;
	knowledge_time: string | null;
}

/** An undecided row as `rezono.answer/1` carries it (contracts/explain.yaml, UndecidedRow). */
export interface Undecided {
	binder: string;
	state: 'unknown' | 'invalid';
	reason?: string;
	cause?: RowRef;
}
/** One page of the answer of an `ask … where`. */
export interface ExprAnswer {
	format: typeof ANSWER;
	/** The form asked: an expression has no term of the bundle, it has a hash. */
	question: 'ask';
	manifest_id: string;
	/** The question: the hash of its normal form (decision Q21) and its text as written, printed in the normal form of §9. */
	expression: { hash: string; text: string };
	/** The warnings of the check; an error gives no answer. */
	diagnostics: Diagnostic[];
	/** The active restriction (or default scope) and resolved manifest. */
	restriction: AskRestriction;
	/** The binder row of each answer row on this page, at distance 0. */
	nodes: { relation: string; key: string; distance: 0; sources?: Source[] }[];
	witnesses: Witness[];
	calc_witnesses?: CalcWitness[];
	output_schema: string;
	counts: { rows: number; undecided: number; not_applicable: number };
	undecided: Undecided[];
	/** The cursor of the next page: the query parameter `after`. */
	next?: string;
	/** The page as a dataset of the output schema (§8a): the `Answer` rows, then the `Undecided` rows, as Row JSON. */
	dataset: { $schema: string; schema: AnswerSchema; rows: (AnswerRow | UndecidedRow)[] };
}
/** What asking gives: an answer, the diagnostics of a text that does not check, or the budget that was passed and its limit. */
export type Asked = { answer: ExprAnswer } | { refused: Diagnostic[] } | { cut: { budget: 'rows' | 'steps'; limit: number } };

export interface Asking {
	/** The text of one `ask`. */
	text: string;
	manifest: string;
	knowledgeTime?: string | null;
	view: View;
	read: Read;
	/**
	 * The most rows this request may read, and the most steps its evaluation may take. Both count only what the
	 * role's reader gave, so a cut is the same in two publications whose role views are equal.
	 */
	budget: { rows: number; steps: number };
	/** The most `Answer` rows, and the most `Undecided` rows, on the page. */
	limit: number;
	/** The cursor a page before gave in `next`. */
	after?: string;
}

const ISO_DATE_RE = /^(\d{4})-(\d{2})-(\d{2})$/;
const ISO_MONTH_RE = /^(\d{4})-(\d{2})$/;
const ISO_YEAR_RE = /^(\d{4})$/;
const NO_VERSION_APPLIES = 'no_version_applies';
const BEFORE_FIRST_KNOWN = 'before_first_known';

/** Returns `text` when it is a valid ISO-8601 calendar date (`YYYY-MM-DD`), otherwise undefined. */
export function parseIsoDate(text: string): string | undefined {
	const m = ISO_DATE_RE.exec(text);
	if (!m) return undefined;
	const y = Number(m[1]), mo = Number(m[2]), d = Number(m[3]);
	if (mo < 1 || mo > 12 || d < 1 || d > 31) return undefined;
	const dt = new Date(Date.UTC(y, mo - 1, d));
	dt.setUTCFullYear(y);
	if (dt.getUTCFullYear() !== y || dt.getUTCMonth() !== mo - 1 || dt.getUTCDate() !== d) return undefined;
	return text;
}

function nextDay(iso: string): string {
	const [y, mo, d] = iso.split('-').map(Number);
	const dt = new Date(Date.UTC(y, mo - 1, d + 1));
	return `${String(dt.getUTCFullYear()).padStart(4, '0')}-${String(dt.getUTCMonth() + 1).padStart(2, '0')}-${String(dt.getUTCDate()).padStart(2, '0')}`;
}

/** Parses an ISO date, month, year, closed range (`..`), or half-open range (`..<`) into `[start, end)`. */
export function parsePeriodText(text: string): { start: string; end: string } | undefined {
	const rangeMatch = /^(.+?)(\.\.<|\.\.)(.+)$/.exec(text);
	if (rangeMatch) {
		const [, left, op, right] = rangeMatch;
		const a = parsePeriodText(left.trim());
		const b = parsePeriodText(right.trim());
		if (!a || !b) return undefined;
		const start = a.start;
		const end = op === '..<' ? b.start : b.end;
		return start < end ? { start, end } : undefined;
	}
	if (parseIsoDate(text)) return { start: text, end: nextDay(text) };
	const ym = ISO_MONTH_RE.exec(text);
	if (ym) {
		const y = Number(ym[1]), mo = Number(ym[2]);
		if (mo < 1 || mo > 12) return undefined;
		const start = `${ym[1]}-${ym[2]}-01`;
		const end = mo === 12
			? `${String(y + 1).padStart(4, '0')}-01-01`
			: `${ym[1]}-${String(mo + 1).padStart(2, '0')}-01`;
		return { start, end };
	}
	const yr = ISO_YEAR_RE.exec(text);
	if (yr) {
		const y = Number(yr[1]);
		return { start: `${yr[1]}-01-01`, end: `${String(y + 1).padStart(4, '0')}-01-01` };
	}
	return undefined;
}

/** Extracts the string value of an atom expression (`path` or `lit`) for `at`/`during`/`as known` contexts. */
export function contextAtomText(e: Expr, what: string): string {
	if ('path' in e && e.path.length === 1) return e.path[0];
	if ('lit' in e) {
		const raw = e.lit;
		if (raw.startsWith('"') && raw.endsWith('"')) {
			try {
				const parsed = JSON.parse(raw);
				if (typeof parsed === 'string') return parsed;
			} catch {
				// fall through
			}
		}
		return raw;
	}
	throw new AskError(400, `${what} expects a literal or identifier`);
}

function parsePeriodExpr(e: Expr): { start: string; end: string } {
	const parsed = 'range' in e
		? parsePeriodText(`${contextAtomText(e.range[0], 'during period')}${e.range[1]}${contextAtomText(e.range[2], 'during period')}`)
		: parsePeriodText(contextAtomText(e, 'during period'));
	if (!parsed) throw new AskError(400, 'invalid during period');
	return parsed;
}

/** Builds the `restriction` summary object for an `ask` response. */
export function restrictionOf(
	context: Context | undefined,
	resolvedManifest: string | null,
	knowledgeTime: string | null
): AskRestriction {
	const at = context?.at ? printContext({ at: context.at })[0].slice('at '.length) : null;
	const during = context?.during ? printContext({ during: context.during })[0].slice('during '.length) : null;
	const as_known = context?.as_known ? printContext({ as_known: context.as_known })[0].slice('as known '.length) : null;
	return {
		default: at === null && during === null && as_known === null,
		at,
		during,
		as_known,
		resolved_manifest: resolvedManifest,
		knowledge_time: knowledgeTime
	};
}

interface ResolvedRestrictions {
	place?: { slot: string; target: string };
	period?: {
		query: { start: string; end: string };
		mode: 'bounds' | 'period';
		validFromSlot: string;
		validUntilSlot?: string;
		periodSlot?: string;
	};
}

/** Validates `at` and `during` context clauses against `view` and returns the resolved slot bindings. */
export function resolveAskRestrictions(checked: Checked, view: View): ResolvedRestrictions {
	const tree = checked.tree;
	if (!tree || !isAsk(tree)) return {};
	const askedKind = checked.answer!.kind;
	const slots = view.schema.kinds[askedKind]?.slots ?? {};
	const out: ResolvedRestrictions = {};

	if (tree.context?.at) {
		const placeSlot = view.placeSlots?.get(askedKind) ?? 'place';
		const def = slots[placeSlot];
		if (!def || def.card === '*' || def.card === '+') {
			throw new AskError(400, `kind ${askedKind} does not support at restriction without a single-valued ${placeSlot} slot`);
		}
		out.place = { slot: placeSlot, target: contextAtomText(tree.context.at, 'at place') };
	}

	if (tree.context?.during) {
		const query = parsePeriodExpr(tree.context.during);
		const vf = slots.valid_from;
		const vu = slots.valid_until;
		const ps = slots.period;
		if (vf && vf.card !== '*' && vf.card !== '+') {
			out.period = {
				query,
				mode: 'bounds',
				validFromSlot: 'valid_from',
				...(vu && vu.card !== '*' && vu.card !== '+' ? { validUntilSlot: 'valid_until' } : {})
			};
		} else if (ps && ps.card !== '*' && ps.card !== '+') {
			out.period = { query, mode: 'period', validFromSlot: 'period', periodSlot: 'period' };
		} else {
			throw new AskError(400, `kind ${askedKind} does not support during restriction without validity bounds`);
		}
	}

	return out;
}

const RANK_STATE: Record<'not_applicable' | 'unknown' | 'invalid', number> = { not_applicable: 1, unknown: 2, invalid: 3 };
type NonKnownV = Extract<V, { s: 'not_applicable' | 'unknown' | 'invalid' }>;

function worstNonKnown(a: NonKnownV, b: NonKnownV): NonKnownV {
	if (RANK_STATE[a.s] !== RANK_STATE[b.s]) return RANK_STATE[a.s] > RANK_STATE[b.s] ? a : b;
	const cmp = byteOrder(a.reason, b.reason) || Number(a.cause !== undefined) - Number(b.cause !== undefined);
	if (cmp !== 0 || !a.cause || !b.cause) return cmp <= 0 ? a : b;
	return (byteOrder(a.cause.relation, b.cause.relation) || byteOrder(canonicalJson(a.cause.key), canonicalJson(b.cause.key))) <= 0 ? a : b;
}

function applyDomainRestrictions(
	view: View,
	askedKind: string,
	data: Data,
	restrictions: ResolvedRestrictions
): Map<string, V> | undefined {
	if (!restrictions.place && !restrictions.period) return undefined;
	const kindRows = data.kinds.get(askedKind);
	if (!kindRows) return undefined;
	const { schema } = view;
	const of = view.kinds.get(askedKind)!;
	const slots = schema.kinds[askedKind].slots;
	const domain = new Map<string, V>();

	const rowCause = (slotName: string, id: string): EvalRowRef =>
		of.columns
			? { relation: of.relation, key: JSON.parse(id) as string[] }
			: { relation: view.slots.get(askedKind)?.get(slotName)?.relation ?? `${snake(askedKind)}__${slotName}`, key: [id] };

	const missingSlotState = (slotName: string, id: string): V => {
		const slot = slots[slotName];
		const cause = rowCause(slotName, id);
		if (inPart(schema, askedKind, slotName)) return { s: 'unknown', reason: NOT_READ_IN_FULL, cause };
		return { s: slot.card === '?' ? 'not_applicable' : 'unknown', reason: '', cause };
	};

	const readSingleCell = (cells: Map<string, unknown>, slotName: string, id: string): V => {
		const raw = cells.get(slotName);
		if (raw === undefined) return missingSlotState(slotName, id);
		if (Array.isArray(raw)) return { s: 'invalid', reason: '', cause: rowCause(slotName, id) };
		return raw as V;
	};

	for (const [id, cells] of [...kindRows.entries()]) {
		let placeState: V = { s: 'known', v: true };
		if (restrictions.place) {
			const cell = readSingleCell(cells, restrictions.place.slot, id);
			if (cell.s === 'known') {
				const placeVal = typeof cell.v === 'string'
					? cell.v
					: (typeof cell.v === 'object' && cell.v !== null && 'id' in cell.v ? (cell.v as { id: string }).id : undefined);
				if (placeVal !== restrictions.place.target) {
					kindRows.delete(id);
					continue;
				}
			} else if (cell.s === 'not_applicable') {
				kindRows.delete(id);
				continue;
			} else {
				placeState = cell;
			}
		}

		let validState: V = { s: 'known', v: true };
		if (restrictions.period) {
			const { query, mode, validFromSlot, validUntilSlot, periodSlot } = restrictions.period;
			if (mode === 'period' && periodSlot) {
				const pCell = readSingleCell(cells, periodSlot, id);
				if (pCell.s === 'unknown' || pCell.s === 'invalid') {
					validState = pCell;
				} else if (pCell.s === 'not_applicable') {
					validState = { s: 'unknown', reason: NO_VERSION_APPLIES, cause: rowCause(periodSlot, id) };
				} else {
					const parsed = parsePeriodText(String(pCell.v));
					if (!parsed) throw new AskError(500, 'invalid period value');
					if (!(parsed.start <= query.start && query.end <= parsed.end)) {
						validState = { s: 'unknown', reason: NO_VERSION_APPLIES, cause: rowCause(periodSlot, id) };
					}
				}
			} else {
				const vfCell = readSingleCell(cells, validFromSlot, id);
				if (vfCell.s === 'unknown' || vfCell.s === 'invalid') {
					validState = vfCell;
				} else if (vfCell.s === 'not_applicable') {
					validState = { s: 'unknown', reason: NO_VERSION_APPLIES, cause: rowCause(validFromSlot, id) };
				} else {
					const rStart = parseIsoDate(String(vfCell.v));
					if (!rStart) throw new AskError(500, 'invalid valid_from date');
					if (query.end <= rStart || rStart > query.start) {
						validState = { s: 'unknown', reason: NO_VERSION_APPLIES, cause: rowCause(validFromSlot, id) };
					} else if (validUntilSlot) {
						const vuCell = readSingleCell(cells, validUntilSlot, id);
						if (vuCell.s === 'not_applicable') {
							validState = { s: 'known', v: true };
						} else if (vuCell.s === 'unknown' || vuCell.s === 'invalid') {
							validState = vuCell;
						} else {
							const rEnd = parseIsoDate(String(vuCell.v));
							if (!rEnd) throw new AskError(500, 'invalid valid_until date');
							if (rEnd <= rStart) {
								validState = { s: 'invalid', reason: 'interval_inverted', cause: rowCause(validUntilSlot, id) };
							} else if (query.end <= rEnd) {
								validState = { s: 'known', v: true };
							} else {
								validState = { s: 'unknown', reason: NO_VERSION_APPLIES, cause: rowCause(validUntilSlot, id) };
							}
						}
					}
				}
			}

			if (validState.s === 'unknown' && validState.reason === NO_VERSION_APPLIES) {
				for (const [slotName, slotDef] of Object.entries(slots)) {
					if (slotDef.inverse === undefined) cells.set(slotName, validState);
				}
			}
		}

		if (placeState.s !== 'known' && validState.s !== 'known') {
			domain.set(id, worstNonKnown(placeState, validState));
		} else if (placeState.s !== 'known') {
			domain.set(id, placeState);
		} else if (validState.s !== 'known') {
			domain.set(id, validState);
		}
	}

	return domain;
}

function cursorOf(text: string | undefined): Cursor {
	if (text === undefined) return {};
	let c: unknown;
	try {
		c = JSON.parse(text);
	} catch {
		c = undefined;
	}
	const ok = (x: unknown): boolean => x === undefined || typeof x === 'string';
	if (typeof c !== 'object' || c === null || Array.isArray(c) || !ok((c as Cursor).rows) || !ok((c as Cursor).undecided)) throw new AskError(400, 'after is not a cursor of an answer');
	const { rows, undecided } = c as Cursor;
	return { ...(rows === undefined ? {} : { rows }), ...(undecided === undefined ? {} : { undecided }) };
}

/**
 * Constructs a `rezono.answer/1` response when `as known on <date>` precedes the earliest published epoch:
 * every visible binder row of the asked kind (or `["*"]` if none exist yet) is returned as `unknown before_first_known`.
 */
export async function beforeFirstKnownAnswer(a: Asking): Promise<Asked> {
	if (!Number.isInteger(a.limit) || a.limit < 1) throw new AskError(400, 'limit is a whole number of at least 1');
	const after = cursorOf(a.after);
	const { schema } = a.view;
	const checked = check(a.text, schema, { allowContext: true });
	if (checked.diagnostics.some(isError) || !checked.tree) return { refused: checked.diagnostics };
	const tree = checked.tree;
	if (!isAsk(tree)) throw new AskError(400, 'the text is not an ask');
	resolveAskRestrictions(checked, a.view);
	const askedKind = checked.answer!.kind;
	const want = wanted(checked, a.view);
	const inTree = [...want.keys()].sort().find((kind) => a.view.trees.has(kind));
	if (inTree !== undefined) throw new AskError(501, `kind ${inTree} is in a tree of kinds with a subkind: a question that reads it is not evaluated yet`);
	const of = a.view.kinds.get(askedKind)!;

	const ids: string[] = [];
	let budgetLeft = a.budget.rows;
	if (a.view.reads.has(of.relation)) {
		for (let nextAfter: Key | undefined; ;) {
			const pageRows = await a.read(of.relation, { prefix: [], ...(nextAfter ? { after: nextAfter } : {}), limit: Math.min(PAGE, budgetLeft + 1) });
			budgetLeft -= pageRows.rows.length;
			if (budgetLeft < 0) return { cut: { budget: 'rows', limit: a.budget.rows } };
			for (const r of pageRows.rows) {
				const parts = (r as { key: Key }).key.map(String);
				ids.push(of.columns ? canonicalJson(parts) : parts[0]);
			}
			if (!pageRows.next) break;
			if (!pageRows.rows.length) throw new AskError(500, `the reader of ${of.relation} names a next page and gives no row`);
			nextAfter = pageRows.next;
		}
	}
	const binderIds = ids.length ? [...new Set(ids)].sort((x, y) => byteOrder(canonicalJson([x]), canonicalJson([y]))) : ['*'];
	const doc = (await outputSchema(tree, checked, schema))!;
	const $schema = await schemaId(doc);
	const allUndecided: UndecidedRow[] = binderIds.map((id) => ({
		$kind: 'Undecided',
		$id: id,
		binder: { $ref: `${doc.imports.p.pack}@${doc.imports.p.schema}:${askedKind}/${id}` },
		state: 'unknown',
		reason: BEFORE_FIRST_KNOWN,
		cause_relation: '',
		cause_key: ''
	}));
	const whole = {
		$schema,
		schema: doc,
		rows: [],
		undecided: allUndecided,
		counts: { rows: 0, undecided: allUndecided.length, not_applicable: 0 }
	};
	const on = page(whole, a.limit, after);
	return {
		answer: {
			format: ANSWER,
			question: 'ask',
			manifest_id: a.manifest,
			expression: { hash: await questionHash(checked, schema), text: print(tree) },
			diagnostics: checked.diagnostics,
			restriction: restrictionOf(tree.context, null, null),
			nodes: [],
			witnesses: [],
			output_schema: $schema,
			counts: whole.counts,
			undecided: on.undecided.map((u) => ({
				binder: u.$id,
				state: u.state,
				...(u.reason ? { reason: u.reason } : {})
			})),
			...(on.next ? { next: canonicalJson(on.next) } : {}),
			dataset: { $schema, schema: doc, rows: on.undecided }
		}
	};
}

/**
 * Answers one `ask` for one role. A text that does not check is refused with its diagnostics and reads no row
 * (§8b). Every page is a slice of the one answer over the role's view, so two publications whose role views
 * are equal give the same bytes (§7a rule 5).
 */
export async function ask(a: Asking): Promise<Asked> {
	if (!Number.isInteger(a.limit) || a.limit < 1) throw new AskError(400, 'limit is a whole number of at least 1');
	const after = cursorOf(a.after);
	const { schema } = a.view;
	const checked = check(a.text, schema, { allowContext: true });
	if (checked.diagnostics.some(isError) || !checked.tree) return { refused: checked.diagnostics };
	const tree = checked.tree;
	if (!isAsk(tree)) throw new AskError(400, 'the text is not an ask');
	const restrictions = resolveAskRestrictions(checked, a.view);
	const askedKind = checked.answer!.kind;
	const want = wanted(checked, a.view);
	if (restrictions.place) want.get(askedKind)!.add(restrictions.place.slot);
	if (restrictions.period) {
		want.get(askedKind)!.add(restrictions.period.validFromSlot);
		if (restrictions.period.validUntilSlot) want.get(askedKind)!.add(restrictions.period.validUntilSlot);
	}
	const inTree = [...want.keys()].sort().find((kind) => a.view.trees.has(kind));
	if (inTree !== undefined) throw new AskError(501, `kind ${inTree} is in a tree of kinds with a subkind: a question that reads it is not evaluated yet`);
	let rows: Record<string, unknown>[];
	try {
		rows = await rowsOf(a.view, want, a.read, { left: a.budget.rows });
	} catch (e) {
		if (e instanceof Cut) return { cut: { budget: 'rows', limit: a.budget.rows } };
		throw e;
	}
	let whole;
	try {
		// The evaluation is told what was read for it: a slot it reads and `wanted` did not name is refused,
		// never read as a value that is not there.
		const data = load(schema, rows, { only: want });
		const domain = applyDomainRestrictions(a.view, askedKind, data, restrictions);
		whole = await answer(checked, schema, data, { steps: a.budget.steps }, schema, domain);
	} catch (e) {
		if (e instanceof OverBudget) return { cut: { budget: 'steps', limit: a.budget.steps } };
		if (e instanceof NotLoaded) throw new AskError(500, `the question reads what was not loaded for it: ${e.message}`);
		if (e instanceof NotEvaluated) throw new AskError(501, `the question checks and is not evaluated yet: ${e.message}`);
		throw e;
	}
	if (!whole) throw new AskError(500, 'a checked ask gave no answer');
	// The evaluation names a cause by kind and slot; the role reads it under the relation's own name.
	const relations = new Map<string, string>();
	for (const [kind, slots] of a.view.slots) for (const [name, at] of slots) relations.set(`${snake(kind)}__${name}`, at.relation);
	const on = page(whole, a.limit, after);
	const undecided = on.undecided.map((u) => ({ ...u, cause_relation: relations.get(u.cause_relation) ?? u.cause_relation }));
	const of = a.view.kinds.get(askedKind)!;
	return {
		answer: {
			format: ANSWER,
			question: 'ask',
			manifest_id: a.manifest,
			// Bind the question hash to the role's schema.
			expression: { hash: await questionHash(checked, schema), text: print(tree) },
			diagnostics: checked.diagnostics,
			restriction: restrictionOf(tree.context, a.manifest, a.knowledgeTime ?? null),
			nodes: on.rows.map((r) => ({ relation: of.relation, key: of.columns ? r.$id : canonicalJson([r.$id]), distance: 0 })),
			witnesses: [],
			output_schema: whole.$schema,
			counts: whole.counts,
			undecided: undecided.map((u) => ({
				binder: u.$id,
				state: u.state,
				...(u.reason ? { reason: u.reason } : {}),
				...(u.cause_relation ? { cause: { relation: u.cause_relation, key: u.cause_key } } : {})
			})),
			...(on.next ? { next: canonicalJson(on.next) } : {}),
			dataset: { $schema: whole.$schema, schema: whole.schema, rows: [...on.rows, ...undecided] }
		}
	};
}
