// Schema-aware checker for a Rezono module (decisions/language-rezono-1-refinements.md).
// Parses the module, constructs its schema and relation signatures, and typechecks its rezono 1 declarations
// (including R028 on collection path projection over sets). rezono 0 modules keep their existing reader form
// without rezono 1 restrictions.
import { isError, near, typing, type RelationDef, type Typed } from './check.ts';
import type { DerivedDecl } from './module-derived.ts';
import type { ExampleDecl } from './module-example.ts';
import type { FactRow, FactTable } from './module-facts.ts';
import { formOfModule, type FormOf } from './module-json.ts';
import type { SlotDecl } from './module-slot.ts';
import type { StepDecl } from './module-step.ts';
import type { TableValue } from './module-table.ts';
import { parseModule, type Module, type ParseModuleOptions } from './module.ts';
import { inOrder, type Span } from './parse.ts';
import { isOrdered, slotType, snake, STATES, typeOf, type KindDef, type Schema, type SlotDef, type StateName, type Ty, type TypeDef } from './schema.ts';
import type { Expr } from './tree.ts';

export interface CheckModuleOptions extends ParseModuleOptions {
	/** Optional pack-level currency symbol mappings (e.g. from imported standard packs). */
	symbols?: Record<string, string>;
}

/** Derives the narrow Unicode currency sign for an ISO 4217 code declared in the module (if it has one). */
function currencySymbolFor(currency: string): string | undefined {
	if (!/^[A-Z]{3}$/.test(currency)) return undefined;
	try {
		const sym = new Intl.NumberFormat('en-US', {
			style: 'currency',
			currency,
			currencyDisplay: 'narrowSymbol',
		})
			.formatToParts(0)
			.find((p) => p.type === 'currency')?.value;
		if (sym && sym !== '¤' && /^\p{Sc}+$/u.test(sym)) return sym;
	} catch {
		return undefined;
	}
	return undefined;
}

function parseUnitDef(unitName: string, body: string, existing: Record<string, TypeDef>): TypeDef | undefined {
	if (body === 'integer') return { of: 'Integer' };
	const money = /^money(?: (minor))? ([A-Z][A-Za-z0-9]*)(?: per ([a-z][a-z0-9_]*))?$/.exec(body);
	if (money) {
		return { of: 'Money', currency: money[2], scale: money[1] ? '0' : '2', ...(money[3] ? { per: money[3] } : {}) };
	}
	const per = /^([A-Za-z]\w*) per ([A-Za-z]\w*)$/.exec(body);
	if (per) {
		const base = existing[per[1]] ?? Object.values(existing).find((t) => t.unit === per[1]);
		if (base?.of === 'Money') {
			return { of: 'Money', currency: base.currency, scale: base.scale ?? '2', per: per[2] };
		}
	}
	const qty = /^([0-9]+(?:\.[0-9]+)?(?:\/[0-9]+)?) ([A-Za-z]\w*)$/.exec(body);
	if (qty) {
		const base = existing[qty[2]] ?? Object.values(existing).find((t) => t.unit === qty[2]);
		if (base?.of === 'Money') {
			return { of: 'Money', currency: base.currency, scale: '2', ...(base.per ? { per: base.per } : {}) };
		}
		return {
			of: 'Quantity',
			unit: unitName,
			dimension: base?.dimension ?? unitName,
			factor: qty[1],
		};
	}
	const pow = /^([0-9]+)\^([0-9]+) ([A-Za-z]\w*)$/.exec(body);
	if (pow) {
		const base = existing[pow[3]] ?? Object.values(existing).find((t) => t.unit === pow[3]);
		return {
			of: 'Quantity',
			unit: unitName,
			dimension: base?.dimension ?? unitName,
			factor: (BigInt(pow[1]) ** BigInt(pow[2])).toString(),
		};
	}
	return undefined;
}

