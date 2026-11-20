import { canonicalJson } from '../../viewer/src/lib/canon.ts';
import { isError, typing, type Head, type Typed } from './check.ts';
import { amount, byteOrder, load, publish, reader, tabulate, type Cell, type Data, type RowRef, type V } from './evaluate.ts';
import type { DefinitionDecl, DerivedDecl } from './module-derived.ts';
import type { ExampleDecl } from './module-example.ts';
import type { FactRow, FactTable } from './module-facts.ts';
import type { ExtendDecl, KindDecl } from './module-kind.ts';
import type { ParamDecl } from './module-parameter.ts';
import type { Clause } from './module-unless.ts';
import type { During, Valid, VersionDecl } from './module-version.ts';
import type { Module } from './module.ts';
import { printExpr } from './print-expression.ts';
import { knownType, slotType, snake, STATES, type KindDef, type Schema, type SlotDef, type Ty, type TypeDef } from './schema.ts';
import type { DecisionTable } from './table.ts';
import type { CheckDecl, Context, Expr } from './tree.ts';

/** A failing assertion inside an `example` block. */
export interface ExampleFailure {
	example: string;
	expectation: string;
	reason: string;
}

/** A W109 coverage warning for a clause exercised by no example (docs/rezono/v0.md §5e). */
export interface CoverageWarning {
	code: 'W109';
	clause: string;
	target: string;
	args: [string, string];
}

/** Result of running all `example` blocks in a module and checking W109 clause coverage. */
export interface ExamplesResult {
	examples: number;
	passed: number;
	failures: ExampleFailure[];
	warnings: CoverageWarning[];
}

interface EvalContext {
	at?: string;
	asKnown?: string;
	during?: string;
	in?: string;
}

interface DerivedEntry {
	kind: string;
	decl: DerivedDecl;
	target: string;
	baseCovered: boolean;
	unlessCovered: boolean[][];
	versionCovered: boolean[];
	defCovered: boolean[];
	versionDefCovered: boolean[][];
	rowCovered: boolean[];
}

interface ParamEntry {
	decl: ParamDecl;
	versionCovered: boolean[];
}

interface CheckEntry {
	decl: CheckDecl;
	target: string;
	passed: boolean;
	violated: boolean;
}

const KNOWN_STATES = STATES;

function atomText(e?: Expr): string | undefined {
	if (!e) return undefined;
	if ('lit' in e) return e.lit;
	if ('path' in e && e.path.length === 1) return e.path[0];
	return undefined;
}

function extractContext(c?: Context): EvalContext {
	if (!c) return {};
	return {
		at: atomText(c.at),
		asKnown: atomText(c.as_known),
		during: atomText(c.during),
		in: atomText(c.in),
	};
}

function matchesContext(
	item: { valid?: Valid; known?: string; during?: During; in?: string[] },
	ctx: EvalContext
): boolean {
	if (item.known !== undefined && ctx.asKnown !== undefined && item.known > ctx.asKnown) return false;
	if (item.valid !== undefined) {
		if (ctx.at === undefined) return false;
		if (ctx.at < item.valid[0]) return false;
		if (item.valid.length === 2 && ctx.at >= item.valid[1]) return false;
	}
	if (item.during !== undefined) {
		if (ctx.during === undefined) return false;
		if ('stage' in item.during) {
			if (ctx.during !== item.during.stage) return false;
		} else {
			if (ctx.during < item.during.from) return false;
			if (item.during.until !== undefined && ctx.during >= item.during.until) return false;
		}
	}
	if (item.in !== undefined) {
		if (ctx.in === undefined || !item.in.includes(ctx.in)) return false;
	}
	return true;
}

type VersionPick<T> = { kind: 'none' } | { kind: 'one'; version: T } | { kind: 'overlap'; versions: T[] };

function selectVersion<T extends { version: string; replaces?: string; known?: string; valid?: Valid }>(
	versions: T[],
	ctx: EvalContext
): VersionPick<T> {
	const active = versions.filter((v) => matchesContext(v, ctx));
	if (!active.length) return { kind: 'none' };
	const replaced = new Set(active.map((v) => v.replaces).filter((r): r is string => r !== undefined));
	let winners = active.filter((v) => !replaced.has(v.version));
	if (!winners.length) winners = active;
	if (winners.length > 1) {
		const maxKnown = winners.map((v) => v.known ?? '').sort().at(-1)!;
		if (maxKnown !== '') winners = winners.filter((v) => (v.known ?? '') === maxKnown);
	}
	return winners.length === 1 ? { kind: 'one', version: winners[0] } : { kind: 'overlap', versions: winners };
}

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

