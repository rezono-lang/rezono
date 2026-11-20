import { block, declaration, named, printSource, type Build, type Line, type Logical, type ModuleComponent } from './module-support.ts';
import { placed, refused } from './parse-support.ts';
import { contexts, printContexts, type During, type Valid } from './module-version.ts';
import { printExpr } from './print-expression.ts';
import type { Expr } from './tree.ts';

/** One slot assignment inside a `decide` block: `<id>.<slot> = <value>`. */
export interface DecideAssign {
	path: string[];
	value: Expr;
}

/** A `decide` block (docs/rezono/v0.md §5, §11; decisions/fact-origin-required.md §1). */
export interface DecideDecl {
	decide: string;
	by: string;
	on: string;
	valid?: Valid;
	during?: During;
	in?: string[];
	known?: string;
	source?: string;
	set: DecideAssign[];
}

export function readDecideDecl(line: Logical, build: Build): DecideDecl {
	const head = build.strip<Omit<DecideDecl, 'set'>>(line.read!);
	if (!line.block.length) build.refuse(line, 'at least one assignment under `decide`');
	const set = line.block.flatMap((child) => {
		build.leaf(child);
		if (child.read!.line !== 'decideAssign') {
			build.refuse(child, 'a slot assignment');
			return [];
		}
		return [build.strip<DecideAssign>(child.read!)];
	});
	const decl: DecideDecl = { ...head, set };
	const span = build.spans.get(head);
	if (span) build.spans.set(decl, span);
	return decl;
}

export function printDecideDecl(d: DecideDecl): string[] {
	return block(
		`decide ${JSON.stringify(d.decide)} by ${d.by} on ${d.on}${printContexts(d)}${printSource(d.source)}`,
		d.set.map((item) => `${item.path.join('.')} = ${printExpr(item.value)}`)
	);
}

export const decide = {
	lineRules: ['DecideLine'],
	grammar: String.raw`
  DecideLine = kw<"decide"> MetaString by decideBy kw<"on"> date ("," FactContext)* Src?
  decideBy (a decider) = idTok | name
  DecideAssignLine = SupposePath "=" Expr
  `,
	actions: {
		DecideLine(_kw, titleNode, _by, decider, _on, dateNode, _commas, ctxs, src) {
			const title = titleNode.decl() as string | undefined;
			if (typeof title !== 'string') refused(titleNode, 'R000', ['a JSON string']);
			const decl: Line = {
				line: 'decide',
				decide: title ?? '',
				by: decider.sourceString,
				on: dateNode.sourceString,
				...contexts(ctxs)
			};
			if (src.numChildren) decl.source = src.child(0).decl() as string;
			return named(titleNode, decl);
		},
		DecideAssignLine(pathNode, _eq, valueNode) {
			const p = pathNode.tree() as { path: string[] };
			return placed(this, { line: 'decideAssign', path: p.path, value: valueNode.tree() as Expr });
		}
	},
	declarations: {
		decide: declaration<DecideDecl>('decide', readDecideDecl, printDecideDecl)
	},
	block: { parent: 'decide', first: 'DecideAssignLine', rest: 'DecideAssignLine', invalidFirst: () => undefined }
} satisfies ModuleComponent;