function slotStates(card: SlotDecl['card'], derived: boolean): StateName[] {
	if (derived) return [...STATES];
	return card === '?' ? ['known', 'not_applicable'] : ['known'];
}

function withinSpan(span: Span, word: string): Span {
	const at = span.text.indexOf(word);
	if (at < 0) return span;
	const start = span.start + [...span.text.slice(0, at)].length;
	return { text: word, start, end: start + [...word].length };
}

function refAtomId(e?: Expr): string | undefined {
	if (!e) return undefined;
	if ('path' in e && e.path.length === 1) return e.path[0];
	if ('lit' in e) {
		if (e.lit === 'n/a' || e.lit.startsWith('unknown ') || e.lit.startsWith('invalid ') || e.lit.startsWith('"')) return undefined;
		const typed = /^[A-Z][A-Za-z0-9]*:`(.*)`$/s.exec(e.lit);
		return typed ? typed[1] : e.lit;
	}
	return undefined;
}

function buildModuleSchema(module: Module, extraSymbols?: Record<string, string>): {
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
	const symbolOwners = new Map<string, string | null>();
	let rounding: Schema['rounding'] | undefined;

	const registerCurrency = (currency: string): void => {
		const sym = currencySymbolFor(currency);
		if (!sym) return;
		const prev = symbolOwners.get(sym);
		if (prev === undefined) symbolOwners.set(sym, currency);
		else if (prev !== currency) symbolOwners.set(sym, null);
	};

	const ensureMoneyType = (typeName: string): void => {
		const money = /^Money<([A-Z][A-Za-z0-9]*)>$/.exec(typeName);
		if (!money) return;
		types[typeName] ??= { of: 'Money', currency: money[1], scale: '2' };
		registerCurrency(money[1]);
	};

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
		ensureMoneyType(typeName);
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
			if (def) {
				types[decl.unit] = def;
				if (def.of === 'Money' && def.currency) registerCurrency(def.currency);
			}
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
			const idSlot = decl.slots.find((s) => s.identifier);
			// In rezono 1, kinds default to world closed.
			kinds[decl.kind] = {
				world: decl.world ?? 'closed',
				id: { type: idSlot ? idSlot.type : 'Text' },
				slots,
				...(decl.parent ? { parent: decl.parent } : {}),
			};
		} else if ('param' in decl) {
			ensureMoneyType(decl.type);
			params[decl.param] = { type: decl.type, states: [...STATES] };
		} else if ('step' in decl) {
			for (const c of decl.columns) ensureMoneyType(c.type);
		}
	}

	// Pass 2a: extend slots/derived (order-independent) and register Money<...> types on module-level derivations.
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
			ensureMoneyType(decl.type);
			for (const p of decl.params ?? []) ensureMoneyType(p.type);
		}
	}

	// Pass 2b: inherit slots transitively from parent kinds (cycle-safe; child slots take precedence).
	const resolvedKinds = new Set<string>();
	const inheritSlots = (kindName: string, visiting: Set<string>): void => {
		if (resolvedKinds.has(kindName) || visiting.has(kindName)) return;
		const kindDef = kinds[kindName];
		if (!kindDef) return;
		visiting.add(kindName);
		const parentName = kindDef.parent;
		if (parentName && kinds[parentName]) {
			inheritSlots(parentName, visiting);
			for (const [slotName, slotDef] of Object.entries(kinds[parentName].slots)) {
				if (!Object.hasOwn(kindDef.slots, slotName)) {
					kindDef.slots[slotName] = slotDef;
				}
			}
		}
		visiting.delete(kindName);
		resolvedKinds.add(kindName);
	};
	for (const kindName of Object.keys(kinds)) {
		inheritSlots(kindName, new Set());
	}

	const symbols: Record<string, string> = {};
	for (const [sym, currency] of symbolOwners) {
		if (currency !== null) symbols[sym] = currency;
	}
	if (extraSymbols) Object.assign(symbols, extraSymbols);

	const schema: Schema = {
		rezono: '1.0',
		pack: module.pack || 'module',
		base: `https://rezono.example/${module.pack || 'module'}/`,
		types,
		enums,
		kinds,
		params,
		symbols,
		...(rounding ? { rounding } : {}),
	};

	// Pass 3: module-level derived relations.
	for (const decl of module.decls) {
		if ('derived' in decl && typeof decl.derived === 'string') {
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

function collectBaseFactIds(module: Module, schema: Schema): Map<string, Set<string>> {
	const baseIds = new Map<string, Set<string>>();
	const resolveKind = (name: string) => Object.keys(schema.kinds).find((k) => k === name || snake(k) === name);
	const addId = (id: string | undefined, kind: string | undefined) => {
		if (!id || !kind) return;
		const set = baseIds.get(id) ?? new Set<string>();
		set.add(kind);
		baseIds.set(id, set);
	};
	const visitFact = (entry: object) => {
		if ('fact' in entry && 'columns' in entry) {
			const table = entry as FactTable;
			const kind = resolveKind(table.fact);
			for (const r of table.rows) addId(refAtomId(r[0] as Expr), kind);
		} else if ('fact' in entry && 'set' in entry) {
			const fr = entry as FactRow;
			addId(fr.id, resolveKind(fr.fact));
		}
	};
	for (const decl of module.decls) {
		visitFact(decl);
		if ('dataset' in decl && 'decls' in decl && Array.isArray((decl as { decls?: unknown }).decls)) {
			for (const entry of (decl as { decls: object[] }).decls) visitFact(entry);
		}
	}
	return baseIds;
}

function kindsWithSlotChain(schema: Schema, slots: string[]): string[] {
	if (!slots.length) return [];
	return Object.keys(schema.kinds)
		.sort()
		.filter((k) => {
			let ty: Ty = { t: 'ref', kind: k };
			return slots.every((s) => {
				if (ty.t !== 'ref') return false;
				const slot = schema.kinds[ty.kind]?.slots[s];
				if (!slot) return false;
				ty = slotType(schema, slot);
				return true;
			});
		});
}

function inferExampleIdKinds(
	schema: Schema,
	baseIds: Map<string, Set<string>>,
	example: ExampleDecl,
): Map<string, string> {
	const candidates = new Map<string, Set<string>>();
	for (const [id, set] of baseIds) candidates.set(id, new Set(set));

	const narrow = (id: string, kinds: string[]) => {
		if (!kinds.length) return;
		const cur = candidates.get(id);
		if (!cur) {
			candidates.set(id, new Set(kinds));
			return;
		}
		const next = new Set(kinds.filter((k) => cur.has(k)));
		if (next.size) candidates.set(id, next);
	};

	for (const g of example.given) {
		if (g.path.length >= 2) narrow(g.path[0], kindsWithSlotChain(schema, g.path.slice(1)));
	}

	// Propagate reference slot targets in `given` assignments until fixed point.
	const maxPasses = example.given.length + 1;
	for (let pass = 0; pass < maxPasses; pass++) {
		let changed = false;
		for (const g of example.given) {
			const [id, ...rest] = g.path;
			const idSet = candidates.get(id);
			if (!idSet || idSet.size !== 1) continue;
			let curKind: string | undefined = [...idSet][0];
			let slotDef: SlotDef | undefined;
			for (const s of rest) {
				slotDef = curKind ? schema.kinds[curKind]?.slots[s] : undefined;
				curKind = slotDef?.ref;
			}
			if (slotDef?.ref) {
				const target = refAtomId(g.value);
				if (target) {
					const beforeSize = candidates.get(target)?.size ?? 0;
					const hadTarget = candidates.has(target);
					narrow(target, [slotDef.ref]);
					if (!hadTarget || (candidates.get(target)?.size ?? 0) !== beforeSize) changed = true;
				}
			}
		}
		if (!changed) break;
	}

	const resolved = new Map<string, string>();
	for (const [id, set] of candidates) {
		if (set.size >= 1) resolved.set(id, [...set].sort()[0]);
	}
	return resolved;
}

/** Parses and schema-checks a Rezono module, enforcing rezono 1 rules where declared. */
export function checkModule(text: string, options?: CheckModuleOptions): FormOf {
	const parsed = parseModule(text, options);
	if (!parsed.module || parsed.diagnostics.some(isError)) return { diagnostics: parsed.diagnostics };
	const { module, spans } = parsed;
	if (module.rezono !== '1') {
		return { form: formOfModule(text, module, spans, options), diagnostics: parsed.diagnostics };
	}

	const { schema, relations, kindNames } = buildModuleSchema(module, options?.symbols);
	const t = typing(text, schema, spans, { rezono1: true, relations });
	const baseFactIds = collectBaseFactIds(module, schema);

	const checkDerivedExpr = (expr: Expr, expectedTy: Ty, expectedSet: boolean): void => {
		const v = t.ex(expr);
		if (v.ty.t === 'err') return;
		if (v.set !== expectedSet && v.ty.t !== 'state') t.report('R005', t.spanOf(expr), []);
		else if (!t.meet(v, expr, t.value(expectedTy), expr)) t.report('R003', t.spanOf(expr), [t.describe(v.ty), t.describe(expectedTy)]);
	};

	const checkDerivedOver = (d: DerivedDecl): void => {
		if (!d.over) return;
		const { relation, args } = d.over;
		const overSpan = t.spanOf(d.over);
		const rel = relations[relation];
		if (rel) {
			if (rel.world === 'open') t.report('R004', overSpan, [relation]);
			if (rel.result.t !== 'bool' || rel.set) {
				t.report('R003', overSpan, [t.describe(rel.result), 'Bool']);
				return;
			}
			if (args.length !== rel.params.length) {
				t.report('R003', overSpan, [relation, String(rel.params.length)]);
				return;
			}
			const paramTypes = new Map(
				(d.params ?? []).map((p) => [p.name, kindNames.has(p.type) ? ({ t: 'ref', kind: p.type } as const) : typeOf(schema, p.type)]),
			);
			for (let i = 0; i < args.length; i++) {
				const argTy = paramTypes.get(args[i]);
				if (!argTy) continue;
				const wantTy = slotType(schema, rel.params[i].slot);
				if (!t.meet(t.value(argTy), d.over, t.value(wantTy), d.over)) {
					t.report('R003', overSpan, [t.describe(argTy), t.describe(wantTy)]);
				}
			}
			return;
		}
		const kindDef = schema.kinds[relation];
		if (kindDef) {
			if (kindDef.world === 'open') t.report('R004', overSpan, [relation]);
			if (args.length !== 1) {
				t.report('R003', overSpan, [relation, '1']);
				return;
			}
			const param = (d.params ?? []).find((p) => p.name === args[0]);
			if (param) {
				const argTy: Ty = kindNames.has(param.type) ? { t: 'ref', kind: param.type } : typeOf(schema, param.type);
				const wantTy: Ty = { t: 'ref', kind: relation };
				if (!t.meet(t.value(argTy), d.over, t.value(wantTy), d.over)) {
					t.report('R003', overSpan, [t.describe(argTy), t.describe(wantTy)]);
				}
			}
			return;
		}
		t.report('R001', withinSpan(overSpan, relation), [relation], {
			suggest: near(relation, [...Object.keys(relations), ...Object.keys(schema.kinds)]),
		});
	};

	const checkDerivedTable = (d: DerivedDecl, expectedTy: Ty): void => {
		const table = d.table;
		if (!table) return;
		const at = t.spanOf(table);
		if (table.table === 'collect' ? d.card !== '*' : d.card === '*' || d.card === '+') {
			t.report('R005', at, []);
		}
		const inputs: (Typed | undefined)[] = [];
		for (const e of table.inputs) {
			const a = t.settled(e);
			if (a.set && a.ty.t !== 'err') t.report('R005', t.spanOf(e), []);
			inputs.push(a.set || a.ty.t === 'err' ? undefined : a);
		}
		const want = t.value(expectedTy);
		for (const row of table.rows) {
			row.tests.forEach((cell, j) => {
				const a = inputs[j];
				if (cell === '-' || !a) return;
				for (const test of cell) {
					const span = t.spanOf(test);
					let good = true;
					const vals = 'lit' in test ? [test] : [test.between.from, test.between.to].filter((v): v is TableValue => v !== undefined);
					for (const v of vals) {
						const b = t.ex(v);
						if (!t.meet(a, table.inputs[j], b, v)) {
							t.report('R003', span, [t.describe(a.ty), t.describe(b.ty)]);
							good = false;
						} else if (b.ty.t === 'err') {
							good = false;
						}
					}
					if (!('lit' in test) && good && !isOrdered(schema, a.ty)) {
						t.report('R003', span, [t.describe(a.ty), test.between.op]);
					}
				}
			});
			const v = t.ex(row.value);
			if (!t.meet(v, row.value, want, row.value)) {
				t.report('R003', t.spanOf(row.value), [t.describe(v.ty), t.describe(expectedTy)]);
			}
		}
	};

	const checkDerivedDecl = (d: DerivedDecl): void => {
		const expectedTy: Ty = kindNames.has(d.type) ? { t: 'ref', kind: d.type } : typeOf(schema, d.type);
		const expectedSet = d.card === '*' || d.card === '+';
		checkDerivedOver(d);
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
		if (d.table) checkDerivedTable(d, expectedTy);
	};

	const checkStepCall = (expr: Expr, requireBool: boolean): void => {
		if ('call' in expr) {
			const [name, args] = expr.call;
			if (relations[name]) {
				if (requireBool) t.truth(expr);
				else t.ex(expr);
				return;
			}
			const kindMatch = Object.keys(schema.kinds).find((k) => snake(k) === name);
			if (kindMatch) {
				if (args.length !== 1) {
					t.report('R003', t.spanOf(expr), [name, '1']);
					return;
				}
				const arg = args[0];
				if (!('wildcard' in arg)) {
					const v = t.ex(arg);
					if (v.set) t.report('R005', t.spanOf(arg), []);
					else {
						const want = t.value({ t: 'ref', kind: kindMatch });
						if (!t.meet(v, arg, want, arg)) t.report('R003', t.spanOf(arg), [t.describe(v.ty), t.describe(want.ty)]);
					}
				}
				return;
			}
			// Report R001 on the unknown callee and still check non-wildcard arguments for errors (e.g. R028).
			t.ex(expr);
			for (const arg of args) {
				if (!('wildcard' in arg)) t.settled(arg);
			}
			return;
		}
		if (requireBool) t.truth(expr);
		else t.settled(expr);
	};

	const checkStepKey = (kind: string, key: Expr, kindDef: KindDef | undefined): void => {
		if (!kindDef) {
			const v = t.settled(key);
			if (v.set && v.ty.t !== 'err') t.report('R005', t.spanOf(key), []);
			return;
		}
		const v = t.ex(key);
		if (v.ty.t === 'err' || v.ty.t === 'state') return;
		if (v.set) {
			t.report('R005', t.spanOf(key), []);
			return;
		}
		const refTy: Ty = { t: 'ref', kind };
		if (v.ty.t === 'ref') {
			if (v.ty.kind !== kind) t.report('R003', t.spanOf(key), [t.describe(v.ty), kind]);
			return;
		}
		if (v.ty.t === 'id' || v.ty.t === 'tok') {
			t.meet(v, key, t.value(refTy), key);
			return;
		}
		const idTy = typeOf(schema, kindDef.id.type);
		if (!t.meet(v, key, t.value(idTy), key)) {
			t.report('R003', t.spanOf(key), [t.describe(v.ty), t.describe(idTy)]);
		}
	};

	const checkStepSlotValue = (kindDef: KindDef | undefined, slotName: string, slotNode: object, valueExpr: Expr): void => {
		if (!kindDef) {
			t.settled(valueExpr);
			return;
		}
		const slotDef = kindDef.slots[slotName];
		if (!slotDef) {
			t.report('R001', withinSpan(t.spanOf(slotNode), slotName), [slotName], {
				suggest: near(slotName, Object.keys(kindDef.slots)),
			});
			t.settled(valueExpr);
			return;
		}
		const v = t.ex(valueExpr);
		if (v.ty.t === 'err') return;
		const many = slotDef.card === '*' || slotDef.card === '+';
		if (v.set && !many && v.ty.t !== 'state') {
			t.report('R005', t.spanOf(valueExpr), []);
			return;
		}
		const expectedTy = slotType(schema, slotDef);
		if (!t.meet(v, valueExpr, t.value(expectedTy), valueExpr)) {
			t.report('R003', t.spanOf(valueExpr), [t.describe(v.ty), t.describe(expectedTy)]);
		}
	};

	const checkStepDecl = (decl: StepDecl): void => {
		const bindings = decl.columns.map((c) => ({
			name: c.name,
			ty: kindNames.has(c.type) ? ({ t: 'ref', kind: c.type } as const) : typeOf(schema, c.type),
		}));
		t.params(bindings, () => {
			t.truth(decl.when);
			for (const f of decl.forbid ?? []) {
				checkStepCall(f.pattern, true);
				checkStepCall(f.within, true);
			}
			for (const change of decl.effect.changes) {
				if ('insert_row' in change) {
					const { kind, key, slots } = change.insert_row;
					const kindDef = schema.kinds[kind];
					if (!kindDef) {
						t.report('R001', withinSpan(t.spanOf(change), kind), [kind], {
							suggest: near(kind, Object.keys(schema.kinds)),
						});
					}
					checkStepKey(kind, key, kindDef);
					for (const s of slots) checkStepSlotValue(kindDef, s.name, s, s.value);
				} else if ('retract_row' in change) {
					const { kind, key } = change.retract_row;
					const kindDef = schema.kinds[kind];
					if (!kindDef) {
						t.report('R001', withinSpan(t.spanOf(change), kind), [kind], {
							suggest: near(kind, Object.keys(schema.kinds)),
						});
					}
					checkStepKey(kind, key, kindDef);
				} else if ('set_slot' in change) {
					const { kind, slot, key, value } = change.set_slot;
					const kindDef = schema.kinds[kind];
					if (!kindDef) {
						t.report('R001', withinSpan(t.spanOf(change), kind), [kind], {
							suggest: near(kind, Object.keys(schema.kinds)),
						});
					}
					checkStepKey(kind, key, kindDef);
					checkStepSlotValue(kindDef, slot, change, value);
				} else {
					const { kind, slot, key } = change.retract_slot;
					const kindDef = schema.kinds[kind];
					if (!kindDef) {
						t.report('R001', withinSpan(t.spanOf(change), kind), [kind], {
							suggest: near(kind, Object.keys(schema.kinds)),
						});
					} else if (!kindDef.slots[slot]) {
						t.report('R001', withinSpan(t.spanOf(change), slot), [slot], {
							suggest: near(slot, Object.keys(kindDef.slots)),
						});
					}
					checkStepKey(kind, key, kindDef);
				}
			}
			checkStepCall(decl.confirm.reader, false);
			const tok = t.settled(decl.confirm.token);
			if (tok.set && tok.ty.t !== 'err') t.report('R005', t.spanOf(decl.confirm.token), []);
		});
	};

	const checkExampleDecl = (decl: ExampleDecl): void => {
		const idKinds = inferExampleIdKinds(schema, baseFactIds, decl);
		const idBindings = [...idKinds.entries()]
			.filter(([id]) => !Object.hasOwn(schema.params ?? {}, id) && !Object.hasOwn(relations, id))
			.map(([id, kind]) => ({ name: id, ty: { t: 'ref', kind } as const }));

		t.params(idBindings, () => {
			for (const g of decl.given) {
				const [root, ...rest] = g.path;
				const rootKind = idKinds.get(root);
				let targetSlot: SlotDef | undefined;
				if (!rootKind) {
					t.report('R001', t.spanOf(g), [rest[0] ?? root]);
				} else {
					let curKind: string | undefined = rootKind;
					let curSet = false;
					for (let i = 0; i < rest.length; i++) {
						const seg = rest[i];
						if (curSet) {
							const baseText = [root, ...rest.slice(0, i)].join('.');
							const projPath = rest.slice(i).join('.');
							t.report('R028', t.spanOf(g), [g.path.join('.'), '1'], {
								hint: { id: 'hint.use_instead', args: [`${baseText}.one(${projPath})`] },
							});
							targetSlot = undefined;
							break;
						}
						const sd: SlotDef | undefined = curKind ? schema.kinds[curKind]?.slots[seg] : undefined;
						if (!sd) {
							t.report('R001', withinSpan(t.spanOf(g), seg), [seg], {
								suggest: curKind ? near(seg, Object.keys(schema.kinds[curKind]?.slots ?? {})) : [],
							});
							targetSlot = undefined;
							break;
						}
						if (sd.card === '*' || sd.card === '+') curSet = true;
						if (i === rest.length - 1) {
							targetSlot = sd;
						} else if (!sd.ref) {
							t.report('R001', withinSpan(t.spanOf(g), rest[i + 1]), [rest[i + 1]]);
							targetSlot = undefined;
							break;
						} else {
							curKind = sd.ref;
						}
					}
				}
				if (targetSlot) {
					const v = t.ex(g.value);
					if (v.ty.t !== 'err') {
						const many = targetSlot.card === '*' || targetSlot.card === '+';
						if (v.set && !many && v.ty.t !== 'state') {
							t.report('R005', t.spanOf(g.value), []);
						} else {
							const expectedTy = slotType(schema, targetSlot);
							if (!t.meet(v, g.value, t.value(expectedTy), g.value)) {
								t.report('R003', t.spanOf(g.value), [t.describe(v.ty), t.describe(expectedTy)]);
							}
						}
					}
				} else {
					t.settled(g.value);
				}
			}

			for (const exp of decl.expect) {
				if ('violation' in exp) continue;
				t.truth(exp);
			}
		});
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
		} else if ('param' in decl) {
			const expectedTy: Ty = kindNames.has(decl.type) ? { t: 'ref', kind: decl.type } : typeOf(schema, decl.type);
			const checkParamBody = () => {
				if (decl.value) checkDerivedExpr(decl.value, expectedTy, false);
				for (const ver of decl.versions ?? []) {
					if (ver.value) checkDerivedExpr(ver.value, expectedTy, false);
				}
			};
			if (decl.per && schema.kinds[decl.per]) t.element(decl.per, checkParamBody);
			else checkParamBody();
		} else if ('check' in decl) {
			const st = typing(text, schema, spans, { rezono1: true, relations });
			st.statement(decl);
			t.found.push(...st.found);
		} else if ('step' in decl) {
			checkStepDecl(decl);
		} else if ('example' in decl) {
			checkExampleDecl(decl);
		}
	}

	const diagnostics = [...parsed.diagnostics, ...t.found].sort(inOrder);
	if (diagnostics.some(isError)) return { diagnostics };
	return { form: formOfModule(text, module, spans, options), diagnostics };
}