function buildSchema(module: Module): {
	schema: Schema;
	kindDecls: Map<string, KindDecl>;
} {
	const types: Record<string, TypeDef> = {
		Int: { of: 'Integer' },
		Rational: { of: 'Ratio' },
	};
	const enums: Record<string, string[] | { world: 'open'; values: string[] }> = {};
	const kinds: Record<string, KindDef> = {};
	const params: Record<string, Pick<SlotDef, 'type' | 'states'>> = {};
	const kindDecls = new Map<string, KindDecl>();
	const kindNames = new Set<string>();
	let rounding: Schema['rounding'] | undefined;

	for (const decl of module.decls) {
		if ('kind' in decl) kindNames.add(decl.kind);
	}

	const slotDefFor = (typeName: string, card: KindDecl['slots'][number]['card'], world?: KindDecl['world'], inverse?: string, derived = false): SlotDef => {
		const base: SlotDef = kindNames.has(typeName) ? { ref: typeName, card: card ?? '1', states: KNOWN_STATES } : { type: typeName, card: card ?? '1', states: KNOWN_STATES };
		if (world) base.world = world;
		if (inverse) base.inverse = inverse;
		if (derived) base.derived = true;
		return base;
	};

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
			kindDecls.set(decl.kind, decl);
			const slots: Record<string, SlotDef> = {};
			for (const s of decl.slots) {
				slots[s.slot] = slotDefFor(s.type, s.card, s.world, s.inverse?.split('.').pop(), false);
			}
			for (const d of decl.derived) {
				slots[d.derived] = slotDefFor(d.type, d.card, undefined, undefined, true);
			}
			kinds[decl.kind] = { world: decl.world ?? 'open', id: { type: 'Text' }, slots };
		} else if ('extend' in decl) {
			const k = kinds[decl.extend];
			if (k) {
				for (const s of decl.slots ?? []) {
					k.slots[s.slot] = slotDefFor(s.type, s.card, s.world, s.inverse?.split('.').pop(), false);
				}
				for (const d of decl.derived) {
					k.slots[d.derived] = slotDefFor(d.type, d.card, undefined, undefined, true);
				}
			}
		} else if ('param' in decl) {
			params[decl.param] = { type: decl.type, states: KNOWN_STATES };
		}
	}

	const schema: Schema = {
		rezono: '1.0',
		pack: module.pack || 'example',
		base: `https://rezono.example/${module.pack || 'example'}/`,
		types,
		enums,
		kinds,
		params,
		symbols: {},
		...(rounding ? { rounding } : {}),
	};
	return { schema, kindDecls };
}

function collectExprNames(node: unknown, out: Set<string>): void {
	if (Array.isArray(node)) {
		for (const item of node) collectExprNames(item, out);
		return;
	}
	if (typeof node !== 'object' || node === null) return;
	const rec = node as Record<string, unknown>;
	if (Array.isArray(rec.path)) {
		for (const p of rec.path) if (typeof p === 'string') out.add(p);
		return;
	}
	if (typeof rec.dot === 'object' && Array.isArray(rec.dot) && typeof rec.dot[1] === 'string') {
		out.add(rec.dot[1]);
	}
	for (const val of Object.values(rec)) collectExprNames(val, out);
}

function sortDerivedEntries(entries: DerivedEntry[]): DerivedEntry[] {
	const byName = new Map<string, number[]>();
	entries.forEach((e, i) => {
		const list = byName.get(e.decl.derived) ?? [];
		list.push(i);
		byName.set(e.decl.derived, list);
	});
	const deps = entries.map((e) => {
		const names = new Set<string>();
		collectExprNames(e.decl, names);
		const d = new Set<number>();
		for (const n of names) {
			for (const j of byName.get(n) ?? []) {
				if (entries[j] !== e) d.add(j);
			}
		}
		return d;
	});
	const state = new Uint8Array(entries.length); // 0 unvisited, 1 visiting, 2 done
	const ordered: DerivedEntry[] = [];
	const visit = (i: number) => {
		if (state[i] !== 0) return;
		state[i] = 1;
		for (const dep of deps[i]) visit(dep);
		state[i] = 2;
		ordered.push(entries[i]);
	};
	for (let i = 0; i < entries.length; i++) visit(i);
	return ordered;
}

function kindsWithChain(schema: Schema, slots: string[]): string[] {
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

function inferIdKinds(
	schema: Schema,
	baseKinds: Data['kinds'],
	example: ExampleDecl
): Map<string, string> {
	const candidates = new Map<string, Set<string>>();
	for (const [k, rows] of baseKinds) {
		for (const id of rows.keys()) {
			const set = candidates.get(id) ?? new Set<string>();
			set.add(k);
			candidates.set(id, set);
		}
	}
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
		if (g.path.length >= 2) narrow(g.path[0], kindsWithChain(schema, g.path.slice(1)));
	}
	const collectExpectPaths = (node: unknown) => {
		if (Array.isArray(node)) {
			node.forEach(collectExpectPaths);
			return;
		}
		if (typeof node !== 'object' || node === null) return;
		const rec = node as Record<string, unknown>;
		if (Array.isArray(rec.path) && rec.path.length >= 2 && typeof rec.path[0] === 'string') {
			const first = rec.path[0];
			if (!schema.params?.[first] && !Object.keys(schema.kinds).some((k) => snake(k) === first)) {
				narrow(first, kindsWithChain(schema, rec.path.slice(1) as string[]));
			}
		}
		for (const v of Object.values(rec)) collectExpectPaths(v);
	};
	for (const exp of example.expect) {
		if (!('violation' in exp)) collectExpectPaths(exp);
	}

	// Propagate reference slot targets in `given` assignments.
	for (let pass = 0; pass < 3; pass++) {
		for (const g of example.given) {
			const [id, ...rest] = g.path;
			const idSet = candidates.get(id);
			if (!idSet || idSet.size !== 1) continue;
			const kind = [...idSet][0];
			let curKind: string | undefined = kind;
			let slotDef: SlotDef | undefined;
			for (const s of rest) {
				slotDef = curKind ? schema.kinds[curKind]?.slots[s] : undefined;
				curKind = slotDef?.ref;
			}
			if (slotDef?.ref) {
				const target = atomText(g.value);
				if (target) narrow(target, [slotDef.ref]);
			}
		}
	}

	const resolved = new Map<string, string>();
	for (const [id, set] of candidates) {
		if (set.size >= 1) resolved.set(id, [...set].sort()[0]);
	}
	return resolved;
}

