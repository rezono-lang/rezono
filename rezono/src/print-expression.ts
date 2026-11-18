// Tree to text, in the one normal form of docs/rezono/expressions.md §9: one space around binary operators and
// after commas, none inside parentheses, parentheses only where precedence needs them, `and` and `or` chains
// flat, a literal as it was written, the question context after the kind in the order `at`, `during`, `in`,
// `as known`. So `print(parse(t))` is stable and `parse(print(tree))` is the tree.
// Module declarations are assembled separately (`printModule`).
import type { Ask, Expr, Question, Tail } from './tree.ts';
import { isAsk, isCheck } from './tree.ts';
import { spellName, spellQualifiedName } from './rule-names.ts';

// Precedence, lowest first (§4). A node prints in parentheses where the place it stands in needs a higher level.
const COND = 0;
const IMPLY = 1;
const OR = 2;
const AND = 3;
const NOT = 4;
const TEST = 5;
const RANGE = 6;
const ADD = 7;
const MUL = 8;
const UNARY = 9;
const POST = 10;
const DOTTED = 11;

function level(e: Expr): number {
	if ('when' in e) return COND;
	if ('imply' in e) return IMPLY;
	if ('or' in e) return OR;
	if ('and' in e) return AND;
	if ('not' in e) return NOT;
	if ('cmp' in e || 'in' in e || 'is' in e) return TEST;
	if ('range' in e) return RANGE;
	if ('arith' in e) return e.arith[0] === '+' || e.arith[0] === '-' ? ADD : MUL;
	if ('neg' in e) return UNARY;
	if ('timesel' in e || 'filter' in e) return POST;
	return DOTTED;
}

/**
 * `min` is the level the place needs. `last` says nothing of the enclosing expression follows this operand: a
 * filter's condition extends as far as it can (§4), so a filter anywhere else is written in parentheses.
 */
function expr(e: Expr, min: number, last: boolean): string {
	const text = bare(e, last);
	return level(e) < min || ('filter' in e && !last) ? `(${text})` : text;
}
/**
 * What a slot or an aggregate is read from. A literal that is not one word stands in parentheses: `3.count()`
 * would read as one token.
 */
const base = (e: Expr) => ('lit' in e && !/^[A-Za-z][A-Za-z0-9_-]*$/.test(e.lit) ? `(${e.lit})` : expr(e, DOTTED, false));
/** An expression where any expression may stand: after `where`, in `show`, in an argument, between parentheses. */
const whole = (e: Expr) => expr(e, COND, true);

function bare(e: Expr, last: boolean): string {
	if ('lit' in e) return e.lit;
	if ('wildcard' in e) return '_';
	if ('path' in e) return e.path.map(name => spellName(name)).join('.');
	if ('kind' in e) return spellQualifiedName(e.kind);
	if ('dot' in e) return `${base(e.dot[0])}.${spellName(e.dot[1])}`;
	if ('agg' in e) {
		const [name, of, arg] = e.agg;
		return `${base(of)}.${name}(${arg ? whole(arg) : ''})`;
	}
	if ('call' in e) return `${spellQualifiedName(e.call[0], true)}(${e.call[1].map(whole).join(', ')})`;
	if ('timesel' in e) {
		const [base, sel] = e.timesel;
		return [expr(base, DOTTED, false), ...(sel.at ? [`at ${atom(sel.at)}`] : []), ...(sel.as_known ? [`as known ${atom(sel.as_known)}`] : [])].join(' ');
	}
	if ('filter' in e) {
		const [set, cond] = e.filter;
		// The set is a path with or without a time selection; a filter of a filter needs its parentheses.
		return `${'timesel' in set ? expr(set, POST, false) : expr(set, DOTTED, false)} where ${whole(cond)}`;
	}
	// Two minus signs in a row would start a comment.
	if ('neg' in e) return 'neg' in e.neg ? `-(${bare(e.neg, true)})` : `-${expr(e.neg, UNARY, last)}`;
	if ('arith' in e) {
		const [op, a, b] = e.arith;
		const at = level(e);
		return `${expr(a, at, false)} ${op} ${expr(b, at + 1, last)}`;
	}
	if ('range' in e) return `${expr(e.range[0], ADD, false)}${e.range[1]}${expr(e.range[2], ADD, last)}`;
	if ('cmp' in e) return `${expr(e.cmp[1], RANGE, false)} ${e.cmp[0]} ${expr(e.cmp[2], RANGE, last)}`;
	if ('in' in e) return `${expr(e.in[0], RANGE, false)} in ${expr(e.in[1], RANGE, last)}`;
	if ('is' in e) return `${expr(e.is[0], RANGE, false)} is ${e.is[1]}`;
	if ('not' in e) return `not ${expr(e.not, NOT, last)}`;
	if ('and' in e) return e.and.map((x, i) => expr(x, NOT, last && i === e.and.length - 1)).join(' and ');
	if ('or' in e) return e.or.map((x, i) => expr(x, AND, last && i === e.or.length - 1)).join(' or ');
	if ('imply' in e) return `${expr(e.imply[0], OR, false)} => ${expr(e.imply[1], IMPLY, last)}`;
	const [c, a, b] = e.when;
	return `when ${whole(c)} then ${whole(a)} else ${whole(b)}`;
}

