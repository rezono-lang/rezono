// Schema-aware checker for a Rezono module (decisions/language-rezono-1-refinements.md).
// Parses the module, constructs its schema and relation signatures, and typechecks its rezono 1 declarations
// (including R028 on collection path projection over sets). rezono 0 modules keep their existing reader form
// without rezono 1 restrictions.
import { isError, typing, type RelationDef } from './check.ts';
import type { DerivedDecl } from './module-derived.ts';
import { formOfModule, type FormOf } from './module-json.ts';
import type { SlotDecl } from './module-slot.ts';
import { parseModule, type Module, type ParseModuleOptions } from './module.ts';
import { inOrder } from './parse.ts';
import { STATES, typeOf, type KindDef, type Schema, type SlotDef, type StateName, type Ty, type TypeDef } from './schema.ts';
import type { Expr } from './tree.ts';

function parseUnitDef(unitName: string, body: string, existing: Record<string, TypeDef>): TypeDef | undefined {
	if (body === 'integer') return { of: 'Integer' };
	const money = /^money(?: (minor))? ([A-Z][A-Za-z0-9]*)(?: per ([a-z][a-z0-9_]*))?$/.exec(body);
	if (money) {
		return { of: 'Money', currency: money[2], scale: money[1] ? '0' : '2', ...(money[3] ? { per: money[3] } : {}) };
	}
	const qty = /^([0-9]+(?:\.[0-9]+)?(?:\/[0-9]+)?) ([A-Za-z]\w*)$/.exec(body);
	if (qty) {
		const base = existing[qty[2]] ?? Object.values(existing).find((t) => t.unit === qty[2]);
		return {
			of: 'Quantity',
			unit: unitName,
			dimension: base?.dimension ?? unitName,
			factor: qty[1],
		};
	}
	return undefined;
}

function slotStates(card: SlotDecl['card'], derived: boolean): StateName[] {
	if (derived) return [...STATES];
	return card === '?' ? ['known', 'not_applicable'] : ['known'];
}

function buildModuleSchema(module: Module): {
	schema: Schema;
	relations: Record<string, RelationDef>;
	kindNames: Set<string>;
} {
	const types: Record<string, TypeDef> = {
		Int: { of: 'Integer' },
		Rational: { of: 'Ratio' },
	};
	const enums: Record<string, string[] | { world: 'open'; values: string[] }> = {};
	const kinds: Record<string, KindDef> = {};
	const params: Record<string, Pick<SlotDef, 'type' | 'states'>> = {};
	const relations: Record<string, RelationDef> = {};
	const kindNames = new Set<string>();
	let rounding: Schema['rounding'] | undefined;

	for (const decl of module.decls) {
		if ('kind' in decl) kindNames.add(decl.kind);
	}

	const slotDefFor = (
		typeName: string,
		card: SlotDecl['card'],
		world?: SlotDecl['world'],
		inverse?: string,
		derived = false,
	): SlotDef => {
		const base: SlotDef = kindNames.has(typeName)
			? { ref: typeName, card: card ?? '1', states: slotStates(card, derived) }
			: { type: typeName, card: card ?? '1', states: slotStates(card, derived) };
		if (world) base.world = world;
		if (inverse) base.inverse = inverse.includes('.') ? inverse.split('.').pop()! : inverse;
		if (derived) base.derived = true;
		return base;
	};

	// Pass 1: types, enums, rounding, params, and kinds with their declared slots and derived members.
	for (const decl of module.decls) {
		if ('unit' in decl) {
			const def = parseUnitDef(decl.unit, decl.is, types);
			if (def) types[decl.unit] = def;
		} else if ('base' in decl && 'type' in decl) {
			types[decl.type] = { of: decl.base };
		} else if ('enum' in decl) {
			types[decl.enum] = { of: 'Enum' };
			enums[decl.enum] = decl.world === 'open' ? { world: 'open', values: decl.values } : decl.values;
		} else if ('rounding' in decl && decl.rounding === 'money') {
			rounding = { money: decl.mode as NonNullable<Schema['rounding']>['money'] };
		} else if ('kind' in decl) {
			const slots: Record<string, SlotDef> = {};
			for (const s of decl.slots) {
				slots[s.slot] = slotDefFor(s.type, s.card, s.world, s.inverse, false);
			}
			for (const d of decl.derived) {
				slots[d.derived] = slotDefFor(d.type, d.card, undefined, undefined, true);
			}
			// In rezono 1, kinds default to world closed.
			kinds[decl.kind] = { world: decl.world ?? 'closed', id: { type: 'Text' }, slots };
		} else if ('param' in decl) {
			params[decl.param] = { type: decl.type, states: [...STATES] };
		}
	}

	const schema: Schema = {
		rezono: '1.0',
		pack: module.pack || 'module',
		base: `https://rezono.example/${module.pack || 'module'}/`,
		types,
		enums,
		kinds,
		params,
		symbols: {},
		...(rounding ? { rounding } : {}),
	};

	// Pass 2: extend slots/derived (order-independent) and module-level derived relations.
	for (const decl of module.decls) {
		if ('extend' in decl) {
			const k = kinds[decl.extend];
			if (k) {
				for (const s of decl.slots ?? []) {
					k.slots[s.slot] = slotDefFor(s.type, s.card, s.world, s.inverse, false);
				}
				for (const d of decl.derived) {
					k.slots[d.derived] = slotDefFor(d.type, d.card, undefined, undefined, true);
				}
			}
		} else if ('derived' in decl && typeof decl.derived === 'string') {
			const result: Ty = kindNames.has(decl.type) ? { t: 'ref', kind: decl.type } : typeOf(schema, decl.type);
			relations[decl.derived] = {
				params: (decl.params ?? []).map((p) => ({
					name: p.name,
					slot: slotDefFor(p.type, undefined, undefined, undefined, false),
				})),
				result,
				set: decl.card === '*' || decl.card === '+',
				world: 'closed',
				states: [...STATES],
			};
		}
	}

	return { schema, relations, kindNames };
}

