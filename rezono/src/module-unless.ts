import { optSrc, printSource, type Build, type Logical, type ModuleComponent } from './module-support.ts';
import type { Diagnostic, Span } from './parse-support.ts';
import { printExpr } from './print-expression.ts';
import type { Expr } from './tree.ts';

export interface Clause {
	when: Expr;
	then: Expr;
	source?: string;
}

const topConjuncts = (e: Expr): Expr[] => ('and' in e ? e.and : [e]);

function handlesInvalid(e: Expr, target: string): boolean {
	if ('is' in e && e.is[1] === 'invalid') return printExpr(e.is[0]) === target;
	if ('and' in e) return e.and.some((part) => handlesInvalid(part, target));
	if ('or' in e) return e.or.some((part) => handlesInvalid(part, target));
	return false;
}

/**
 * Emits warning W115 when a `rezono 1` `unless` clause guards on `<expr> is known` and static state typing shows
 * `<expr>` can be `invalid`, unless a sibling `unless` clause in the same derivation handles `<expr> is invalid`
 * (decisions/language-rezono-1-refinements.md, section 2).
 */
export function warnUnlessMasksInvalid(
	groups: Clause[][],
	typed: Map<object, { states: Set<string> }>,
	spanOf: (node: object) => Span,
	diagnostics: Diagnostic[],
): void {
	const clauses = groups.flat();
	for (const clause of clauses) {
		for (const part of topConjuncts(clause.when)) {
			if (!('is' in part) || part.is[1] !== 'known') continue;
			const subject = part.is[0];
			if (!typed.get(subject)?.states.has('invalid')) continue;
			const target = printExpr(subject);
			if (clauses.some((sibling) => sibling !== clause && handlesInvalid(sibling.when, target))) continue;
			const replacement = printExpr(clause.then) === target ? `${target} otherwise ...` : `not (${target} is n/a)`;
			diagnostics.push({
				code: 'W115',
				span: spanOf(part),
				args: [target],
				hint: { id: 'hint.use_instead', args: [replacement] },
			});
		}
	}
}

export function readUnless(line: Logical, build: Build): Clause[] {
	const clause = line.read!.clause as Clause | undefined;
	if (clause) {
		build.leaf(line);
		return [clause];
	}
	if (!line.block.length) build.refuse(line, '`when` under it');
	return build.leaves(line, 'when', '`when`').map((when) => when.clause as Clause);
}

export function printUnless(clauses: Clause[]): string[] {
	const printClause = (c: Clause) => `${printExpr(c.when)} then ${printExpr(c.then)}${printSource(c.source)}`;
	return clauses.length === 1 ? [`unless ${printClause(clauses[0])}`] : ['unless', ...clauses.map((c) => `  when ${printClause(c)}`)];
}

export const unless = {
	lineRules: ['UnlessLine', 'WhenLine'],
	grammar: String.raw`
  UnlessLine = kw<"unless"> (Expr then Expr Src?)?
  WhenLine = when Expr then Expr Src?
  `,
	actions: {
		UnlessLine(_k, cond, _then, value, src) {
			if (!cond.numChildren) return { line: 'unless' };
			const clause: Clause = { when: cond.child(0).tree() as Expr, then: value.child(0).tree() as Expr };
			const source = optSrc(src);
			if (source !== undefined) clause.source = source;
			return { line: 'unless', clause };
		},
		WhenLine(_when, cond, _then, value, src) {
			const clause: Clause = { when: cond.tree() as Expr, then: value.tree() as Expr };
			if (src.numChildren) clause.source = src.child(0).decl();
			return { line: 'when', clause };
		}
	},
} satisfies ModuleComponent;
