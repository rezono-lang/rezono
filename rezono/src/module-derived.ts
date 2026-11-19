import { block, named, opt, optTree, printValue, typeOf, type Build, type Card, type Line, type Logical, type ModuleComponent } from './module-support.ts';
import { printTable, readTable, type Table } from './module-table.ts';
import { printUnless, readUnless, type Clause } from './module-unless.ts';
import { printVersion, readVersion, type VersionDecl } from './module-version.ts';
import { printExpr } from './print-expression.ts';
import type { Expr } from './tree.ts';

/** The relation and slot a calculation writes to: `output relation.slot`. */
export interface OutputDecl {
	relation: string;
	slot: string;
}

/** One named definition of a calculation: `definition name when condition then expression`. */
export interface DefinitionDecl {
	name: string;
	when: Expr;
	value: Expr;
}

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
	/** The explicit output of a calculation: no relation is guessed from a display name. */
	output?: OutputDecl;
	/** The ordered, named definitions of a calculation. */
	definitions?: DefinitionDecl[];
}

export function readDerived(line: Logical, build: Build): DerivedDecl {
	const decl = build.strip<DerivedDecl>(line.read!);
	for (const child of line.block) {
		const kind = child.read!.line;
		if (kind === 'version') {
			(decl.versions ??= []).push(readVersion(child, build));
			if (decl.definitions) build.refuse(child, 'definitions or versions, not both');
		} else if (kind === 'output') {
			build.leaf(child);
			if (decl.output) build.refuse(child, 'one `output`');
			else decl.output = build.strip<OutputDecl>(child.read!);
		} else if (kind === 'definition') {
			build.leaf(child);
			const definition = build.strip<DefinitionDecl>(child.read!);
			if (decl.versions) build.refuse(child, 'definitions or versions, not both');
			else if (decl.definitions?.some((other) => other.name === definition.name)) build.refuse(child, 'a definition name not used before');
			else (decl.definitions ??= []).push(definition);
		} else if (kind === 'unless') (decl.unless ??= []).push(readUnless(child, build));
		else if (kind !== 'table') build.refuse(child, '`output`, `definition`, `unless`, `table` or `version`');
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
		...(d.output ? [`output ${d.output.relation}.${d.output.slot}`] : []),
		...(d.definitions ?? []).map((x) => `definition ${x.name} when ${printExpr(x.when)} then ${printExpr(x.value)}`),
		...(d.unless ?? []).flatMap(printUnless),
		...(d.versions ?? []).map(printVersion),
		...(d.table ? printTable(d.table) : [])
	]);
}

export const derived = {
	lineRules: ['DerivedLine', 'OutputLine', 'DefinitionLine'],
	grammar: String.raw`
  DerivedLine = kw<"total">? kw<"derived"> name ":" Type Card? ("=" Expr)?
  OutputLine = kw<"output"> name "." name
  DefinitionLine = kw<"definition"> name when Expr then Expr
  `,
	actions: {
		DerivedLine(total, _k, n, _c, type, card, _eq, value) {
			const decl: Line = { line: 'derived', derived: n.sourceString, ...(total.numChildren ? { totality: 'total' } : {}), type: typeOf(type) };
			if (card.numChildren) decl.card = opt(card);
			if (value.numChildren) decl.value = optTree(value);
			return named(n, decl);
		},
		OutputLine: (_k, relation, _dot, slot) => ({ line: 'output', relation: relation.sourceString, slot: slot.sourceString }),
		DefinitionLine(_k, n, _when, cond, _then, value) {
			return named(n, { line: 'definition', name: n.sourceString, when: cond.tree() as Expr, value: value.tree() as Expr });
		}
	},
} satisfies ModuleComponent;
