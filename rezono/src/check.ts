// Names and types of a question against the schema of the role that asks (docs/rezono/expressions.md §5, §6),
// with the diagnostics that follow from them:
//
//   R001  an unknown name, with the names it may have meant (never one the role does not read: the schema
//         handed in is the role's, §5 rule 8); `it` outside an element scope, with the question's row as hint
//   R002  an id where no kind is expected
//   R003  two types that do not go together: dimensions that differ, and every other pair the operator
//         cannot combine (v0 §10 has one code for a failed type check of an operator)
//   R004  `not`, `none(…)`, `all(…)`, the left side of `=>` or an aggregate (`count`, `sum`, `min`, `max`)
//         over an open relation
//   R005  a set where one value is needed
//   R011  a name that is both an element slot and a name outside it
//   R012  a literal token that its expected type does not read; R013 one with no expected type
//   R017  something that is not a truth value where a condition is needed
//   R030  a second argument of `round` that is not one of the four roundings
//   W105  a shown expression that can be unknown on a row of the answer (§13 point 9)
//
// The span of each is the smallest expression it is about (§13 point 11). A reserved construct is not looked
// into: its operands are neither resolved nor typed (§1). This is the check-only mode of §8b: it reads the
// question and the schema and no row.
import { grammar } from './grammar.ts';
import { parse, type Diagnostic, type Span } from './parse.ts';
import { printExpr } from './print.ts';
import { dimText, inPart, mulDim, sameDim, slotType, snake, typeOf, unitOf, type Schema, type StateName, type Ty } from './schema.ts';
import { isAsk, isCheck, type Ask, type CheckDecl, type Expr, type Question } from './tree.ts';

/** What is known of an expression once its names and types are. */
export interface Typed {
	ty: Ty;
	/** A set: a kind, a path through a multivalued slot, a filter, a range (§6). */
	set: boolean;
	/** The states its value can take by typing (§8a). */
	states: Set<StateName>;
	/** The values it reads, by their path from the question's row, and whether each can be unknown. */
	reads: Map<string, boolean>;
	/** The open relations whose missing rows it reads (§6). */
	opens: string[];
	/** The calls of a rule that can be undecided and has no keyed outcome: a missing success row proves nothing about them. */
	partials: Expr[];
	/** The values that are known whenever this one is: what its strict operators read (Appendix A.3). */
	sure: Set<string>;
	/**
	 * A number that a division made, or a product with anything but a whole number: as an amount of money or a
	 * quantity, the type that shows it may not hold it exactly (§8a). `round` takes it away.
	 */
	inexact: boolean;
}
export interface Shown {
	expr: Expr;
	/** The expression in its normal form (§9). */
	text: string;
	typed: Typed;
}
/**
 * How the first name of a path was found (§5): the row of a scope (the question's row by its binder, an element
 * by `it`), a slot of such a row, a parameter, or an id with its kind. `level` counts the scopes from the
 * question's row, 0, inwards. A lone id that took its kind from its context has no entry: its type says it.
 */
export type Head = { as: 'row' | 'slot'; level: number } | { as: 'param' } | { as: 'id'; kind: string };
export interface Checked {
	/** Absent when a parse-level check failed. */
	tree?: Question;
	/** What is known of each expression of the tree, by its node: evaluation reads the types from here. */
	typed: Map<object, Typed>;
	/** How each path of the tree starts, by its node. */
	heads: Map<object, Head>;
	/** Every diagnostic, the parse's own included, in source order. */
	diagnostics: Diagnostic[];
	/** Each id with its kind, and each name that is the question's row (`binder`). */
	resolve: Record<string, string>;
	/** For an `ask` without an error: its binder and what it shows (the default `show` of §8 when none is written). */
	answer?: { binder: string; kind: string; shown: Shown[] };
	/**
	 * For a check statement without an error: its word, its name, and the row it ranges over (absent when its
	 * condition names no kind).
	 */
	publication?: { verb: Exclude<CheckDecl['check'], 'norm'>; name?: string; binder?: string; kind?: string };
}

/** A warning leaves a question valid; every other code is an error. */
export const isError = (d: Diagnostic): boolean => !d.code.startsWith('W');

/** One scope: the question's row (the outermost) or the element of an aggregate, a quantifier or a filter. */
interface Level {
	ty: Ty;
	/** Where its values are read from, as the first part of their path. */
	at: string;
	/** The name of the question's row; absent for an element. */
	binder?: string;
}

const AGGREGATES = new Set(['sum', 'count', 'min', 'max']);
/** The roundings `round(x, mode)` can name (v0 §5f). */
const ROUNDINGS = ['half_even', 'half_up', 'down', 'up'];

