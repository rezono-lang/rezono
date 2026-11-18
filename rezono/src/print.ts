import { printDeclaration } from './module-components.ts';
import { printHeader } from './module-header.ts';
import type { Decl, Module } from './module.ts';

export { grouping, print, printExpr } from './print-expression.ts';

/**
 * The normal form of a module (v0 §2, §11): one statement on one line, two spaces for each block, no blank
 * line, no comment; expressions as in a question (§9). What the tree does not order is written in one order: in
 * a kind `applies`, `sealed`, the slots, the derived values; under a derived value its `unless` lines, its
 * versions, its table; on a version or a fact row `valid` before `known`. One `unless` clause stands on the
 * `unless` line, more than one as `when` lines under it. So `parseModule(printModule(m))` is `m`, and printing
 * that again gives the same text.
 */
export function printModule(m: Module): string {
	return [
		...printHeader(m),
		...m.decls.flatMap(printDeclaration),
		''
	].join('\n');
}

/** Declarations without a header, in the normal form of a module: what `parseDeclarations` reads. */
export const printDeclarations = (decls: Decl[]): string => [...decls.flatMap(printDeclaration), ''].join('\n');
