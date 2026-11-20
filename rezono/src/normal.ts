// The normal form of a question, and the question hash taken from it. Two ways of writing one
// question have one normal form, so they have one hash, and a link to an answer does not depend on how the
// question was written. The written text stays what is shown (`print` of the tree as written); the normal form
// is what is hashed.
//
// The normal form is a question itself, and it works on the checked question, because whether a bare name is a
// slot of the binder, of an element, a parameter or an id is name resolution (§5), which `Checked.heads` records.
// It makes four rewrites, each of which keeps the value and the reason of every row (Appendix A, A.4):
//
// 1. The binder has a canonical name: the kind's name in snake case, the binder `ask Host where …` has without
//    one (§5 rule 1). Where that name would be another name at a place a path is written from the binder (a
//    parameter, a slot of a kind in scope there, an id, a value of an enum, a keyword), the first of `<name>_2`,
//    `<name>_3`, … that is none of them. The slots and parameters are those of the pack's whole schema, not the
//    role's: the definition of a pack is the same for every role, so one question has one hash for
//    every role, whatever each reads. A check statement keeps its binder: the language fixes it (v0 §5).
// 2. Every path is written in full: a bare slot of the question's row from the binder (`memory_need` is
//    `host.memory_need`, §5 rule 1), and a bare slot of the innermost element from `it` (`it` is that element,
//    §5 rule 2). A slot of an element further out has no other spelling and stays bare; so does a slot of the
//    row in a check statement where the binder's name is a slot of an element in scope (§5 rule 7).
// 3. The operands of `and` and `or` are sorted by the UTF-8 bytes of their canonical JSON. Both are commutative
//    in value and in reason: the least reason wins, then the cause that sorts first, whatever the order
//    (§13 point 7, A.4); every operand is evaluated, so the steps do not depend on the order either.
// 4. A comparison has one orientation: `a > b` is `b < a`, `a >= b` is `b <= a`, and the operands of `=` and
//    `!=` are sorted as those of `and`. A comparison is strict: it takes the highest state of its operands with
//    the reason A.4 gives, and orders two known values with an order that is antisymmetric (A.3). Its result is
//    a truth value, so no type name follows its operands' order. Arithmetic is not reordered: the type of
//    `a + b` takes the name of `a`'s type first, so `b + a` can be another type in the output schema.
//
// Nothing else is rewritten: `show` keeps its order (it is the order of the columns), a literal stays as it was
// written, and `not`, `=>`, `in`, ranges and arithmetic keep their operands' places. So equal hashes mean equal
// questions; two questions that mean the same but differ in anything else have two hashes.
//
// A question with an error keeps its names as written (rewrites 1 and 2 need them resolved); its operands are
// still sorted. A question that has a hash is one that checks: the gate refuses any other.
import { canonicalJson, canonicalSha256 } from '../../viewer/src/lib/canon.ts';
import { isError, type Checked } from './check.ts';
import { grammar } from './grammar.ts';
import { snake, type Schema } from './schema.ts';
import { isAsk, isCheck, type Ask, type CheckDecl, type Expr, type Question } from './tree.ts';

/**
 * The version of the normal form. It is part of what the hash is taken over, so a change of the normal form
 * changes every hash and no hash of one version is read as one of another.
 */
export const NORMAL_QUESTION = 'rezono.normal-question/1';

const utf8 = new TextEncoder();
/** The order of two texts by their UTF-8 bytes (A.4; publication §6.2). */
function byteOrder(a: string, b: string): number {
	const [x, y] = [utf8.encode(a), utf8.encode(b)];
	for (let i = 0; i < Math.min(x.length, y.length); i++) if (x[i] !== y[i]) return x[i] - y[i];
	return x.length - y.length;
}
const sorted = (es: Expr[]): Expr[] =>
	es
		.map((e) => [canonicalJson(e), e] as const)
		.sort(([a], [b]) => byteOrder(a, b))
		.map(([, e]) => e);

/** A scope a path is written in, outermost first: the kind of the question's row or of an element, if it is one. */
type Levels = { kind: string | undefined; binder?: string }[];