/** The edits between two words: a letter added, left out or changed, or two neighbours swapped. */
function distance(a: string, b: string): number {
	let before: number[] = [];
	let row = Array.from({ length: b.length + 1 }, (_, i) => i);
	for (let i = 1; i <= a.length; i++) {
		const next = [i];
		for (let j = 1; j <= b.length; j++) {
			next.push(Math.min(row[j] + 1, next[j - 1] + 1, row[j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1)));
			if (i > 1 && j > 1 && a[i - 1] === b[j - 2] && a[i - 2] === b[j - 1]) next[j] = Math.min(next[j], before[j - 2] + 1);
		}
		before = row;
		row = next;
	}
	return row[b.length];
}
/** The names of a list that a word may have meant: one edit away, two for a word of six letters or more; nearest first. */
export function near(word: string, names: Iterable<string>): string[] {
	const limit = word.length < 6 ? 1 : 2;
	return [...new Set(names)]
		.map((n) => [distance(word, n), n] as const)
		// Never a name with nothing in common: `$` is not a misspelt `€`.
		.filter(([d, n]) => d <= limit && d < Math.max(word.length, n.length))
		.sort(([d1, n1], [d2, n2]) => d1 - d2 || (n1 < n2 ? -1 : 1))
		.map(([, n]) => n);
}
const union = <T>(...sets: Iterable<T>[]): Set<T> => new Set(sets.flatMap((s) => [...s]));
const common = <T>(a: Set<T>, b: Set<T>): Set<T> => new Set([...a].filter((x) => b.has(x)));

/** Checks one question (an `ask` or a suppose line) or one check statement against a schema. */
export function check(text: string, schema: Schema): Checked {
	const parsed = parse(text);
	const { tree } = parsed;
	if (!tree) return { typed: new Map(), heads: new Map(), diagnostics: parsed.diagnostics, resolve: {} };
	const { typed, heads, resolve, found, ask, statement, suppose } = typing(text, schema, parsed.spans);
	const answer = isAsk(tree) ? ask(tree) : undefined;
	const publication = isCheck(tree) ? statement(tree) : undefined;
	if (!isAsk(tree) && !isCheck(tree)) suppose(tree);
	// A reserved construct is reported by the parse; what was found here stands beside it, in source order.
	const diagnostics = [...parsed.diagnostics, ...found].sort((a, b) => a.span.start - b.span.start || a.span.end - b.span.end);
	const valid = !diagnostics.some(isError);
	return { tree, typed, heads, diagnostics, resolve, ...(answer && valid ? { answer } : {}), ...(publication && valid ? { publication } : {}) };
}

/**
 * The names and types of one text against a schema: what the check of a question and the check of a decision
 * table (table.ts) share. `spans` places the nodes of the text; what is found is collected in `found`.
 */
