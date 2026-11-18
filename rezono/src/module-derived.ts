import { block, named, opt, optTree, printValue, typeOf, type Build, type Card, type Line, type Logical, type ModuleComponent } from './module-support.ts';
import { printTable, readTable, type Table } from './module-table.ts';
import { printUnless, readUnless, type Clause } from './module-unless.ts';
import { printVersion, readVersion, type VersionDecl } from './module-version.ts';
import type { Expr } from './tree.ts';

export interface DerivedDecl {
	derived: string;
	/** `total` before `derived` (v0 §5d): the value is proven known. Read on a value with a table only. */
	totality?: 'total';
	type: string;
	card?: Card;
	value?: Expr;
	/** Each `unless`, in order: its one clause, or the clauses of its block (§5b). */
	unless?: Clause[][];
	versions?: VersionDecl[];
	table?: Table;
}

export function readDerived(line: Logical, build: Build): DerivedDecl {
	const decl = build.strip<DerivedDecl>(line.read!);
	for (const child of line.block) {
		const kind = child.read!.line;
		if (kind === 'version') (decl.versions ??= []).push(readVersion(child, build));
		else if (kind === 'unless') (decl.unless ??= []).push(readUnless(child, build));
		else if (kind !== 'table') build.refuse(child, '`unless`, `table` or `version`');
		else if (decl.table) build.refuse(child, 'one `table`');
		else {
			const table = readTable(child, decl.derived, build);
			if (table) decl.table = table;
			// A table is the whole definition (v0 section 11).
			if (decl.value || line.block.some((other) => other.read!.line === 'unless' || other.read!.line === 'version'))
				build.refuse(child, 'a `table` alone under its derived value');
		}
	}
	if (decl.totality && !line.block.some((child) => child.read!.line === 'table')) build.refuse(line, 'a `table` under a `total` value');
	return decl;
}

export function printDerived(d: DerivedDecl): string[] {
	return block(`${d.totality ? `${d.totality} ` : ''}derived ${d.derived}: ${d.type}${d.card ?? ''}${printValue(d.value)}`, [
		...(d.unless ?? []).flatMap(printUnless),
		...(d.versions ?? []).map(printVersion),
		...(d.table ? printTable(d.table) : [])
	]);
}

export const derived = {
	lineRules: ['DerivedLine'],
	grammar: String.raw`
  DerivedLine = kw<"total">? kw<"derived"> name ":" Type Card? ("=" Expr)?
  `,
	actions: {
		DerivedLine(total, _k, n, _c, type, card, _eq, value) {
			const decl: Line = { line: 'derived', derived: n.sourceString, ...(total.numChildren ? { totality: 'total' } : {}), type: typeOf(type) };
			if (card.numChildren) decl.card = opt(card);
			if (value.numChildren) decl.value = optTree(value);
			return named(n, decl);
		}
	},
} satisfies ModuleComponent;
