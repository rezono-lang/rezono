// Two-knowledge-date comparison for Rezono (`ask ... as known D1` vs `as known D2`),
// reusing `rezono.turns/1` to report changed rows (before/after values and states)
// and the amended rule, parameter, or fact version causing each turn
// (decisions/language-rezono-1.md §1; docs/rezono/v0.md §5a, §5b).

import { canonicalJson } from '../../viewer/src/lib/canon.ts';
import { isError, typing, type Head, type Typed } from './check.ts';
import {
	amount,
	byteOrder,
	factor,
	reader,
	type Cell,
	type Data,
	type Frac,
	type RowRef,
	type V,
} from './evaluate.ts';
import type { DefinitionDecl } from './module-derived.ts';
import type { FactCell, FactRow, FactTable } from './module-facts.ts';
import type { ExtendDecl, KindDecl } from './module-kind.ts';
import type { ParamDecl } from './module-parameter.ts';
import {
	parseModule,
	type Clause,
	type DerivedDecl,
	type Module,
	type TableTest,
	type TableValue,
	type Valid,
	type VersionDecl,
} from './module.ts';
import { parse } from './parse.ts';
import { printExpr } from './print.ts';
import {
	slotType,
	snake,
	type KindDef,
	type Schema,
	type SlotDef,
	type StateName,
	type Ty,
	type TypeDef,
} from './schema.ts';
import { isAsk, type Ask, type Expr } from './tree.ts';

export interface CompareAsKnownOptions {
	question: string;
	beforeKnown: string;
	afterKnown: string;
	validAt?: string;
}

export interface VersionAmendmentCause {
	cause: 'version' | 'definition' | 'state' | 'presence' | 'value';
	target?: 'param' | 'derived' | 'fact';
	name?: string;
	kind?: string;
	property?: string;
	key?: string;
	slot?: string;
	before_version?: string;
	after_version?: string;
	replaces?: string;
	before_known?: string;
	after_known?: string;
	before_definition?: string;
	after_definition?: string;
	before_state?: StateName;
	after_state?: StateName;
	source?: string;
}

export interface TurnSide {
	present: boolean;
	state: StateName;
	reason?: string;
	values?: Record<string, unknown>;
	states?: Record<string, { state: StateName; reason?: string }>;
}

export interface KnowledgeTurn {
	relation: string;
	key: string;
	before: TurnSide;
	after: TurnSide;
	causes: VersionAmendmentCause[];
}

export interface KnowledgeComparison {
	format: 'rezono.turns/1';
	question: string;
	kind: string;
	valid_at?: string;
	before: { as_known: string; rows: number; undecided: number };
	after: { as_known: string; rows: number; undecided: number };
	turns: KnowledgeTurn[];
}

interface VersionChoice {
	target: 'param' | 'derived' | 'fact';
	name: string;
	kind?: string;
	property?: string;
	key?: string;
	slot?: string;
	version?: string;
	replaces?: string;
	known?: string;
	source?: string;
	state: StateName;
	reason?: string;
}

interface EvalTrace {
	versions: Map<string, VersionChoice>;
	definitions: Map<string, string>;
}

interface VersionedFactEntry {
	version: string;
	valid?: Valid;
	known?: string;
	value: Expr;
	source?: string;
}

interface ModuleModel {
	module: Module;
	schema: Schema;
	params: Map<string, ParamDecl>;
	derived: Map<string, Map<string, DerivedDecl>>;
	appliesAt: Map<string, string>;
	baseKinds: Map<string, Map<string, Map<string, Cell>>>;
	versionedFacts: Map<string, Map<string, Map<string, VersionedFactEntry[]>>>;
	tableWhen: Map<object, Expr[][]>;
	typed: Map<object, Typed>;
	heads: Map<object, Head>;
}

const CORE_TYPE_MAP: Record<string, string> = {
	Int: 'Integer',
	Integer: 'Integer',
	Text: 'Text',
	Bool: 'Bool',
	Ratio: 'Ratio',
	Date: 'Date',
	DateTime: 'DateTime',
};

const CORE_OF_MAP: Record<string, TypeDef['of']> = {
	Int: 'Integer',
	Integer: 'Integer',
	Text: 'Text',
	Bool: 'Bool',
	Ratio: 'Ratio',
	Date: 'Date',
	DateTime: 'DateTime',
};

function mapTypeName(name: string, types: Record<string, TypeDef>): string {
	if (name in CORE_TYPE_MAP) return CORE_TYPE_MAP[name];
	const money = /^Money<([A-Za-z0-9]+)>$/.exec(name);
	if (money) {
		types[name] ??= { of: 'Money', currency: money[1], scale: '2' };
		return name;
	}
	return name;
}

function parseUnitBody(isText: string): TypeDef | undefined {
	const money = /^money(?:\s+(minor))?\s+([A-Za-z0-9]+)(?:\s+per\s+([A-Za-z]\w*))?$/.exec(isText.trim());
	if (money) {
		return {
			of: 'Money',
			currency: money[2],
			scale: money[1] ? '0' : '2',
			...(money[3] ? { per: money[3] } : {}),
		};
	}
	if (isText.trim() === 'integer') return { of: 'Integer' };
	return undefined;
}

function makeSlotDef(type: string, card: SlotDef['card'], kindNames: Set<string>, types: Record<string, TypeDef>, extra: Partial<SlotDef> = {}): SlotDef {
	const states: StateName[] = card === '?' ? ['known', 'not_applicable', 'unknown', 'invalid'] : ['known', 'unknown', 'invalid'];
	if (kindNames.has(type)) {
		return { ref: type, card, states, ...extra };
	}
	return { type: mapTypeName(type, types), card, states, ...extra };
}