/**
 * Rebuilds a tree bottom up, with `path` deciding each path from the scopes it is written in, as the check opens
 * them: the question's row, then the element of each aggregate, quantifier and filter (check.ts, `inside`).
 */
function rebuild(e: Expr, levels: Levels, kindOf: (e: Expr) => string | undefined, path: (e: { path: string[] }, levels: Levels) => string[]): Expr {
	const at = (x: Expr, inner = levels) => rebuild(x, inner, kindOf, path);
	if ('path' in e) return { path: path(e, levels) };
	if ('lit' in e) return { lit: e.lit };
	if ('kind' in e) return { kind: e.kind };
	if ('dot' in e) return { dot: [at(e.dot[0]), e.dot[1]] };
	if ('agg' in e) {
		const [name, of, arg, binder] = e.agg;
		if (arg === undefined) return { agg: [name, at(of)] };
		const inner = at(arg, [...levels, { kind: kindOf(of), binder }]);
		return { agg: binder === undefined ? [name, at(of), inner] : [name, at(of), inner, binder] };
	}
	if ('filter' in e) {
		const [set, cond, binder] = e.filter;
		const inner = at(cond, [...levels, { kind: kindOf(set), binder }]);
		return { filter: binder === undefined ? [at(set), inner] : [at(set), inner, binder] };
	}
	if ('cmp' in e) {
		const [op, a, b] = e.cmp;
		const [x, y] = [at(a), at(b)];
		if (op === '>' || op === '>=') return { cmp: [op === '>' ? '<' : '<=', y, x] };
		if (op === '=' || op === '!=') {
			const [p, q] = sorted([x, y]);
			return { cmp: [op, p, q] };
		}
		return { cmp: [op, x, y] };
	}
	if ('in' in e) return { in: [at(e.in[0]), at(e.in[1])] };
	if ('is' in e) return { is: [at(e.is[0]), e.is[1]] };
	if ('range' in e) return { range: [at(e.range[0]), e.range[1], at(e.range[2])] };
	if ('and' in e) return { and: sorted(e.and.map((x) => at(x))) };
	if ('or' in e) return { or: sorted(e.or.map((x) => at(x))) };
	if ('not' in e) return { not: at(e.not) };
	if ('imply' in e) return { imply: [at(e.imply[0]), at(e.imply[1])] };
	if ('otherwise' in e) return { otherwise: [at(e.otherwise[0]), at(e.otherwise[1])] };
	if ('arith' in e) return { arith: [e.arith[0], at(e.arith[1]), at(e.arith[2])] };
	if ('neg' in e) return { neg: at(e.neg) };
	if ('when' in e) return { when: [at(e.when[0]), at(e.when[1]), at(e.when[2])] };
	if ('call' in e) return { call: [e.call[0], e.call[1].map((x) => at(x))] };
	if ('as' in e) return { as: [at(e.as[0]), e.as[1]] };
	// A time selection is reserved (§1): a question that holds one does not check, so it is kept as written.
	return structuredClone(e);
}

/**
 * The normal form of a checked question. `pack` is the pack's whole schema, whose names the binder
 * avoids; the question itself is checked against the role's. Where the role's schema names every slot and
 * parameter of the pack, as the gate's does (`roleSchema` maps every kind and slot of the bundle), it is that one.
 */