export function typing(text: string, schema: Schema, spans: WeakMap<object, Span>) {
	const resolve: Record<string, string> = {};
	const typed = new Map<object, Typed>();
	const heads = new Map<object, Head>();
	const found: Diagnostic[] = [];
	const levels: Level[] = [];

	const spanOf = (node: object): Span => spans.get(node) ?? { text, start: 0, end: [...text].length };
	/** The span of one word inside a node's span, when it can be found there. */
	function within(node: object, word: string, from: 'start' | 'end'): Span {
		const span = spanOf(node);
		const at = from === 'start' ? span.text.indexOf(word) : span.text.lastIndexOf(word);
		if (at < 0) return span;
		const start = span.start + [...span.text.slice(0, at)].length;
		return { text: word, start, end: start + [...word].length };
	}
	function report(code: string, span: Span, args: string[], more: Pick<Diagnostic, 'hint' | 'suggest'> = {}): Typed {
		found.push({ code, span, args, ...more });
		return value({ t: 'err' });
	}
	function value(ty: Ty, parts: Typed[] = [], set = false): Typed {
		const reads = new Map<string, boolean>();
		for (const p of parts) for (const [path, open] of p.reads) reads.set(path, open || (reads.get(path) ?? false));
		return {
			ty,
			set,
			states: union<StateName>(['known'], ...parts.map((p) => p.states)),
			reads,
			opens: [...union(...parts.map((p) => p.opens))],
			partials: [...union(...parts.map((p) => p.partials))],
			sure: union(...parts.map((p) => p.sure)),
			inexact: ty.t === 'num' && parts.some((p) => p.inexact)
		};
	}
	/** A whole number by its form: a literal of digits, a count, or a value of a type of integers. */
	const whole = (v: Typed, node: Expr): boolean =>
		v.ty.t === 'num' &&
		Object.keys(v.ty.dim).length === 0 &&
		(('lit' in node && /^[0-9]+$/.test(node.lit)) || ('agg' in node && node.agg[0] === 'count') || (v.ty.name !== undefined && (schema.types?.[v.ty.name]?.of ?? v.ty.name) === 'Integer'));
	/** An amount of money or a quantity: a number with a dimension, which its type stores as an integer (publication §3.2). */
	const stored = (ty: Ty): boolean => ty.t === 'num' && Object.keys(ty.dim).length > 0;
	const describe = (ty: Ty): string => (ty.t === 'bool' ? 'Bool' : ty.t === 'num' ? (ty.name ?? dimText(ty.dim)) : ty.t === 'ref' ? ty.kind : ty.t === 'val' ? ty.name : ty.t === 'id' || ty.t === 'tok' ? ty.text : '');
	const slotsOf = (ty: Ty) => (ty.t === 'ref' ? (schema.kinds[ty.kind]?.slots ?? {}) : {});
	/** The values of an enum type, by the type's name; undefined for a type that is no enum. */
	function enumValues(name: string): string[] | undefined {
		const def = schema.types?.[name];
		if (def?.of !== 'Enum') return undefined;
		const values = schema.enums?.[def.enum ?? name];
		return values === undefined ? undefined : Array.isArray(values) ? values : values.values;
	}

	/** The slots one single-valued step away that have this name: `spec.nodes` for `nodes` (E20). */
	function reach(name: string, ty: Ty): string[] {
		const slots = slotsOf(ty);
		return Object.keys(slots)
			.sort()
			.filter((s) => slots[s].ref !== undefined && (slots[s].card === '1' || slots[s].card === '?') && schema.kinds[slots[s].ref!]?.slots[name])
			.map((s) => `${s}.${name}`);
	}
	/** What an unknown bare name may have meant, from what is in scope here. */
	function suggestions(name: string): string[] {
		const inScope: string[] = Object.keys(schema.params ?? {});
		for (const l of levels) inScope.push(...Object.keys(slotsOf(l.ty)), ...(l.binder ? [l.binder] : []));
		return [...new Set([...near(name, inScope), ...[...levels].reverse().flatMap((l) => reach(name, l.ty))])];
	}

	/** An id or a literal token that met no type: R001 for a word that reads as a name, R002 or R013 otherwise. */
	function unresolved(v: Typed, node: object): void {
		const ty = v.ty;
		if (ty.t === 'id') {
			// A keyword reads as a name too: in a table's cell it is a bare word (tables.md §7 point 1).
			if (['name', 'valueWord'].some((r) => grammar.match(ty.text, r).succeeded())) report('R001', spanOf(node), [ty.text], ty.suggest.length ? { suggest: ty.suggest } : {});
			else report('R002', spanOf(node), [ty.text]);
		} else if (ty.t === 'tok') report('R013', spanOf(node), [ty.text]);
		else return;
		v.ty = { t: 'err' };
	}
	/** A value that is used as it is, with no type expected of it. */
	function settled(e: Expr): Typed {
		const v = ex(e);
		unresolved(v, e);
		return v;
	}
	/** Gives an id or a literal token the type its context expects (§3, §6). */
	function expect(v: Typed, node: object, other: Ty): void {
		const ty = v.ty;
		if (ty.t === 'id' && other.t === 'ref') {
			resolve[ty.text] = other.kind;
			v.ty = other;
		} else if (ty.t === 'id' && other.t === 'val' && enumValues(other.name)) {
			// A bare word where an enum is expected is one of its values (`tier = high`), or no name at all.
			const values = enumValues(other.name)!;
			if (values.includes(ty.text)) v.ty = other;
			else {
				v.ty = { ...ty, suggest: near(ty.text, values) };
				unresolved(v, node);
			}
		} else if (ty.t === 'tok' && other.t === 'val') {
			const pattern = schema.types?.[other.name]?.pattern;
			if (pattern === undefined) report('R013', spanOf(node), [ty.text]);
			else if (!new RegExp(`^(?:${pattern})$`, 'u').test(ty.text)) report('R012', spanOf(node), [ty.text, other.name]);
			v.ty = other;
		} else if (other.t !== 'state' && other.t !== 'err') unresolved(v, node);
	}
	/** Whether two values go together; an id or a literal token on one side takes the other side's type. */
	function meet(a: Typed, an: object, b: Typed, bn: object): boolean {
		const pending = (v: Typed) => v.ty.t === 'id' || v.ty.t === 'tok';
		if (pending(a) && pending(b)) {
			unresolved(a, an);
			unresolved(b, bn);
		} else if (pending(a)) expect(a, an, b.ty);
		else if (pending(b)) expect(b, bn, a.ty);
		const x = a.ty;
		const y = b.ty;
		if (x.t === 'err' || y.t === 'err' || x.t === 'state' || y.t === 'state' || x.t === 'id' || y.t === 'id') return true;
		if (x.t === 'num' && y.t === 'num') return sameDim(x.dim, y.dim);
		if (x.t === 'ref' && y.t === 'ref') return x.kind === y.kind;
		if (x.t === 'val' && y.t === 'val') return x.name === y.name;
		return x.t === y.t;
	}
	/** An operand that must be a truth value (R017). */
	function truth(e: Expr): Typed {
		const v = settled(e);
		if (v.set) return report('R005', spanOf(e), []);
		if (v.ty.t !== 'bool' && v.ty.t !== 'err' && v.ty.t !== 'state') {
			report('R017', spanOf(e), [describe(v.ty)]);
			v.ty = { t: 'err' };
		}
		return v;
	}
	/** `not`, `all`, `none`, the left side of `=>` and an aggregate read a missing row as not there: only over a closed relation. */
	function closed(v: Typed, node: object, atCall = false): void {
		if (v.opens.length) report('R004', spanOf(node), [v.opens[0]]);
		// A rule that can be undecided and gives no outcome cannot tell a miss from an undecided call (R047).
		if (v.partials.length) {
			const call = v.partials[0];
			report('R047', spanOf(atCall ? call : node), [(call as { call: [string, Expr[]] }).call[0]]);
		}
		v.opens = [];
		v.partials = [];
	}

	function literal(e: { lit: string }): Typed {
		const is = (rule: string) => grammar.match(e.lit, rule).succeeded();
		if (is('stateLit')) {
			const v = value({ t: 'state' });
			v.states = new Set<StateName>([e.lit === 'n/a' ? 'not_applicable' : e.lit.startsWith('unknown') ? 'unknown' : 'invalid']);
			return v;
		}
		if (is('boolLit')) return value({ t: 'bool' });
		if (is('datetime')) return value({ t: 'val', name: 'DateTime' });
		if (is('date')) return value({ t: 'val', name: 'Date' });
		if (is('money')) {
			const [, symbol, , per] = /^(\S+?) ?([0-9][0-9.]*(?:\/[0-9]+)?)(?:\/([A-Za-z]\w*))?$/u.exec(e.lit)!;
			const currency = schema.symbols?.[symbol];
			if (currency === undefined) return report('R001', within(e, symbol, 'start'), [symbol], { suggest: near(symbol, Object.keys(schema.symbols ?? {})) });
			const unit = per === undefined ? undefined : unitOf(schema, per);
			if (per !== undefined && !unit) return unknownUnit(e, per);
			return value({ t: 'num', dim: mulDim({ [`money ${currency}`]: 1 }, unit?.dim ?? {}, -1) });
		}
		if (is('percent') || is('number')) return value({ t: 'num', dim: {} });
		if (is('quantity')) {
			const word = e.lit.slice(e.lit.lastIndexOf(' ') + 1);
			const unit = unitOf(schema, word);
			return unit ? value({ t: 'num', dim: unit.dim, name: unit.name }) : unknownUnit(e, word);
		}
		if (is('text')) return value({ t: 'val', name: 'Text' });
		if (is('typedText')) {
			const name = e.lit.slice(0, e.lit.indexOf('"'));
			const pattern = schema.types?.[name]?.pattern;
			if (pattern !== undefined && !new RegExp(`^(?:${pattern})$`, 'u').test(e.lit.slice(name.length + 1, -1))) return report('R012', spanOf(e), [e.lit.slice(name.length), name]);
			return value(typeOf(schema, name));
		}
		if (is('typedId')) {
			const kind = e.lit.slice(0, e.lit.indexOf(':'));
			if (!schema.kinds[kind]) return report('R001', within(e, kind, 'start'), [kind], { suggest: near(kind, Object.keys(schema.kinds)) });
			resolve[e.lit.slice(kind.length + 2, -1)] = kind;
			return value({ t: 'ref', kind });
		}
		if (is('numTok')) return value({ t: 'tok', text: e.lit });
		return value({ t: 'id', text: e.lit, suggest: [] });
	}
	const unknownUnit = (e: object, word: string) => report('R001', within(e, word, 'end'), [word], { suggest: near(word, Object.keys(schema.types ?? {})) });

	/** One slot further along a path. */
	function step(from: Typed, at: string, name: string, node: object): [Typed, string] {
		if (from.ty.t === 'err') return [from, at];
		const slot = slotsOf(from.ty)[name];
		if (!slot) return [report('R001', within(node, name, 'end'), [name], { suggest: [...near(name, Object.keys(slotsOf(from.ty))), ...reach(name, from.ty)] }), at];
		const here = `${at}.${name}`;
		const many = slot.card === '*' || slot.card === '+';
		const v = value(slotType(schema, slot), [from], from.set || many);
		for (const s of slot.states) v.states.add(s);
		const kind = (from.ty as { kind: string }).kind;
		// An element of an open kind may have no row, and then every slot of it is unknown (§7, "Sets").
		const unlisted = schema.kinds[kind].world === 'open';
		// A single value of a relation the role reads in part may be one it does not read: unknown, whatever the
		// slot's cardinality (§7a rule 1).
		const part = inPart(schema, kind, name);
		const maybe = unlisted || (part && !many);
		if (maybe) v.states.add('unknown');
		v.reads.set(here, maybe || slot.states.includes('unknown'));
		// An inverse slot is the relation of its forward slot read the other way (publication §3.4). It is open
		// when it says so itself, when its forward slot is open, or when the kind that carries the forward slot is
		// open: an element nobody listed may point here. A `closed` written on either slot does not close that.
		// A relation the role reads in part is open for the role, from either end.
		const forward = slot.inverse !== undefined && slot.ref !== undefined ? schema.kinds[slot.ref]?.slots[slot.inverse] : undefined;
		const open = forward
			? slot.world === 'open' || forward.world === 'open' || schema.kinds[slot.ref!].world === 'open' || inPart(schema, slot.ref!, slot.inverse!)
			: part || (slot.world ?? schema.kinds[kind].world) === 'open';
		if (many && open) v.opens.push(`${kind}.${name}`);
		if (!v.set && !here.startsWith('~')) v.sure.add(here);
		return [v, here];
	}
	/** The first name of a path: `it`, a slot of an element, the question's row, one of its slots, a parameter. */
	function head(name: string, node: object, alone: boolean): [Typed, string] | undefined {
		const inner = levels[levels.length - 1];
		if (name === 'it') {
			if (inner && !inner.binder) {
				heads.set(node, { as: 'row', level: levels.length - 1 });
				return [value(inner.ty), inner.at];
			}
			const row = levels[0]?.binder;
			return [report('R001', within(node, name, 'start'), [name], row ? { hint: { id: 'hint.row', args: [row] } } : {}), ''];
		}
		const hits: (() => [Typed, string])[] = [];
		for (const [level, l] of [...levels.entries()].reverse()) {
			if (l.binder === name) {
				hits.push(() => {
					resolve[name] = 'binder';
					heads.set(node, { as: 'row', level });
					return [value(l.ty), l.at];
				});
			}
			if (slotsOf(l.ty)[name]) {
				hits.push(() => {
					heads.set(node, { as: 'slot', level });
					return step(value(l.ty), l.at, name, node);
				});
			}
		}
		const param = schema.params?.[name];
		if (param) {
			hits.push(() => {
				heads.set(node, { as: 'param' });
				const v = value(slotType(schema, param));
				for (const s of param.states) v.states.add(s);
				v.reads.set(`param ${name}`, param.states.includes('unknown'));
				v.sure.add(`param ${name}`);
				return [v, ''];
			});
		}
		if (hits.length > 1) return [report('R011', within(node, name, 'start'), [name]), ''];
		if (hits.length === 1) return hits[0]();
		// No name in scope: alone it may be an id, which its context decides (§3).
		return alone ? [value({ t: 'id', text: name, suggest: suggestions(name) }), ''] : undefined;
	}
	/** The kinds of the schema that have this chain of slots: what an id at the head of a path can be. */
	function kindsWith(slots: string[]): string[] {
		return Object.keys(schema.kinds)
			.sort()
			.filter((k) => {
				let ty: Ty = { t: 'ref', kind: k };
				return slots.every((s) => {
					const slot = slotsOf(ty)[s];
					if (slot) ty = slotType(schema, slot);
					return slot !== undefined;
				});
			});
	}
	function path(e: { path: string[] }): Typed {
		const [first, ...rest] = e.path;
		let at = head(first, e, rest.length === 0);
		if (!at) {
			// `host-b.owner`: an id and its slots. Its kind is the one kind that has them.
			const kinds = kindsWith(rest);
			const suggest = grammar.match(first, 'name').succeeded() ? suggestions(first) : [];
			if (suggest.length || !kinds.length) return report('R001', within(e, first, 'start'), [first], suggest.length ? { suggest } : {});
			if (kinds.length > 1) return report('R002', within(e, first, 'start'), [first]);
			resolve[first] = kinds[0];
			heads.set(e, { as: 'id', kind: kinds[0] });
			at = [value({ t: 'ref', kind: kinds[0] }), `id ${first}`];
		}
		for (const name of rest) at = step(at[0], at[1], name, e);
		return at[0];
	}

	/** The scope of an element of a kind, where a derived value is written (v0 §5): its slots by their bare name. */
	function element<T>(kind: string, body: () => T): T {
		levels.push({ ty: { t: 'ref', kind }, at: snake(kind) });
		try {
			return body();
		} finally {
			levels.pop();
		}
	}
	/** The scope of an element: inside an aggregate, a quantifier or a filter (§5 rule 2). */
	function inside<T>(element: Typed, body: () => T): T {
		levels.push({ ty: element.ty, at: `~${levels.length}` });
		try {
			return body();
		} finally {
			levels.pop();
		}
	}

	function ex(e: Expr): Typed {
		const v = form(e);
		typed.set(e, v);
		return v;
	}
	function form(e: Expr): Typed {
		if ('lit' in e) return literal(e);
		if ('path' in e) return path(e);
		if ('kind' in e) {
			const kind = schema.kinds[e.kind];
			if (!kind) return report('R001', spanOf(e), [e.kind], { suggest: near(e.kind, Object.keys(schema.kinds)) });
			const v = value({ t: 'ref', kind: e.kind }, [], true);
			if (kind.world === 'open') v.opens.push(e.kind);
			return v;
		}
		if ('dot' in e) return step(settled(e.dot[0]), '~', e.dot[1], e)[0];
		if ('timesel' in e) return ex(e.timesel[0]);
		if ('agg' in e) {
			const [name, of, arg] = e.agg;
			const base = settled(of);
			if (base.ty.t === 'err') return value({ t: 'err' });
			const element = { ...base, set: false };
			if (AGGREGATES.has(name)) {
				const over = arg === undefined ? element : inside(element, () => (name === 'count' ? truth(arg) : settled(arg)));
				if (over.set) return report('R005', spanOf(arg ?? e), []);
				const v = value(name === 'count' ? { t: 'num', dim: {} } : over.ty, [base, over]);
				if (name === 'sum' && over.ty.t !== 'num' && over.ty.t !== 'err' && over.ty.t !== 'state') return report('R003', spanOf(arg ?? e), [name, describe(over.ty)]);
				if (name === 'min' || name === 'max') v.states.add('not_applicable');
				// A count, a sum, the least and the greatest speak of every member: over a set that is not known
				// complete they would read a missing row as "not there".
				closed(v, e, true);
				v.sure = new Set();
				return v;
			}
			const over = arg === undefined ? undefined : inside(element, () => truth(arg));
			const v = value({ t: 'bool' }, over ? [base, over] : [base]);
			if (name !== 'any') closed(v, e, true);
			v.sure = new Set();
			return v;
		}
		if ('filter' in e) {
			const base = settled(e.filter[0]);
			if (base.ty.t === 'err') return value({ t: 'err' });
			const cond = inside({ ...base, set: false }, () => truth(e.filter[1]));
			const v = value(base.ty, [base, cond], true);
			v.sure = new Set();
			return v;
		}
		if ('cmp' in e || 'in' in e || 'range' in e) {
			const [an, bn] = 'cmp' in e ? [e.cmp[1], e.cmp[2]] : 'in' in e ? e.in : [e.range[0], e.range[2]];
			const a = ex(an);
			const b = ex(bn);
			if (a.set || (b.set && !('in' in e))) return report('R005', spanOf(e), []);
			if (!meet(a, an, b, bn)) return report('R003', spanOf(e), [describe(a.ty), describe(b.ty)]);
			// `in` asks whether a value is a member: its right side is a set or a range, never one value.
			if ('in' in e && !b.set && b.ty.t !== 'err' && b.ty.t !== 'state') return report('R003', spanOf(e), [describe(a.ty), describe(b.ty)]);
			const ordered = (ty: Ty) => ty.t !== 'ref' && ty.t !== 'bool';
			if ('range' in e || ('cmp' in e && e.cmp[0] !== '=' && e.cmp[0] !== '!=')) if (!ordered(a.ty) || !ordered(b.ty)) return report('R003', spanOf(e), [describe(a.ty), describe(b.ty)]);
			return 'range' in e ? value(a.ty.t === 'state' ? b.ty : a.ty, [a, b], true) : value({ t: 'bool' }, [a, b]);
		}
		if ('is' in e) {
			const v = value({ t: 'bool' }, [settled(e.is[0])]);
			// A state test is always true or false (A.3b): it is known whatever it reads.
			v.states = new Set<StateName>(['known']);
			for (const read of v.reads.keys()) v.reads.set(read, false);
			v.sure = new Set();
			return v;
		}
		if ('and' in e || 'or' in e || 'not' in e || 'imply' in e) {
			// `not a` and `a => b` read a missing row of `a` as false.
			const parts = ('and' in e ? e.and : 'or' in e ? e.or : 'not' in e ? [e.not] : e.imply).map(truth);
			if ('not' in e || 'imply' in e) closed(parts[0], e);
			const v = value({ t: 'bool' }, parts);
			// A condition can be decided while one of its operands is not (A.1, A.2): `knownWhen` reads it.
			v.sure = new Set();
			return v;
		}
		if ('neg' in e || 'arith' in e) {
			const nodes = 'neg' in e ? [e.neg] : [e.arith[1], e.arith[2]];
			const [a, b = a] = nodes.map(ex);
			if (a.set || b.set) return report('R005', spanOf(e), []);
			const op = 'neg' in e ? '-' : e.arith[0];
			if (op === '*' || op === '/') nodes.forEach((n, i) => unresolved([a, b][i], n));
			const together = op === '*' || op === '/' || meet(a, nodes[0], b, nodes[1] ?? nodes[0]);
			const x = a.ty.t === 'state' ? b.ty : a.ty;
			const y = b.ty.t === 'state' ? a.ty : b.ty;
			if (x.t === 'err' || y.t === 'err' || x.t === 'state') return value({ t: 'err' }, [a, b]);
			// Dates and their periods are typed with v0 §5f. Until then a date takes a number or a date beside it,
			// and nothing else; a date moved by a number is a date, and what two dates give is not examined.
			const date = (ty: Ty) => ty.t === 'val' && (ty.name === 'Date' || ty.name === 'DateTime');
			if (date(x)) {
				if ((op !== '+' && op !== '-') || !(y.t === 'num' || (op === '-' && date(y)))) return report('R003', spanOf(e), [describe(a.ty), describe(b.ty)]);
				return value(y.t === 'num' ? x : { t: 'err' }, [a, b]);
			}
			if (!together || x.t !== 'num' || y.t !== 'num') return report('R003', spanOf(e), [describe(a.ty), describe(b.ty)]);
			if (op === '+' || op === '-') return value({ t: 'num', dim: x.dim, name: x.name ?? y.name }, [a, b]);
			const plain = (ty: { dim: Record<string, number> }) => Object.keys(ty.dim).length === 0;
			const v = value({ t: 'num', dim: mulDim(x.dim, y.dim, op === '*' ? 1 : -1), name: plain(y) ? x.name : plain(x) && op === '*' ? y.name : undefined }, [a, b]);
			// A division by zero is invalid (S1 §2): the one state a calculation adds on its own.
			if (op === '/') v.states.add('invalid');
			// A quotient, and a product with anything but a whole number, may be a value no decimal of its type holds.
			if (op === '/' || !(whole(a, nodes[0]) || whole(b, nodes[1]))) v.inexact = true;
			return v;
		}
		if ('when' in e) {
			const [c, an, bn] = e.when;
			const cond = truth(c);
			const a = ex(an);
			const b = ex(bn);
			if (!meet(a, an, b, bn)) return report('R003', spanOf(e), [describe(a.ty), describe(b.ty)]);
			// Both branches are one value, or both are a set; a state stands for either.
			if (a.set !== b.set && a.ty.t !== 'state' && b.ty.t !== 'state' && a.ty.t !== 'err' && b.ty.t !== 'err') return report('R005', spanOf(e), []);
			const v = value(a.ty.t === 'state' ? b.ty : a.ty, [cond, a, b], a.set || b.set);
			v.sure = new Set();
			return v;
		}
		const [name, args] = e.call;
		if (name === 'round') {
			// `round(x)` or `round(x, mode)`: the mode is a name of the pack's rounding (v0 §5f), not a value.
			const v = args.length ? settled(args[0]) : value({ t: 'err' });
			if (v.set) return report('R005', spanOf(e), []);
			if (args.length < 1 || args.length > 2 || (v.ty.t !== 'num' && v.ty.t !== 'err' && v.ty.t !== 'state')) return report('R003', spanOf(e), [name, args.length ? describe(v.ty) : '']);
			// The mode is one of the four roundings by its bare name; it is not looked up or typed as a value.
			const mode = args[1];
			if (mode !== undefined && !('path' in mode && mode.path.length === 1 && ROUNDINGS.includes(mode.path[0]))) return report('R030', spanOf(mode), [printExpr(mode)]);
			const rounded = value(v.ty, [v]);
			// A rounded amount has the places of its type.
			rounded.inexact = false;
			return rounded;
		}
		const rule = schema.rules?.[name];
		const called = within(e, name, 'start');
		const slot = levels.find((l) => slotsOf(l.ty)[name]);
		if (!rule) return report('R001', called, [name], { suggest: near(name, Object.keys(schema.rules ?? {})) });
		if (slot) return report('R001', called, [name], { suggest: [`${name}(…)`, `${slot.binder ?? 'it'}.${name}`] });
		const given = args.map(ex);
		if (given.length !== rule.binders.length) return report('R003', spanOf(e), [name, String(rule.binders.length)]);
		for (const [i, v] of given.entries()) {
			if (v.set) return report('R005', spanOf(args[i]), []);
			const want = value({ t: 'ref', kind: rule.binders[i].ref });
			if (!meet(v, args[i], want, args[i])) return report('R003', spanOf(args[i]), [describe(v.ty), describe(want.ty)]);
		}
		const v = value({ t: 'bool' }, given);
		if (rule.world === 'open') v.opens.push(name);
		if (!rule.outcome && rule.states?.some((s) => s !== 'known')) v.partials.push(e);
		return v;
	}

	/** The values that are known on every row where a condition is true (or false): Appendix A, read backwards. */
	function knownWhen(e: Expr, holds: boolean): Set<string> {
		const sure = (x: Expr) => typed.get(x)?.sure ?? new Set<string>();
		if ('and' in e || 'or' in e) {
			const parts = ('and' in e ? e.and : e.or).map((x) => knownWhen(x, holds));
			return 'and' in e === holds ? union(...parts) : parts.reduce(common);
		}
		if ('not' in e) return knownWhen(e.not, !holds);
		if ('imply' in e) {
			const [a, b] = [knownWhen(e.imply[0], !holds), knownWhen(e.imply[1], holds)];
			return holds ? common(a, b) : union(a, b);
		}
		if ('when' in e) return union(common(knownWhen(e.when[0], true), knownWhen(e.when[0], false)), common(knownWhen(e.when[1], holds), knownWhen(e.when[2], holds)));
		if ('is' in e) return holds && e.is[1] === 'known' ? sure(e.is[0]) : new Set();
		if ('call' in e) return holds ? sure(e) : new Set();
		return 'cmp' in e || 'in' in e || 'path' in e || 'dot' in e ? sure(e) : new Set();
	}
	/** The default `show` (§8): every single value the condition reads, in source order; an aggregate as itself. */
	function read(e: Expr, out: Expr[]): Expr[] {
		const v = typed.get(e);
		if ('path' in e || 'dot' in e || 'agg' in e) {
			if (v && !v.set && v.reads.size && v.ty.t !== 'err' && !out.some((o) => printExpr(o) === printExpr(e))) out.push(e);
		} else if (!('filter' in e || 'lit' in e || 'kind' in e)) {
			const parts = Object.values(e)[0] as unknown;
			for (const p of Array.isArray(parts) ? parts.flat() : [parts]) if (typeof p === 'object' && p !== null && typed.has(p)) read(p as Expr, out);
		}
		return out;
	}

	function ask(q: Ask): Checked['answer'] {
		if (!schema.kinds[q.ask]) {
			report('R001', within(q, q.ask, 'start'), [q.ask], { suggest: near(q.ask, Object.keys(schema.kinds)) });
			return undefined;
		}
		const binder = q.binder ?? snake(q.ask);
		levels.push({ ty: { t: 'ref', kind: q.ask }, at: binder, binder });
		truth(q.where);
		const known = knownWhen(q.where, true);
		const shown = (q.show ?? read(q.where, [])).map((expr): Shown => {
			const v = q.show ? settled(expr) : typed.get(expr)!;
			// A computed amount that its type cannot hold exactly is shown as `unknown not_exact` (§8a): every shown
			// amount but a stored value and a rounded one lists that state, and one that divides, or multiplies by
			// anything but a whole number, warns.
			if (stored(v.ty) && !('path' in expr || 'dot' in expr || ('call' in expr && expr.call[0] === 'round'))) v.states.add('unknown');
			if (v.set) report('R005', spanOf(expr), []);
			else if (([...v.reads].some(([path, open]) => open && !known.has(path)) || (stored(v.ty) && v.inexact)) && q.show) found.push({ code: 'W105', span: spanOf(expr), args: [printExpr(expr)] });
			return { expr, text: printExpr(expr), typed: v };
		});
		return { binder, kind: q.ask, shown };
	}
	function suppose(q: Exclude<Question, Ask | CheckDecl>): void {
		// A whole-record insertion reads and prints (decisions/language-safe-steps.md §1); checking it against the
		// schema is not done yet, so it is refused at its span rather than read as a change it does not make.
		if ('insert_row' in q) {
			report('R015', spanOf(q), ['a whole-record insertion']);
			return;
		}
		if ('retract_row' in q) {
			const [kind] = q.retract_row;
			if (!schema.kinds[kind]) report('R001', within(q, kind, 'start'), [kind], { suggest: near(kind, Object.keys(schema.kinds)) });
			else resolve[q.retract_row[1]] = kind;
			return;
		}
		const target = 'set' in q ? q.set[0] : q.retract;
		const slot = path(target);
		if (!('set' in q)) return;
		const to = ex(q.set[1]);
		if (to.set !== slot.set && to.ty.t !== 'err' && slot.ty.t !== 'err') report('R005', spanOf(q.set[1]), []);
		else if (!meet(to, q.set[1], slot, target)) report('R003', spanOf(q.set[1]), [describe(to.ty), describe(slot.ty)]);
	}

	/**
	 * A check statement ranges over every element of the kind its condition names in lowercase (v0 §5): the
	 * first name of a path that is a kind's name in lowercase is its row, as the binder of an `ask` is. A second
	 * such kind is a second binder, reserved as in an `ask` (§1).
	 */
	function statement(q: CheckDecl): Checked['publication'] {
		// `norm` is reserved (v0 §5): the parse reported it, and its condition is not looked into (§1).
		if (q.check === 'norm') return undefined;
		const firsts: [string, object][] = [];
		const walk = (x: unknown): void => {
			if (Array.isArray(x)) x.forEach(walk);
			else if (typeof x === 'object' && x !== null) {
				if ('path' in x) firsts.push([(x as { path: string[] }).path[0], x]);
				else Object.values(x).forEach(walk);
			}
		};
		walk(q.cond);
		const kindOf = (name: string) => Object.keys(schema.kinds).find((k) => snake(k) === name);
		const rows = firsts.filter(([name]) => kindOf(name) !== undefined).sort(([, a], [, b]) => spanOf(a).start - spanOf(b).start);
		const other = rows.find(([name]) => name !== rows[0][0]);
		if (other) {
			found.push({ code: 'R015', span: within(other[1], other[0], 'start'), args: ['a second binder'] });
			return undefined;
		}
		const binder = rows[0]?.[0];
		if (binder !== undefined) levels.push({ ty: { t: 'ref', kind: kindOf(binder)! }, at: binder, binder });
		truth(q.cond);
		return { verb: q.check, ...(q.name !== undefined ? { name: q.name } : {}), ...(binder !== undefined ? { binder, kind: kindOf(binder)! } : {}) };
	}

	return { typed, heads, resolve, found, ask, statement, suppose, element, settled, ex, meet, report, value, describe, spanOf, enumValues };
}