function moduleToSchema(module: Module): {
	schema: Schema;
	params: Map<string, ParamDecl>;
	derived: Map<string, Map<string, DerivedDecl>>;
	appliesAt: Map<string, string>;
	factTables: FactTable[];
	factRows: FactRow[];
} {
	const types: Record<string, TypeDef> = {};
	const enums: NonNullable<Schema['enums']> = {};
	const kinds: Record<string, KindDef> = {};
	const schemaParams: NonNullable<Schema['params']> = {};
	const rounding: NonNullable<Schema['rounding']> = {};

	const params = new Map<string, ParamDecl>();
	const derived = new Map<string, Map<string, DerivedDecl>>();
	const appliesAt = new Map<string, string>();
	const kindNames = new Set<string>();
	const kindDecls: KindDecl[] = [];
	const extendDecls: ExtendDecl[] = [];
	const factTables: FactTable[] = [];
	const factRows: FactRow[] = [];

	for (const decl of module.decls) {
		if ('kind' in decl) {
			kindNames.add(decl.kind);
			kindDecls.push(decl);
		} else if ('extend' in decl) {
			extendDecls.push(decl);
		} else if ('enum' in decl) {
			enums[decl.enum] = decl.world === 'open' ? { world: 'open', values: decl.values } : decl.values;
			types[decl.enum] = { of: 'Enum', enum: decl.enum };
		} else if ('unit' in decl && 'is' in decl) {
			const unitDef = parseUnitBody(String(decl.is));
			if (unitDef) types[decl.unit] = unitDef;
		} else if ('type' in decl && 'base' in decl) {
			const base = String(decl.base);
			types[String(decl.type)] = { of: CORE_OF_MAP[base] ?? base };
		} else if ('rounding' in decl && 'mode' in decl) {
			const r = decl as { rounding: 'date' | 'money'; mode: 'half_even' | 'half_up' | 'down' | 'up' };
			if (r.rounding === 'money') rounding.money = r.mode;
		} else if ('param' in decl) {
			params.set(decl.param, decl);
		} else if ('fact' in decl && 'columns' in decl) {
			factTables.push(decl);
		} else if ('fact' in decl && 'set' in decl) {
			factRows.push(decl);
		} else if ('dataset' in decl && 'decls' in decl) {
			for (const entry of (decl as { decls: (FactTable | Record<string, unknown>)[] }).decls) {
				if ('columns' in entry) factTables.push(entry as FactTable);
			}
		}
	}

	for (const k of kindDecls) {
		const idSlot = k.slots.find((s) => s.identifier);
		const idType = idSlot ? mapTypeName(idSlot.type, types) : 'Text';
		const slots: Record<string, SlotDef> = {};
		for (const s of k.slots) {
			slots[s.slot] = makeSlotDef(s.type, s.card ?? '1', kindNames, types, {
				...(s.world ? { world: s.world } : {}),
				...(s.inverse !== undefined ? { inverse: s.inverse } : {}),
			});
		}
		if (k.applies?.axis === 'at') appliesAt.set(k.kind, k.applies.slot);
		const derivedMap = derived.get(k.kind) ?? new Map<string, DerivedDecl>();
		for (const d of k.derived) {
			derivedMap.set(d.derived, d);
			slots[d.derived] = makeSlotDef(d.type, d.card ?? '1', kindNames, types, {
				derived: true,
				states: ['known', 'not_applicable', 'unknown', 'invalid'],
			});
		}
		derived.set(k.kind, derivedMap);
		kinds[k.kind] = { world: k.world ?? (module.rezono === '1' ? 'closed' : 'open'), id: { type: idType }, slots };
	}

	for (const ext of extendDecls) {
		const target = kinds[ext.extend];
		if (!target) continue;
		const derivedMap = derived.get(ext.extend) ?? new Map<string, DerivedDecl>();
		for (const d of ext.derived) {
			derivedMap.set(d.derived, d);
			target.slots[d.derived] = makeSlotDef(d.type, d.card ?? '1', kindNames, types, {
				derived: true,
				states: ['known', 'not_applicable', 'unknown', 'invalid'],
			});
		}
		derived.set(ext.extend, derivedMap);
	}

	for (const [name, p] of params) {
		schemaParams[name] = {
			type: mapTypeName(p.type, types),
			states: ['known', 'not_applicable', 'unknown', 'invalid'],
		};
	}

	const pack = module.pack || 'sample';
	const schema: Schema = {
		rezono: '1.0',
		pack,
		base: `urn:rezono:${pack}/`,
		kinds,
		...(Object.keys(types).length ? { types } : {}),
		...(Object.keys(enums).length ? { enums } : {}),
		...(Object.keys(schemaParams).length ? { params: schemaParams } : {}),
		...(Object.keys(rounding).length ? { rounding } : {}),
	};

	return { schema, params, derived, appliesAt, factTables, factRows };
}

function unquoteText(text: string): string {
	return text.slice(1, -1).replace(/\\(.)/gs, '$1');
}

function extractId(cell: FactCell): string {
	if (typeof cell !== 'object' || cell === null) throw new Error('Invalid fact id cell');
	if ('path' in cell && cell.path.length === 1) return cell.path[0];
	if ('kind' in cell) return cell.kind;
	if ('lit' in cell) {
		if (cell.lit.startsWith('"')) return unquoteText(cell.lit);
		return /^[A-Z][A-Za-z0-9]*:`(.*)`$/s.exec(cell.lit)?.[1] ?? cell.lit;
	}
	throw new Error('Unsupported fact id cell');
}

function factExprToV(schema: Schema, ty: Ty, cell: Expr, cause: RowRef, literals: ReturnType<typeof reader>): V {
	if ('path' in cell && cell.path.length === 1) {
		const word = cell.path[0];
		if (ty.t === 'ref') return { s: 'known', v: { id: word } };
		if (ty.t === 'val') return { s: 'known', v: word };
	}
	if ('kind' in cell) {
		if (ty.t === 'ref') return { s: 'known', v: { id: cell.kind } };
		if (ty.t === 'val') return { s: 'known', v: cell.kind };
	}
	if ('neg' in cell && 'lit' in cell.neg && ty.t === 'num') {
		const f = amount(schema, `-${cell.neg.lit}`);
		if (f) return { s: 'known', v: f };
	}
	if ('lit' in cell) {
		if (cell.lit === 'n/a') return { s: 'not_applicable', reason: '', cause };
		const stated = /^(unknown|invalid)[ \t]+(.*)$/s.exec(cell.lit);
		if (stated) {
			const reason = stated[2].startsWith('"') ? unquoteText(stated[2]) : stated[2];
			return { s: stated[1] as 'unknown' | 'invalid', reason, cause };
		}
		if (ty.t === 'bool') return { s: 'known', v: cell.lit === 'true' };
		if (ty.t === 'num') {
			const f = amount(schema, cell.lit);
			if (f) return { s: 'known', v: f };
		}
		if (ty.t === 'ref') {
			return { s: 'known', v: { id: /^[A-Z][A-Za-z0-9]*:`(.*)`$/s.exec(cell.lit)?.[1] ?? cell.lit } };
		}
		if (ty.t === 'val') {
			const value = /^(?:[A-Z][A-Za-z0-9]*)?"/.test(cell.lit) ? unquoteText(cell.lit.slice(cell.lit.indexOf('"'))) : cell.lit;
			return { s: 'known', v: value };
		}
	}
	const evaluated = literals.ex(cell);
	return evaluated.s === 'known' ? evaluated : { ...evaluated, cause };
}

