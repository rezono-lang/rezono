import type { Node } from 'ohm-js';
import { printDecideDecl, readDecideDecl, type DecideDecl } from './module-decide.ts';
import { printSourceDecl, readSourceDecl, type SourceDecl } from './module-source.ts';
import { block, declaration, named, printRow, printSource, type Build, type Logical, type ModuleComponent } from './module-support.ts';
import { placed, refused } from './parse-support.ts';
import { contexts, printContexts, type During, type Valid } from './module-version.ts';
import { printExpr } from './print-expression.ts';
import { readRuleName, spellName } from './rule-names.ts';
import type { Expr } from './tree.ts';

export interface FactTable {
	fact: string;
	/** The name of the source declaration that the table cites with `@`. */
	source?: string;
	columns: string[];
	/** The source fields of the `@` columns, which follow the slot columns. */
	sourceColumns?: string[];
	rows: FactCell[][];
}
/**
 * A cell of a fact table: a value, a list of cells, an embedded record of cells by slot name, or a dash for an
 * omitted slot (decisions/language-facts.md).
 */
export type FactCell = Expr | { list: FactCell[] } | { record: Record<string, FactCell> } | typeof OMITTED;
export interface FactRow {
	fact: string;
	id: string;
	valid?: Valid;
	during?: During;
	in?: string[];
	known?: string;
	set: { slot: string; value: Expr; source?: string }[];
}

interface Dataset {
	dataset: string;
	decls: (FactTable | SourceDecl | DecideDecl)[];
}

/** A dash: an omitted slot, or in a source column the value of the source declaration. */
const OMITTED = { boundary: 'omitted' } as const;
type Cell = FactCell | '-' | { out: Expr } | { sourceField: string };

const isOmitted = (cell: unknown) => typeof cell === 'object' && cell !== null && 'boundary' in cell;
const isSourceHead = (cell: unknown): cell is { sourceField: string } => typeof cell === 'object' && cell !== null && 'sourceField' in cell;
const isValue = (cell: unknown) => typeof cell === 'object' && cell !== null && !('out' in cell) && !('sourceField' in cell);
// A source cell is a text literal, or a dash for the value of the source declaration.
const isSourceCell = (cell: unknown) => typeof cell === 'object' && cell !== null && ('boundary' in cell || ('lit' in cell && String(cell.lit).startsWith('"')));

function readFactTable(line: Logical, build: Build): FactTable {
	const lines = line.block.filter((child) => child.read!.line === 'row' || (build.refuse(child, 'a row'), false));
	const [head = [], ...rows] = lines.map((child) => child.read!.cells as Cell[]);
	for (const child of line.block) build.leaf(child);
	const slots = head.filter((cell) => !isSourceHead(cell));
	const fields = head.filter(isSourceHead).map((cell) => cell.sourceField);
	// A header of names, source fields after them, followed by rows with exactly one value per column. A dash omits
	// a slot in any fact table (decisions/language-facts.md), but never the row identity in the first column.
	lines.forEach((child, i) => {
		const cells = child.read!.cells as Cell[];
		if (i === 0) {
			if (!cells.every((cell) => isSourceHead(cell) || (isValue(cell) && 'path' in (cell as object)))) build.refuse(child, 'a row of column names', child.end);
			else if (cells.slice(slots.length).some((cell) => !isSourceHead(cell))) build.refuse(child, 'the source columns after the other columns', child.end);
			else if (new Set(fields).size !== fields.length) build.refuse(child, 'each source field once', child.end);
			else if (fields.length && line.read!.source === undefined) build.refuse(child, 'a source citation `@ name` after the fact kind to give the source columns', child.end);
		} else if (cells.length !== head.length || isOmitted(cells[0])
			|| !cells.every((cell, at) => (at < slots.length ? isValue(cell) : isSourceCell(cell)))) {
			build.refuse(child, `${head.length} values`, child.end);
		}
	});
	const decl: FactTable = {
		...build.strip<{ fact: string; source?: string }>(line.read!),
		columns: slots.map((cell) => (typeof cell === 'object' && 'path' in cell ? cell.path.join('.') : '')),
		...(fields.length ? { sourceColumns: fields } : {}),
		rows: rows as FactCell[][]
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
		if (child.read!.line === 'decide') return [readDecideDecl(child, build)];
		if (child.read!.line !== 'facts') {
			build.refuse(child, 'a fact table, a source or a decide block');
			return [];
		}
		const table = readFactTable(child, build);
		table.rows = table.rows.map((row) => row.map((cell) => datasetCell(cell, build)));
		return [table];
	});
	return dataset;
}

// Fact table cells use bare identifiers and signed integers as literals, without expression name resolution.
function datasetCell(cell: FactCell, build: Build): FactCell {
	if (typeof cell !== 'object' || cell === null || 'boundary' in cell) return cell;
	if ('list' in cell) {
		cell.list = cell.list.map((item) => datasetCell(item, build));
		return cell;
	}
	if ('record' in cell) {
		for (const [slot, value] of Object.entries(cell.record)) cell.record[slot] = datasetCell(value, build);
		return cell;
	}
	let literal: string | undefined;
	if ('path' in cell && cell.path.length === 1) literal = cell.path[0];
	if ('kind' in cell) literal = cell.kind;
	if ('neg' in cell && 'lit' in cell.neg && /^\d+$/.test(cell.neg.lit)) literal = '-' + cell.neg.lit;
	if (literal === undefined) return cell;
	const value = { lit: literal };
	build.spans.set(value, build.spans.get(cell)!);
	return value;
}

