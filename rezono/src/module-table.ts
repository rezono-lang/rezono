import type { Node } from 'ohm-js';
import { named, printRow, type Build, type ModuleComponent } from './module-support.ts';
import { placed, type Diagnostic } from './parse-support.ts';
import type { Logical } from './module-layout.ts';
import { printExpr } from './print-expression.ts';
import type { Expr } from './tree.ts';

/** A value of a decision table as the text wrote it: a literal, an id or a value of an enum as a bare word. */
export type TableValue = { lit: string };
/** One test of a cell: a value (equality), or a range with `from` or `to` absent for an open end. */
export type TableTest = TableValue | { between: { from?: TableValue; op: '..' | '..<'; to?: TableValue } };
export interface TableRow {
	/** One cell for each input: `-` for no test, or its tests, which are alternatives. */
	tests: ('-' | TableTest[])[];
	value: TableValue;
}
/** A decision table (docs/rezono/tables.md §2): its hit policy, its inputs, and its rows in the order written. */
export interface Table {
	table: 'unique' | 'first' | 'priority' | 'collect';
	inputs: Expr[];
	output: string;
	rows: TableRow[];
}

export function readTable(line: Logical, of: string, build: Build): Table | undefined {
	const policy = line.read!.table as Table['table'];
	if (build.version === '1' && policy === 'priority') {
		build.removed(line, 'table priority', build.spans.get(line.read!), { id: 'hint.use_instead', args: ['table first'] });
		return undefined;
	}
	const [head, ...rows] = line.block;
	for (const child of line.block) build.leaf(child);
	if (!head) return void build.refuse(line, 'a header under it: `| input | -> name |`');
	const { inputs, output } = head.read as unknown as { inputs: Expr[]; output: { name: string } };
	for (const child of rows) if ((child.read!.tests as unknown[]).length !== inputs.length) build.refuse(child, `${inputs.length} cells and a value`, child.end);
	if (output.name !== of) build.later.push({ code: 'R001', span: build.spans.get(output)!, args: [output.name], suggest: [of] });
	const decl: Table = { table: policy, inputs, output: output.name, rows: rows.map((child) => build.strip<TableRow>(child.read!)) };
	build.spans.set(decl, build.spans.get(line.read!)!);
	return decl;
}

/** Refuse the whole row if the header lacks an output name and no cell itself is malformed. */
function invalidHeader(text: string, line: Logical, cp: (at: number) => number, matches: (rule: string) => boolean): Diagnostic | undefined {
	if (!matches('RowLine')) return;
	return {
		code: 'R000',
		span: { text: text.slice(line.start, line.end), start: cp(line.start), end: cp(line.end) },
		args: ['a header that ends in `->` and a name']
	};
}

const printTest = (t: TableTest) => ('lit' in t ? t.lit : `${t.between.from?.lit ?? ''}${t.between.op}${t.between.to?.lit ?? ''}`);

export function printTable(table: Table): string[] {
	return [
		`table ${table.table}`,
		`  ${printRow([...table.inputs.map(printExpr), `-> ${table.output}`])}`,
		...table.rows.map((r) => `  ${printRow([...r.tests.map((c) => (c === '-' ? c : c.map(printTest).join(', '))), r.value.lit])}`)
	];
}

export const table = {
	lineRules: ['TableLine'],
	grammar: String.raw`
  TableLine = kw<"table"> (kw<"unique"> | kw<"first"> | kw<"priority"> | kw<"collect">)
  // The header and a row of a decision table (tables.md §2). The last cell of a row is its output: a cell is
  // one of the tests only while something follows its closing bar.
  TableHead = "|" (Expr "|")+ "->" name "|"
  TableRow = "|" (TCell "|" &rowValue)+ TValue "|"
  TCell = dash                         -- any
        | NonemptyListOf<TTest, ",">  -- tests
  TTest = TValue rangeOp TValue  -- between
        | TValue rangeOp         -- from
        | rangeOp TValue         -- to
        | TValue
  // A value is also a keyword written as a bare word (tables.md §7 point 1): an enum of the schema may have
  // the value valid or open, and a cell is the only place it is written. true and false stay Bool.
  TValue = ~stateLit literal | idTok | typeName | name | oddWord | valueWord
  `,
	actions: {
		TableLine(_k, policy) {
			return placed(this, { line: 'table', table: policy.sourceString });
		},
		TableHead: (_open, inputs, _bars, _arrow, n, _close) => ({ line: 'head', inputs: inputs.children.map((e: Node) => e.tree()), output: named(n, { name: n.sourceString }) }),
		TableRow(_open, cells, _bars, _more, value, _close) {
			return placed(this, { line: 'trow', tests: cells.children.map((c: Node) => c.decl()), value: value.decl() });
		},
		TCell_any: (_dash) => '-',
		TCell_tests(tests) {
			// The list of a cell's tests has the place of the cell: where an overlap of two rows is reported.
			return placed(this, tests.asIteration().children.map((t: Node) => t.decl()));
		},
		TTest_between(from, op, to) {
			return placed(this, { between: { from: from.decl(), op: op.sourceString, to: to.decl() } });
		},
		TTest_from(from, op) {
			return placed(this, { between: { from: from.decl(), op: op.sourceString } });
		},
		TTest_to(op, to) {
			return placed(this, { between: { op: op.sourceString, to: to.decl() } });
		},
		TValue(v) {
			return placed(this, { lit: v.ctorName === 'literal' ? (v.lit() as string) : v.sourceString });
		}
	},
	block: { parent: 'table', first: 'TableHead', rest: 'TableRow', invalidFirst: invalidHeader }
} satisfies ModuleComponent;