export function normalQuestion(checked: Checked, pack: Schema): Question {
	const { tree } = checked;
	if (!tree) throw new TypeError('a text that does not parse has no normal form');
	const named = !checked.diagnostics.some(isError);
	const kindOf = (e: Expr): string | undefined => {
		const ty = checked.typed.get(e)?.ty;
		return ty?.t === 'ref' ? ty.kind : undefined;
	};
	// The question's row: the kind of an `ask`, or the kind a check statement ranges over, when it names one.
	const row = !named ? undefined : isAsk(tree) ? tree.ask : isCheck(tree) ? checked.publication?.kind : undefined;
	const exprs: Expr[] = isAsk(tree) ? [tree.where, ...(tree.show ?? [])] : isCheck(tree) ? [tree.cond] : 'set' in tree ? [tree.set[1]] : 'insert_row' in tree ? tree.insert_row.slots.map((s) => s.value) : [];
	const top: Levels = row === undefined ? [] : [{ kind: row }];

	/** How a path is written in full: from the binder, from `it`, from an explicit method binder, or as it stands. */
	function form(p: { path: string[] }, levels: Levels): 'binder' | 'row slot' | 'it' | 'method' | 'as written' {
		const head = named ? checked.heads.get(p) : undefined;
		if (head?.as === 'row') return head.level === 0 && p.path[0] !== 'it' ? 'binder' : 'as written';
		if (head?.as === 'slot' && head.level === 0 && row !== undefined) return 'row slot';
		if (head?.as === 'slot' && head.level === levels.length - 1) return levels[head.level].binder !== undefined ? 'method' : 'it';
		return 'as written';
	}
	/** The names that the binder's name must not be at a place it is written: the pack's slots of every kind in scope there, explicit method binders, and its parameters. */
	const taken = (levels: Levels): Set<string> =>
		new Set([
			...levels.flatMap((l) => [
				...(l.kind === undefined ? [] : Object.keys(pack.kinds[l.kind]?.slots ?? {})),
				...(l.binder ? [l.binder] : []),
			]),
			...Object.keys(pack.params ?? {}),
		]);

	// The binder's name: the language's own for a check statement; for an `ask`, the first candidate that is no
	// other name where the binder is written, and no name the normal form holds as written.
	let binder: string | undefined = isCheck(tree) ? checked.publication?.binder : undefined;
	if (isAsk(tree) && row !== undefined) {
		const avoid = new Set(['it']);
		for (const e of exprs)
			rebuild(e, top, kindOf, (p, levels) => {
				const how = form(p, levels);
				if (how === 'binder' || how === 'row slot') for (const name of taken(levels)) avoid.add(name);
				else if (how === 'as written') avoid.add(p.path[0]);
				return p.path;
			});
		for (const name of Object.keys(pack.params ?? {})) avoid.add(name);
		const first = snake(row);
		for (let n = 1; binder === undefined; n++) {
			const candidate = n === 1 ? first : `${first}_${n}`;
			if (!avoid.has(candidate) && grammar.match(candidate, 'name').succeeded()) binder = candidate;
		}
	}

	const path = (p: { path: string[] }, levels: Levels): string[] => {
		const how = form(p, levels);
		if (how === 'binder') return [binder!, ...p.path.slice(1)];
		// In a check statement the binder's name may be an element's slot here; then the bare slot is its only spelling.
		if (how === 'row slot') return binder !== undefined && !taken(levels).has(binder) ? [binder, ...p.path] : [...p.path];
		if (how === 'it') return ['it', ...p.path];
		if (how === 'method') return [levels[levels.length - 1].binder!, ...p.path];
		return [...p.path];
	};
	const normal = (e: Expr) => rebuild(e, top, kindOf, path);

	if (isAsk(tree)) {
		const q: Ask = { ...structuredClone(tree), where: normal(tree.where) };
		if (tree.show) q.show = tree.show.map(normal);
		if (named) {
			// The binder `ask Host` has without a name is the canonical one; a binder of another name is written.
			if (binder === snake(tree.ask)) delete q.binder;
			else q.binder = binder;
		}
		return q;
	}
	if (isCheck(tree)) return { ...structuredClone(tree), cond: normal(tree.cond) } satisfies CheckDecl;
	if ('set' in tree) return { set: [structuredClone(tree.set[0]), normal(tree.set[1])] };
	if ('insert_row' in tree) return { insert_row: { ...tree.insert_row, slots: tree.insert_row.slots.map((s) => ({ name: s.name, value: normal(s.value) })) } };
	return structuredClone(tree);
}

/**
 * The question hash: the SHA-256, in hex, of the canonical JSON (RFC 8785) of the normal form with its version,
 * `{"normal": NORMAL_QUESTION, "question": …}`. The text of a question and its JSON form have one tree, so one
 * hash (E52); two ways of writing one question have one normal form, so one hash; and one question asked by
 * two roles has one hash, since `pack` is the pack's schema.
 */
export const questionHash = (checked: Checked, pack: Schema): Promise<string> => canonicalSha256({ normal: NORMAL_QUESTION, question: normalQuestion(checked, pack) });
