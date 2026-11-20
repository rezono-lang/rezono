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

/** `overrides name because "reason"`: this definition goes before the named one of the same list. */
export interface OverrideDecl {
	definition: string;
	reason: string;
}

/** One named definition of a calculation: `definition name when condition then expression`. */
export interface DefinitionDecl {
	name: string;
	when: Expr;
	value: Expr;
	/** The definitions of the same list that this one goes before, each with its reason, in the order written. */
	overrides?: OverrideDecl[];
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
	/** `unit TEXT`: the unit of the calculated value, as written. */
	unit?: string;
	/** The ordered, named definitions of a calculation. */
	definitions?: DefinitionDecl[];
}

/**
 * The definitions of one list: those directly under a derived value, or those of one version. A name is used once,
 * and each override names another definition of the same list and gives a reason.
 */
export function readDefinitions(lines: Logical[], build: Build): DefinitionDecl[] | undefined {
	const read: [Logical, DefinitionDecl][] = [];
	for (const child of lines) {
		build.leaf(child);
		if (child.read!.line !== 'definition') build.refuse(child, '`definition`');
		else {
			const definition = build.strip<DefinitionDecl>(child.read!);
			if (read.some(([, other]) => other.name === definition.name)) build.refuse(child, 'a definition name not used before');
			else read.push([child, definition]);
		}
	}
	const names = new Set(read.map(([, definition]) => definition.name));
	for (const [child, definition] of read) {
		for (const override of definition.overrides ?? []) {
			if (override.definition === definition.name || !names.has(override.definition))
				build.refuse(child, 'an override that names another definition beside it');
			else if (!override.reason.trim()) build.refuse(child, 'an override with a reason');
		}
	}
	return read.length ? read.map(([, definition]) => definition) : undefined;
}

export function readDerived(line: Logical, build: Build): DerivedDecl {
	const decl = build.strip<DerivedDecl>(line.read!);
	const definitions: Logical[] = [];
	for (const child of line.block) {
		const kind = child.read!.line;
		if (kind === 'version') {
			(decl.versions ??= []).push(readVersion(child, build, readDefinitions));
			if (definitions.length) build.refuse(child, 'definitions or versions, not both');
		} else if (kind === 'output') {
			build.leaf(child);
			if (decl.output) build.refuse(child, 'one `output`');
			else decl.output = build.strip<OutputDecl>(child.read!);
		} else if (kind === 'derivedUnit') {
			build.leaf(child);
			if (decl.unit !== undefined) build.refuse(child, 'one `unit`');
			else decl.unit = child.read!.unit as string;
		} else if (kind === 'definition') {
			if (!decl.versions) definitions.push(child);
			else {
				build.leaf(child);
				build.refuse(child, 'definitions or versions, not both');
			}
		} else if (kind === 'unless') (decl.unless ??= []).push(readUnless(child, build));
		else if (kind !== 'table') build.refuse(child, '`output`, `unit`, `definition`, `unless`, `table` or `version`');
		else if (decl.table) build.refuse(child, 'one `table`');
		else {
			const table = readTable(child, decl.derived, build);
			if (table) decl.table = table;
			// A table is the whole definition (v0 section 11).
			if (decl.value || line.block.some((other) => other.read!.line === 'unless' || other.read!.line === 'version'))
				build.refuse(child, 'a `table` alone under its derived value');
		}
	}
	const read = definitions.length ? readDefinitions(definitions, build) : undefined;
	if (read) decl.definitions = read;
	if (decl.totality && !line.block.some((child) => child.read!.line === 'table')) build.refuse(line, 'a `table` under a `total` value');
	return decl;
}

export const printDefinition = (x: DefinitionDecl) =>
	`definition ${x.name} when ${printExpr(x.when)} then ${printExpr(x.value)}${(x.overrides ?? [])
		.map((o) => ` overrides ${o.definition} because ${JSON.stringify(o.reason)}`).join('')}`;

export function printDerived(d: DerivedDecl): string[] {
	return block(`${d.totality ? `${d.totality} ` : ''}derived ${d.derived}: ${d.type}${d.card ?? ''}${printValue(d.value)}`, [
		...(d.output ? [`output ${d.output.relation}.${d.output.slot}`] : []),
		...(d.unit !== undefined ? [`unit ${d.unit}`] : []),
		...(d.definitions ?? []).map(printDefinition),
		...(d.unless ?? []).flatMap(printUnless),
		...(d.versions ?? []).flatMap((v) => block(printVersion(v), (v.definitions ?? []).map(printDefinition))),
		...(d.table ? printTable(d.table) : [])
	]);
}

export const derived = {
	lineRules: ['DerivedLine', 'OutputLine', 'DerivedUnitLine', 'DefinitionLine'],
	grammar: String.raw`
  DerivedLine = kw<"total">? kw<"derived"> name ":" Type Card? ("=" Expr)?
  OutputLine = kw<"output"> name "." name
  // A line with "=" is a unit declaration: its refusal stays that of the declaration.
  DerivedUnitLine = ~(kw<"unit"> unitWord "=") kw<"unit"> unitWord
  DefinitionLine = kw<"definition"> name when Expr then Expr Override*
  Override = kw<"overrides"> name kw<"because"> text
  `,
	actions: {
		DerivedLine(total, _k, n, _c, type, card, _eq, value) {
			const decl: Line = { line: 'derived', derived: n.sourceString, ...(total.numChildren ? { totality: 'total' } : {}), type: typeOf(type) };
			if (card.numChildren) decl.card = opt(card);
			if (value.numChildren) decl.value = optTree(value);
			return named(n, decl);
		},
		OutputLine: (_k, relation, _dot, slot) => ({ line: 'output', relation: relation.sourceString, slot: slot.sourceString }),
		DerivedUnitLine: (_k, unit) => ({ line: 'derivedUnit', unit: unit.sourceString }),
		DefinitionLine(_k, n, _when, cond, _then, value, overrides) {
			const decl: Line = { line: 'definition', name: n.sourceString, when: cond.tree() as Expr, value: value.tree() as Expr };
			if (overrides.numChildren) decl.overrides = overrides.children.map((override) => override.decl());
			return named(n, decl);
		},
		Override(_k, n, _because, reason) {
			let text = '';
			try {
				text = JSON.parse(reason.sourceString) as string;
			} catch {
				// A reason that does not decode is no reason; readDefinitions refuses it.
			}
			return named(n, { definition: n.sourceString, reason: text });
		}
	},
} satisfies ModuleComponent;
