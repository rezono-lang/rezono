import type { Node } from 'ohm-js';
import type { RuleColumn } from './module-native-rule.ts';
import { block, declaration, named, type Build, type Logical, type ModuleComponent } from './module-support.ts';
import { placed, refused } from './parse-support.ts';
import { printExpr } from './print-expression.ts';
import { readRuleName, spellName, spellQualifiedName } from './rule-names.ts';
import type { Expr } from './tree.ts';

export interface StepForbid {
	pattern: Expr;
	within: Expr;
}

export interface StepSlot {
	name: string;
	value: Expr;
}

export type StepChange =
	| { insert_row: { kind: string; key: Expr; slots: StepSlot[] } }
	| { retract_row: { kind: string; key: Expr } }
	| { set_slot: { kind: string; slot: string; key: Expr; value: Expr } }
	| { retract_slot: { kind: string; slot: string; key: Expr } };

export interface StepEffect {
	operation: string;
	changes: StepChange[];
}

export interface StepConfirm {
	reader: Expr;
	token: Expr;
}

export interface StepDecl {
	step: string;
	columns: RuleColumn[];
	when: Expr;
	forbid?: StepForbid[];
	effect: StepEffect;
	confirm: StepConfirm;
}

function hasWildcard(node: unknown): boolean {
	if (Array.isArray(node)) return node.some(hasWildcard);
	if (typeof node !== 'object' || node === null) return false;
	if ('wildcard' in node) return true;
	return Object.values(node).some(hasWildcard);
}

function requireNoWildcard(node: Node, expr: Expr, where: string): Expr {
	if (hasWildcard(expr)) refused(node, 'R000', [`no wildcard in ${where}`]);
	return expr;
}

function readEffect(line: Logical, build: Build): StepEffect {
	const changes: StepChange[] = [];
	if (!line.block.length) build.refuse(line, 'one or more changes under `effect`');
	for (const child of line.block) {
		if (child.read!.line !== 'stepChange') {
			build.refuse(child, 'an effect change');
			continue;
		}
		build.leaf(child);
		changes.push(child.read!.change as StepChange);
	}
	return Object.assign(build.strip<StepEffect>(line.read!), { changes });
}

function readStep(line: Logical, build: Build): StepDecl {
	let when: Expr | undefined;
	const forbid: StepForbid[] = [];
	let effect: StepEffect | undefined;
	let confirm: StepConfirm | undefined;

	for (const child of line.block) {
		const kind = child.read!.line;
		if (kind === 'stepWhen') {
			build.leaf(child);
			if (when !== undefined) build.refuse(child, 'one `when`');
			else when = child.read!.when as Expr;
		} else if (kind === 'stepForbid') {
			build.leaf(child);
			forbid.push(build.strip<StepForbid>(child.read!));
		} else if (kind === 'stepEffect') {
			if (effect !== undefined) build.refuse(child, 'one `effect`');
			else effect = readEffect(child, build);
		} else if (kind === 'stepConfirm') {
			build.leaf(child);
			if (confirm !== undefined) build.refuse(child, 'one `confirm`');
			else confirm = build.strip<StepConfirm>(child.read!);
		} else {
			build.refuse(child, '`when`, `forbid`, `effect` or `confirm`');
		}
	}

	if (when === undefined) build.refuse(line, 'a `when` clause under `step`');
	if (effect === undefined) build.refuse(line, 'an `effect` clause under `step`');
	if (confirm === undefined) build.refuse(line, 'a `confirm` clause under `step`');

	return Object.assign(build.strip<StepDecl>(line.read!), {
		when: when!,
		...(forbid.length ? { forbid } : {}),
		effect: effect!,
		confirm: confirm!,
	});
}

function printColumn(column: RuleColumn): string {
	return `${spellName(column.name)}: ${spellQualifiedName(column.type)}`;
}

function printChange(change: StepChange): string {
	if ('insert_row' in change) {
		const { kind, key, slots } = change.insert_row;
		const entries = slots.map(slot => `${spellName(slot.name)} = ${printExpr(slot.value)}`).join(', ');
		return `+ ${spellQualifiedName(kind)} ${printExpr(key)} {${entries}}`;
	}
	if ('retract_row' in change) {
		const { kind, key } = change.retract_row;
		return `- ${spellQualifiedName(kind)} ${printExpr(key)}`;
	}
	if ('set_slot' in change) {
		const { kind, slot, key, value } = change.set_slot;
		return `+ ${spellQualifiedName(kind)}.${spellName(slot)}(${printExpr(key)}) = ${printExpr(value)}`;
	}
	const { kind, slot, key } = change.retract_slot;
	return `- ${spellQualifiedName(kind)}.${spellName(slot)}(${printExpr(key)})`;
}

