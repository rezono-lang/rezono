import { optSrc, printSource, type Build, type Logical, type ModuleComponent } from './module-support.ts';
import { printExpr } from './print-expression.ts';
import type { Expr } from './tree.ts';

export interface Clause {
	when: Expr;
	then: Expr;
	source?: string;
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
