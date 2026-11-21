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
import { baseTypeOf, dimText, inPart, isOrdered, mulDim, sameDim, slotType, snake, typeOf, unitOf, type Schema, type SlotDef, type StateName, type Ty, type World } from './schema.ts';
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

/** A module-level derivation visible in a rezono 1 module as both a callable relation/function and a tuple set. */
export interface RelationDef {
	params: { name: string; slot: SlotDef }[];
	result: Ty;
	set?: boolean;
	world: World;
	states: StateName[];
}

export interface TypingOptions {
	/** Enforce rezono 1 type rules (e.g. R028 on collection path projections). */
	rezono1?: boolean;
	/** Module-level derivations callable by name and usable as tuple sets in rezono 1. */
	relations?: Record<string, RelationDef>;
	/** Refuse reading slots marked `personal` with R054 (decisions/personal-data-handling.md §3). */
	forbidPersonal?: boolean;
}

/** One scope: the question's row (the outermost) or the element of an aggregate, a quantifier or a filter. */
interface Level {
	ty: Ty;
	/** Where its values are read from, as the first part of their path. */
	at: string;
	/** The name of the question's row, a derivation parameter, or an explicit method binder; absent for implicit `it`. */
	binder?: string;
	/** When true, only the binder name itself is in scope (not its slots as bare names). */
	paramOnly?: boolean;
	/** When true, this scope was opened by an explicit method binder (`S.any(x: ...)`): bare slots yield to outer variables. */
	methodBinder?: true;
	/** Named columns when ranging over a relation tuple set. */
	fields?: Record<string, SlotDef>;
}

type ProjectionContext = { kind: 'agg'; name: string; arg?: Expr } | { kind: 'in'; lhs: Expr };

