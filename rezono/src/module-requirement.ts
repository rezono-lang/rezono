import type { Node } from 'ohm-js';
import type { DerivedOver } from './module-derived.ts';
import type { RuleColumn } from './module-native-rule.ts';
import { block, declaration, named, printSource, type Build, type Line, type Logical, type ModuleComponent } from './module-support.ts';
import { placed, refused } from './parse-support.ts';
import { printExpr } from './print-expression.ts';
import { readRuleName, spellName, spellQualifiedName } from './rule-names.ts';
import type { Expr } from './tree.ts';

export type RequirementOption = { invariant: true };

export type RequirementBoundOp = 'at_least' | 'at_most' | 'exactly';

export interface RequirementBound {
	op: RequirementBoundOp;
	count: string;
}

export interface RequirementExists {
	binder: string;
	kind?: string;
	relation?: string;
	bound?: RequirementBound;
	where?: Expr;
}

export interface RequirementDecl {
	require: string;
	params: RuleColumn[];
	options?: RequirementOption[];
	over?: DerivedOver;
	when?: Expr;
	exists: RequirementExists[];
	means?: string;
	source?: string;
}

const BOUND_KEYWORDS: Record<RequirementBoundOp, string> = {
	at_least: 'at least',
	at_most: 'at most',
	exactly: 'exactly',
};

function readBound(node: Node, op: RequirementBoundOp, countNode: Node): RequirementBound {
	const count = countNode.sourceString.replaceAll('_', '');
	if (!/^(0|[1-9][0-9]*)$/.test(count)) {
		refused(countNode, 'R000', ['a natural number without leading zeros']);
	} else if (op === 'at_least' && count === '0') {
		refused(countNode, 'R000', ['a count of at least 1']);
	}
	return placed(node, { op, count });
}

function readExistsClause(
	bound: Node,
	binder: Node,
	target: Node,
	pred: Node,
	targetField: 'kind' | 'relation',
): Line {
	const clause: Line = {
		line: 'requirementExists',
		binder: readRuleName(binder),
		[targetField]: target.decl() as string,
	};
	if (bound.numChildren) clause.bound = bound.child(0).decl() as RequirementBound;
	if (pred.numChildren) clause.where = pred.child(0).tree() as Expr;
	return named(binder, clause);
}

function readRequirement(line: Logical, build: Build): RequirementDecl {
	const decl = build.strip<RequirementDecl>(line.read!);
	if (build.version !== '1') {
		build.refuse(line, 'a `rezono 1` module for `require`');
		return decl;
	}
	const paramNames = new Set(decl.params.map(p => p.name));
	if (paramNames.size !== decl.params.length) {
		build.refuse(line, 'distinct parameter names');
	}

	const exists: RequirementExists[] = [];
	let overLine: Logical = line;

	for (const child of line.block) {
		build.leaf(child);
		const read = child.read!;
		if (read.line === 'requirementOver') {
			if (decl.over) build.refuse(child, 'one `over`');
			else {
				decl.over = read.over as DerivedOver;
				overLine = child;
			}
		} else if (read.line === 'requirementWhen') {
			if (decl.when !== undefined) build.refuse(child, 'one `when`');
			else decl.when = read.when as Expr;
		} else if (read.line === 'requirementExists') {
			const clause = build.strip<RequirementExists>(read);
			if (paramNames.has(clause.binder)) {
				const span = build.spans.get(clause) ?? { text: clause.binder, start: 0, end: clause.binder.length };
				build.error({ code: 'R011', span, args: [clause.binder] });
			}
			exists.push(clause);
		} else if (read.line === 'ruleMeans') {
			if (decl.means !== undefined) build.refuse(child, 'one `means` line');
			else {
				decl.means = read.means as string;
				build.placeMember(decl, 'means', build.spans.get(read));
				if (read.source !== undefined) decl.source = read.source as string;
			}
		} else {
			build.refuse(child, '`over`, `when`, `exists` or `means`');
		}
	}

	if (!exists.length) {
		build.refuse(line, 'at least one `exists` clause under `require`');
	}
	if (decl.params.length >= 2 && !decl.over) {
		build.refuse(line, 'an `over` domain for a multi-key `require`');
	}
	if (decl.over) {
		const validArgs = decl.over.args.length === decl.params.length
			&& new Set(decl.over.args).size === decl.over.args.length
			&& decl.over.args.every(arg => paramNames.has(arg));
		if (!validArgs) build.refuse(overLine, 'domain arguments matching the declared parameters');
	}

	return Object.assign(decl, { exists });
}

