// What a question is checked against: the schema of the role that asks (docs/rezono/expressions.md §5 rule 8,
// §7a rule 2). It is a publication schema document (docs/publication/l0.md §2.1: kinds with their slots, types
// with their dimension, enums), which is also the form of an answer's output schema (§8a), with the three
// things a question can name that are not a slot: rules, parameters and the symbols of money. Whoever hands it
// in has already left out what the role does not read, so nothing here can name or suggest it.
//
// Nothing in this module knows a kind, a unit or a currency: they are all data of the schema.

export type StateName = 'known' | 'not_applicable' | 'unknown' | 'invalid';
/** The states in code order (publication §2.1). */
export const STATES: StateName[] = ['known', 'not_applicable', 'unknown', 'invalid'];
export type World = 'open' | 'closed';

export interface SlotDef {
	/** Exactly one of `type` (a core type or a type of `types`) and `ref` (a kind). */
	type?: string;
	ref?: string;
	card: '1' | '?' | '*' | '+';
	states: StateName[];
	world?: World;
	derived?: boolean;
	inverse?: string;
	min?: string;
	max?: string;
	/** In an answer schema: the printed expression the slot holds (§8a). */
	expr?: string;
}
export interface KindDef {
	world: World;
	id: { type: string };
	slots: Record<string, SlotDef>;
	iri?: string;
	parent?: string;
	plane?: 'control';
	owner?: string;
	tuple_key?: string[];
}
export interface TypeDef {
	of: 'Text' | 'Bool' | 'Integer' | 'Ratio' | 'Date' | 'DateTime' | 'Quantity' | 'Money' | 'Period' | 'Enum' | (string & {});
	min?: string;
	max?: string;
	dimension?: string;
	unit?: string;
	storage_unit?: string;
	factor?: string;
	scale?: string;
	currency?: string;
	per?: string;
	pattern?: string;
	enum?: string;
}
export interface RuleDef {
	/** The binders in the order of the call: `rule fits(h: Host, p: Plan)`. */
	binders: { name: string; ref: string }[];
	/** What a missing row means: `not fits(…)` needs `closed` (§6). */
	world: World;
	/** The truth states a ground call can take: `known` alone for a decided rule. Without it a rule reads as decided. */
	states?: string[];
	/** Whether the publication carries a checked outcome for the rule, keyed by the complete invocation. */
	outcome?: boolean;
}
export interface Schema {
	rezono: '1.0';
	pack: string;
	base: string;
	kinds: Record<string, KindDef>;
	types?: Record<string, TypeDef>;
	enums?: Record<string, string[] | { world: 'open'; values: string[] }>;
	/** Beyond the publication: the rules a question may call. */
	rules?: Record<string, RuleDef>;
	/** Beyond the publication: the parameters a question may read, typed like a slot. */
	params?: Record<string, Pick<SlotDef, 'type' | 'states'>>;
	/** Beyond the publication: the symbol a pack writes before an amount, and its currency (v0 §3). */
	symbols?: Record<string, string>;
	/** Beyond the publication: the pack's one named rounding, which `round(x)` uses (v0 §5f). */
	rounding?: { money?: 'half_even' | 'half_up' | 'down' | 'up' };
	/**
	 * Beyond the publication: per kind, the slots over a relation the role reads in part, or not at all (§7a rule 1).
	 * It follows from the shape of the role's read rules, never from the rows. The document itself
	 * shows it only as `world: open` and the state `unknown`, which a slot can have for other reasons too.
	 */
	in_part?: Record<string, string[]>;
}

/** Why a single value is unknown when the role reads its relation in part: its files cannot tell "no value" from "not yours to read" (§7a rule 1). */
export const NOT_READ_IN_FULL = 'not_read_in_full';
/** Whether the role reads the relation of a slot in part only. Such a relation is open for the role, whatever the pack declares. */
export const inPart = (schema: Schema, kind: string, slot: string): boolean => schema.in_part?.[kind]?.includes(slot) ?? false;

/** The exponent of each base dimension; no member is a plain number. `GiB` is `{data: 1}`, a price per hour `{money EUR: 1, time: -1}`. */
export type Dim = Record<string, number>;

/** The type of an expression. `id` and `tok` wait for the type their context expects (§3, §6). */
export type Ty =
	| { t: 'bool' }
	| { t: 'num'; dim: Dim; name?: string }
	| { t: 'ref'; kind: string }
	| { t: 'val'; name: string }
	| { t: 'id'; text: string; suggest: string[] }
	| { t: 'tok'; text: string }
	| { t: 'state' }
	| { t: 'err' };