function printStep(decl: StepDecl): string[] {
	return block(`step ${spellName(decl.step)}(${decl.columns.map(printColumn).join(', ')})`, [
		`when ${printExpr(decl.when)}`,
		...(decl.forbid ?? []).map(clause => `forbid ${printExpr(clause.pattern)} within ${printExpr(clause.within)}`),
		...block(`effect ${spellName(decl.effect.operation)}`, decl.effect.changes.map(printChange)),
		`confirm ${printExpr(decl.confirm.reader)} token ${printExpr(decl.confirm.token)}`,
	]);
}

export const step = {
	lineRules: ['StepLine'],
	grammar: String.raw`
  StepLine = kw<"step"> rName "(" NonemptyListOf<RuleColumn, ","> ")"
  StepClauseLine = StepWhenLine | StepForbidLine | StepEffectLine | StepConfirmLine
  StepWhenLine = when Expr
  StepForbidLine = kw<"forbid"> Call kw<"within"> Call
  StepEffectLine = kw<"effect"> rName
  StepConfirmLine = kw<"confirm"> Call kw<"token"> Expr
  `,
	actions: {
		StepLine(_step, name, _open, columns, _close) {
			return named(name, {
				line: 'step',
				step: readRuleName(name),
				columns: columns.asIteration().children.map(column => column.decl() as RuleColumn),
			});
		},
		StepWhenLine(_when, expr) {
			return { line: 'stepWhen', when: requireNoWildcard(expr, expr.tree() as Expr, '`when`') };
		},
		StepForbidLine(keyword, pattern, _within, within) {
			const pat = pattern.tree() as Expr;
			const scope = requireNoWildcard(within, within.tree() as Expr, '`within`');
			if ('call' in pat && pat.call[1].some(arg => !('wildcard' in arg) && hasWildcard(arg))) {
				refused(pattern, 'R000', ['a wildcard only as a pattern column']);
			}
			return named(keyword, { line: 'stepForbid', pattern: pat, within: scope });
		},
		StepEffectLine: (_keyword, op) => named(op, { line: 'stepEffect', operation: readRuleName(op) }),
		StepConfirmLine(keyword, reader, _token, token) {
			return named(keyword, {
				line: 'stepConfirm',
				reader: requireNoWildcard(reader, reader.tree() as Expr, '`confirm`'),
				token: requireNoWildcard(token, token.tree() as Expr, '`confirm`'),
			});
		},
	},
	declarations: {
		step: declaration<StepDecl>('step', readStep, printStep),
	},
	block: { parent: 'step', first: 'StepClauseLine', rest: 'StepClauseLine', invalidFirst: () => undefined },
} satisfies ModuleComponent;

export const stepEffect = {
	lineRules: [],
	grammar: String.raw`
  StepChangeLine = "+" StepChangeKind "." rName "(" Expr ")" "=" Expr       -- set_slot
                 | "+" StepChangeKind Expr "{" ListOf<StepSlot, ","> "}"   -- insert_row
                 | "-" StepChangeKind "." rName "(" Expr ")"                -- retract_slot
                 | "-" StepChangeKind Expr                                  -- retract_row
  StepChangeKind = (rName ".")? typeName
  StepSlot = rName "=" Expr
  `,
	actions: {
		StepChangeKind(pack, _dot, type) {
			return [...pack.children.map(readRuleName), type.sourceString].join('.');
		},
		StepSlot(name, _eq, value) {
			return named(name, {
				name: readRuleName(name),
				value: requireNoWildcard(value, value.tree() as Expr, '`effect`'),
			});
		},
		StepChangeLine_set_slot(op, kind, _dot, slot, _open, key, _close, _eq, value) {
			return {
				line: 'stepChange',
				change: placed(op, {
					set_slot: {
						kind: kind.decl() as string,
						slot: readRuleName(slot),
						key: requireNoWildcard(key, key.tree() as Expr, '`effect`'),
						value: requireNoWildcard(value, value.tree() as Expr, '`effect`'),
					},
				}),
			};
		},
		StepChangeLine_insert_row(op, kind, key, _open, slots, _close) {
			return {
				line: 'stepChange',
				change: placed(op, {
					insert_row: {
						kind: kind.decl() as string,
						key: requireNoWildcard(key, key.tree() as Expr, '`effect`'),
						slots: slots.asIteration().children.map(slot => slot.decl() as StepSlot),
					},
				}),
			};
		},
		StepChangeLine_retract_slot(op, kind, _dot, slot, _open, key, _close) {
			return {
				line: 'stepChange',
				change: placed(op, {
					retract_slot: {
						kind: kind.decl() as string,
						slot: readRuleName(slot),
						key: requireNoWildcard(key, key.tree() as Expr, '`effect`'),
					},
				}),
			};
		},
		StepChangeLine_retract_row(op, kind, key) {
			return {
				line: 'stepChange',
				change: placed(op, {
					retract_row: {
						kind: kind.decl() as string,
						key: requireNoWildcard(key, key.tree() as Expr, '`effect`'),
					},
				}),
			};
		},
	},
	block: { parent: 'stepEffect', first: 'StepChangeLine', rest: 'StepChangeLine', invalidFirst: () => undefined },
} satisfies ModuleComponent;
