import { block, declaration, named, type Build, type Line, type Logical, type ModuleComponent } from './module-support.ts';
import { placed, refused } from './parse-support.ts';
import { printContext, printExpr } from './print-expression.ts';
import { spellName } from './rule-names.ts';
import type { Context, Expr } from './tree.ts';

/** One slot assignment inside an example's `given` block: `id.slot = value`. */
export interface ExampleGiven {
	path: string[];
	value: Expr;
}

/** An expected check or core violation inside an example's `expect` block. */
export interface ExampleViolation {
	violation: string;
	on?: string;
}

export type ExampleExpect = ExampleViolation | Expr;

/** A pack-embedded `example` declaration (docs/rezono/v0.md §5e). */
export interface ExampleDecl {
	example: string;
	context?: Context;
	given: ExampleGiven[];
	expect: ExampleExpect[];
}

function readExample(line: Logical, build: Build): ExampleDecl {
	if (build.version !== '1') {
		build.refuse(line, 'a declaration');
		return Object.assign(build.strip<Omit<ExampleDecl, 'given' | 'expect'>>(line.read!), { given: [], expect: [] });
	}
	let given: ExampleGiven[] | undefined;
	let expect: ExampleExpect[] | undefined;
	for (const child of line.block) {
		const section = child.read!.line;
		if (section === 'exampleGiven') {
			if (given !== undefined) {
				build.refuse(child, 'one `given`');
				continue;
			}
			given = child.block.flatMap((item) => {
				build.leaf(item);
				if (item.read!.line !== 'exampleGivenItem') {
					build.refuse(item, 'a slot assignment');
					return [];
				}
				return [build.strip<ExampleGiven>(item.read!)];
			});
		} else if (section === 'exampleExpect') {
			if (expect !== undefined) {
				build.refuse(child, 'one `expect`');
				continue;
			}
			expect = child.block.flatMap((item) => {
				build.leaf(item);
				if (item.read!.line !== 'exampleExpectItem') {
					build.refuse(item, 'an expectation or `violation`');
					return [];
				}
				return [item.read!.expect as ExampleExpect];
			});
		} else {
			build.refuse(child, '`given` or `expect`');
		}
	}
	if (given === undefined) build.refuse(line, 'a `given` clause under `example`');
	if (expect === undefined) build.refuse(line, 'an `expect` clause under `example`');
	return Object.assign(build.strip<Omit<ExampleDecl, 'given' | 'expect'>>(line.read!), {
		given: given ?? [],
		expect: expect ?? [],
	});
}

function printExpect(item: ExampleExpect): string {
	if ('violation' in item) return `violation ${spellName(item.violation)}${item.on !== undefined ? ` on ${item.on}` : ''}`;
	return printExpr(item);
}

export function printExample(decl: ExampleDecl): string[] {
	const ctx = printContext(decl.context);
	const head = `example ${JSON.stringify(decl.example)}${ctx.length ? ` ${ctx.join(' ')}` : ''}`;
	return block(head, [
		...block('given', decl.given.map((g) => `${g.path.map((n) => spellName(n)).join('.')} = ${printExpr(g.value)}`)),
		...block('expect', decl.expect.map(printExpect)),
	]);
}

export const example = {
	lineRules: ['ExampleLine'],
	grammar: String.raw`
  ExampleLine = kw<"example"> MetaString Context*
  ExampleSectionLine = kw<"given"> | kw<"expect">
  `,
	actions: {
		ExampleLine(_kw, titleNode, contexts) {
			const title = titleNode.decl() as string | undefined;
			if (typeof title !== 'string') refused(titleNode, 'R000', ['a JSON string']);
			const context: Context = {};
			for (const c of contexts.children) {
				const [axis, value] = c.tree() as [keyof Context, Expr];
				if (axis in context) refused(c, 'R018', [axis.replace('_', ' ')]);
				else context[axis] = value;
			}
			const decl: Line = {
				line: 'example',
				example: title,
				...(Object.keys(context).length ? { context } : {}),
			};
			return named(titleNode, decl);
		},
		ExampleSectionLine: (section) => ({
			line: section.sourceString === 'given' ? 'exampleGiven' : 'exampleExpect',
		}),
	},
	declarations: {
		example: declaration<ExampleDecl>('example', readExample, printExample),
	},
	block: { parent: 'example', first: 'ExampleSectionLine', rest: 'ExampleSectionLine', invalidFirst: () => undefined },
} satisfies ModuleComponent;

export const exampleGiven = {
	lineRules: [],
	grammar: String.raw`
  ExampleGivenLine = SupposePath "=" Expr
  `,
	actions: {
		ExampleGivenLine(pathNode, _eq, valueNode) {
			const p = pathNode.tree() as { path: string[] };
			return placed(this, { line: 'exampleGivenItem', path: p.path, value: valueNode.tree() as Expr });
		},
	},
	block: { parent: 'exampleGiven', first: 'ExampleGivenLine', rest: 'ExampleGivenLine', invalidFirst: () => undefined },
} satisfies ModuleComponent;

export const exampleExpect = {
	lineRules: [],
	grammar: String.raw`
  ExampleExpectLine = ExampleViolationLine | ExampleExprLine
  ExampleViolationLine = kw<"violation"> name (kw<"on"> rowId)?
  ExampleExprLine = Expr
  `,
	actions: {
		ExampleExpectLine: (item) => ({ line: 'exampleExpectItem', expect: item.decl() }),
		ExampleViolationLine(_kw, checkName, _on, subject) {
			const item: ExampleViolation = { violation: checkName.sourceString };
			if (subject.numChildren) item.on = subject.child(0).sourceString;
			return named(checkName, item);
		},
		ExampleExprLine: (expr) => expr.tree() as Expr,
	},
	block: { parent: 'exampleExpect', first: 'ExampleExpectLine', rest: 'ExampleExpectLine', invalidFirst: () => undefined },
} satisfies ModuleComponent;