const RANK = { not_applicable: 1, unknown: 2, invalid: 3 } as const;

function worstV(values: V[]): V | undefined {
	let out: V | undefined;
	for (const v of values) {
		if (v.s === 'known') continue;
		if (!out || out.s === 'known' || RANK[v.s] > RANK[out.s]) out = v;
		else if (RANK[v.s] === RANK[out.s] && byteOrder(v.reason, out.reason) < 0) out = v;
	}
	return out;
}

function sameValue(a: V, b: V): boolean {
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

function mergeCell(before: Cell, next: V): Cell {
	if (Array.isArray(before)) {
		return before.some((w) => sameValue(w, next)) ? before : [...before, next];
	}
	return sameValue(before, next) ? before : { s: 'invalid', reason: '' };
}

function formatV(v: V): string {
	if (v.s !== 'known') return `${v.s}${v.reason ? ` ${v.reason}` : ''}`;
	const val = v.v;
	if (typeof val === 'object' && val !== null && 'n' in val) return val.d === 1n ? val.n.toString() : `${val.n}/${val.d}`;
	if (typeof val === 'object' && val !== null && 'id' in val) return val.id;
	return String(val);
}

function evalExpr(
	expr: Expr,
	schema: Schema,
	data: Data,
	idKinds: Map<string, string>,
	scopeKind?: string,
	scopeId?: string
): { value: V; diagnostics: ReturnType<typeof typing>['found'] } {
	const spans = new WeakMap<object, { text: string; start: number; end: number }>();
	const nodeBySpan = new Map<number, object>();
	let nextSpanId = 1;
	const assignSpans = (node: unknown): void => {
		if (Array.isArray(node)) {
			node.forEach(assignSpans);
			return;
		}
		if (typeof node !== 'object' || node === null) return;
		if (!spans.has(node)) {
			const id = nextSpanId++;
			spans.set(node, { text: '', start: id, end: id });
			nodeBySpan.set(id, node);
		}
		for (const v of Object.values(node as Record<string, unknown>)) assignSpans(v);
	};
	assignSpans(expr);

	const t = typing('', schema, spans);
	const run = () => t.ex(expr);
	if (scopeKind !== undefined) t.element(scopeKind, run);
	else run();

	// Disambiguate any id-headed path when multiple kinds share a slot name.
	const patchedNodes = new Set<object>();
	const patchHeads = (node: unknown): void => {
		if (Array.isArray(node)) {
			node.forEach(patchHeads);
			return;
		}
		if (typeof node !== 'object' || node === null) return;
		const rec = node as Record<string, unknown>;
		if (Array.isArray(rec.path) && rec.path.length >= 2 && typeof rec.path[0] === 'string' && !t.heads.has(node)) {
			const kind = idKinds.get(rec.path[0]);
			if (kind) {
				t.heads.set(node, { as: 'id', kind });
				let cur: Ty = { t: 'ref', kind };
				let set = false;
				for (const s of (rec.path as string[]).slice(1)) {
					if (cur.t !== 'ref') break;
					const sd = schema.kinds[cur.kind]?.slots[s];
					if (!sd) break;
					if (sd.card === '*' || sd.card === '+') set = true;
					cur = slotType(schema, sd);
				}
				t.typed.set(node, t.value(cur, [], set));
				patchedNodes.add(node);
			}
		}
		for (const v of Object.values(rec)) patchHeads(v);
	};
	patchHeads(expr);

	if (patchedNodes.size) {
		const recheckPatchedPeers = (node: unknown): void => {
			if (Array.isArray(node)) {
				node.forEach(recheckPatchedPeers);
				return;
			}
			if (typeof node !== 'object' || node === null) return;
			const rec = node as Record<string, unknown>;
			if (Array.isArray(rec.cmp) && rec.cmp.length === 3) {
				const [, an, bn] = rec.cmp as [string, object, object];
				if (patchedNodes.has(an) || patchedNodes.has(bn)) {
					const ta = t.typed.get(an);
					const tb = t.typed.get(bn);
					if (ta && tb && !t.meet(ta, an, tb, bn)) {
						t.report('R003', spans.get(node) ?? { text: '', start: 0, end: 0 }, [t.describe(ta.ty), t.describe(tb.ty)]);
					}
				}
			}
			for (const v of Object.values(rec)) recheckPatchedPeers(v);
		};
		recheckPatchedPeers(expr);
	}

	const diagnostics = patchedNodes.size
		? t.found.filter((d) => {
			if (d.code !== 'R002' && d.code !== 'R003') return true;
			const diagNode = nodeBySpan.get(d.span.start);
			return !diagNode || !patchedNodes.has(diagNode);
		})
		: t.found;

	if (diagnostics.some(isError)) {
		return { value: { s: 'invalid', reason: '' }, diagnostics };
	}

	const r = reader({ typed: t.typed, heads: t.heads }, schema, data);
	const value = scopeKind !== undefined && scopeId !== undefined
		? r.within({ s: 'known', v: { id: scopeId } }, { t: 'ref', kind: scopeKind }, () => r.ex(expr))
		: r.ex(expr);
	return { value, diagnostics };
}

function buildBaseData(
	module: Module,
	schema: Schema,
	ctx: EvalContext
): Data {
	const rows: Record<string, unknown>[] = [];
	for (const decl of module.decls) {
		if ('fact' in decl && 'columns' in decl) {
			const table = decl as FactTable;
			for (const r of table.rows) {
				const row: Record<string, unknown> = { $kind: table.fact, $id: atomText(r[0] as Expr) ?? '' };
				for (let c = 1; c < table.columns.length; c++) {
					const cell = r[c];
					if (typeof cell === 'object' && cell !== null && 'boundary' in cell) continue;
					if (typeof cell === 'object' && cell !== null && 'lit' in cell) row[table.columns[c]] = cell.lit;
					else if (typeof cell === 'object' && cell !== null && 'path' in cell && (cell as { path: string[] }).path.length === 1) {
						row[table.columns[c]] = (cell as { path: string[] }).path[0];
					}
				}
				rows.push(row);
			}
		}
	}
	const data = load(schema, rows);

	// Group dated/contextual FactRows by (kind, id, slot) and apply context rules (§5a rule 5).
	const factKindName = (factName: string) =>
		Object.keys(schema.kinds).find((k) => k === factName || snake(k) === factName);
	const factEntries = new Map<string, { kind: string; id: string; slot: string; items: { row: FactRow; value: Expr }[] }>();
	for (const decl of module.decls) {
		if ('fact' in decl && 'set' in decl) {
			const fr = decl as FactRow;
			const kind = factKindName(fr.fact);
			if (!kind) continue;
			for (const assign of fr.set) {
				const key = `${kind}\0${fr.id}\0${assign.slot}`;
				const entry = factEntries.get(key) ?? { kind, id: fr.id, slot: assign.slot, items: [] };
				entry.items.push({ row: fr, value: assign.value });
				factEntries.set(key, entry);
			}
		}
	}
	for (const { kind, id, slot, items } of factEntries.values()) {
		const active = items.filter((it) => matchesContext(it.row, ctx));
		if (!active.length) continue;
		const maxKnown = active.map((it) => it.row.known ?? '').sort().at(-1)!;
		const winners = maxKnown !== '' ? active.filter((it) => (it.row.known ?? '') === maxKnown) : active;
		if (!data.kinds.has(kind)) data.kinds.set(kind, new Map());
		const kindMap = data.kinds.get(kind)!;
		if (!kindMap.has(id)) kindMap.set(id, new Map());
		const cellMap = kindMap.get(id)!;
		const slotDef = schema.kinds[kind]?.slots[slot];
		const many = slotDef?.card === '*' || slotDef?.card === '+';
		for (const w of winners) {
			const val = evalExpr(w.value, schema, data, new Map()).value;
			const attributed: V = val.s === 'known' ? val : { ...val, cause: { relation: `${snake(kind)}__${slot}`, key: [id] } };
			if (many) {
				const cur = cellMap.get(slot);
				cellMap.set(slot, cur === undefined ? [attributed] : mergeCell(cur, attributed));
			} else {
				const cur = cellMap.get(slot);
				cellMap.set(slot, cur === undefined ? attributed : mergeCell(cur, attributed));
			}
		}
	}
	return data;
}

function resolveParams(
	paramEntries: ParamEntry[],
	schema: Schema,
	data: Data,
	ctx: EvalContext,
	idKinds: Map<string, string>
): void {
	data.params.clear();
	for (const entry of paramEntries) {
		const p = entry.decl;
		if (p.versions?.length) {
			const pick = selectVersion(p.versions, ctx);
			if (pick.kind === 'none') {
				data.params.set(p.param, { s: 'unknown', reason: 'no_version_applies', cause: { relation: 'param', key: [p.param] } });
			} else if (pick.kind === 'overlap') {
				data.params.set(p.param, { s: 'invalid', reason: 'versions_overlap', cause: { relation: 'param', key: [p.param] } });
			} else {
				const idx = p.versions.indexOf(pick.version);
				if (idx >= 0) entry.versionCovered[idx] = true;
				if (pick.version.value) {
					data.params.set(p.param, evalExpr(pick.version.value, schema, data, idKinds).value);
				}
			}
		} else if (p.value) {
			data.params.set(p.param, evalExpr(p.value, schema, data, idKinds).value);
		}
	}
}

function idsOf(data: Data, kind: string): string[] {
	return [...(data.kinds.get(kind)?.keys() ?? [])].sort((a, b) => byteOrder(canonicalJson([a]), canonicalJson([b])));
}

function referencedKinds(expr: unknown, schema: Schema, out = new Set<string>()): Set<string> {
	if (Array.isArray(expr)) {
		expr.forEach((x) => referencedKinds(x, schema, out));
		return out;
	}
	if (typeof expr !== 'object' || expr === null) return out;
	const rec = expr as Record<string, unknown>;
	if (typeof rec.kind === 'string' && schema.kinds[rec.kind]) out.add(rec.kind);
	if (Array.isArray(rec.path) && typeof rec.path[0] === 'string') {
		const k = Object.keys(schema.kinds).find((name) => snake(name) === rec.path[0]);
		if (k) out.add(k);
	}
	for (const v of Object.values(rec)) referencedKinds(v, schema, out);
	return out;
}

/**
 * Executes every `example` block in `module` against its declarations and checks `W109` coverage
 * across derivations, `unless` lines, versions, table rows, definitions, and checks.
 */
export function runExamples(module: Module): ExamplesResult {
	const { schema, kindDecls } = buildSchema(module);

	const paramEntries: ParamEntry[] = [];
	const rawDerived: DerivedEntry[] = [];
	const checkEntries: CheckEntry[] = [];
	const examples: ExampleDecl[] = [];

	const makeDerivedEntry = (kind: string, decl: DerivedDecl): DerivedEntry => ({
		kind,
		decl,
		target: kind ? `${kind}.${decl.derived}` : decl.derived,
		baseCovered: false,
		unlessCovered: (decl.unless ?? []).map((block) => block.map(() => false)),
		versionCovered: (decl.versions ?? []).map(() => false),
		defCovered: (decl.definitions ?? []).map(() => false),
		versionDefCovered: (decl.versions ?? []).map((v) => (v.definitions ?? []).map(() => false)),
		rowCovered: (decl.table?.rows ?? []).map(() => false),
	});

	for (const decl of module.decls) {
		if ('param' in decl) {
			paramEntries.push({ decl, versionCovered: (decl.versions ?? []).map(() => false) });
		} else if ('kind' in decl) {
			for (const d of decl.derived) rawDerived.push(makeDerivedEntry(decl.kind, d));
		} else if ('extend' in decl) {
			for (const d of decl.derived) rawDerived.push(makeDerivedEntry(decl.extend, d));
		} else if ('check' in decl) {
			checkEntries.push({
				decl,
				target: decl.name ?? `${decl.check}`,
				passed: false,
				violated: false,
			});
		} else if ('example' in decl) {
			examples.push(decl);
		}
	}

	const derivedEntries = sortDerivedEntries(rawDerived);
	const failures: ExampleFailure[] = [];
	let passedExamples = 0;

	for (const exDecl of examples) {
		const exCtx = extractContext(exDecl.context);
		let data = buildBaseData(module, schema, exCtx);
		const idKinds = inferIdKinds(schema, data.kinds, exDecl);
		resolveParams(paramEntries, schema, data, exCtx, idKinds);

		// Apply `given` slot assignments.
		const givenSingle = new Set<string>();
		for (const g of exDecl.given) {
			const [id, ...rest] = g.path;
			const kind = idKinds.get(id);
			if (!kind || !rest.length) continue;
			if (!data.kinds.has(kind)) data.kinds.set(kind, new Map());
			const kindRows = data.kinds.get(kind)!;
			if (!kindRows.has(id)) kindRows.set(id, new Map());

			// Follow intermediate ref slots if g.path has > 2 segments.
			let curKind = kind;
			let curId = id;
			let broken = false;
			for (let i = 0; i < rest.length - 1; i++) {
				const cell = data.kinds.get(curKind)?.get(curId)?.get(rest[i]);
				const sd = schema.kinds[curKind]?.slots[rest[i]];
				if (!sd?.ref || !cell || Array.isArray(cell) || cell.s !== 'known' || typeof cell.v !== 'object' || cell.v === null || !('id' in cell.v)) {
					broken = true;
					break;
				}
				curKind = sd.ref;
				curId = cell.v.id;
			}
			if (broken) continue;
			const slot = rest[rest.length - 1];
			const slotDef = schema.kinds[curKind]?.slots[slot];
			if (!slotDef) continue;

			const t = typing('', schema, new WeakMap());
			const expected = t.value(slotType(schema, slotDef), [], slotDef.card === '*' || slotDef.card === '+');
			const to = t.ex(g.value);
			t.meet(to, g.value, expected, g.value);
			const r = reader({ typed: t.typed, heads: t.heads }, schema, data);
			const val = r.ex(g.value);
			const cause: RowRef = { relation: `${snake(curKind)}__${slot}`, key: [curId] };
			const attributed: V = val.s === 'known' ? val : { ...val, cause };
			if (!data.kinds.has(curKind)) data.kinds.set(curKind, new Map());
			const targetRows = data.kinds.get(curKind)!;
			if (!targetRows.has(curId)) targetRows.set(curId, new Map());
			const cellMap = targetRows.get(curId)!;
			const many = slotDef.card === '*' || slotDef.card === '+';
			if (many) {
				const prev = cellMap.get(slot);
				cellMap.set(slot, prev === undefined ? [attributed] : mergeCell(prev, attributed));
			} else {
				const gk = `${curKind}\0${curId}\0${slot}`;
				if (!givenSingle.has(gk)) {
					givenSingle.add(gk);
					cellMap.set(slot, attributed);
				} else {
					const prev = cellMap.get(slot);
					cellMap.set(slot, prev === undefined ? attributed : mergeCell(prev, attributed));
				}
			}
		}

		// Track core violations (exception_conflict, versions_overlap) per example.
		const coreViolations = new Map<string, Set<string>>();
		const addCoreViolation = (name: string, id: string) => {
			const set = coreViolations.get(name) ?? new Set<string>();
			set.add(id);
			coreViolations.set(name, set);
		};

		// Evaluate derived properties in dependency order.
		for (const entry of derivedEntries) {
			const { kind, decl } = entry;
			const kindDef = schema.kinds[kind];
			if (!kindDef) continue;
			const relation = `${snake(kind)}_${decl.derived}`;

			if (decl.table) {
				const tbl = decl.table;
				const t = typing('', schema, new WeakMap());
				const dtRows: DecisionTable['rows'] = [];
				t.element(kind, () => {
					const inputExprs = tbl.inputs;
					const inputTypes: Typed[] = inputExprs.map((e) => t.settled(e));
					for (const row of tbl.rows) {
						const when: Expr[] = [];
						row.tests.forEach((cell, colIdx) => {
							if (cell === '-') return;
							const inputExpr = inputExprs[colIdx];
							const inputTy = inputTypes[colIdx];
							const parts = cell.map((test): Expr => {
								if ('lit' in test) {
									const litExpr: Expr = { lit: test.lit };
									const b = t.ex(litExpr);
									t.meet(inputTy, inputExpr, b, litExpr);
									return { cmp: ['=', inputExpr, litExpr] };
								}
								const { from, op, to } = test.between;
								if (from && to) {
									const fExpr: Expr = { lit: from.lit };
									const tExpr: Expr = { lit: to.lit };
									t.meet(inputTy, inputExpr, t.ex(fExpr), fExpr);
									t.meet(inputTy, inputExpr, t.ex(tExpr), tExpr);
									return { in: [inputExpr, { range: [fExpr, op, tExpr] }] };
								}
								if (from) {
									const fExpr: Expr = { lit: from.lit };
									t.meet(inputTy, inputExpr, t.ex(fExpr), fExpr);
									return { cmp: ['>=', inputExpr, fExpr] };
								}
								const tExpr: Expr = { lit: to!.lit };
								t.meet(inputTy, inputExpr, t.ex(tExpr), tExpr);
								return { cmp: [op === '..' ? '<=' : '<', inputExpr, tExpr] };
							});
							when.push(parts.length === 1 ? parts[0] : { or: parts });
						});
						const outTy = t.value(slotType(schema, kindDef.slots[decl.derived]));
						t.meet(t.ex(row.value), row.value, outTy, row.value);
						dtRows.push({ when, value: row.value });
					}
				});
				const order = tbl.table === 'priority' ? (() => {
					const ty = slotType(schema, kindDef.slots[decl.derived]);
					if (ty.t !== 'val') return undefined;
					const ev = schema.enums?.[schema.types?.[ty.name]?.enum ?? ty.name];
					return ev === undefined ? undefined : Array.isArray(ev) ? ev : ev.values;
				})() : undefined;
				const dt: DecisionTable = { kind, slot: decl.derived, policy: tbl.table, rows: dtRows, ...(order ? { order } : {}) };
				const tab = tabulate({ schema, tables: [dt], typed: t.typed, heads: t.heads }, data);
				data = tab.data;
				const whyMap = tab.why.get(`${snake(kind)}__${decl.derived}`);
				if (whyMap) {
					for (const [id, witnesses] of whyMap) {
						const cell = data.kinds.get(kind)?.get(id)?.get(decl.derived);
						if (!Array.isArray(cell) && cell?.s === 'invalid' && cell.reason === 'exception_conflict') {
							addCoreViolation('exception_conflict', id);
						}
						const produced = Array.isArray(cell)
							? cell.length > 0
							: cell !== undefined && (cell.s === 'known' || (cell.s === 'invalid' && cell.reason === 'exception_conflict'));
						if (produced) {
							for (const w of witnesses) {
								if (w.row >= 1 && w.row <= entry.rowCovered.length) entry.rowCovered[w.row - 1] = true;
							}
						}
					}
				}
				continue;
			}

			const kd = kindDecls.get(kind);
			const evalSubject = (id: string) => {
				const subjectCtx: EvalContext = { ...exCtx };
				if (kd?.applies) {
					const slotVal = data.kinds.get(kind)?.get(id)?.get(kd.applies.slot);
					if (slotVal && !Array.isArray(slotVal) && slotVal.s === 'known' && typeof slotVal.v === 'string') {
						if (kd.applies.axis === 'at') subjectCtx.at = slotVal.v;
						else if (kd.applies.axis === 'during') subjectCtx.during = slotVal.v;
						else if (kd.applies.axis === 'in') subjectCtx.in = slotVal.v;
					}
				}
				resolveParams(paramEntries, schema, data, subjectCtx, idKinds);

				const evalBody = (expr: Expr): V => evalExpr(expr, schema, data, idKinds, kind, id).value;

				const evalDefs = (defs: DefinitionDecl[], flags: boolean[]): V => {
					const trueIndices: number[] = [];
					const undecided: { idx: number; v: V }[] = [];
					defs.forEach((def, di) => {
						const v = evalBody(def.when);
						if (v.s === 'known' && v.v === true) trueIndices.push(di);
						else if (v.s === 'unknown' || v.s === 'invalid') undecided.push({ idx: di, v });
					});
					const overrides = new Map<string, Set<string>>();
					for (const def of defs) {
						overrides.set(def.name, new Set((def.overrides ?? []).map((o) => o.definition)));
					}
					// Transitive closure of overrides.
					let changed = true;
					while (changed) {
						changed = false;
						for (const targets of overrides.values()) {
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
					const winners = trueIndices.filter(
						(di) => !trueIndices.some((other) => other !== di && overrides.get(defs[other].name)!.has(defs[di].name))
					);
					if (undecided.length) {
						const blockingUndecided = undecided.filter(
							(u) => !trueIndices.some((ai) => overrides.get(defs[ai].name)!.has(defs[u.idx].name))
						);
						if (blockingUndecided.length && winners.length <= 1) {
							return worstV(blockingUndecided.map((u) => u.v))!;
						}
					}
					if (winners.length > 1) {
						for (const di of winners) flags[di] = true;
						addCoreViolation('exception_conflict', id);
						return { s: 'invalid', reason: 'exception_conflict', cause: { relation, key: [id] } };
					}
					if (winners.length === 1) {
						const winIdx = winners[0];
						flags[winIdx] = true;
						return evalBody(defs[winIdx].value);
					}
					return { s: 'unknown', reason: 'no_row_applies', cause: { relation, key: [id] } };
				};

				const evalUnless = (blocks: Clause[][]): V | undefined => {
					for (let bi = blocks.length - 1; bi >= 0; bi--) {
						const blk = blocks[bi];
						const trueIndices: number[] = [];
						const undecided: V[] = [];
						blk.forEach((clause, ci) => {
							const v = evalBody(clause.when);
							if (v.s === 'known' && v.v === true) trueIndices.push(ci);
							else if (v.s === 'unknown' || v.s === 'invalid') undecided.push(v);
						});
						if (trueIndices.length > 1) {
							for (const ci of trueIndices) entry.unlessCovered[bi][ci] = true;
							addCoreViolation('exception_conflict', id);
							return { s: 'invalid', reason: 'exception_conflict', cause: { relation, key: [id] } };
						}
						if (undecided.length > 0) return worstV(undecided)!;
						if (trueIndices.length === 1) {
							const ci = trueIndices[0];
							entry.unlessCovered[bi][ci] = true;
							return evalBody(blk[ci].then);
						}
					}
					return undefined;
				};

				if (decl.versions?.length) {
					const pick = selectVersion(decl.versions, subjectCtx);
					if (pick.kind === 'none') {
						return { s: 'unknown', reason: 'no_version_applies', cause: { relation, key: [id] } } satisfies V;
					}
					if (pick.kind === 'overlap') {
						addCoreViolation('versions_overlap', id);
						return { s: 'invalid', reason: 'versions_overlap', cause: { relation, key: [id] } } satisfies V;
					}
					const vi = decl.versions.indexOf(pick.version);
					if (vi >= 0) entry.versionCovered[vi] = true;
					if (pick.version.definitions?.length) {
						return evalDefs(pick.version.definitions, entry.versionDefCovered[vi]);
					}
					if (pick.version.value) return evalBody(pick.version.value);
					return { s: 'unknown', reason: 'no_version_applies', cause: { relation, key: [id] } } satisfies V;
				}
				if (decl.definitions?.length) {
					return evalDefs(decl.definitions, entry.defCovered);
				}
				if (decl.unless?.length) {
					const overridden = evalUnless(decl.unless);
					if (overridden !== undefined) return overridden;
				}
				if (decl.value) {
					entry.baseCovered = true;
					return evalBody(decl.value);
				}
				return { s: 'unknown', reason: 'no_value', cause: { relation, key: [id] } } satisfies V;
			};

			for (const id of idsOf(data, kind)) {
				const val = evalSubject(id);
				data.kinds.get(kind)!.get(id)!.set(decl.derived, val);
			}
		}

		// Restore example-level parameter context before checks and expectations.
		resolveParams(paramEntries, schema, data, exCtx, idKinds);

		// Evaluate checks and record violations and pass/violate coverage.
		const checkViolations = new Map<string, { any: boolean; subjects: Set<string> }>();
		for (const ce of checkEntries) {
			const c = ce.decl;
			if (c.check === 'norm') continue;
			const t = typing('', schema, new WeakMap());
			const pub = t.statement(c);
			if (pub?.kind !== undefined) {
				const kindCount = data.kinds.get(pub.kind)?.size ?? 0;
				const result = publish({ tree: c, typed: t.typed, heads: t.heads, diagnostics: [], resolve: {}, publication: pub }, schema, data);
				if (result) {
					const badIds = new Set([...result.violations, ...result.blocking]);
					if (badIds.size > 0) {
						ce.violated = true;
						if (c.name) checkViolations.set(c.name, { any: true, subjects: badIds });
					} else if (kindCount > 0 && result.undecided.length === 0) {
						ce.passed = true;
					}
				}
			} else {
				const { value } = evalExpr(c.cond, schema, data, idKinds);
				const refKinds = referencedKinds(c.cond, schema);
				const hasRows = refKinds.size === 0 || [...refKinds].some((k) => (data.kinds.get(k)?.size ?? 0) > 0);
				if (value.s === 'known' && value.v === true) {
					if (hasRows) ce.passed = true;
				} else if ((value.s === 'known' && value.v === false) || value.s === 'invalid') {
					ce.violated = true;
					const badIds = new Set<string>();
					if ('agg' in c.cond && (c.cond.agg[0] === 'all' || c.cond.agg[0] === 'none') && c.cond.agg[2] !== undefined) {
						const [aggName, setExpr, pred] = c.cond.agg;
						const setEval = evalExpr(setExpr, schema, data, idKinds);
						const tSet = typing('', schema, new WeakMap());
						const setTyped = tSet.ex(setExpr);
						if (setEval.value.s === 'known' && Array.isArray(setEval.value.v) && setTyped.ty.t === 'ref') {
							for (const m of setEval.value.v) {
								if (m.s !== 'known' || typeof m.v !== 'object' || !('id' in m.v)) continue;
								const pVal = evalExpr(pred, schema, data, idKinds, setTyped.ty.kind, m.v.id).value;
								const fails = aggName === 'all'
									? (pVal.s === 'known' && pVal.v === false) || pVal.s === 'invalid'
									: (pVal.s === 'known' && pVal.v === true) || pVal.s === 'invalid';
								if (fails) badIds.add(m.v.id);
							}
						}
					} else if (value.s === 'invalid' && value.cause?.key?.[0]) {
						badIds.add(value.cause.key[0]);
					}
					if (c.name) checkViolations.set(c.name, { any: true, subjects: badIds });
				}
			}
		}

		// Verify every `expect` item for this example.
		let exampleFailed = false;
		for (const exp of exDecl.expect) {
			if ('violation' in exp) {
				const label = `violation ${exp.violation}${exp.on !== undefined ? ` on ${exp.on}` : ''}`;
				const fromCheck = checkViolations.get(exp.violation);
				const fromCore = coreViolations.get(exp.violation);
				const hit = exp.on !== undefined
					? Boolean(fromCheck?.subjects.has(exp.on) || fromCore?.has(exp.on))
					: Boolean(fromCheck?.any || (fromCore && fromCore.size > 0));
				if (!hit) {
					exampleFailed = true;
					failures.push({
						example: exDecl.example,
						expectation: label,
						reason: `expected ${label}, but no matching violation occurred`,
					});
				}
			} else {
				const { value, diagnostics } = evalExpr(exp, schema, data, idKinds);
				const text = printExpr(exp);
				const errs = diagnostics.filter(isError);
				if (errs.length) {
					exampleFailed = true;
					failures.push({
						example: exDecl.example,
						expectation: text,
						reason: `type error ${errs[0].code} (${errs[0].args.join(', ')})`,
					});
				} else if (!(value.s === 'known' && value.v === true)) {
					exampleFailed = true;
					failures.push({
						example: exDecl.example,
						expectation: text,
						reason: `got ${formatV(value)}`,
					});
				}
			}
		}
		if (!exampleFailed) passedExamples++;
	}

	// Collect W109 warnings for every uncovered clause.
	const warnings: CoverageWarning[] = [];
	const warn = (clause: string, target: string) => {
		warnings.push({ code: 'W109', clause, target, args: [clause, target] });
	};

	for (const entry of paramEntries) {
		const versions = entry.decl.versions ?? [];
		for (let i = 0; i < versions.length; i++) {
			if (!entry.versionCovered[i]) warn(`version ${versions[i].version}`, entry.decl.param);
		}
	}

	for (const entry of derivedEntries) {
		const { decl, target } = entry;
		if (decl.versions?.length) {
			decl.versions.forEach((v, vi) => {
				if (!entry.versionCovered[vi]) warn(`version ${v.version}`, target);
				(v.definitions ?? []).forEach((def, di) => {
					if (!entry.versionDefCovered[vi][di]) warn(`definition ${def.name}`, target);
				});
			});
		} else if (decl.table) {
			decl.table.rows.forEach((_row, ri) => {
				if (!entry.rowCovered[ri]) warn(`table row ${ri + 1}`, target);
			});
		} else if (decl.definitions?.length) {
			decl.definitions.forEach((def, di) => {
				if (!entry.defCovered[di]) warn(`definition ${def.name}`, target);
			});
		} else if (decl.value && !entry.baseCovered) {
			warn(`derived ${decl.derived}`, target);
		}
		(decl.unless ?? []).forEach((block, bi) => {
			block.forEach((clause, ci) => {
				if (!entry.unlessCovered[bi][ci]) {
					warn(`unless ${printExpr(clause.when)} then ${printExpr(clause.then)}`, target);
				}
			});
		});
	}

	for (const ce of checkEntries) {
		if (ce.decl.check === 'norm') continue;
		if (!ce.passed) warn(`${ce.decl.check} (never passed)`, ce.target);
		if (!ce.violated) warn(`${ce.decl.check} (never violated)`, ce.target);
	}

	return {
		examples: examples.length,
		passed: passedExamples,
		failures,
		warnings,
	};
}