const AGGREGATES = new Set(['sum', 'count', 'min', 'max']);
/** The roundings `round(x, mode)` can name (v0 §5f). */
const ROUNDINGS = ['half_even', 'half_up', 'down', 'up'];
/** The built-in rounding functions that accept an optional `as TargetType` specifier. */
const ROUND_FNS = new Set(['round', 'floor', 'ceil']);

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
export function check(text: string, schema: Schema, options?: TypingOptions): Checked {
	const parsed = parse(text);
	const { tree } = parsed;
	if (!tree) return { typed: new Map(), heads: new Map(), diagnostics: parsed.diagnostics, resolve: {} };
	const { typed, heads, resolve, found, ask, statement, suppose } = typing(text, schema, parsed.spans, options);
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
export function typing(text: string, schema: Schema, spans: WeakMap<object, Span>, options?: TypingOptions) {
	const resolve: Record<string, string> = {};
	const typed = new Map<object, Typed>();
	const heads = new Map<object, Head>();
	const found: Diagnostic[] = [];
	const levels: Level[] = [];
	const tupleFields = new WeakMap<Typed, Record<string, SlotDef>>();
	let projectionContext: ProjectionContext | undefined;
	let inCheckStatement = false;

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
		(('lit' in node && /^[0-9]+$/.test(node.lit)) || ('agg' in node && node.agg[0] === 'count') || (v.ty.name !== undefined && baseTypeOf(schema, v.ty.name) === 'Integer'));
	/** An amount of money or a quantity: a number with a dimension, which its type stores as an integer (publication §3.2). */
	const stored = (ty: Ty): boolean => ty.t === 'num' && Object.keys(ty.dim).length > 0;
	/** Whether a type supports ordering operators (`<`, `<=`, `>`, `>=`, `..`, `min`, `max`). */
	const ordered = (ty: Ty): boolean => ty.t === 'err' || ty.t === 'state' || isOrdered(schema, ty);
	/** Whether an expression is a constant numeric literal (possibly negated) whose value is non-zero. */
	function nonZeroConst(node: Expr): boolean {
		if ('neg' in node) return nonZeroConst(node.neg);
		if (!('lit' in node)) return false;
		const m = /^(?:\S+? ?)?([0-9]+(?:\.[0-9]+|\/[0-9]+)?)(?:[ \t]*%|[ \t]+[A-Za-z]\w*|\/[A-Za-z]\w*)?$/u.exec(node.lit);
		if (!m) return false;
		const num = m[1];
		if (/\/0+$/.test(num)) return false;
		return /[1-9]/.test(num.split('/')[0]);
	}
	const describe = (ty: Ty): string => (ty.t === 'bool' ? 'Bool' : ty.t === 'num' ? (ty.name ?? dimText(ty.dim)) : ty.t === 'ref' ? ty.kind : ty.t === 'val' ? ty.name : ty.t === 'id' || ty.t === 'tok' ? ty.text : '');
	const slotsOf = (ty: Ty) => (ty.t === 'ref' ? (schema.kinds[ty.kind]?.slots ?? {}) : {});
	const slotsOfTyped = (v: Typed) => tupleFields.get(v) ?? slotsOf(v.ty);
	const slotsOfLevel = (l: Level) => (l.paramOnly ? {} : (l.fields ?? slotsOf(l.ty)));
	/** Formats a collection receiver expression in rezono 1 `.where(...)` spelling for R028 hints. */
	function formatCollectionBase(e: Expr): string {
		if ('filter' in e) {
			const [set, cond, binder] = e.filter;
			return `${formatCollectionBase(set)}.where(${binder ? `${binder}: ` : ''}${printExpr(cond)})`;
		}
		return printExpr(e);
	}
	/** Prefixes bare paths inside an aggregate argument when rewriting `S.p.agg(q)` to `S.agg(p.q)`. */
	function prefixProjectionArg(projPath: string, arg: Expr): string {
		if ('path' in arg) {
			if (arg.path[0] === 'it') return arg.path.length > 1 ? `${projPath}.${arg.path.slice(1).join('.')}` : projPath;
			return `${projPath}.${arg.path.join('.')}`;
		}
		return printExpr(arg);
	}
	/** Builds the `hint.use_instead` replacement for a refused collection path projection in rezono 1. */
	function buildProjectionHint(baseText: string, projPath: string, ctx?: ProjectionContext): string {
		if (ctx?.kind === 'agg') {
			if (ctx.name === 'count') {
				return ctx.arg === undefined ? `${baseText}.count()` : `${baseText}.count(${prefixProjectionArg(projPath, ctx.arg)})`;
			}
			if (ctx.name === 'sum' || ctx.name === 'min' || ctx.name === 'max' || ctx.name === 'one') {
				return ctx.arg === undefined ? `${baseText}.${ctx.name}(${projPath})` : `${baseText}.${ctx.name}(${prefixProjectionArg(projPath, ctx.arg)})`;
			}
			return ctx.arg === undefined ? `${baseText}.${ctx.name}()` : `${baseText}.${ctx.name}(${prefixProjectionArg(projPath, ctx.arg)})`;
		}
		if (ctx?.kind === 'in') return `${baseText}.any(${projPath} = ${printExpr(ctx.lhs)})`;
		return `${baseText}.one(${projPath})`;
	}
	function refuseCollectionProjection(node: object, baseText: string, projPath: string, ctx?: ProjectionContext): Typed {
		const span = spanOf(node);
		return report('R028', span, [span.text, '1'], {
			hint: { id: 'hint.use_instead', args: [buildProjectionHint(baseText, projPath, ctx)] },
		});
	}
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
		const inScope: string[] = [...Object.keys(schema.params ?? {}), ...Object.keys(options?.relations ?? {})];
		for (const l of levels) inScope.push(...Object.keys(slotsOfLevel(l)), ...(l.binder ? [l.binder] : []));
		return [...new Set([...near(name, inScope), ...[...levels].reverse().flatMap((l) => (l.paramOnly ? [] : reach(name, l.ty)))])];
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
			const [, symbol, numText, per] = /^(\S+?) ?([0-9]+(?:\.[0-9]+|\/[0-9]+)?)(?:\/([A-Za-z]\w*))?$/u.exec(e.lit)!;
			const currency = schema.symbols?.[symbol];
			if (currency === undefined) return report('R001', within(e, symbol, 'start'), [symbol], { suggest: near(symbol, Object.keys(schema.symbols ?? {})) });
			const unit = per === undefined ? undefined : unitOf(schema, per);
			if (per !== undefined && !unit) return unknownUnit(e, per);
			const ty: Ty = { t: 'num', dim: mulDim({ [`money ${currency}`]: 1 }, unit?.dim ?? {}, -1) };
			if (/\/0+$/.test(numText)) return report('R012', spanOf(e), [e.lit, describe(ty)]);
			const v = value(ty);
			if (numText.includes('/')) v.inexact = true;
			return v;
		}
		if (is('percent') || is('number')) {
			const numText = e.lit.replace(/[ \t]*%$/, '');
			if (/\/0+$/.test(numText)) return report('R012', spanOf(e), [e.lit, 'number']);
			const v = value({ t: 'num', dim: {} });
			if (numText.includes('/')) v.inexact = true;
			return v;
		}
		if (is('quantity')) {
			const cut = e.lit.lastIndexOf(' ');
			const numText = e.lit.slice(0, cut).trim();
			const word = e.lit.slice(cut + 1);
			const unit = unitOf(schema, word);
			if (!unit) return unknownUnit(e, word);
			if (/\/0+$/.test(numText)) return report('R012', spanOf(e), [e.lit, unit.name]);
			const v = value({ t: 'num', dim: unit.dim, name: unit.name });
			if (numText.includes('/')) v.inexact = true;
			return v;
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
		const slots = slotsOfTyped(from);
		const slot = slots[name];
		if (!slot) return [report('R001', within(node, name, 'end'), [name], { suggest: [...near(name, Object.keys(slots)), ...reach(name, from.ty)] }), at];
		if ((options?.forbidPersonal || inCheckStatement) && slot.personal) {
			const target = from.ty.t === 'ref' ? `${from.ty.kind}.${name}` : name;
			return [report('R054', within(node, name, 'end'), [target]), at];
		}
		const here = `${at}.${name}`;
		const many = slot.card === '*' || slot.card === '+';
		const v = value(slotType(schema, slot), [from], from.set || many);
		for (const s of slot.states) v.states.add(s);
		if (from.ty.t === 'ref') {
			const kind = from.ty.kind;
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
		}
		if (!v.set && !here.startsWith('~')) v.sure.add(here);
		return [v, here];
	}
	/** The first name of a path: `it`, a slot of an element, the question's row, one of its slots, a parameter, or a rezono 1 relation tuple set. */
	function head(name: string, node: object, alone: boolean): [Typed, string] | undefined {
		const inner = levels[levels.length - 1];
		if (name === 'it') {
			if (inner && !inner.binder) {
				heads.set(node, { as: 'row', level: levels.length - 1 });
				const row = value(inner.ty);
				if (inner.fields) tupleFields.set(row, inner.fields);
				return [row, inner.at];
			}
			const row = inner?.binder ?? levels[0]?.binder;
			return [report('R001', within(node, name, 'start'), [name], row && row !== 'it' ? { hint: { id: 'hint.row', args: [row] } } : {}), ''];
		}
		const hits: (() => [Typed, string])[] = [];
		for (const [level, l] of [...levels.entries()].reverse()) {
			if (l.binder === name) {
				hits.push(() => {
					resolve[name] = 'binder';
					heads.set(node, { as: 'row', level });
					const row = value(l.ty);
					if (l.fields) tupleFields.set(row, l.fields);
					return [row, l.at];
				});
			}
			if (slotsOfLevel(l)[name]) {
				const shadowedByMethodBinder = levels.slice(level).some((inner) => inner.methodBinder && inner.binder === name);
				const shadowedByOuterVar =
					l.methodBinder &&
					(levels.slice(0, level).some((outer) => outer.binder === name) || Object.hasOwn(schema.params ?? {}, name));
				if (!shadowedByMethodBinder && !shadowedByOuterVar) {
					hits.push(() => {
						heads.set(node, { as: 'slot', level });
						const row = value(l.ty);
						if (l.fields) tupleFields.set(row, l.fields);
						return step(row, l.at, name, node);
					});
				}
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
		const rel = options?.relations?.[name];
		if (rel) {
			hits.push(() => {
				const v = value({ t: 'val', name }, [], true);
				tupleFields.set(v, Object.fromEntries(rel.params.map((p) => [p.name, p.slot])));
				if (rel.world === 'open') v.opens.push(name);
				return [v, name];
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
	function path(e: { path: string[] }, ctx?: ProjectionContext): Typed {
		const [first, ...rest] = e.path;
		let at = head(first, e, rest.length === 0);
		if (!at) {
			const isName = grammar.match(first, 'name').succeeded();
			const suggest = isName ? suggestions(first) : [];
			// In rezono 1, an unbound bare name appearing as the receiver of a path (e.g. `za.outside`)
			// is always R001 and never inferred as an element ID from slot names.
			if (options?.rezono1 && isName) return report('R001', within(e, first, 'start'), [first], suggest.length ? { suggest } : {});
			// `host-b.owner`: an id and its slots. Its kind is the one kind that has them.
			const kinds = kindsWith(rest);
			if (suggest.length || !kinds.length) return report('R001', within(e, first, 'start'), [first], suggest.length ? { suggest } : {});
			if (kinds.length > 1) return report('R002', within(e, first, 'start'), [first]);
			resolve[first] = kinds[0];
			heads.set(e, { as: 'id', kind: kinds[0] });
			at = [value({ t: 'ref', kind: kinds[0] }), `id ${first}`];
		}
		for (let i = 0; i < rest.length; i++) {
			if (options?.rezono1 && at[0].set) {
				const baseText = [first, ...rest.slice(0, i)].join('.');
				const projPath = rest.slice(i).join('.');
				return refuseCollectionProjection(e, baseText, projPath, ctx);
			}
			at = step(at[0], at[1], rest[i], e);
		}
		return at[0];
	}

	/** The scope of an element of a kind, where a derived value is written (v0 §5): its slots by their bare name. */
	function element<T>(kind: string, body: () => T, binder?: string): T {
		levels.push({ ty: { t: 'ref', kind }, at: binder ?? snake(kind), ...(binder !== undefined ? { binder } : {}) });
		try {
			return body();
		} finally {
			levels.pop();
		}
	}
	/** The scope of named parameters of a multi-key derivation (only the parameter names are in scope, not their slots). */
	function params<T>(bindings: { name: string; ty: Ty }[], body: () => T): T {
		for (const b of bindings) levels.push({ ty: b.ty, at: b.name, binder: b.name, paramOnly: true });
		try {
			return body();
		} finally {
			for (let i = 0; i < bindings.length; i++) levels.pop();
		}
	}
	/** The span of an explicit method binder `<name>:` inside `S.method(name: expr)`. */
	function binderSpan(node: object, base: Expr, binder: string): Span {
		const span = spanOf(node);
		const baseEnd = spanOf(base).end;
		const afterBase = Math.max(0, baseEnd - span.start);
		const tail = [...span.text].slice(afterBase).join('');
		const m = /\(\s*([a-z][a-z0-9_]*)\s*:/.exec(tail);
		if (!m || m[1] !== binder) return within(node, binder, 'start');
		const offsetInTail = m.index + m[0].indexOf(binder);
		const start = span.start + afterBase + [...tail.slice(0, offsetInTail)].length;
		return { text: binder, start, end: start + [...binder].length };
	}
	/** The scope of an element: inside an aggregate, a quantifier or a filter (§5 rule 2). */
	function inside<T>(element: Typed, body: () => T, binder?: string, bSpan?: Span): T {
		let effectiveBinder = binder;
		if (binder !== undefined) {
			const reserved = binder === 'it';
			const duplicate =
				reserved ||
				levels.some((l) => l.binder === binder) ||
				Object.hasOwn(schema.params ?? {}, binder);
			if (duplicate) report('R011', bSpan ?? { text: binder, start: 0, end: binder.length }, [binder]);
			if (reserved) effectiveBinder = undefined;
		}
		const fields = tupleFields.get(element);
		levels.push({
			ty: element.ty,
			at: `~${levels.length}`,
			...(effectiveBinder !== undefined ? { binder: effectiveBinder, methodBinder: true as const } : {}),
			...(fields ? { fields } : {}),
		});
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
		const ctx = projectionContext;
		projectionContext = undefined;
		if ('lit' in e) return literal(e);
		if ('wildcard' in e) return value({ t: 'state' });
		if ('path' in e) return path(e, ctx);
		if ('kind' in e) {
			const kind = schema.kinds[e.kind];
			if (!kind) return report('R001', spanOf(e), [e.kind], { suggest: near(e.kind, Object.keys(schema.kinds)) });
			const v = value({ t: 'ref', kind: e.kind }, [], true);
			if (kind.world === 'open') v.opens.push(e.kind);
			return v;
		}
		if ('dot' in e) {
			if (!options?.rezono1) return step(settled(e.dot[0]), '~', e.dot[1], e)[0];
			const chain: { dot: [Expr, string] }[] = [];
			let cur: Expr = e;
			while ('dot' in cur) {
				chain.unshift(cur);
				cur = cur.dot[0];
			}
			let at: [Typed, string] = [settled(cur), '~'];
			for (let i = 0; i < chain.length; i++) {
				if (at[0].set) {
					const prefix = formatCollectionBase(cur);
					const baseText = i === 0 ? prefix : `${prefix}.${chain.slice(0, i).map((d) => d.dot[1]).join('.')}`;
					const projPath = chain.slice(i).map((d) => d.dot[1]).join('.');
					return refuseCollectionProjection(e, baseText, projPath, ctx);
				}
				at = step(at[0], at[1], chain[i].dot[1], chain[i]);
				typed.set(chain[i], at[0]);
			}
			return at[0];
		}
		if ('timesel' in e) return ex(e.timesel[0]);
		if ('agg' in e) {
			const [name, of, arg, binder] = e.agg;
			projectionContext = options?.rezono1 ? { kind: 'agg', name, arg } : undefined;
			let base: Typed;
			try {
				base = settled(of);
			} finally {
				projectionContext = undefined;
			}
			if (base.ty.t === 'err') return value({ t: 'err' });
			if (!base.set && base.ty.t !== 'state') return report('R003', spanOf(e), [name, describe(base.ty)]);
			const baseFields = tupleFields.get(base);
			const element = { ...base, set: false };
			if (baseFields) tupleFields.set(element, baseFields);
			const bSpan = binder !== undefined ? binderSpan(e, of, binder) : undefined;
			if (name === 'one') {
				const over = arg === undefined ? element : inside(element, () => settled(arg), binder, bSpan);
				if (over.set) return report('R005', spanOf(arg ?? e), []);
				const v = value(over.ty, arg === undefined ? [base] : [base, over]);
				v.states.add('unknown');
				v.states.add('not_applicable');
				v.states.add('invalid');
				closed(v, e, true);
				v.sure = new Set();
				return v;
			}
			if (AGGREGATES.has(name)) {
				const over = arg === undefined ? element : inside(element, () => (name === 'count' ? truth(arg) : settled(arg)), binder, bSpan);
				if (over.set) return report('R005', spanOf(arg ?? e), []);
				const v = value(name === 'count' ? { t: 'num', dim: {} } : over.ty, [base, over]);
				if (name === 'sum' && over.ty.t !== 'num' && over.ty.t !== 'err' && over.ty.t !== 'state') return report('R003', spanOf(arg ?? e), [name, describe(over.ty)]);
				if (name === 'min' || name === 'max') {
					if (!ordered(over.ty)) return report('R003', spanOf(arg ?? e), [name, describe(over.ty)]);
					v.states.add('not_applicable');
				}
				// A count, a sum, the least and the greatest speak of every member: over a set that is not known
				// complete they would read a missing row as "not there".
				closed(v, e, true);
				v.sure = new Set();
				return v;
			}
			const over = arg === undefined ? undefined : inside(element, () => truth(arg), binder, bSpan);
			const v = value({ t: 'bool' }, over ? [base, over] : [base]);
			if (name !== 'any') closed(v, e, true);
			v.sure = new Set();
			return v;
		}
		if ('filter' in e) {
			const [of, pred, binder] = e.filter;
			const base = settled(of);
			if (base.ty.t === 'err') return value({ t: 'err' });
			if (!base.set && base.ty.t !== 'state') return report('R003', spanOf(e), ['where', describe(base.ty)]);
			const baseFields = tupleFields.get(base);
			const element = { ...base, set: false };
			if (baseFields) tupleFields.set(element, baseFields);
			const bSpan = binder !== undefined ? binderSpan(e, of, binder) : undefined;
			const cond = inside(element, () => truth(pred), binder, bSpan);
			const v = value(base.ty, [base, cond], true);
			if (baseFields) tupleFields.set(v, baseFields);
			v.sure = new Set();
			return v;
		}
		if ('cmp' in e || 'in' in e || 'range' in e) {
			const [an, bn] = 'cmp' in e ? [e.cmp[1], e.cmp[2]] : 'in' in e ? e.in : [e.range[0], e.range[2]];
			const a = ex(an);
			projectionContext = 'in' in e && options?.rezono1 ? { kind: 'in', lhs: an } : undefined;
			let b: Typed;
			try {
				b = ex(bn);
			} finally {
				projectionContext = undefined;
			}
			if (a.set || (b.set && !('in' in e))) return report('R005', spanOf(e), []);
			if (!meet(a, an, b, bn)) return report('R003', spanOf(e), [describe(a.ty), describe(b.ty)]);
			// `in` asks whether a value is a member: its right side is a set or a range, never one value.
			if ('in' in e && !b.set && b.ty.t !== 'err' && b.ty.t !== 'state') return report('R003', spanOf(e), [describe(a.ty), describe(b.ty)]);
			if ('range' in e || ('cmp' in e && e.cmp[0] !== '=' && e.cmp[0] !== '!=')) if (!ordered(a.ty) || !ordered(b.ty)) return report('R003', spanOf(e), [describe(a.ty), describe(b.ty)]);
			return 'range' in e ? value(a.ty.t === 'state' ? b.ty : a.ty, [a, b], true) : value({ t: 'bool' }, [a, b]);
		}
		if ('is' in e) {
			const v = value({ t: 'bool' }, [settled(e.is[0])]);
			// A state test is always true or false (A.3b): it is known whatever it reads.
			v.states = new Set<StateName>(['known']);
			for (const read of v.reads.keys()) v.reads.set(read, false);
			v.opens = [];
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
			// Dates and instants take a time/calendar duration for `+`/`-`, or another date/instant for `-` (v0 §5f).
			const date = (ty: Ty) => ty.t === 'val' && (baseTypeOf(schema, ty.name) === 'Date' || baseTypeOf(schema, ty.name) === 'DateTime');
			const duration = (ty: Ty) => ty.t === 'num' && (sameDim(ty.dim, { time: 1 }) || sameDim(ty.dim, { calendar: 1 }));
			if (date(x)) {
				if ('neg' in e) return report('R003', spanOf(e), ['-', describe(a.ty)]);
				if (op !== '+' && op !== '-') return report('R003', spanOf(e), [describe(a.ty), describe(b.ty)]);
				if (b.ty.t === 'state') return value(x, [a, b]);
				if (!(duration(y) || (op === '-' && date(y)))) return report('R003', spanOf(e), [describe(a.ty), describe(b.ty)]);
				return value(y.t === 'num' ? x : { t: 'err' }, [a, b]);
			}
			if (!together || x.t !== 'num' || y.t !== 'num') return report('R003', spanOf(e), [describe(a.ty), describe(b.ty)]);
			if (op === '+' || op === '-') return value({ t: 'num', dim: x.dim, name: x.name ?? y.name }, [a, b]);
			const plain = (ty: { dim: Record<string, number> }) => Object.keys(ty.dim).length === 0;
			const v = value({ t: 'num', dim: mulDim(x.dim, y.dim, op === '*' ? 1 : -1), name: plain(y) ? x.name : plain(x) && op === '*' ? y.name : undefined }, [a, b]);
			// A division by zero is invalid (S1 §2): only when the divisor is not a constant non-zero literal.
			if (op === '/' && !nonZeroConst(nodes[1])) v.states.add('invalid');
			// A quotient, and a product with anything but a whole number, may be a value no decimal of its type holds.
			if (op === '/' || !(whole(a, nodes[0]) || whole(b, nodes[1]))) v.inexact = true;
			return v;
		}
		if ('otherwise' in e) {
			const [an, bn] = e.otherwise;
			const a = ex(an);
			const b = ex(bn);
			if (!meet(a, an, b, bn)) return report('R003', spanOf(e), [describe(a.ty), describe(b.ty)]);
			if (a.set !== b.set && a.ty.t !== 'state' && b.ty.t !== 'state' && a.ty.t !== 'err' && b.ty.t !== 'err') return report('R005', spanOf(e), []);
			const ty = a.ty.t === 'state' ? b.ty : a.ty.t === 'num' && b.ty.t === 'num' ? { ...a.ty, name: a.ty.name ?? b.ty.name } : a.ty;
			const v = value(ty, [a, b], a.set || b.set);
			const states = new Set<StateName>(a.states);
			if (states.has('not_applicable')) {
				states.delete('not_applicable');
				for (const s of b.states) states.add(s);
			}
			v.states = states;
			v.sure = union(a.sure, [`expr ${printExpr(e)}`]);
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
		if ('as' in e) return report('R003', spanOf(e), [printExpr(e.as[0]), e.as[1]]);
		const [name, args] = e.call;
		if (ROUND_FNS.has(name)) {
			// `round(x [as TargetType][, mode])`, `floor(x [as TargetType])`, `ceil(x [as TargetType])`.
			const arg0 = args[0];
			const inner = arg0 && 'as' in arg0 ? arg0.as[0] : arg0;
			const targetName = arg0 && 'as' in arg0 ? arg0.as[1] : undefined;
			const v = inner ? settled(inner) : value({ t: 'err' });
			if (arg0 && 'as' in arg0) typed.set(arg0, v);
			if (v.set) return report('R005', spanOf(e), []);
			const badArity = name === 'round' ? args.length < 1 || args.length > 2 : args.length !== 1;
			if (badArity || (v.ty.t !== 'num' && v.ty.t !== 'err' && v.ty.t !== 'state')) {
				return report('R003', spanOf(e), [name, args.length ? describe(v.ty) : '']);
			}
			// The mode is one of the four roundings by its bare name; it is not looked up or typed as a value.
			const mode = name === 'round' ? args[1] : undefined;
			if (mode !== undefined && !('path' in mode && mode.path.length === 1 && ROUNDINGS.includes(mode.path[0]))) {
				return report('R030', spanOf(mode), [printExpr(mode)]);
			}
			if (v.ty.t === 'err') return value({ t: 'err' });
			let outTy: Ty = v.ty;
			if (targetName !== undefined) {
				const targetTy = typeOf(schema, targetName);
				if (targetTy.t !== 'num' || baseTypeOf(schema, targetName) === 'Ratio') {
					return report('R003', spanOf(e), [describe(v.ty), targetName]);
				}
				if (v.ty.t === 'num' && !sameDim(v.ty.dim, targetTy.dim)) {
					return report('R003', spanOf(e), [describe(v.ty), targetName]);
				}
				outTy = targetTy;
			} else if (v.ty.t === 'num') {
				if (v.ty.name !== undefined) {
					outTy =
						Object.keys(v.ty.dim).length === 0 && baseTypeOf(schema, v.ty.name) === 'Ratio'
							? { t: 'num', dim: {}, name: 'Integer' }
							: v.ty;
				} else if (Object.keys(v.ty.dim).length === 0) {
					outTy = { t: 'num', dim: {}, name: 'Integer' };
				} else {
					const dim = dimText(v.ty.dim);
					const declared = schema.default_units?.[dim];
					const declaredTy = declared === undefined ? undefined : typeOf(schema, declared);
					if (declaredTy?.t === 'num' && sameDim(declaredTy.dim, v.ty.dim)) {
						outTy = declaredTy;
					} else {
						const sample =
							Object.keys(schema.types ?? {})
								.sort()
								.find((n) => {
									const t = typeOf(schema, n);
									return t.t === 'num' && sameDim(t.dim, v.ty.dim);
								}) ?? 'Type';
						const rest = mode !== undefined ? `, ${printExpr(mode)}` : '';
						return report('R013', spanOf(e), [printExpr(inner)], {
							hint: { id: 'hint.use_instead', args: [`${name}(${printExpr(inner)} as ${sample}${rest})`] }
						});
					}
				}
			}
			const rounded = value(outTy, [v]);
			// A rounded amount has the places of its type.
			rounded.inexact = false;
			return rounded;
		}
		const rel = options?.relations?.[name];
		if (rel) {
			const given = args.map(ex);
			if (given.length !== rel.params.length) return report('R003', spanOf(e), [name, String(rel.params.length)]);
			for (const [i, v] of given.entries()) {
				if ('wildcard' in args[i]) continue;
				if (v.set) return report('R005', spanOf(args[i]), []);
				const want = value(slotType(schema, rel.params[i].slot));
				if (!meet(v, args[i], want, args[i])) return report('R003', spanOf(args[i]), [describe(v.ty), describe(want.ty)]);
			}
			const v = value(rel.result, given, rel.set ?? false);
			for (const s of rel.states) v.states.add(s);
			if (rel.world === 'open') v.opens.push(name);
			return v;
		}
		const rule = schema.rules?.[name];
		const called = within(e, name, 'start');
		const slot = levels.find((l) => slotsOfLevel(l)[name]);
		if (!rule) return report('R001', called, [name], { suggest: near(name, [...Object.keys(schema.rules ?? {}), ...Object.keys(options?.relations ?? {})]) });
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
		return 'cmp' in e || 'in' in e || 'path' in e || 'dot' in e || 'otherwise' in e ? sure(e) : new Set();
	}
	/** Whether `e` can evaluate to `unknown` on a row where `known` holds (for W105). */
	function mayBeUnknown(e: Expr, known: Set<string>): boolean {
		const v = typed.get(e);
		if (!v || v.ty.t === 'err') return false;
		if (known.has(`expr ${printExpr(e)}`)) return false;
		if ('otherwise' in e) {
			const [a, b] = e.otherwise;
			const va = typed.get(a);
			return mayBeUnknown(a, known) || (Boolean(va?.states.has('not_applicable')) && mayBeUnknown(b, known));
		}
		if ('arith' in e) return mayBeUnknown(e.arith[1], known) || mayBeUnknown(e.arith[2], known);
		if ('neg' in e) return mayBeUnknown(e.neg, known);
		return [...v.reads].some(([path, open]) => open && !known.has(path));
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
			if (stored(v.ty) && !('path' in expr || 'dot' in expr || ('call' in expr && ROUND_FNS.has(expr.call[0])))) v.states.add('unknown');
			if (v.set) report('R005', spanOf(expr), []);
			else if ((mayBeUnknown(expr, known) || (stored(v.ty) && v.inexact)) && q.show) found.push({ code: 'W105', span: spanOf(expr), args: [printExpr(expr)] });
			return { expr, text: printExpr(expr), typed: v };
		});
		return { binder, kind: q.ask, shown };
	}
	/** Checks a slot assignment expression against its expected typed slot.
	 * A state stands for the whole set on a many-valued slot, in both `set` and `insert_row` (evaluate.ts `Cell`). */
	function assign(expr: Expr, expected: Typed, target: object): void {
		const to = ex(expr);
		if (to.set !== expected.set && to.ty.t !== 'err' && expected.ty.t !== 'err' && to.ty.t !== 'state') report('R005', spanOf(expr), []);
		else if (!meet(to, expr, expected, target)) report('R003', spanOf(expr), [describe(to.ty), describe(expected.ty)]);
	}
	/** The span of the record key following the kind name in a whole-record insertion. */
	function keySpan(node: object, kind: string, key: string): Span {
		const span = spanOf(node);
		const afterKind = span.text.indexOf(kind);
		const at = afterKind < 0 ? -1 : span.text.indexOf(key, afterKind + kind.length);
		if (at < 0) return span;
		const start = span.start + [...span.text.slice(0, at)].length;
		return { text: key, start, end: start + [...key].length };
	}
	/** Whether an authored record key matches the schema's identifier type (canonical decimal text for Integer). */
	function validKey(key: string, typeName: string): boolean {
		const ty = typeOf(schema, typeName);
		const of = baseTypeOf(schema, typeName);
		if (ty.t === 'bool') return key === 'true' || key === 'false';
		if (ty.t === 'num') return of === 'Integer' ? /^(?:0|-?[1-9][0-9]*)$/.test(key) : grammar.match(key, 'number').succeeded();
		if (ty.t === 'val') {
			if (of === 'Date') return grammar.match(key, 'date').succeeded();
			if (of === 'DateTime') return grammar.match(key, 'datetime').succeeded();
			const enums = enumValues(typeName);
			if (enums) return enums.includes(key);
			const pattern = schema.types?.[typeName]?.pattern;
			if (pattern !== undefined) return new RegExp(`^(?:${pattern})$`, 'u').test(key);
		}
		return true;
	}
	function suppose(q: Exclude<Question, Ask | CheckDecl>): void {
		if ('insert_row' in q) {
			const { kind, key, slots } = q.insert_row;
			const def = schema.kinds[kind];
			if (!def) {
				report('R001', within(q, kind, 'start'), [kind], { suggest: near(kind, Object.keys(schema.kinds)) });
				return;
			}
			const idType = def.id?.type ?? 'Text';
			if (!validKey(key, idType)) report('R012', keySpan(q, kind, key), [key, idType]);
			else resolve[key] = kind;
			const writable = Object.keys(def.slots).filter((s) => !def.slots[s].derived && def.slots[s].inverse === undefined);
			const seen = new Set<string>();
			for (const entry of slots) {
				const slotSpan = within(entry, entry.name, 'start');
				if (seen.has(entry.name)) {
					report('R036', slotSpan, [entry.name]);
					continue;
				}
				seen.add(entry.name);
				if (entry.name === 'id') {
					report('R037', slotSpan, [entry.name, kind]);
					continue;
				}
				const slotDef = def.slots[entry.name];
				if (!slotDef) {
					report('R001', slotSpan, [entry.name], { suggest: near(entry.name, writable) });
					continue;
				}
				if (slotDef.inverse !== undefined || slotDef.derived) {
					report('R037', slotSpan, [entry.name, kind]);
					continue;
				}
				const many = slotDef.card === '*' || slotDef.card === '+';
				assign(entry.value, value(slotType(schema, slotDef), [], many), entry.value);
			}
			for (const name of writable) {
				const slotDef = def.slots[name];
				if ((slotDef.card === '1' || slotDef.card === '+') && !seen.has(name)) {
					report('R035', within(q, kind, 'start'), [kind, name]);
				}
			}
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
		assign(q.set[1], slot, target);
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
		inCheckStatement = true;
		try {
			truth(q.cond);
		} finally {
			inCheckStatement = false;
		}
		return { verb: q.check, ...(q.name !== undefined ? { name: q.name } : {}), ...(binder !== undefined ? { binder, kind: kindOf(binder)! } : {}) };
	}

	return { typed, heads, resolve, found, ask, statement, suppose, element, params, settled, truth, ex, meet, report, value, describe, spanOf, enumValues };
}