/** Parses and schema-checks a Rezono module, enforcing rezono 1 rules where declared. */
export function checkModule(text: string, options?: ParseModuleOptions): FormOf {
	const parsed = parseModule(text, options);
	if (!parsed.module || parsed.diagnostics.some(isError)) return { diagnostics: parsed.diagnostics };
	const { module, spans } = parsed;
	if (module.rezono !== '1') {
		return { form: formOfModule(text, module, spans, options), diagnostics: parsed.diagnostics };
	}

	const { schema, relations, kindNames } = buildModuleSchema(module);
	const t = typing(text, schema, spans, { rezono1: true, relations });

	const checkDerivedExpr = (expr: Expr, expectedTy: Ty, expectedSet: boolean): void => {
		const v = t.ex(expr);
		if (v.ty.t === 'err') return;
		if (v.set !== expectedSet && v.ty.t !== 'state') t.report('R005', t.spanOf(expr), []);
		else if (!t.meet(v, expr, t.value(expectedTy), expr)) t.report('R003', t.spanOf(expr), [t.describe(v.ty), t.describe(expectedTy)]);
	};

	const checkDerivedDecl = (d: DerivedDecl): void => {
		const expectedTy: Ty = kindNames.has(d.type) ? { t: 'ref', kind: d.type } : typeOf(schema, d.type);
		const expectedSet = d.card === '*' || d.card === '+';
		if (d.value) checkDerivedExpr(d.value, expectedTy, expectedSet);
		for (const group of d.unless ?? []) {
			for (const clause of group) {
				t.truth(clause.when);
				checkDerivedExpr(clause.then, expectedTy, expectedSet);
			}
		}
		for (const def of d.definitions ?? []) {
			t.truth(def.when);
			checkDerivedExpr(def.value, expectedTy, expectedSet);
		}
		for (const ver of d.versions ?? []) {
			if (ver.value) checkDerivedExpr(ver.value, expectedTy, expectedSet);
			for (const group of ver.unless ?? []) {
				for (const clause of group) {
					t.truth(clause.when);
					checkDerivedExpr(clause.then, expectedTy, expectedSet);
				}
			}
			for (const def of ver.definitions ?? []) {
				t.truth(def.when);
				checkDerivedExpr(def.value, expectedTy, expectedSet);
			}
		}
	};

	for (const decl of module.decls) {
		if ('kind' in decl) {
			t.element(decl.kind, () => {
				for (const d of decl.derived) checkDerivedDecl(d);
				for (const c of decl.checks ?? []) {
					t.truth(c.when);
					t.truth(c.then);
				}
			});
		} else if ('extend' in decl && schema.kinds[decl.extend]) {
			t.element(
				decl.extend,
				() => {
					for (const d of decl.derived) checkDerivedDecl(d);
				},
				decl.binder,
			);
		} else if ('derived' in decl && typeof decl.derived === 'string') {
			const bindings = (decl.params ?? []).map((p) => ({
				name: p.name,
				ty: kindNames.has(p.type) ? ({ t: 'ref', kind: p.type } as const) : typeOf(schema, p.type),
			}));
			t.params(bindings, () => checkDerivedDecl(decl));
		} else if ('check' in decl) {
			t.statement(decl);
		}
	}

	const diagnostics = [...parsed.diagnostics, ...t.found].sort(inOrder);
	if (diagnostics.some(isError)) return { diagnostics };
	return { form: formOfModule(text, module, spans, options), diagnostics };
}
