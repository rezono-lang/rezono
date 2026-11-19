// The syntax tree of a question. It is the JSON form of docs/rezono/expressions.md §4a itself: one plain object
// per node, strings and arrays only, so `JSON.stringify` of a tree is the JSON form, and the canonical JSON (RFC
// 8785) of the tree's normal form (normal.ts) is what the question hash is taken over. Parentheses
// are not in the tree; the printer writes them where precedence needs them (§9).
//
// Three members are not in the table of §4a, because the text there does not give them a JSON form:
// - `dot`: a slot read from something that is not a name, as in `(Plan where a).provider`;
// - `more` and `tail` on an `ask`: the reserved second binders and `order by`, `group by`, `limit` (§1). A
//   question that holds them is reported as R015 and is never evaluated, so no hash or answer depends on them.

export type State = 'known' | 'unknown' | 'n/a' | 'invalid';
export type Path = { path: string[] };

export type Expr =
	| { lit: string }
	| { wildcard: true }
	| Path
	| { dot: [Expr, string] }
	| { kind: string }
	| { agg: [string, Expr] | [string, Expr, Expr] }
	| { filter: [Expr, Expr] }
	| { cmp: [string, Expr, Expr] }
	| { in: [Expr, Expr] }
	| { is: [Expr, State] }
	| { range: [Expr, string, Expr] }
	| { and: Expr[] }
	| { or: Expr[] }
	| { not: Expr }
	| { imply: [Expr, Expr] }
	| { arith: [string, Expr, Expr] }
	| { neg: Expr }
	| { when: [Expr, Expr, Expr] }
	| { call: [string, Expr[]] }
	| { timesel: [Expr, TimeSel] };

/** A value along the validity axis (`at`) and the knowledge axis (`as_known`); reserved (§1). */
export type TimeSel = { at?: Expr; as_known?: Expr };
/** The question context between the kind and `where` (§4); each axis at most once. */
export type Context = { at?: Expr; as_known?: Expr; during?: Expr; in?: Expr };
export type Tail = { order: Expr[] } | { group: Expr[] } | { limit: string };

export interface Ask {
	ask: string;
	binder?: string;
	more?: [string, string][];
	context?: Context;
	where: Expr;
	show?: Expr[];
	tail?: Tail[];
}
/** One named slot of a whole-record insertion: `name = value`. */
export interface SupposeSlot {
	name: string;
	value: Expr;
}
/**
 * A suppose line (§8): `+ path = value`, `- path`, `- Kind id`, and `+ Kind id {slot = value, ...}`, which
 * inserts a whole record with its slots in authored order (decisions/language-safe-steps.md §1).
 */
export type Suppose =
	| { set: [Path, Expr] }
	| { retract: Path }
	| { retract_row: [string, string] }
	| { insert_row: { kind: string; key: string; slots: SupposeSlot[] } };
/**
 * A check statement (v0 §5): `check`, `require` and `warn` decide at publication (v0 §7b); `norm` is reserved.
 * `name` is the name written before the colon, `cond` the condition. It ranges over every element of the kind
 * that its condition names in lowercase (`host.memory_need`), as an `ask` ranges over its kind.
 */
export interface CheckDecl {
	check: 'check' | 'require' | 'warn' | 'norm';
	name?: string;
	cond: Expr;
}
/** What the parse reads: a question (an `ask` or a suppose line), or a check statement. */
export type Question = Ask | Suppose | CheckDecl;

export const isAsk = (q: Question): q is Ask => 'ask' in q;
export const isCheck = (q: Question): q is CheckDecl => 'check' in q;

/** The effect class of a form (§8b): an `ask` and a check statement read, a suppose line transacts. */
export const classOf = (q: Question): 'reads' | 'transacts' => (isAsk(q) || isCheck(q) ? 'reads' : 'transacts');

/** The one member that names a node's form. */
export const formOf = (e: Expr): string => Object.keys(e)[0];