function factCellToCell(schema: Schema, slotDef: SlotDef, cell: FactCell, cause: RowRef, literals: ReturnType<typeof reader>): Cell | undefined {
	if (typeof cell !== 'object' || cell === null) return undefined;
	if ('boundary' in cell) return undefined;
	const ty = slotType(schema, slotDef);
	if ('list' in cell) {
		return cell.list
			.map((item) => factCellToCell(schema, slotDef, item, cause, literals))
			.filter((v): v is V => v !== undefined && !Array.isArray(v));
	}
	if ('record' in cell) return undefined;
	return factExprToV(schema, ty, cell, cause, literals);
}

function isValidAt(valid: Valid | undefined, date: string): boolean {
	if (!valid) return true;
	if (valid.length === 1) return valid[0] <= date;
	return valid[0] <= date && date < valid[1];
}

function isKnownAt(known: string | undefined, knownCut: string): boolean {
	if (known === undefined) return true;
	return known <= knownCut;
}

interface SelectableVersion {
	version: string;
	replaces?: string;
	valid?: Valid;
	known?: string;
	source?: string;
}

type VersionSelection<T extends SelectableVersion> =
	| { status: 'selected'; version: T }
	| { status: 'none' }
	| { status: 'overlap' };

function selectVersion<T extends SelectableVersion>(versions: readonly T[], validAt: string, knownAt: string): VersionSelection<T> {
	const active = versions.filter((v) => isValidAt(v.valid, validAt) && isKnownAt(v.known, knownAt));
	if (!active.length) return { status: 'none' };
	if (active.length === 1) return { status: 'selected', version: active[0] };

	// Rule 4a (v0.md §5a): explicit `replaces` among active versions (transitive).
	const activeNumbers = new Set(active.map((v) => v.version));
	const replacedNumbers = new Set<string>();
	for (const v of active) {
		if (v.replaces !== undefined && activeNumbers.has(v.replaces)) {
			replacedNumbers.add(v.replaces);
		}
	}
	let remaining = active.filter((v) => !replacedNumbers.has(v.version));
	if (remaining.length === 1) return { status: 'selected', version: remaining[0] };
	if (!remaining.length) remaining = active;

	// Rule 4b (v0.md §5a): later `known` date corrects an earlier one on overlap.
	const maxKnown = remaining.reduce((best, v) => {
		const k = v.known ?? '';
		return k > best ? k : best;
	}, '');
	const latest = remaining.filter((v) => (v.known ?? '') === maxKnown);
	if (latest.length === 1) return { status: 'selected', version: latest[0] };

	// Rule 4c (v0.md §5a): unresolved overlap.
	return { status: 'overlap' };
}

function worstOf(values: V[]): (V & { s: Exclude<StateName, 'known'> }) | undefined {
	const rank: Record<Exclude<StateName, 'known'>, number> = { not_applicable: 1, unknown: 2, invalid: 3 };
	let out: (V & { s: Exclude<StateName, 'known'> }) | undefined;
	for (const v of values) {
		if (v.s === 'known') continue;
		if (!out || rank[v.s] > rank[out.s]) {
			out = v;
		} else if (rank[v.s] === rank[out.s]) {
			const byReason = byteOrder(v.reason, out.reason);
			if (byReason < 0) out = v;
			else if (byReason === 0 && !v.cause && out.cause) out = v;
			else if (byReason === 0 && v.cause && out.cause) {
				const byCause = byteOrder(v.cause.relation, out.cause.relation)
					|| byteOrder(canonicalJson(v.cause.key), canonicalJson(out.cause.key));
				if (byCause < 0) out = v;
			}
		}
	}
	return out;
}

