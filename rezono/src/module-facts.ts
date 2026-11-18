import type { Node } from 'ohm-js';
import { block, declaration, named, printRow, printSource, type Build, type Logical, type ModuleComponent } from './module-support.ts';
import { contexts, printContexts, type Valid } from './module-version.ts';
import { printExpr } from './print-expression.ts';
import type { Expr } from './tree.ts';

export interface FactTable {
	fact: string;
	columns: string[];
	rows: Expr[][];
}
export interface FactRow {
	fact: string;
	id: string;
	valid?: Valid;
	known?: string;
	set: { slot: string; value: Expr; source?: string }[];
}

function readFactTable(line: Logical, build: Build): FactTable {
	const lines = line.block.filter((child) => child.read!.line === 'row' || (build.refuse(child, 'a row'), false));
	const [head = [], ...rows] = lines.map((child) => child.read!.cells as (Expr | '-' | { out: Expr })[]);
	for (const child of line.block) build.leaf(child);
	// A header of names, followed by rows with exactly one value per column.
	const value = (cell: unknown) => typeof cell === 'object' && cell !== null && !('out' in cell);
	lines.forEach((child, i) => {
		const cells = child.read!.cells as unknown[];
		if (i === 0 ? !cells.every((cell) => value(cell) && 'path' in (cell as object)) : cells.length !== head.length || !cells.every(value))
			build.refuse(child, i === 0 ? 'a row of column names' : `${head.length} values`, child.end);
	});
	const decl: FactTable = {
		...build.strip<{ fact: string }>(line.read!),
		columns: head.map((cell) => (typeof cell === 'object' && 'path' in cell ? cell.path.join('.') : '')),
		rows: rows as Expr[][]
	};
	build.spans.set(decl, build.spans.get(line.read!)!);
	return decl;
}

function readFactRow(line: Logical, build: Build): FactRow {
	const decl: FactRow = {
		...build.strip<Omit<FactRow, 'set'>>(line.read!),
		set: build.leaves(line, 'assign', 'a slot `=` a value').map((assignment) => assignment.set as FactRow['set'][number])
	};
	build.spans.set(decl, build.spans.get(line.read!)!);
	return decl;
}

export const facts = {
	lineRules: ['RowLine', 'FactLine'],
	grammar: String.raw`
  RowLine = "|" NonemptyListOf<Cell, "|"> "|"
  Cell = "->" Expr  -- out
       | dash       -- any
       | Expr       -- test
  FactLine = kw<"fact"> typeName                    -- table
           | kw<"fact"> name rowId ("," VContext)*  -- row
  AssignLine = name "=" Expr Src?
  `,
	actions: {
		RowLine: (_open, cells, _close) => ({ line: 'row', cells: cells.asIteration().children.map((c: Node) => c.decl()) }),
		Cell_out: (_arrow, e) => ({ out: e.tree() }),
		Cell_any: (_dash) => '-',
		Cell_test: (e) => e.tree(),
		FactLine_table: (_k, t) => named(t, { line: 'facts', fact: t.sourceString }),
		FactLine_row: (_k, n, id, _commas, ctxs) => named(n, { line: 'fact', fact: n.sourceString, id: id.sourceString, ...contexts(ctxs) }),
		AssignLine(n, _eq, value, src) {
			const set: FactRow['set'][number] = { slot: n.sourceString, value: value.tree() as Expr };
			if (src.numChildren) set.source = src.child(0).decl();
			return { line: 'assign', set: named(n, set) };
		}
	},
	trailingRules: ['AssignLine'],
	declarations: {
		facts: declaration<FactTable>('columns', readFactTable, d => block(`fact ${d.fact}`,
			d.columns.length || d.rows.length ? [printRow(d.columns), ...d.rows.map((cells) => printRow(cells.map(printExpr)))] : []
		)),
		fact: declaration<FactRow>('set', readFactRow, d => block(`fact ${d.fact} ${d.id}${printContexts(d)}`,
			d.set.map((s) => `${s.slot} = ${printExpr(s.value)}${printSource(s.source)}`)
		))
	}
} satisfies ModuleComponent;