const CORE: Record<string, TypeDef['of']> = { Text: 'Text', Bool: 'Bool', Integer: 'Integer', Ratio: 'Ratio', Date: 'Date', DateTime: 'DateTime' };

export const sameDim = (a: Dim, b: Dim): boolean => {
	const keys = new Set([...Object.keys(a), ...Object.keys(b)]);
	return [...keys].every((k) => (a[k] ?? 0) === (b[k] ?? 0));
};
export function mulDim(a: Dim, b: Dim, sign: 1 | -1): Dim {
	const out: Dim = { ...a };
	for (const [k, n] of Object.entries(b)) {
		out[k] = (out[k] ?? 0) + sign * n;
		if (out[k] === 0) delete out[k];
	}
	return out;
}
/** A dimension as a reader sees it: `data`, `money EUR/time`, `number`. */
export function dimText(d: Dim): string {
	const keys = Object.keys(d).sort();
	const part = (ks: string[]) => ks.map((k) => (Math.abs(d[k]) === 1 ? k : `${k}^${Math.abs(d[k])}`)).join('·');
	const up = part(keys.filter((k) => d[k] > 0));
	const down = part(keys.filter((k) => d[k] < 0));
	return up || down ? `${up || '1'}${down ? `/${down}` : ''}` : 'number';
}

/** Whether a type name means something in a schema: a core type, a type of `types`, or a kind. */
export const knownType = (schema: Schema, name: string): boolean => Object.hasOwn(CORE, name) || Object.hasOwn(schema.types ?? {}, name) || Object.hasOwn(schema.kinds, name);

/** Follows `schema.types[name].of` through any alias chain to its base type name (cycle-safe). */
export function baseTypeOf(schema: Schema, name: string): string {
	let cur = name;
	const seen = new Set<string>();
	while (!seen.has(cur)) {
		seen.add(cur);
		const next = schema.types?.[cur]?.of;
		if (!next) break;
		cur = next;
	}
	return cur;
}

/** The type that a type name of the schema stands for; a name the schema does not explain is a type of its own. */
export function typeOf(schema: Schema, name: string): Ty {
	let cur = name;
	let def: TypeDef | undefined;
	const seen = new Set<string>();
	while (!seen.has(cur)) {
		seen.add(cur);
		const next = schema.types?.[cur];
		if (!next) break;
		def = next;
		cur = next.of;
	}
	def ??= CORE[name] ? { of: CORE[name] } : undefined;
	if (!def) return schema.kinds[name] ? { t: 'ref', kind: name } : { t: 'val', name };
	if (def.of === 'Bool') return { t: 'bool' };
	if (def.of === 'Integer' || def.of === 'Ratio') return { t: 'num', dim: {}, name };
	if (def.of === 'Quantity') return { t: 'num', dim: def.dimension ? { [def.dimension]: 1 } : {}, name };
	if (def.of === 'Money') {
		const money: Dim = { [`money ${def.currency ?? ''}`.trim()]: 1 };
		const per = def.per === undefined ? undefined : unitOf(schema, def.per);
		return { t: 'num', dim: per ? mulDim(money, per.dim, -1) : money, name };
	}
	return { t: 'val', name };
}

/** The type a unit word names (`GiB` in `384 GiB`, `h` in `730 h`): the type with that unit, or a type of that name that has no unit of its own. */
export function unitOf(schema: Schema, word: string): { name: string; dim: Dim } | undefined {
	const types = schema.types ?? {};
	const name = Object.keys(types).sort().find((n) => types[n].unit === word) ?? (types[word] && types[word].unit === undefined ? word : undefined);
	if (name === undefined) return undefined;
	const ty = typeOf(schema, name);
	return ty.t === 'num' ? { name, dim: ty.dim } : undefined;
}

/** The type of a slot or a parameter. */
export const slotType = (schema: Schema, slot: Pick<SlotDef, 'type' | 'ref'>): Ty => (slot.ref !== undefined ? { t: 'ref', kind: slot.ref } : typeOf(schema, slot.type ?? 'Text'));

/** Whether a type has a built-in total order: numbers (including quantities and money), dates, and instants. */
export function isOrdered(schema: Schema, ty: Ty): boolean {
	if (ty.t === 'num') return true;
	if (ty.t !== 'val') return false;
	const base = baseTypeOf(schema, ty.name);
	return base === 'Date' || base === 'DateTime';
}

/** The implicit binder of a kind: its name in snake case (§5 rule 1). */
export const snake = (kind: string): string => kind.replace(/(?<=[a-z0-9])(?=[A-Z])/g, '_').toLowerCase();