function printExistsClause(clause: RequirementExists): string {
	const bound = clause.bound ? `${BOUND_KEYWORDS[clause.bound.op]} ${clause.bound.count} ` : '';
	const target = clause.kind !== undefined
		? `${spellName(clause.binder)}: ${spellQualifiedName(clause.kind)}`
		: `${spellName(clause.binder)} in ${spellQualifiedName(clause.relation!)}`;
	const filter = clause.where !== undefined ? ` where ${printExpr(clause.where)}` : '';
	return `exists ${bound}${target}${filter}`;
}

function printRequirement(decl: RequirementDecl): string[] {
	const params = decl.params.map(p => `${spellName(p.name)}: ${spellQualifiedName(p.type)}`).join(', ');
	const options = (decl.options ?? []).map(o => (o.invariant ? ' invariant' : '')).join('');
	return block(`require ${spellName(decl.require)}(${params})${options}`, [
		...(decl.over ? [`over ${spellQualifiedName(decl.over.relation)}(${decl.over.args.map(a => spellName(a)).join(', ')})`] : []),
		...(decl.when !== undefined ? [`when ${printExpr(decl.when)}`] : []),
		...decl.exists.map(printExistsClause),
		...(decl.means !== undefined ? [`means ${JSON.stringify(decl.means)}${printSource(decl.source)}`] : []),
	]);
}

export const requirement = {
	lineRules: ['RequirementLine'],
	grammar: String.raw`
  RequirementLine = kw<"require"> rName "(" NonemptyListOf<RuleColumn, ","> ")" RequirementOption*
  RequirementOption = kw<"invariant">  -- invariant
  RequirementClauseLine = RequirementOverLine | RequirementWhenLine | RequirementExistsLine | RuleMeansLine
  RequirementOverLine = DerivedOver
  RequirementWhenLine = when Expr
  RequirementExistsLine = kw<"exists"> RequirementBound? rName ":" RuleType (where Expr)?   -- kind
                        | kw<"exists"> RequirementBound? rName in RuleRef (where Expr)?     -- relation
  RequirementBound = at kw<"least"> reqCount       -- at_least
                   | at kw<"most"> reqCount        -- at_most
                   | kw<"exactly"> reqCount        -- exactly
  reqCount = digits ~tokCont
  `,
	actions: {
		RequirementLine(_require, name, _open, columns, _close, options) {
			const parsedOptions = options.children.map(option => option.decl() as RequirementOption);
			const seen = new Set<string>();
			parsedOptions.forEach((option, index) => {
				const kind = Object.keys(option)[0];
				if (seen.has(kind)) refused(options.child(index), 'R000', ['each requirement option at most once']);
				seen.add(kind);
			});
			const decl: Line = {
				line: 'require',
				require: readRuleName(name),
				params: columns.asIteration().children.map(column => column.decl() as RuleColumn),
			};
			if (parsedOptions.length) decl.options = parsedOptions;
			return named(name, decl);
		},
		RequirementOption_invariant: name => named(name, { invariant: true }),
		RequirementOverLine: over => ({ line: 'requirementOver', over: over.decl() }),
		RequirementWhenLine: (_when, expr) => ({ line: 'requirementWhen', when: expr.tree() as Expr }),
		RequirementExistsLine_kind(_exists, bound, binder, _colon, type, _where, pred) {
			return readExistsClause(bound, binder, type, pred, 'kind');
		},
		RequirementExistsLine_relation(_exists, bound, binder, _in, rel, _where, pred) {
			return readExistsClause(bound, binder, rel, pred, 'relation');
		},
		RequirementBound_at_least(_at, _least, count) {
			return readBound(this, 'at_least', count);
		},
		RequirementBound_at_most(_at, _most, count) {
			return readBound(this, 'at_most', count);
		},
		RequirementBound_exactly(_exactly, count) {
			return readBound(this, 'exactly', count);
		},
	},
	declarations: {
		require: declaration<RequirementDecl>('require', readRequirement, printRequirement),
	},
	block: { parent: 'require', first: 'RequirementClauseLine', rest: 'RequirementClauseLine', invalidFirst: () => undefined },
} satisfies ModuleComponent;
