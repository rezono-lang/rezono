import type { InvariantWithin, RuleColumn } from './module-native-rule.ts';
import { block, named, opt, optTree, printSource, printValue, type Build, type Card, type Declaration, type Line, type Logical, type ModuleComponent } from './module-support.ts';
import { printTable, readTable, type Table } from './module-table.ts';
import { printUnless, readUnless, type Clause } from './module-unless.ts';
import { printVersion, readVersion, type VersionDecl } from './module-version.ts';
import { placed, refused } from './parse-support.ts';
import { printExpr } from './print-expression.ts';
import { readRuleName, spellName, spellQualifiedName } from './rule-names.ts';
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

/** The finite closed domain relation for a multi-key functional derivation: `over relation(k1, ..., kn)`. */
export interface DerivedOver {
	relation: string;
	args: string[];
}

export type DerivedOption =
	| { extend: true }
	| { invariant: true }
	| { invariant: 'intermediate'; within: InvariantWithin }
	| { explain: string };

export interface DerivedDecl {
	derived: string;
	/** `total` before `derived` (v0 §5d): the value is proven known. */
	totality?: 'total';
	/** Typed key parameters of a module-level derivation (rezono 1). */
	params?: RuleColumn[];
	type: string;
	card?: Card;
	/** Modifiers on a rezono 1 derivation (`extend`, `invariant`, `invariant intermediate within`, `explain`). */
	options?: DerivedOption[];
	/** Mandatory finite closed domain relation for a multi-key functional derivation (rezono 1). */
	over?: DerivedOver;
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
	/** The derivation's sentence in the pack's default language (`means "..."`). */
	means?: string;
	/** The source reference after `@`. */
	source?: string;
}

const isFunctionalDerived = (decl: DerivedDecl): boolean =>
	!(decl.type === 'Bool' && decl.card === undefined) && decl.card !== '*' && decl.card !== '+';