function printCell(cell: FactCell): string {
	if ('boundary' in cell) return '-';
	if ('list' in cell) return `[${cell.list.map(printCell).join(', ')}]`;
	if ('record' in cell) return `{${Object.entries(cell.record).map(([slot, value]) => `${slot}: ${printCell(value)}`).join(', ')}}`;
	return printExpr(cell);
}

function printFactTable(d: FactTable): string[] {
	const header = [...d.columns, ...(d.sourceColumns ?? []).map((field) => `@ ${field}`)];
	return block(`fact ${d.fact}${printSource(d.source)}`, header.length || d.rows.length
		? [printRow(header), ...d.rows.map((cells) => printRow(cells.map(printCell)))] : []);
}

export const facts = {
	lineRules: ['RowLine', 'FactLine', 'DatasetLine'],
	grammar: String.raw`
  DatasetLine = kw<"dataset"> (name | quotedName)
  RowLine = "|" NonemptyListOf<Cell, "|"> "|"
  Cell = "->" Expr  -- out
       | dash       -- any
       | "@" sourceKey  -- source
       | CellValue  -- test
  CellValue = "[" ListOf<CellValue, ","> "]"  -- list
            | "{" ListOf<CellEntry, ","> "}"  -- record
            | Expr                            -- expr
  CellEntry = name ":" (cellDash | CellValue)
  cellDash = "-" &(hsp* ("," | "}"))
  FactLine = kw<"fact"> typeName ("@" name)?        -- table
           | kw<"fact"> name rowId ("," FactContext)*  -- row
  FactContext = VContext                            -- plain
              | kw<"during"> rowId "..<" rowId      -- during_closed
              | kw<"during"> rowId ".."             -- during_open
              | kw<"during"> rowId                  -- during_one
              | kw<"in"> NonemptyListOf<rowId, "|"> -- in
  AssignLine = name "=" Expr Src?
  `,
	actions: {
		DatasetLine: (_k, n) => named(n, { line: 'dataset', dataset: readRuleName(n) }),
		RowLine: (_open, cells, _close) => ({ line: 'row', cells: cells.asIteration().children.map((c: Node) => c.decl()) }),
		Cell_out: (_arrow, e) => ({ out: e.tree() }),
		Cell_any(_dash) {
			return placed(this, { ...OMITTED });
		},
		Cell_source(_at, field) {
			return placed(this, { sourceField: field.sourceString });
		},
		Cell_test: (value) => value.decl(),
		// A list cell, a record cell and the mapping of a record are nodes of the form, so each has a place: its brackets.
		CellValue_list(_open, items, _close) {
			return placed(this, { list: items.asIteration().children.map((c: Node) => c.decl()) });
		},
		CellValue_record(_open, entries, _close) {
			const record: Record<string, FactCell> = {};
			for (const entry of entries.asIteration().children as Node[]) {
				const [slot, value] = entry.decl() as [string, FactCell];
				if (Object.hasOwn(record, slot)) refused(entry, 'R000', ['each slot once in a record']);
				record[slot] = value;
			}
			return placed(this, { record: placed(this, record) });
		},
		CellValue_expr: (e) => e.tree(),
		CellEntry: (slot, _colon, value) => [slot.sourceString, value.decl()],
		cellDash(_dash, _space, _next) {
			return placed(this, { ...OMITTED });
		},
		FactLine_table: (_k, t, _at, source) => named(t, { line: 'facts', fact: t.sourceString, ...(source.numChildren ? { source: source.child(0).sourceString } : {}) }),
		FactLine_row: (_k, n, id, _commas, ctxs) => named(n, { line: 'fact', fact: n.sourceString, id: id.sourceString, ...contexts(ctxs) }),
		FactContext_plain: (c) => c.decl(),
		FactContext_during_closed: (_k, from, _op, until) => ({ during: { from: from.sourceString, until: until.sourceString } }),
		FactContext_during_open: (_k, from, _op) => ({ during: { from: from.sourceString } }),
		FactContext_during_one: (_k, stage) => ({ during: { stage: stage.sourceString } }),
		FactContext_in: (_k, setups) => ({ in: setups.asIteration().children.map((c: Node) => c.sourceString) }),
		AssignLine(n, _eq, value, src) {
			const set: FactRow['set'][number] = { slot: n.sourceString, value: value.tree() as Expr };
			if (src.numChildren) set.source = src.child(0).decl();
			return { line: 'assign', set: named(n, set) };
		}
	},
	trailingRules: ['AssignLine'],
	declarations: {
		dataset: declaration<Dataset>('dataset', readDataset, d => block(`dataset ${spellName(d.dataset)}`, d.decls.flatMap((decl) => ('fields' in decl ? printSourceDecl(decl) : 'decide' in decl ? printDecideDecl(decl) : printFactTable(decl))))),
		facts: declaration<FactTable>('columns', readFactTable, printFactTable),
		fact: {
			read: readFactRow,
			print: (decl) => 'fact' in decl && 'set' in decl
				? block(`fact ${(decl as FactRow).fact} ${(decl as FactRow).id}${printContexts(decl as FactRow)}`,
					(decl as FactRow).set.map((s) => `${s.slot} = ${printExpr(s.value)}${printSource(s.source)}`))
				: undefined
		}
	}
} satisfies ModuleComponent;