/** The operand of a context or a time selection is an atom (§4): one name, a literal, a kind or a call. */
const atom = (e: Expr): string => (('path' in e && e.path.length === 1) || 'lit' in e || 'kind' in e || 'call' in e ? bare(e, false) : `(${whole(e)})`);
const list = (es: Expr[]) => es.map(whole).join(', ');
const tail = (t: Tail) => ('order' in t ? `order by ${list(t.order)}` : 'group' in t ? `group by ${list(t.group)}` : `limit ${t.limit}`);

function ask(q: Ask): string {
	const c = q.context ?? {};
	return [
		`ask ${q.binder ? `${q.binder}: ` : ''}${q.ask}${(q.more ?? []).map(([name, kind]) => `, ${name}: ${kind}`).join('')}`,
		...(c.at ? [`at ${atom(c.at)}`] : []),
		...(c.during ? [`during ${atom(c.during)}`] : []),
		...(c.in ? [`in ${atom(c.in)}`] : []),
		...(c.as_known ? [`as known ${atom(c.as_known)}`] : []),
		`where ${whole(q.where)}`,
		...(q.show ? [`show ${list(q.show)}`] : []),
		...(q.tail ?? []).map(tail)
	].join(' ');
}

/** The normal form of a question (§9), and of a check statement: its word, its name and a colon, its condition. */
export function print(q: Question): string {
	if (isAsk(q)) return ask(q);
	if (isCheck(q)) return `${q.check} ${q.name !== undefined ? `${q.name}: ` : ''}${whole(q.cond)}`;
	if ('set' in q) return `+ ${q.set[0].path.join('.')} = ${expr(q.set[1], UNARY, true)}`;
	if ('retract' in q) return `- ${q.retract.path.join('.')}`;
	return `- ${q.retract_row[0]} ${q.retract_row[1]}`;
}

/** The normal form of one expression. */
export const printExpr = whole;

/** The parse fully parenthesised: every operand that is itself an operation stands in parentheses. */
export function grouping(e: Expr): string {
	const g = (x: Expr) => (level(x) < POST ? `(${grouping(x)})` : whole(x));
	if ('and' in e) return e.and.map(g).join(' and ');
	if ('or' in e) return e.or.map(g).join(' or ');
	if ('not' in e) return `not ${g(e.not)}`;
	if ('imply' in e) return `${g(e.imply[0])} => ${g(e.imply[1])}`;
	if ('cmp' in e) return `${g(e.cmp[1])} ${e.cmp[0]} ${g(e.cmp[2])}`;
	if ('in' in e) return `${g(e.in[0])} in ${g(e.in[1])}`;
	if ('is' in e) return `${g(e.is[0])} is ${e.is[1]}`;
	if ('range' in e) return `${g(e.range[0])}${e.range[1]}${g(e.range[2])}`;
	if ('arith' in e) return `${g(e.arith[1])} ${e.arith[0]} ${g(e.arith[2])}`;
	if ('neg' in e) return `-${g(e.neg)}`;
	if ('when' in e) return `when ${g(e.when[0])} then ${g(e.when[1])} else ${g(e.when[2])}`;
	return whole(e);
}