function decimalText(f: Frac, scale = 0): string | undefined {
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

function formatShownValue(v: V, ty: Ty, schema: Schema): unknown {
	if (v.s !== 'known') return { [v.s === 'not_applicable' ? '$na' : `$${v.s}`]: v.reason };
	const value = v.v;
	if (typeof value === 'object' && value !== null && 'id' in value) return { $ref: value.id };
	if (typeof value === 'boolean' || typeof value === 'string') return value;
	if (typeof value !== 'object' || value === null || !('n' in value)) return String(value);

	const whole = (f: Frac) => (f.d === 1n ? f.n.toString() : `${f.n}/${f.d}`);
	if (ty.t === 'num' && ty.name !== undefined) {
		const def = schema.types?.[ty.name];
		if (def?.of === 'Quantity') {
			const fac = amount(schema, def.factor ?? '1') ?? { n: 1n, d: 1n };
			const inUnit = { n: value.n * fac.d, d: value.d * fac.n };
			return `${decimalText(inUnit) ?? whole(inUnit)} ${def.unit ?? ''}`.trim();
		}
		if (def?.of === 'Money') {
			const per = def.per ? factor(schema, def.per) : { n: 1n, d: 1n };
			const inUnit = { n: value.n * per.n, d: value.d * per.d };
			const sym = Object.keys(schema.symbols ?? {}).sort().find((s) => schema.symbols![s] === def.currency) ?? def.currency ?? '';
			return `${sym} ${decimalText(inUnit, Number(def.scale ?? '2')) ?? whole(inUnit)}${def.per ? `/${def.per}` : ''}`.trim();
		}
	}
	return whole(value);
}

function sameV(a: V, b: V): boolean {
	if (a.s !== b.s) return false;
	if (a.s !== 'known') return a.reason === (b as Exclude<V, { s: 'known' }>).reason;
	const av = a.v;
	const bv = (b as { s: 'known'; v: typeof av }).v;
	if (typeof av === 'object' && av !== null && 'n' in av && typeof bv === 'object' && bv !== null && 'n' in bv) {
		return av.n * bv.d === bv.n * av.d;
	}
	if (typeof av === 'object' && av !== null && 'id' in av && typeof bv === 'object' && bv !== null && 'id' in bv) {
		return av.id === bv.id;
	}
	return av === bv;
}

function conditionToExpr(input: Expr, inputTy: Typed, test: TableTest, t: ReturnType<typeof typing>): Expr {
	if ('lit' in test) {
		const b = t.ex(test);
		t.meet(inputTy, input, b, test);
		const cmp: Expr = { cmp: ['=', input, test] };
		t.typed.set(cmp, t.value({ t: 'bool' }));
		return cmp;
	}
	const { from, op, to } = test.between;
	if (from && to) {
		t.meet(inputTy, input, t.ex(from), from);
		t.meet(inputTy, input, t.ex(to), to);
		const range: Expr = { range: [from, op, to] };
		t.typed.set(range, t.value(inputTy.ty, [], true));
		const inExpr: Expr = { in: [input, range] };
		t.typed.set(inExpr, t.value({ t: 'bool' }));
		return inExpr;
	}
	if (from) {
		t.meet(inputTy, input, t.ex(from), from);
		const cmp: Expr = { cmp: ['>=', input, from] };
		t.typed.set(cmp, t.value({ t: 'bool' }));
		return cmp;
	}
	t.meet(inputTy, input, t.ex(to!), to!);
	const cmp: Expr = { cmp: [op === '..' ? '<=' : '<', input, to!] };
	t.typed.set(cmp, t.value({ t: 'bool' }));
	return cmp;
}

function typeCheckModuleAndAsk(module: Module, questionText: string): {
	model: ModuleModel;
	askTree: Ask;
	binder: string;
	askKind: string;
	shown: { expr: Expr; text: string; ty: Ty }[];
	questionValidAt?: string;
} {
	const { schema, params, derived, appliesAt, factTables, factRows } = moduleToSchema(module);
	const parsedAsk = parse(questionText);
	const badAskDiagnostics = parsedAsk.diagnostics.filter(
		(d) => isError(d) && !(d.code === 'R015' && typeof d.args[0] === 'string' && d.args[0].endsWith('in a question context'))
	);
	if (badAskDiagnostics.length || !parsedAsk.tree || !isAsk(parsedAsk.tree)) {
		const msg = badAskDiagnostics.map((d) => `${d.code}: ${d.span.text}`).join('; ') || 'Expected an `ask` question';
		throw new Error(msg);
	}

	const askTree = parsedAsk.tree;
	const t = typing(questionText, schema, parsedAsk.spans);

	const checkExpr = (expr: Expr | undefined) => {
		if (expr) t.ex(expr);
	};

	const checkDefinitions = (defs: DefinitionDecl[] | undefined) => {
		if (!defs) return;
		for (const def of defs) {
			checkExpr(def.when);
			checkExpr(def.value);
		}
	};

	const checkVersions = (versions: VersionDecl[] | undefined) => {
		if (!versions) return;
		for (const v of versions) {
			checkExpr(v.value);
			checkDefinitions(v.definitions);
		}
	};

	for (const p of params.values()) {
		checkExpr(p.value);
		checkVersions(p.versions);
	}

	const tableWhen = new Map<object, Expr[][]>();

	for (const [kindName, dMap] of derived) {
		t.element(kindName, () => {
			for (const d of dMap.values()) {
				checkExpr(d.value);
				for (const block of d.unless ?? []) {
					for (const clause of block) {
						checkExpr(clause.when);
						checkExpr(clause.then);
					}
				}
				checkDefinitions(d.definitions);
				checkVersions(d.versions);
				if (d.table) {
					const inputTypes = d.table.inputs.map((input) => t.settled(input));
					const slotDef = schema.kinds[kindName]?.slots[d.derived];
					const outTy = slotDef ? t.value(slotType(schema, slotDef)) : undefined;
					const rowsWhen: Expr[][] = [];
					for (const row of d.table.rows) {
						const whenExprs: Expr[] = [];
						row.tests.forEach((cell, j) => {
							if (cell === '-') return;
							const conds = cell.map((test) => conditionToExpr(d.table!.inputs[j], inputTypes[j], test, t));
							if (conds.length === 1) {
								whenExprs.push(conds[0]);
							} else if (conds.length > 1) {
								const orExpr: Expr = { or: conds };
								t.typed.set(orExpr, t.value({ t: 'bool' }));
								whenExprs.push(orExpr);
							}
						});
						const valTy = t.ex(row.value as TableValue);
						if (outTy) t.meet(valTy, row.value, outTy, row.value);
						rowsWhen.push(whenExprs);
					}
					tableWhen.set(d.table, rowsWhen);
				}
			}
		});
	}

	const checkedAsk = t.ask(askTree);
	const errors = t.found.filter(isError);
	if (errors.length || !checkedAsk) {
		throw new Error(errors.map((d) => `${d.code}: ${d.span.text}`).join('; ') || 'Question failed type check');
	}

	const literals = reader({ typed: t.typed, heads: t.heads }, schema, {
		kinds: new Map(),
		rules: new Map(),
		outcomes: new Map(),
		params: new Map(),
	});

	const baseKinds = new Map<string, Map<string, Map<string, Cell>>>();
	const kindBySnake = new Map<string, string>();
	for (const kindName of Object.keys(schema.kinds)) {
		baseKinds.set(kindName, new Map());
		kindBySnake.set(snake(kindName), kindName);
	}

	for (const table of factTables) {
		const kindDef = schema.kinds[table.fact];
		if (!kindDef) continue;
		const rowsMap = baseKinds.get(table.fact)!;
		for (const row of table.rows) {
			const id = extractId(row[0]);
			const cells = rowsMap.get(id) ?? new Map<string, Cell>();
			const startCol = table.columns[0] === 'id' ? 1 : 0;
			for (let colIdx = startCol; colIdx < table.columns.length; colIdx++) {
				const slotName = table.columns[colIdx];
				const slotDef = kindDef.slots[slotName];
				if (!slotDef || slotDef.inverse !== undefined) continue;
				const cause: RowRef = { relation: `${snake(table.fact)}__${slotName}`, key: [id] };
				const converted = factCellToCell(schema, slotDef, row[colIdx], cause, literals);
				if (converted !== undefined) cells.set(slotName, converted);
			}
			rowsMap.set(id, cells);
		}
	}

	const versionedFacts = new Map<string, Map<string, Map<string, VersionedFactEntry[]>>>();
	for (let rowIdx = 0; rowIdx < factRows.length; rowIdx++) {
		const fr = factRows[rowIdx];
		const kindName = schema.kinds[fr.fact] ? fr.fact : kindBySnake.get(fr.fact);
		const kindDef = kindName ? schema.kinds[kindName] : undefined;
		if (!kindName || !kindDef) continue;
		if (!baseKinds.get(kindName)!.has(fr.id)) baseKinds.get(kindName)!.set(fr.id, new Map());
		let byId = versionedFacts.get(kindName);
		if (!byId) {
			byId = new Map();
			versionedFacts.set(kindName, byId);
		}
		let bySlot = byId.get(fr.id);
		if (!bySlot) {
			bySlot = new Map();
			byId.set(fr.id, bySlot);
		}
		for (const assign of fr.set) {
			const slotDef = kindDef.slots[assign.slot];
			if (!slotDef) continue;
			if (!fr.valid && fr.known === undefined) {
				const cause: RowRef = { relation: `${snake(kindName)}__${assign.slot}`, key: [fr.id] };
				const v = factExprToV(schema, slotType(schema, slotDef), assign.value, cause, literals);
				baseKinds.get(kindName)!.get(fr.id)!.set(assign.slot, v);
			} else {
				const entries = bySlot.get(assign.slot) ?? [];
				entries.push({
					version: String(entries.length + 1),
					valid: fr.valid,
					known: fr.known,
					value: assign.value,
				});
				bySlot.set(assign.slot, entries);
			}
		}
	}

	let questionValidAt: string | undefined;
	if (askTree.context?.at) {
		const atVal = askTree.context.at;
		if ('lit' in atVal) questionValidAt = atVal.lit;
	}

	return {
		model: {
			module,
			schema,
			params,
			derived,
			appliesAt,
			baseKinds,
			versionedFacts,
			tableWhen,
			typed: t.typed,
			heads: t.heads,
		},
		askTree,
		binder: checkedAsk.binder,
		askKind: checkedAsk.kind,
		shown: checkedAsk.shown.map((s) => ({ expr: s.expr, text: s.text, ty: s.typed.ty })),
		questionValidAt,
	};
}

function evaluateSnapshot(
	model: ModuleModel,
	askTree: Ask,
	askKind: string,
	shown: { expr: Expr; text: string; ty: Ty }[],
	knownAt: string,
	defaultValidAt: string
): Map<string, { side: TurnSide; trace: EvalTrace }> {
	const { schema, params, derived, appliesAt, baseKinds, versionedFacts, typed, heads } = model;
	const out = new Map<string, { side: TurnSide; trace: EvalTrace }>();
	const elementIds = [...(baseKinds.get(askKind)?.keys() ?? [])].sort((a, b) =>
		byteOrder(canonicalJson([a]), canonicalJson([b]))
	);

	const evalParamAt = (name: string, validAt: string, trace: EvalTrace, memo: Map<string, V>): V => {
		const memoKey = `${name}@${validAt}`;
		const cached = memo.get(memoKey);
		const p = params.get(name);
		if (!p) return { s: 'unknown', reason: '', cause: { relation: 'param', key: [name] } };

		if (p.versions?.length) {
			const picked = selectVersion(p.versions, validAt, knownAt);
			const traceKey = `param:${name}`;
			if (picked.status === 'none') {
				trace.versions.set(traceKey, { target: 'param', name, state: 'unknown', reason: 'no_version_applies' });
				const v: V = { s: 'unknown', reason: 'no_version_applies', cause: { relation: 'param', key: [name] } };
				memo.set(memoKey, v);
				return v;
			}
			if (picked.status === 'overlap') {
				trace.versions.set(traceKey, { target: 'param', name, state: 'invalid', reason: 'versions_overlap' });
				const v: V = { s: 'invalid', reason: 'versions_overlap', cause: { relation: 'param', key: [name] } };
				memo.set(memoKey, v);
				return v;
			}
			const ver = picked.version;
			trace.versions.set(traceKey, {
				target: 'param',
				name,
				version: ver.version,
				...(ver.replaces !== undefined ? { replaces: ver.replaces } : {}),
				...(ver.known !== undefined ? { known: ver.known } : {}),
				...(ver.source !== undefined ? { source: ver.source } : {}),
				state: 'known',
			});
			if (cached) return cached;
			const v = ver.value
				? makeReader(validAt, trace, memo).ex(ver.value)
				: ({ s: 'unknown', reason: '', cause: { relation: 'param', key: [name] } } as V);
			memo.set(memoKey, v);
			return v;
		}
		if (cached) return cached;
		if (p.source) {
			const rows = baseKinds.get(p.source.kind);
			if (rows) {
				for (const [id, cells] of rows) {
					const nameCell = cells.get(p.source.nameSlot);
					if (nameCell && !Array.isArray(nameCell) && nameCell.s === 'known' && nameCell.v === name) {
						const slotVal = evalSlotAt(p.source.kind, id, p.source.slot, validAt, trace, memo);
						const v: V = slotVal && !Array.isArray(slotVal) ? slotVal : { s: 'unknown', reason: '', cause: { relation: 'param', key: [name] } };
						memo.set(memoKey, v);
						return v;
					}
				}
			}
		}
		const v = p.value
			? makeReader(validAt, trace, memo).ex(p.value)
			: ({ s: 'unknown', reason: '', cause: { relation: 'param', key: [name] } } as V);
		memo.set(memoKey, v);
		return v;
	};

	const evalDefinitions = (
		defs: DefinitionDecl[],
		kindName: string,
		id: string,
		propName: string,
		validAt: string,
		trace: EvalTrace,
		memo: Map<string, V>
	): V => {
		const r = makeReader(validAt, trace, memo);
		const ty: Ty = { t: 'ref', kind: kindName };
		const cause: RowRef = { relation: `${snake(kindName)}_${propName}`, key: [id] };
		const results = defs.map((def) => ({
			def,
			cond: r.within({ s: 'known', v: { id } }, ty, () => r.ex(def.when)),
		}));
		const overrides = new Map<string, Set<string>>();
		for (const def of defs) {
			overrides.set(def.name, new Set((def.overrides ?? []).map((o) => o.definition)));
		}
		// Transitive closure of overrides
		let changed = true;
		while (changed) {
			changed = false;
			for (const [, targets] of overrides) {
				for (const target of [...targets]) {
					for (const trans of overrides.get(target) ?? []) {
						if (!targets.has(trans)) {
							targets.add(trans);
							changed = true;
						}
					}
				}
			}
		}

		const applying = results.filter((x) => x.cond.s === 'known' && x.cond.v === true);
		const undecided = results.filter((x) => x.cond.s === 'unknown' || x.cond.s === 'invalid');

		// Filter applying by overrides from other applying definitions
		const unoverridden = applying.filter(
			(x) => !applying.some((other) => other !== x && overrides.get(other.def.name)!.has(x.def.name))
		);

		const blockingUndecided = undecided.filter(
			(u) => !applying.some((a) => overrides.get(a.def.name)!.has(u.def.name))
		);

		if (unoverridden.length > 1) {
			const resolvingUndecided = blockingUndecided.filter((u) =>
				unoverridden.every((w) => overrides.get(u.def.name)!.has(w.def.name))
			);
			if (resolvingUndecided.length) {
				return worstOf(resolvingUndecided.map((u) => u.cond))!;
			}
			return { s: 'invalid', reason: 'exception_conflict', cause };
		}
		if (blockingUndecided.length) {
			return worstOf(blockingUndecided.map((u) => u.cond))!;
		}
		if (!unoverridden.length) return { s: 'unknown', reason: 'no_row_applies', cause };
		const chosen = unoverridden[0].def;
		trace.definitions.set(`derived:${kindName}.${propName}`, chosen.name);
		return r.within({ s: 'known', v: { id } }, ty, () => r.ex(chosen.value));
	};

	const evalUnless = (
		blocks: Clause[][],
		fallback: Expr | undefined,
		kindName: string,
		id: string,
		propName: string,
		validAt: string,
		trace: EvalTrace,
		memo: Map<string, V>
	): V => {
		const r = makeReader(validAt, trace, memo);
		const ty: Ty = { t: 'ref', kind: kindName };
		const cause: RowRef = { relation: `${snake(kindName)}_${propName}`, key: [id] };

		for (let i = blocks.length - 1; i >= 0; i--) {
			const clauses = blocks[i];
			const evaluated = clauses.map((c) => ({
				clause: c,
				cond: r.within({ s: 'known', v: { id } }, ty, () => r.ex(c.when)),
			}));
			const applying = evaluated.filter((x) => x.cond.s === 'known' && x.cond.v === true);
			const undecided = evaluated.filter((x) => x.cond.s === 'unknown' || x.cond.s === 'invalid');
			if (applying.length > 1) return { s: 'invalid', reason: 'exception_conflict', cause };
			if (undecided.length) return worstOf(undecided.map((x) => x.cond))!;
			if (applying.length === 1) {
				return r.within({ s: 'known', v: { id } }, ty, () => r.ex(applying[0].clause.then));
			}
		}

		if (!fallback) return { s: 'unknown', reason: 'no_row_applies', cause };
		return r.within({ s: 'known', v: { id } }, ty, () => r.ex(fallback));
	};

	const evaluating = new Set<string>();

	const evalDerivedAt = (
		kindName: string,
		id: string,
		propName: string,
		callerValidAt: string,
		trace: EvalTrace,
		memo: Map<string, V>
	): V => {
		const decl = derived.get(kindName)?.get(propName);
		if (!decl) return { s: 'unknown', reason: '', cause: { relation: `${snake(kindName)}_${propName}`, key: [id] } };

		let subjectValidAt = callerValidAt;
		const appliesSlot = appliesAt.get(kindName);
		if (appliesSlot !== undefined) {
			const dateCell = evalSlotAt(kindName, id, appliesSlot, callerValidAt, trace, memo);
			if (!Array.isArray(dateCell) && dateCell !== undefined) {
				if (dateCell.s !== 'known') return dateCell;
				if (typeof dateCell.v === 'string') subjectValidAt = dateCell.v;
			}
		}

		const memoKey = `${kindName}:${id}:${propName}@${subjectValidAt}`;
		const cached = memo.get(memoKey);
		const cause: RowRef = { relation: `${snake(kindName)}_${propName}`, key: [id] };
		if (evaluating.has(memoKey)) return { s: 'invalid', reason: 'cycle', cause };
		evaluating.add(memoKey);
		try {

		if (decl.versions?.length) {
			const picked = selectVersion(decl.versions, subjectValidAt, knownAt);
			const traceKey = `derived:${kindName}.${propName}`;
			if (picked.status === 'none') {
				trace.versions.set(traceKey, {
					target: 'derived',
					name: `${kindName}.${propName}`,
					kind: kindName,
					property: propName,
					state: 'unknown',
					reason: 'no_version_applies',
				});
				const v: V = { s: 'unknown', reason: 'no_version_applies', cause };
				memo.set(memoKey, v);
				return v;
			}
			if (picked.status === 'overlap') {
				trace.versions.set(traceKey, {
					target: 'derived',
					name: `${kindName}.${propName}`,
					kind: kindName,
					property: propName,
					state: 'invalid',
					reason: 'versions_overlap',
				});
				const v: V = { s: 'invalid', reason: 'versions_overlap', cause };
				memo.set(memoKey, v);
				return v;
			}
			const ver = picked.version;
			trace.versions.set(traceKey, {
				target: 'derived',
				name: `${kindName}.${propName}`,
				kind: kindName,
				property: propName,
				version: ver.version,
				...(ver.replaces !== undefined ? { replaces: ver.replaces } : {}),
				...(ver.known !== undefined ? { known: ver.known } : {}),
				...(ver.source !== undefined ? { source: ver.source } : {}),
				state: 'known',
			});
			if (cached) return cached;
			let v: V;
			if (ver.definitions?.length) {
				v = evalDefinitions(ver.definitions, kindName, id, propName, subjectValidAt, trace, memo);
			} else if (decl.unless?.length) {
				v = evalUnless(decl.unless, ver.value, kindName, id, propName, subjectValidAt, trace, memo);
			} else if (ver.value) {
				const r = makeReader(subjectValidAt, trace, memo);
				v = r.within({ s: 'known', v: { id } }, { t: 'ref', kind: kindName }, () => r.ex(ver.value!));
			} else {
				v = { s: 'unknown', reason: '', cause };
			}
			memo.set(memoKey, v);
			return v;
		}

		if (cached) return cached;
		let v: V;
		if (decl.definitions?.length) {
			v = evalDefinitions(decl.definitions, kindName, id, propName, subjectValidAt, trace, memo);
		} else if (decl.table) {
			const r = makeReader(subjectValidAt, trace, memo);
			const ty: Ty = { t: 'ref', kind: kindName };
			const table = decl.table;
			const rowsWhen = model.tableWhen.get(table) ?? [];
			const outputs = table.rows.map((row) => r.ex(row.value as TableValue) as V & { s: 'known' });
			const decided = table.rows.map((_row, idx) => {
				const whenExprs = rowsWhen[idx] ?? [];
				const condVal = r.within({ s: 'known', v: { id } }, ty, () => {
					const vals = whenExprs.map((w) => r.ex(w));
					if (vals.some((x) => x.s === 'known' && x.v === false)) return { s: 'known', v: false } as V;
					return worstOf(vals) ?? ({ s: 'known', v: true } as V);
				});
				return { idx, v: condVal };
			});
			const applying = decided.filter((d) => d.v.s === 'known' && d.v.v === true);
			const undecided = decided.filter((d) => d.v.s === 'unknown' || d.v.s === 'invalid');
			const sameOut = (i: number, j: number): boolean => sameV(outputs[i], outputs[j]);
			if (table.table === 'collect') {
				const open = undecided.filter((d) => !applying.some((a) => sameOut(a.idx, d.idx)));
				const from = [...applying, ...open].sort((a, b) => a.idx - b.idx);
				const members = from
					.filter((d, n) => !from.slice(0, n).some((o) => sameOut(o.idx, d.idx)))
					.map((d) =>
						applying.includes(d)
							? outputs[d.idx]
							: { ...outputs[d.idx], maybe: worstOf(open.filter((o) => sameOut(o.idx, d.idx)).map((o) => o.v))! }
					);
				v = { s: 'known', v: members };
			} else if (table.table === 'unique') {
				if (applying.length > 1) {
					v = { s: 'invalid', reason: 'exception_conflict', cause };
				} else if (applying.length === 1) {
					v = undecided.length ? worstOf(undecided.map((d) => d.v))! : outputs[applying[0].idx];
				} else {
					v = worstOf(undecided.map((d) => d.v)) ?? { s: 'unknown', reason: 'no_row_applies', cause };
				}
			} else if (!applying.length) {
				v = worstOf(undecided.map((d) => d.v)) ?? { s: 'unknown', reason: 'no_row_applies', cause };
			} else if (table.table === 'priority') {
				const slotTy = slotType(schema, schema.kinds[kindName].slots[propName]);
				const ev = slotTy.t === 'val' ? schema.enums?.[schema.types?.[slotTy.name]?.enum ?? slotTy.name] : undefined;
				const orderList = ev === undefined ? undefined : Array.isArray(ev) ? ev : ev.values;
				const rank = (idx: number): number => {
					const out: V = outputs[idx];
					if (out.s !== 'known') return Number.POSITIVE_INFINITY;
					if (!orderList) return idx;
					const pos = orderList.indexOf(out.v as string);
					return pos < 0 ? Number.POSITIVE_INFINITY : pos;
				};
				const picked = applying.reduce((best, d) => (rank(d.idx) < rank(best.idx) ? d : best));
				const wins = undecided.filter((d) => rank(d.idx) < rank(picked.idx));
				v = wins.length ? worstOf(wins.map((d) => d.v))! : outputs[picked.idx];
			} else {
				const picked = applying[0];
				const wins = undecided.filter((d) => d.idx < picked.idx && !sameOut(d.idx, picked.idx));
				v = wins.length ? worstOf(wins.map((d) => d.v))! : outputs[picked.idx];
			}
		} else if (decl.unless?.length) {
			v = evalUnless(decl.unless, decl.value, kindName, id, propName, subjectValidAt, trace, memo);
		} else if (decl.value) {
			const r = makeReader(subjectValidAt, trace, memo);
			v = r.within({ s: 'known', v: { id } }, { t: 'ref', kind: kindName }, () => r.ex(decl.value!));
		} else {
			v = { s: 'unknown', reason: '', cause };
		}
		memo.set(memoKey, v);
		return v;
		} finally {
			evaluating.delete(memoKey);
		}
	};

	const evalSlotAt = (
		kindName: string,
		id: string,
		slotName: string,
		validAt: string,
		trace: EvalTrace,
		memo: Map<string, V>
	): Cell | undefined => {
		if (derived.get(kindName)?.has(slotName)) {
			return evalDerivedAt(kindName, id, slotName, validAt, trace, memo);
		}
		const entries = versionedFacts.get(kindName)?.get(id)?.get(slotName);
		if (entries?.length) {
			const picked = selectVersion(entries, validAt, knownAt);
			const traceKey = `fact:${kindName}:${id}:${slotName}`;
			const cause: RowRef = { relation: `${snake(kindName)}__${slotName}`, key: [id] };
			if (picked.status === 'none') {
				trace.versions.set(traceKey, {
					target: 'fact',
					name: `${kindName}.${slotName}`,
					kind: kindName,
					key: id,
					slot: slotName,
					state: 'unknown',
					reason: 'no_version_applies',
				});
				return baseKinds.get(kindName)?.get(id)?.get(slotName) ?? { s: 'unknown', reason: 'no_version_applies', cause };
			}
			if (picked.status === 'overlap') {
				trace.versions.set(traceKey, {
					target: 'fact',
					name: `${kindName}.${slotName}`,
					kind: kindName,
					key: id,
					slot: slotName,
					state: 'invalid',
					reason: 'versions_overlap',
				});
				return { s: 'invalid', reason: 'versions_overlap', cause };
			}
			const ver = picked.version;
			trace.versions.set(traceKey, {
				target: 'fact',
				name: `${kindName}.${slotName}`,
				kind: kindName,
				key: id,
				slot: slotName,
				version: ver.version,
				...(ver.known !== undefined ? { known: ver.known } : {}),
				state: 'known',
			});
			const slotDef = schema.kinds[kindName]?.slots[slotName];
			if (!slotDef) return undefined;
			const r = makeReader(validAt, trace, memo);
			return factExprToV(schema, slotType(schema, slotDef), ver.value, cause, r);
		}
		return baseKinds.get(kindName)?.get(id)?.get(slotName);
	};

	function makeReader(validAt: string, trace: EvalTrace, memo: Map<string, V>) {
		const kindsView = new Map<string, Map<string, Map<string, Cell>>>();
		for (const [kindName, rows] of baseKinds) {
			const rowProxyMap = new Map<string, Map<string, Cell>>();
			for (const id of rows.keys()) {
				const cellMap = {
					get(slotName: string): Cell | undefined {
						return evalSlotAt(kindName, id, slotName, validAt, trace, memo);
					},
				} as Map<string, Cell>;
				rowProxyMap.set(id, cellMap);
			}
			kindsView.set(kindName, rowProxyMap);
		}
		const paramsView = {
			get(name: string): V | undefined {
				return evalParamAt(name, validAt, trace, memo);
			},
		} as Map<string, V>;
		const data: Data = {
			kinds: kindsView,
			rules: new Map(),
			outcomes: new Map(),
			params: paramsView,
		};
		return reader({ typed, heads }, schema, data);
	}

	const ty: Ty = { t: 'ref', kind: askKind };
	for (const id of elementIds) {
		const trace: EvalTrace = { versions: new Map(), definitions: new Map() };
		const memo = new Map<string, V>();
		const r = makeReader(defaultValidAt, trace, memo);
		const row = { s: 'known', v: { id } } as const;
		const cond = r.within(row, ty, () => r.ex(askTree.where));

		if (cond.s === 'known' && cond.v === true) {
			const values: Record<string, unknown> = {};
			const states: Record<string, { state: StateName; reason?: string }> = {};
			for (const s of shown) {
				const val = r.within(row, ty, () => r.ex(s.expr));
				values[s.text] = formatShownValue(val, s.ty, schema);
				states[s.text] = val.s === 'known' ? { state: 'known' } : { state: val.s, reason: val.reason };
			}
			out.set(id, { side: { present: true, state: 'known', values, states }, trace });
		} else if (cond.s === 'known') {
			out.set(id, { side: { present: false, state: 'known' }, trace });
		} else if (cond.s === 'not_applicable') {
			out.set(id, { side: { present: false, state: 'not_applicable', reason: cond.reason }, trace });
		} else {
			out.set(id, { side: { present: false, state: cond.s, reason: cond.reason }, trace });
		}
	}

	return out;
}

function diffCauses(
	beforeSide: TurnSide,
	afterSide: TurnSide,
	beforeTrace: EvalTrace,
	afterTrace: EvalTrace
): VersionAmendmentCause[] {
	const causes: VersionAmendmentCause[] = [];
	const allKeys = [...new Set([...beforeTrace.versions.keys(), ...afterTrace.versions.keys()])].sort();

	for (const key of allKeys) {
		const b = beforeTrace.versions.get(key);
		const a = afterTrace.versions.get(key);
		if (!b || !a) continue;
		if (b.version === a.version && b.state === a.state && b.reason === a.reason && b.known === a.known) continue;
		causes.push({
			cause: 'version',
			target: a.target,
			name: a.name,
			...(a.kind !== undefined ? { kind: a.kind } : {}),
			...(a.property !== undefined ? { property: a.property } : {}),
			...(a.key !== undefined ? { key: a.key } : {}),
			...(a.slot !== undefined ? { slot: a.slot } : {}),
			...(b.version !== undefined ? { before_version: b.version } : {}),
			...(a.version !== undefined ? { after_version: a.version } : {}),
			...(a.replaces !== undefined ? { replaces: a.replaces } : {}),
			...(b.known !== undefined ? { before_known: b.known } : {}),
			...(a.known !== undefined ? { after_known: a.known } : {}),
			...(a.source !== undefined ? { source: a.source } : {}),
		});
	}

	for (const key of [...new Set([...beforeTrace.definitions.keys(), ...afterTrace.definitions.keys()])].sort()) {
		const b = beforeTrace.definitions.get(key);
		const a = afterTrace.definitions.get(key);
		if (b && a && b !== a) {
			causes.push({
				cause: 'definition',
				name: key.replace(/^derived:/, ''),
				before_definition: b,
				after_definition: a,
			});
		}
	}

	if (!causes.length) {
		for (const key of allKeys) {
			const b = beforeTrace.versions.get(key);
			const a = afterTrace.versions.get(key);
			const choice = a ?? b;
			if (!choice) continue;
			if (b && a && b.version === a.version && b.state === a.state && b.reason === a.reason && b.known === a.known) continue;
			causes.push({
				cause: 'version',
				target: choice.target,
				name: choice.name,
				...(choice.kind !== undefined ? { kind: choice.kind } : {}),
				...(choice.property !== undefined ? { property: choice.property } : {}),
				...(choice.key !== undefined ? { key: choice.key } : {}),
				...(choice.slot !== undefined ? { slot: choice.slot } : {}),
				...(b?.version !== undefined ? { before_version: b.version } : {}),
				...(a?.version !== undefined ? { after_version: a.version } : {}),
				...(a?.replaces !== undefined ? { replaces: a.replaces } : {}),
				...(b?.known !== undefined ? { before_known: b.known } : {}),
				...(a?.known !== undefined ? { after_known: a.known } : {}),
				...(choice.source !== undefined ? { source: choice.source } : {}),
			});
		}
	}

	if (!causes.length) {
		if (beforeSide.present !== afterSide.present) {
			causes.push({ cause: 'presence' });
		} else if (beforeSide.state !== afterSide.state || beforeSide.reason !== afterSide.reason) {
			causes.push({
				cause: 'state',
				before_state: beforeSide.state,
				after_state: afterSide.state,
			});
		} else {
			causes.push({ cause: 'value' });
		}
	}

	return causes;
}

/**
 * Compares an `ask` question over a Rezono module at two knowledge dates (`beforeKnown` vs `afterKnown`),
 * returning a `rezono.turns/1` summary of turned rows (before/after values and states) and the amended
 * rule, parameter, or fact version causing each turn.
 */
export function compareAsKnown(source: string | Module, options: CompareAsKnownOptions): KnowledgeComparison {
	let module: Module;
	if (typeof source === 'string') {
		const parsed = parseModule(source);
		const errors = parsed.diagnostics.filter(isError);
		if (errors.length || !parsed.module) {
			throw new Error(errors.map((d) => `${d.code}: ${d.span.text}`).join('; ') || 'Module parse failed');
		}
		module = parsed.module;
	} else {
		module = source;
	}

	const { model, askTree, askKind, shown, questionValidAt } = typeCheckModuleAndAsk(module, options.question);
	const validAt = options.validAt ?? questionValidAt ?? options.afterKnown;

	const beforeMap = evaluateSnapshot(model, askTree, askKind, shown, options.beforeKnown, validAt);
	const afterMap = evaluateSnapshot(model, askTree, askKind, shown, options.afterKnown, validAt);

	const keys = [...new Set([...beforeMap.keys(), ...afterMap.keys()])].sort((a, b) =>
		byteOrder(canonicalJson([a]), canonicalJson([b]))
	);

	let beforeRows = 0;
	let beforeUndecided = 0;
	let afterRows = 0;
	let afterUndecided = 0;
	const turns: KnowledgeTurn[] = [];

	for (const key of keys) {
		const b = beforeMap.get(key) ?? { side: { present: false, state: 'unknown' as const }, trace: { versions: new Map(), definitions: new Map() } };
		const a = afterMap.get(key) ?? { side: { present: false, state: 'unknown' as const }, trace: { versions: new Map(), definitions: new Map() } };

		if (b.side.present) beforeRows++;
		else if (b.side.state === 'unknown' || b.side.state === 'invalid') beforeUndecided++;

		if (a.side.present) afterRows++;
		else if (a.side.state === 'unknown' || a.side.state === 'invalid') afterUndecided++;

		if (canonicalJson(b.side) === canonicalJson(a.side)) continue;

		turns.push({
			relation: askKind,
			key,
			before: b.side,
			after: a.side,
			causes: diffCauses(b.side, a.side, b.trace, a.trace),
		});
	}

	return {
		format: 'rezono.turns/1',
		question: options.question,
		kind: askKind,
		...(options.validAt ?? questionValidAt ? { valid_at: options.validAt ?? questionValidAt } : {}),
		before: { as_known: options.beforeKnown, rows: beforeRows, undecided: beforeUndecided },
		after: { as_known: options.afterKnown, rows: afterRows, undecided: afterUndecided },
		turns,
	};
}