function derivedOptionKind(option: DerivedOption): string {
	if ('explain' in option) return option.explain === 'fold' ? 'fold' : 'storage';
	if ('invariant' in option) return 'invariant';
	return Object.keys(option)[0];
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

export function readDerived(line: Logical, build: Build, scope: 'member' | 'module' = 'member'): DerivedDecl {
	const decl = build.strip<DerivedDecl>(line.read!);
	const rezono1 = build.version === '1';
	if (scope === 'module' && !rezono1) {
		build.refuse(line, 'a declaration');
		return decl;
	}
	if (!rezono1) {
		if (decl.params || decl.options || decl.over || decl.source !== undefined || decl.type.includes('.') || build.spans.get(decl)?.text.startsWith('`')) {
			build.refuse(line, 'a `rezono 0` derived value');
		}
	} else if (scope === 'member') {
		if (decl.params) build.refuse(line, 'no parameters on a derived property of a kind');
		if (decl.over) build.refuse(line, 'no `over` on a derived property of a kind');
	} else {
		if (!decl.params?.length) build.refuse(line, 'parameters on a module-level `derived`');
		else if (new Set(decl.params.map(p => p.name)).size !== decl.params.length) build.refuse(line, 'distinct parameter names');
	}

	let overLine: Logical = line;
	const definitions: Logical[] = [];
	for (const child of line.block) {
		const kind = child.read!.line;
		if (kind === 'derivedOver' && rezono1) {
			build.leaf(child);
			if (scope === 'member') build.refuse(child, 'no `over` on a derived property of a kind');
			else if (decl.over) build.refuse(child, 'one `over`');
			else {
				decl.over = child.read!.over as DerivedOver;
				overLine = child;
			}
		} else if (kind === 'derivedValue' && rezono1) {
			build.leaf(child);
			if (decl.value !== undefined) build.refuse(child, 'one `=` value');
			else if (decl.table) build.refuse(child, 'a `table` alone under its derived value');
			else {
				decl.value = child.read!.value as Expr;
				if (child.read!.source !== undefined) {
					if (decl.source !== undefined) build.refuse(child, 'one `@` source');
					else decl.source = child.read!.source as string;
				}
			}
		} else if (kind === 'ruleMeans' && rezono1) {
			build.leaf(child);
			if (decl.means !== undefined) build.refuse(child, 'one `means` line');
			else {
				decl.means = child.read!.means as string;
				if (child.read!.source !== undefined) {
					if (decl.source !== undefined) build.refuse(child, 'one `@` source');
					else decl.source = child.read!.source as string;
				}
			}
		} else if (kind === 'version') {
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
		else if (kind !== 'table') {
			build.refuse(
				child,
				rezono1
					? '`over`, `=`, `means`, `output`, `unit`, `definition`, `unless`, `table` or `version`'
					: '`output`, `unit`, `definition`, `unless`, `table` or `version`'
			);
		} else if (decl.table) build.refuse(child, 'one `table`');
		else {
			const table = readTable(child, decl.derived, build);
			if (table) decl.table = table;
			// A table is the whole definition (v0 section 11).
			if (decl.value || line.block.some((other) => other.read!.line === 'derivedValue' || other.read!.line === 'unless' || other.read!.line === 'version'))
				build.refuse(child, 'a `table` alone under its derived value');
		}
	}
	const read = definitions.length ? readDefinitions(definitions, build) : undefined;
	if (read) decl.definitions = read;
	if (decl.totality && !rezono1 && !line.block.some((child) => child.read!.line === 'table')) {
		build.refuse(line, 'a `table` under a `total` value');
	}
	if (rezono1 && scope === 'module' && decl.params?.length) {
		if (isFunctionalDerived(decl) && !decl.over) {
			build.refuse(line, 'an `over` domain for a multi-key functional derivation');
		}
		if (decl.over) {
			const paramNames = new Set(decl.params.map(p => p.name));
			const validArgs = decl.over.args.length === decl.params.length
				&& new Set(decl.over.args).size === decl.over.args.length
				&& decl.over.args.every(arg => paramNames.has(arg));
			if (!validArgs) build.refuse(overLine, 'domain arguments matching the declared parameters');
		}
	}
	return decl;
}

const readModuleDerived = (line: Logical, build: Build): DerivedDecl => readDerived(line, build, 'module');

export const printDefinition = (x: DefinitionDecl) =>
	`definition ${x.name} when ${printExpr(x.when)} then ${printExpr(x.value)}${(x.overrides ?? [])
		.map((o) => ` overrides ${o.definition} because ${JSON.stringify(o.reason)}`).join('')}`;

function printDerivedOption(option: DerivedOption): string {
	if ('extend' in option) return 'extend';
	if ('invariant' in option) {
		return option.invariant === 'intermediate'
			? `invariant intermediate within ${spellQualifiedName(option.within.relation)}`
			: 'invariant';
	}
	return `explain ${option.explain}`;
}

export function printDerived(d: DerivedDecl): string[] {
	const params = d.params
		? `(${d.params.map(p => `${spellName(p.name)}: ${spellQualifiedName(p.type)}`).join(', ')})`
		: '';
	const options = (d.options ?? []).map(o => ` ${printDerivedOption(o)}`).join('');
	const valueInBlock = d.over !== undefined && d.value !== undefined;
	const sourceOnHeader = d.means === undefined && !valueInBlock ? printSource(d.source) : '';
	const sourceOnValue = d.means === undefined && valueInBlock ? printSource(d.source) : '';
	const head = `${d.totality ? `${d.totality} ` : ''}derived ${spellName(d.derived)}${params}: ${spellQualifiedName(d.type)}${d.card ?? ''}${options}${valueInBlock ? '' : printValue(d.value)}${sourceOnHeader}`;
	return block(head, [
		...(d.over ? [`over ${spellQualifiedName(d.over.relation)}(${d.over.args.map(a => spellName(a)).join(', ')})`] : []),
		...(valueInBlock ? [`= ${printExpr(d.value!)}${sourceOnValue}`] : []),
		...(d.output ? [`output ${d.output.relation}.${d.output.slot}`] : []),
		...(d.unit !== undefined ? [`unit ${d.unit}`] : []),
		...(d.definitions ?? []).map(printDefinition),
		...(d.unless ?? []).flatMap(printUnless),
		...(d.versions ?? []).flatMap((v) => block(printVersion(v), (v.definitions ?? []).map(printDefinition))),
		...(d.table ? printTable(d.table) : []),
		...(d.means !== undefined ? [`means ${JSON.stringify(d.means)}${printSource(d.source)}`] : []),
	]);
}

const moduleDerivedDeclaration: Declaration<DerivedDecl> = {
	read: readModuleDerived,
	print: decl => 'derived' in decl && typeof (decl as { derived?: unknown }).derived === 'string'
		? printDerived(decl as DerivedDecl)
		: undefined,
};

export const derived = {
	lineRules: ['DerivedLine', 'DerivedOverLine', 'DerivedValueLine', 'RuleMeansLine', 'OutputLine', 'DerivedUnitLine', 'DefinitionLine'],
	grammar: String.raw`
  DerivedLine = kw<"total">? kw<"derived"> rName DerivedParams? ":" RuleType Card? DerivedOption* DerivedOver? ("=" Expr)? Src?
  DerivedParams = "(" NonemptyListOf<RuleColumn, ","> ")"
  DerivedOver = kw<"over"> DerivedOverRef "(" NonemptyListOf<rName, ","> ")"
  DerivedOverRef = rName "." typeName  -- qualifiedKind
                 | typeName            -- kind
                 | RuleRef             -- rule
  DerivedOverLine = DerivedOver
  DerivedValueLine = "=" Expr Src?
  DerivedOption = kw<"extend">                                              -- extend
                | kw<"invariant"> kw<"intermediate"> kw<"within"> RuleRef   -- invariant_intermediate
                | kw<"invariant">                                           -- invariant
                | kw<"explain"> RuleExplain                                 -- explain
  OutputLine = kw<"output"> name "." name
  // A line with "=" is a unit declaration: its refusal stays that of the declaration.
  DerivedUnitLine = ~(kw<"unit"> unitWord "=") kw<"unit"> unitWord
  DefinitionLine = kw<"definition"> name when Expr then Expr Override*
  Override = kw<"overrides"> name kw<"because"> text
  `,
	actions: {
		DerivedLine(total, _k, n, params, _c, type, card, options, over, _eq, value, src) {
			const parsedOptions = options.children.map(option => option.decl() as DerivedOption);
			const seen = new Set<string>();
			parsedOptions.forEach((option, index) => {
				const kind = derivedOptionKind(option);
				if (seen.has(kind)) refused(options.child(index), 'R000', ['each derived option at most once']);
				seen.add(kind);
			});
			const decl: Line = {
				line: 'derived',
				derived: readRuleName(n),
				...(total.numChildren ? { totality: 'total' } : {}),
				type: type.decl() as string,
			};
			if (params.numChildren) decl.params = params.child(0).decl();
			if (card.numChildren) decl.card = opt(card);
			if (parsedOptions.length) decl.options = parsedOptions;
			if (over.numChildren) decl.over = over.child(0).decl();
			if (value.numChildren) decl.value = optTree(value);
			if (src.numChildren) decl.source = src.child(0).decl();
			return named(n, decl);
		},
		DerivedParams: (_open, columns, _close) => columns.asIteration().children.map(child => child.decl() as RuleColumn),
		DerivedOver(_over, relation, _open, args, _close) {
			return placed(this, {
				relation: relation.decl() as string,
				args: args.asIteration().children.map(arg => readRuleName(arg)),
			});
		},
		DerivedOverRef_qualifiedKind: (pack, _dot, kind) => `${readRuleName(pack)}.${kind.sourceString}`,
		DerivedOverRef_kind: kind => kind.sourceString,
		DerivedOverRef_rule: rule => rule.decl(),
		DerivedOverLine: over => ({ line: 'derivedOver', over: over.decl() }),
		DerivedValueLine(_eq, value, src) {
			const line: Line = { line: 'derivedValue', value: value.tree() as Expr };
			if (src.numChildren) line.source = src.child(0).decl();
			return line;
		},
		DerivedOption_extend: name => named(name, { extend: true }),
		DerivedOption_invariant_intermediate(invariant, _intermediate, _within, relation) {
			const within = named(relation, { relation: relation.decl() as string });
			return named(invariant, { invariant: 'intermediate', within });
		},
		DerivedOption_invariant: name => named(name, { invariant: true }),
		DerivedOption_explain(_keyword, mode) {
			return named(this, { explain: mode.sourceString });
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
	declarations: {
		derived: moduleDerivedDeclaration,
	},
} satisfies ModuleComponent;
