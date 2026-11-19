import type { Node } from 'ohm-js';
import { printSourceDecl, readSourceDecl, type SourceDecl } from './module-source.ts';
import { block, declaration, named, printRow, printSource, type Build, type Logical, type ModuleComponent } from './module-support.ts';
import { placed } from './parse-support.ts';
import { contexts, printContexts, type Valid } from './module-version.ts';
import { printExpr } from './print-expression.ts';
import type { Expr } from './tree.ts';

export interface FactTable {
	fact: string;
	/** The name of the source declaration that the table cites with `@`. */
	source?: string;
	columns: string[];
	/** The source fields of the `@` columns, which follow the slot columns. */
	sourceColumns?: string[];
	rows: Expr[][];
}
export interface FactRow {
	fact: string;
	id: string;
	valid?: Valid;
	known?: string;
	set: { slot: string; value: Expr; source?: string }[];
}

interface Dataset {
	dataset: string;
	decls: (FactTable | SourceDecl)[];
}

/** A dash in a source column: the value of the source declaration. */
const OMITTED = { boundary: 'omitted' } as const;
type Cell = Expr | '-' | { out: Expr } | { sourceField: string } | typeof OMITTED;

const isSourceHead = (cell: unknown): cell is { sourceField: string } => typeof cell === 'object' && cell !== null && 'sourceField' in cell;
const isValue = (cell: unknown) => typeof cell === 'object' && cell !== null && !('out' in cell) && !('sourceField' in cell) && !('boundary' in cell);
// A source cell is a text literal, or a dash for the value of the source declaration.
const isSourceCell = (cell: unknown) => typeof cell === 'object' && cell !== null && ('boundary' in cell || ('lit' in cell && String(cell.lit).startsWith('"')));

function readFactTable(line: Logical, build: Build): FactTable {
	const lines = line.block.filter((child) => child.read!.line === 'row' || (build.refuse(child, 'a row'), false));
	const [head = [], ...rows] = lines.map((child) => child.read!.cells as Cell[]);
	for (const child of line.block) build.leaf(child);
	const slots = head.filter((cell) => !isSourceHead(cell));
	const fields = head.filter(isSourceHead).map((cell) => cell.sourceField);
	// A header of names, source fields after them, followed by rows with exactly one value per column.
	lines.forEach((child, i) => {
		const cells = child.read!.cells as Cell[];
		if (i === 0) {
			if (!cells.every((cell) => isSourceHead(cell) || (isValue(cell) && 'path' in (cell as object)))) build.refuse(child, 'a row of column names', child.end);
			else if (cells.slice(slots.length).some((cell) => !isSourceHead(cell))) build.refuse(child, 'the source columns after the other columns', child.end);
			else if (new Set(fields).size !== fields.length) build.refuse(child, 'each source field once', child.end);
			else if (fields.length && line.read!.source === undefined) build.refuse(child, 'a source citation `@ name` after the fact kind to give the source columns', child.end);
		} else if (cells.length !== head.length || !cells.every((cell, at) => (at < slots.length ? isValue(cell) : isSourceCell(cell)))) {
			build.refuse(child, `${head.length} values`, child.end);
		}
	});
	const decl: FactTable = {
		...build.strip<{ fact: string; source?: string }>(line.read!),
		columns: slots.map((cell) => (typeof cell === 'object' && 'path' in cell ? cell.path.join('.') : '')),
		...(fields.length ? { sourceColumns: fields } : {}),
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

function readDataset(line: Logical, build: Build): Dataset {
	if (!line.block.length) build.refuse(line, 'a dataset containing fact tables');
	const dataset = build.strip<Dataset>(line.read!);
	dataset.decls = line.block.flatMap((child) => {
		if (child.read!.line === 'source') return [readSourceDecl(child, build)];
		if (child.read!.line !== 'facts') {
			build.refuse(child, 'a fact table or a source');
			return [];
		}
		const table = readFactTable(child, build);
		table.rows = table.rows.map((row) => row.map((cell) => datasetCell(cell, build)));
		return [table];
	});
	return dataset;
}

// Fact table cells use bare identifiers and signed integers as literals, without expression name resolution.
function datasetCell(cell: Expr, build: Build): Expr {
	if (typeof cell !== 'object' || cell === null) return cell;
	let literal: string | undefined;
	if ('path' in cell && cell.path.length === 1) literal = cell.path[0];
	if ('kind' in cell) literal = cell.kind;
	if ('neg' in cell && 'lit' in cell.neg && /^\d+$/.test(cell.neg.lit)) literal = '-' + cell.neg.lit;
	if (literal === undefined) return cell;
	const value = { lit: literal };
	build.spans.set(value, build.spans.get(cell)!);
	return value;
}

const printCell = (cell: Expr) => (typeof cell === 'object' && 'boundary' in cell ? '-' : printExpr(cell));

function printFactTable(d: FactTable): string[] {
	const header = [...d.columns, ...(d.sourceColumns ?? []).map((field) => `@ ${field}`)];
	return block(`fact ${d.fact}${printSource(d.source)}`, header.length || d.rows.length
		? [printRow(header), ...d.rows.map((cells) => printRow(cells.map(printCell)))] : []);
}

export const facts = {
	lineRules: ['RowLine', 'FactLine', 'DatasetLine'],
	grammar: String.raw`
  DatasetLine = kw<"dataset"> name
  RowLine = "|" NonemptyListOf<Cell, "|"> "|"
  Cell = "->" Expr  -- out
       | dash       -- any
       | "@" sourceKey  -- source
       | Expr       -- test
  FactLine = kw<"fact"> typeName ("@" name)?        -- table
           | kw<"fact"> name rowId ("," VContext)*  -- row
  AssignLine = name "=" Expr Src?
  `,
	actions: {
		DatasetLine: (_k, n) => named(n, { line: 'dataset', dataset: n.sourceString }),
		RowLine: (_open, cells, _close) => ({ line: 'row', cells: cells.asIteration().children.map((c: Node) => c.decl()) }),
		Cell_out: (_arrow, e) => ({ out: e.tree() }),
		Cell_any(_dash) {
			return placed(this, { ...OMITTED });
		},
		Cell_source(_at, field) {
			return placed(this, { sourceField: field.sourceString });
		},
		Cell_test: (e) => e.tree(),
		FactLine_table: (_k, t, _at, source) => named(t, { line: 'facts', fact: t.sourceString, ...(source.numChildren ? { source: source.child(0).sourceString } : {}) }),
		FactLine_row: (_k, n, id, _commas, ctxs) => named(n, { line: 'fact', fact: n.sourceString, id: id.sourceString, ...contexts(ctxs) }),
		AssignLine(n, _eq, value, src) {
			const set: FactRow['set'][number] = { slot: n.sourceString, value: value.tree() as Expr };
			if (src.numChildren) set.source = src.child(0).decl();
			return { line: 'assign', set: named(n, set) };
		}
	},
	trailingRules: ['AssignLine'],
	declarations: {
		dataset: declaration<Dataset>('dataset', readDataset, d => block(`dataset ${d.dataset}`, d.decls.flatMap((decl) => ('fields' in decl ? printSourceDecl(decl) : printFactTable(decl))))),
		facts: declaration<FactTable>('columns', readFactTable, printFactTable),
		fact: declaration<FactRow>('set', readFactRow, d => block(`fact ${d.fact} ${d.id}${printContexts(d)}`,
			d.set.map((s) => `${s.slot} = ${printExpr(s.value)}${printSource(s.source)}`)
		))
	}
} satisfies ModuleComponent;
