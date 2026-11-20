// The output schema of an `ask` (docs/rezono/expressions.md §8a): a publication schema document
// (docs/publication/l0.md §2.1, §7.1) generated from the question and the schema it was checked against. An
// answer names it in `$schema`, so a client gets the types of an answer without guessing.
//
// Kind `Answer` has the slot `binder` and one slot `c1`, `c2`, … per shown expression, each with its type, the
// states typing gives it and the printed expression in `expr`; kind `Undecided` has the binder, the state, the
// reason and the cause. The names are fixed, so no name of the question can collide with them. The types and
// kinds of the pack are named through the import `p`, pinned on the pack schema's id.
import { canonicalSha256 } from '../../viewer/src/lib/canon.ts';
import type { Checked, Typed } from './check.ts';
import { questionHash } from './normal.ts';
import { dimText, sameDim, STATES, typeOf, type KindDef, type Schema, type SlotDef, type TypeDef } from './schema.ts';
import type { Ask } from './tree.ts';

/** A schema document with the members an answer schema has. */
export interface AnswerSchema {
	rezono: '1.0';
	pack: string;
	base: string;
	imports: Record<string, { pack: string; schema: string }>;
	kinds: { Answer: KindDef; Undecided: KindDef };
	types: Record<string, TypeDef>;
	enums: Record<string, string[]>;
}

const CORE = new Set(['Text', 'Bool', 'Integer', 'Ratio', 'Date', 'DateTime']);

/** The id of a schema document: `s-` and the canonical hash of the document (publication §2.2). */
export const schemaId = async (document: object): Promise<string> => `s-${await canonicalSha256(document)}`;

/** The the publication document of a schema: without what a question needs beyond it. */
export function dataSchema(schema: Schema): object {
	const { rules: _rules, params: _params, symbols: _symbols, rounding: _rounding, in_part: _inPart, default_units: _defaultUnits, ...document } = schema;
	return document;
}

/**
 * The output schema of a checked `ask`; undefined when the check found an error. `pack` is the pack's whole
 * schema, which the question hash in `base` is taken against (normal.ts, O10); by default the role's.
 */
export async function outputSchema(q: Ask, checked: Checked, schema: Schema, pack: Schema = schema): Promise<AnswerSchema | undefined> {
	const { answer } = checked;
	if (!answer) return undefined;
	const types: Record<string, TypeDef> = {
		Reason: { of: 'Text', pattern: '([a-z][a-z0-9_]*)?' },
		UndecidedState: { of: 'Enum', enum: 'UndecidedState' }
	};
	const named = (name: string) => (CORE.has(name) ? name : `p.${name}`);
	/** The slot of a value: its type or kind, and the states it can take, in code order. */
	function slot(v: Typed): SlotDef {
		const states = STATES.filter((s) => s === 'known' || v.states.has(s));
		const of = { card: states.includes('not_applicable') ? ('?' as const) : ('1' as const), states };
		const ty = v.ty;
		if (ty.t === 'ref') return { ref: named(ty.kind), ...of };
		if (ty.t === 'bool') return { type: 'Bool', ...of };
		if (ty.t === 'val') return { type: named(ty.name), ...of };
		if (ty.t !== 'num') return { type: 'Text', ...of };
		if (ty.name !== undefined) return { type: named(ty.name), ...of };
		if (!Object.keys(ty.dim).length) return { type: 'Ratio', ...of };
		// A computed quantity takes the pack's first type of its dimension; without one, a type of its own.
		const declared = Object.keys(schema.types ?? {})
			.sort()
			.find((n) => {
				const t = typeOf(schema, n);
				return t.t === 'num' && sameDim(t.dim, ty.dim);
			});
		if (declared !== undefined) return { type: named(declared), ...of };
		// Its unit is the product of the storage units of its dimensions, so its values are exact as they stand.
		const base = (dimension: string) => Object.values(schema.types ?? {}).find((t) => t.dimension === dimension)?.storage_unit ?? dimension.replace(/^money /, '');
		const unit = dimText(Object.fromEntries(Object.entries(ty.dim).map(([d, n]) => [base(d), n])));
		const own = `Q${Object.keys(types).length - 1}`;
		types[own] = { of: 'Quantity', dimension: dimText(ty.dim), unit, storage_unit: unit, factor: '1' };
		return { type: own, ...of };
	}
	const id = { type: named(schema.kinds[answer.kind].id.type) };
	const binder: SlotDef = { ref: named(answer.kind), card: '1', states: ['known'] };
	const text: SlotDef = { type: 'Text', card: '1', states: ['known'] };
	const shown = answer.shown.map((s, i) => [`c${i + 1}`, { ...slot(s.typed), expr: s.text }] as const);
	return {
		rezono: '1.0',
		pack: schema.pack,
		base: `${schema.base}ask/${await questionHash(checked, pack)}/`,
		imports: { p: { pack: schema.pack, schema: await schemaId(dataSchema(schema)) } },
		kinds: {
			Answer: { world: 'closed', id, slots: { binder: { ...binder, expr: answer.binder }, ...Object.fromEntries(shown) } },
			Undecided: {
				world: 'closed',
				id,
				slots: { binder, state: { type: 'UndecidedState', card: '1', states: ['known'] }, reason: { ...text, type: 'Reason' }, cause_relation: text, cause_key: text }
			}
		},
		types,
		enums: { UndecidedState: ['unknown', 'invalid'] }
	};
}
