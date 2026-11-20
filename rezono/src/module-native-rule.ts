import type { Node } from 'ohm-js';
import { declaration, leafDeclaration, named, typeOf, type ModuleComponent } from './module-support.ts';
import { refused } from './parse-support.ts';
import { printExpr } from './print-expression.ts';
import { readRuleName, spellName, spellQualifiedName } from './rule-names.ts';
import type { Expr } from './tree.ts';

export interface RuleColumn {
	name: string;
	type: string;
}

export interface InvariantWithin {
	relation: string;
}

type RuleOption =
	| { extend: true }
	| { invariant: true }
	| { invariant: 'intermediate'; within: InvariantWithin }
	| { absence: true }
	| { outcome: string }
	| { closes: string }
	| { explain: string };

interface RuleFields {
	rule: string;
	options?: RuleOption[];
	locals?: RuleColumn[];
	when?: Expr;
}

export type NativeRuleDecl = RuleFields & ({ columns: RuleColumn[] } | { args: Expr[] });

function readList<T>(node: Node): T[] {
	return node.asIteration().children.map(child => child.decl() as T);
}

function printColumn(column: RuleColumn): string {
	return `${spellName(column.name)}: ${spellQualifiedName(column.type)}`;
}

function optionKind(option: RuleOption): string {
	if ('explain' in option) return option.explain === 'fold' ? 'fold' : 'storage';
	if ('invariant' in option) return 'invariant';
	return Object.keys(option)[0];
}

function printOption(option: RuleOption): string {
	if ('extend' in option) return 'extend';
	if ('invariant' in option) {
		return option.invariant === 'intermediate'
			? `invariant intermediate within ${spellQualifiedName(option.within.relation)}`
			: 'invariant';
	}
	if ('absence' in option) return 'absence';
	if ('outcome' in option) return 'outcome ' + spellQualifiedName(option.outcome);
	if ('closes' in option) return 'closes ' + spellQualifiedName(option.closes);
	return 'explain ' + option.explain;
}

function printRule(rule: NativeRuleDecl): string[] {
	const head = 'columns' in rule ? rule.columns.map(printColumn) : rule.args.map(printExpr);
	return [[
		`rule ${spellQualifiedName(rule.rule)}(${head.join(', ')})`,
		...(rule.options ?? []).map(printOption),
		...(rule.locals ? ['with ' + rule.locals.map(printColumn).join(', ')] : []),
		...(rule.when ? ['when ' + printExpr(rule.when)] : []),
	].join(' ')];
}

export const nativeRule = {
	// The reader selects this line in the grammar with native pattern atoms.
	lineRules: [],
	grammar: String.raw`
  NativeRuleLine = kw<"rule"> RuleRef "(" RuleHead ")" RuleOption* RuleLocals? RuleGuard?
  RuleRef = rName ("." rName)?
  RuleHead = NonemptyListOf<RuleColumn, ",">  -- typed
           | NonemptyListOf<Expr, ",">        -- positional
  RuleColumn = rName ":" RuleType
  RuleType = (rName ".")? Type
  RuleLocals = kw<"with"> NonemptyListOf<RuleColumn, ",">
  RuleGuard = when Expr
  RuleOption = kw<"extend">                                                 -- extend
             | kw<"invariant"> kw<"intermediate"> kw<"within"> RuleRef      -- invariant_intermediate
             | kw<"invariant">                                              -- invariant
             | kw<"absence">                                                -- absence
             | kw<"outcome"> RuleType                                       -- outcome
             | kw<"closes"> RuleRef                                         -- closes
             | kw<"explain"> RuleExplain                                    -- explain
  RuleExplain = kw<"materialize"> | kw<"on_demand"> | kw<"fold">
  rName (a name) = name | quotedName
  quotedName (a quoted name) = "\x60" az (az | d | "_")* "\x60"
  `,
	actions: {
		NativeRuleLine(_rule, name, _open, head, _close, options, locals, guard) {
			const contents = head.decl() as { columns: RuleColumn[] } | { args: Expr[] };
			const parsedOptions = options.children.map(option => option.decl() as RuleOption);
			if ('args' in contents) {
				if (!guard.numChildren) refused(this, 'R000', ['a positional rule head followed by when']);
				if (options.numChildren) refused(options.child(0), 'R000', ['options on a typed rule head']);
			} else {
				const seen = new Set<string>();
				parsedOptions.forEach((option, index) => {
					const kind = optionKind(option);
					if (seen.has(kind)) refused(options.child(index), 'R000', ['each rule option at most once']);
					seen.add(kind);
				});
			}
			return named(name, {
				line: 'rule',
				rule: name.decl(),
				...contents,
				...(parsedOptions.length ? { options: parsedOptions } : {}),
				...(locals.numChildren ? { locals: locals.child(0).decl() } : {}),
				...(guard.numChildren ? { when: guard.child(0).decl() } : {}),
			});
		},
		RuleRef(first, _dot, second) {
			return [readRuleName(first), ...second.children.map(readRuleName)].join('.');
		},
		RuleHead_typed: columns => ({ columns: readList<RuleColumn>(columns) }),
		RuleHead_positional: args => ({ args: args.asIteration().children.map(child => child.tree()) }),
		RuleColumn(name, _colon, type) {
			return named(name, { name: readRuleName(name), type: type.decl() });
		},
		RuleType(pack, _dot, type) {
			return [...pack.children.map(readRuleName), typeOf(type)].join('.');
		},
		RuleLocals: (_with, columns) => readList<RuleColumn>(columns),
		RuleGuard: (_when, guard) => guard.tree(),
		RuleOption_extend: name => named(name, { extend: true }),
		RuleOption_invariant_intermediate(invariant, _intermediate, _within, relation) {
			const within = named(relation, { relation: relation.decl() as string });
			return named(invariant, { invariant: 'intermediate', within });
		},
		RuleOption_invariant: name => named(name, { invariant: true }),
		RuleOption_absence: name => named(name, { absence: true }),
		RuleOption_outcome(_keyword, type) {
			return named(this, { outcome: type.decl() });
		},
		RuleOption_closes(_keyword, rule) {
			return named(this, { closes: rule.decl() });
		},
		RuleOption_explain(_keyword, mode) {
			return named(this, { explain: mode.sourceString });
		},
	},
	declarations: {
		rule: declaration<NativeRuleDecl>('rule', leafDeclaration<NativeRuleDecl>, printRule),
	},
} satisfies ModuleComponent;
