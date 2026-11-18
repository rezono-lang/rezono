// A module of Rezono v0 (docs/rezono/v0.md §4, §5, §11) read into its declarations: the header, units, enums,
// reasons, roundings, parameters with their versions, kinds with their slots, `extend` with derived values,
// checks and facts. It is a parse and nothing more: no name is resolved, no type checked, nothing evaluated.
// What v0 reserves still parses and is reported as R015 at its span (§13): a time selection on a value (§5a,
// P10.5), `norm`. A decision table under a derived value is read into the tree of docs/rezono/tables.md §2; its
// check is table.ts and its evaluation evaluate.ts.
//
// Layout (§11). Rezono is indentation-sensitive: a line indented deeper than the line before it opens a block
// under that line, and a line at the indent of an open block closes the blocks inside it. The EBNF does not say
// how one statement goes on over several lines; this reader takes a deeper line as a continuation of the line
// before it, not as a block, when either line shows that the statement is not finished:
// - the line before ends in `=`, `=>`, `+`, `-`, `*`, `/`, `(`, `,` or the word `when`, `then`, `else`, `and`,
//   `or` or `not`, or leaves a parenthesis open;
// - the line itself begins with `then`, `else`, `and`, `or`, `=>`, `+`, `-`, `*`, `/` or `)`.
// A comment ends at the end of its line (§3) and is not part of either test.
//
// The diagnostics a module's text alone shows:
//   R000  a syntax error, or a line where its block does not allow it; and what the tree could only hold by
//         dropping a part of it: a second `applies` or `sealed` in a kind, a fact table whose header is not a
//         row of names, a fact row that has not one value for each column, a line under a line that takes no
//         block (a `when` line, a version, a slot, a line of a table), a second `table`, a table without a
//         header or with a header without its output, a row of a table that has not one cell for each input,
//         a table beside `=`, `unless` or a version, and `total` on a derived value without a table (§5d:
//         only a table's value is proven known here); and a line end inside a text literal or an id between
//         backticks, which would be part of the value
//   R001  the name after `->` in the header of a table that is not the name of its derived value
//   R014, R016  as in a question (parse.ts)
//   R018  `valid` or `known` twice on one version or fact row
//   R015  a reserved construct
//   W108  a declaration with versions has none before the earliest `valid` date: there its value is
//         `unknown no_version_applies` (§5a rule 4). Only that first gap is reported here; a gap between two
//         versions needs the order of their contexts, which the checker gives later.
// As in a question, an R000, R014, R016 or R018 leaves no module and no other diagnostic.
import type { Node } from 'ohm-js';
import { inOrder, placed, points, readRule, refused, semantics, type Diagnostic, type Span } from './parse.ts';
import type { CheckDecl, Expr } from './tree.ts';
import { torn, tornAt } from './parse.ts';

export type World = 'open' | 'closed';
export type Card = '?' | '*' | '+';
/** A validity range as written: a start and an end exclusive, or a start alone for an open range (§3). */
export type Valid = [string] | [string, string];
export interface VersionDecl {
	version: string;
	valid?: Valid;
	known?: string;
	value?: Expr;
	source?: string;
}
export interface Clause {
	when: Expr;
	then: Expr;
	source?: string;
}
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
export interface ParamDecl {
	param: string;
	type: string;
	per?: string;
	value?: Expr;
	versions?: VersionDecl[];
}
export interface SlotDecl {
	slot: string;
	type: string;
	card?: Card;
	inverse?: string;
	world?: World;
	identifier?: true;
	embedded?: true;
}
export interface DerivedDecl {
	derived: string;
	/** `total` before `derived` (v0 §5d): the value is proven known. Read on a value with a table only. */
	totality?: 'total';
	type: string;
	card?: Card;
	value?: Expr;
	/** Each `unless`, in order: its one clause, or the clauses of its block (§5b). */
	unless?: Clause[][];
	versions?: VersionDecl[];
	table?: Table;
}
export interface KindDecl {
	kind: string;
	embedded?: true;
	abstract?: true;
	world?: World;
	applies?: { axis: 'at' | 'during' | 'in'; slot: string };
	sealed?: string;
	slots: SlotDecl[];
	derived: DerivedDecl[];
}
export interface ExtendDecl {
	extend: string;
	derived: DerivedDecl[];
}
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
export type Decl =
	| { unit: string; is: string }
	| { enum: string; world?: World; values: string[] }
	| { reason: string; text: string }
	| { rounding: 'date' | 'money'; mode: string }
	| ParamDecl
	| KindDecl
	| ExtendDecl
	| CheckDecl
	| FactTable
	| FactRow;
export interface Module {
	rezono?: string;
	pack: string;
	use: { use: string; as?: string }[];
	decls: Decl[];
}
export interface ParsedModule {
	/** Absent when a parse-level check failed. */
	module?: Module;
	/** In source order. */
	diagnostics: Diagnostic[];
	/**
	 * The place of every expression and of every declaration. A declaration, a slot, a derived value, a version,
	 * a `use` line and an assignment of a fact row stand at their name (a rounding at what it rounds, a version
	 * at its number), `applies` at its slot, a check statement at the whole statement.
	 */
	spans: WeakMap<object, Span>;
}

/** One line as the grammar reads it, before it is put in its block. */
type Line = { line: string; [member: string]: unknown };

const opt = (iter: Node): string | undefined => (iter.numChildren ? iter.child(0).sourceString : undefined);
const optTree = (iter: Node): Expr | undefined => (iter.numChildren ? (iter.child(0).tree() as Expr) : undefined);
/** The source of an optional group that ends in `Src?`: an iteration of an iteration. */
const optSrc = (iter: Node): string | undefined => (iter.numChildren && iter.child(0).numChildren ? iter.child(0).child(0).decl() : undefined);
/** A node's text without its comments: one over two lines is no part of the tree (§3). */
const bare = (node: Node) => node.sourceString.split('\n').map(codeOf).join(' ');
const typeOf = (node: Node) => bare(node).replace(/\s+/g, '');
const listOf = (node: Node) => node.asIteration().children.map((c: Node) => c.sourceString);
function contexts(nodes: Node): { valid?: Valid; known?: string } {
	const out: { valid?: Valid; known?: string } = {};
	for (const c of nodes.children) {
		const context = c.decl() as { valid?: Valid; known?: string };
		// A second `valid` or `known` would replace the first one unseen.
		if (Object.keys(context).some((axis) => axis in out)) refused(c, 'R018', Object.keys(context));
		Object.assign(out, context);
	}
	return out;
}
function named<T extends object>(name: Node, decl: T): T {
	return placed(name, decl);
}

semantics.addOperation<unknown>('decl', {
	Line: (line) => line.decl(),
	RezonoLine: (_k, n) => ({ line: 'rezono', rezono: n.sourceString }),
	PackLine: (_k, n) => ({ line: 'pack', pack: n.sourceString }),
	UseLine: (_k, names, _as, alias) => named(names, { line: 'use', use: listOf(names).join('.'), ...(alias.numChildren ? { as: opt(alias) } : {}) }),
	RoundingLine: (_k, what, mode) => named(what, { line: 'rounding', rounding: what.sourceString, mode: mode.sourceString }),
	ReasonLine: (_k, n, _eq, text) => named(n, { line: 'reason', reason: n.sourceString, text: text.sourceString }),
	UnitLine(_k, t, _eq, body) {
		// A quantity is an expression: read as one, so that what v0 reserves in it is an R015 at its span. The form
		// keeps its text.
		if (body.child(0).ctorName === 'UnitBody_quantity') body.child(0).child(0).tree();
		return named(t, { line: 'unit', unit: t.sourceString, is: bare(body).replace(/\s+/g, ' ') });
	},
	EnumLine: (_k, t, world, _eq, values) => named(t, { line: 'enum', enum: t.sourceString, ...(world.numChildren ? { world: world.child(0).decl() } : {}), values: listOf(values) }),
	World: (_k, which) => which.sourceString,
	ParamLine(_k, n, _c, type, _per, per, _eq, value) {
		const decl: Line = { line: 'param', param: n.sourceString, type: typeOf(type) };
		if (per.numChildren) decl.per = opt(per);
		if (value.numChildren) decl.value = optTree(value);
		return named(n, decl);
	},
	KindLine(modifier, _k, t, world) {
		const decl: Line = { line: 'kind', kind: t.sourceString };
		const kindModifier = opt(modifier);
		if (kindModifier === 'embedded') decl.embedded = true;
		if (kindModifier === 'abstract') decl.abstract = true;
		if (world.numChildren) decl.world = world.child(0).decl();
		return named(t, decl);
	},
	ExtendLine: (_k, t) => named(t, { line: 'extend', extend: t.sourceString }),
	AppliesLine: (_k, axis, _c, n) => named(n, { line: 'applies', axis: axis.sourceString, slot: n.sourceString }),
	SealedLine: (_k, _at, _c, n) => ({ line: 'sealed', slot: n.sourceString }),
	DerivedLine(total, _k, n, _c, type, card, _eq, value) {
		const decl: Line = { line: 'derived', derived: n.sourceString, ...(total.numChildren ? { totality: 'total' } : {}), type: typeOf(type) };
		if (card.numChildren) decl.card = opt(card);
		if (value.numChildren) decl.value = optTree(value);
		return named(n, decl);
	},
	SlotLine(n, _c, type, card, _inverse, inverse, world, identifier, embedded) {
		const decl: Line = { line: 'slot', slot: n.sourceString, type: typeOf(type) };
		if (card.numChildren) decl.card = opt(card);
		if (inverse.numChildren) decl.inverse = opt(inverse);
		if (world.numChildren) decl.world = world.child(0).decl();
		if (identifier.numChildren) decl.identifier = true;
		if (embedded.numChildren) decl.embedded = true;
		return named(n, decl);
	},
	VersionLine(_k, n, _commas, ctxs, _eq, value, src) {
		const decl: Line = { line: 'version', version: n.sourceString, ...contexts(ctxs) };
		if (value.numChildren) decl.value = optTree(value);
		const source = optSrc(src);
		if (source !== undefined) decl.source = source;
		return named(n, decl);
	},
	VContext_closed: (_k, from, _op, to) => ({ valid: [from.sourceString, to.sourceString] }),
	VContext_open: (_k, from, _op) => ({ valid: [from.sourceString] }),
	VContext_known: (_k, date) => ({ known: date.sourceString }),
	UnlessLine(_k, cond, _then, value, src) {
		if (!cond.numChildren) return { line: 'unless' };
		const clause: Clause = { when: cond.child(0).tree() as Expr, then: value.child(0).tree() as Expr };
		const source = optSrc(src);
		if (source !== undefined) clause.source = source;
		return { line: 'unless', clause };
	},
	WhenLine(_when, cond, _then, value, src) {
		const clause: Clause = { when: cond.tree() as Expr, then: value.tree() as Expr };
		if (src.numChildren) clause.source = src.child(0).decl();
		return { line: 'when', clause };
	},
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
	},
	RowLine: (_open, cells, _close) => ({ line: 'row', cells: cells.asIteration().children.map((c: Node) => c.decl()) }),
	Cell_out: (_arrow, e) => ({ out: e.tree() }),
	Cell_any: (_dash) => '-',
	Cell_test: (e) => e.tree(),
	FactLine_table: (_k, t) => named(t, { line: 'facts', fact: t.sourceString }),
	FactLine_row: (_k, n, id, _commas, ctxs) => named(n, { line: 'fact', fact: n.sourceString, id: id.sourceString, ...contexts(ctxs) }),
	Check(_verb, _name, _colon, _cond) {
		return { line: 'check', check: this.tree() };
	},
	AssignLine(n, _eq, value, src) {
		const set: FactRow['set'][number] = { slot: n.sourceString, value: value.tree() as Expr };
		if (src.numChildren) set.source = src.child(0).decl();
		return { line: 'assign', set: named(n, set) };
	},
	Src: (_at, ref) => ref.sourceString
});

/** A logical line: its text range in the file, its indent, and the lines of its block. */
interface Logical {
	indent: number;
	start: number;
	end: number;
	/** The code of its last physical line, without comment, for the continuation tests. */
	last: string;
	/** Parentheses left open, outside text literals and comments. */
	depth: number;
	block: Logical[];
	read?: Line;
}

/** A line's code without its comment: `--` outside a text literal ends it (§3). */
function codeOf(line: string): string {
	let inText = false;
	for (let i = 0; i < line.length; i++) {
		const c = line[i];
		if (inText) {
			if (c === '\\') i++;
			else if (c === '"') inText = false;
		} else if (c === '"') inText = true;
		else if (c === '-' && line[i + 1] === '-') return line.slice(0, i).trimEnd();
	}
	return line.trimEnd();
}
function depthOf(code: string): number {
	let depth = 0;
	let inText = false;
	for (let i = 0; i < code.length; i++) {
		const c = code[i];
		if (inText) {
			if (c === '\\') i++;
			else if (c === '"') inText = false;
		} else if (c === '"') inText = true;
		else if (c === '(') depth++;
		else if (c === ')') depth--;
	}
	return depth;
}
const OPEN_END = /(?:=|(?:^|\s)[+\-*/]|[(,]|\b(?:when|then|else|and|or|not))$/;
const GOES_ON = /^(?:(?:then|else|and|or)\b|=>|[+*/)]|-(?!-))/;

/** Splits a file into logical lines and their blocks (§11); a tab in an indent is an R000. */
function layout(text: string, errors: Diagnostic[], cp: (at: number) => number): Logical[] {
	const top: Logical[] = [];
	const open: Logical[] = [];
	let at = 0;
	let current: Logical | undefined;
	for (const raw of text.split('\n')) {
		const start = at;
		at += raw.length + 1;
		const line = raw.endsWith('\r') ? raw.slice(0, -1) : raw;
		const code = codeOf(line);
		if (!code.trim()) continue;
		const indent = /^ */.exec(code)![0].length;
		if (code[indent] === '\t') {
			errors.push({ code: 'R000', span: { text: '\t', start: cp(start + indent), end: cp(start + indent + 1) }, args: ['spaces'] });
			continue;
		}
		const body = code.slice(indent);
		if (current && indent > current.indent && (current.depth > 0 || OPEN_END.test(current.last) || GOES_ON.test(body))) {
			current.end = start + code.length;
			current.last = body;
			current.depth += depthOf(body);
			continue;
		}
		current = { indent, start: start + indent, end: start + code.length, last: body, depth: depthOf(body), block: [] };
		while (open.length && open[open.length - 1].indent >= indent) open.pop();
		(open.length ? open[open.length - 1].block : top).push(current);
		open.push(current);
	}
	return top;
}
/** The file with all but one logical line blanked: offsets stay those of the file. */
function only(text: string, line: Logical): string {
	const blank = (s: string) => s.replace(/[^\n]/g, ' ');
	return blank(text.slice(0, line.start)) + text.slice(line.start, line.end) + blank(text.slice(line.end));
}

const WHAT: Record<string, string> = {
	param: 'version',
	kind: '`applies`, `sealed`, a slot or `derived`',
	extend: '`derived`',
	derived: '`unless`, `table` or `version`',
	unless: '`when`',
	table: 'a row',
	facts: 'a row',
	fact: 'a slot `=` a value',
	top: 'a declaration'
};
const ALLOWED: Record<string, string[]> = {
	param: ['version'],
	kind: ['applies', 'sealed', 'slot', 'derived'],
	extend: ['derived'],
	derived: ['unless', 'table', 'version'],
	unless: ['when'],
	table: ['row'],
	facts: ['row'],
	fact: ['assign'],
	top: ['rounding', 'reason', 'unit', 'enum', 'param', 'kind', 'extend', 'check', 'facts', 'fact']
};

/** Reads one Rezono file into its module. */
export const parseModule = (text: string): ParsedModule => readModule(text, false);

/**
 * Reads declarations that stand without a header: what a conformance case declares on top of a schema
 * (docs/rezono/tables.md §6). A header line is no declaration here (R000).
 */
export function parseDeclarations(text: string): Omit<ParsedModule, 'module'> & { decls?: Decl[] } {
	const { module, ...rest } = readModule(text, true);
	return { ...(module ? { decls: module.decls } : {}), ...rest };
}

function readModule(text: string, bare: boolean): ParsedModule {
	const spans = new WeakMap<object, Span>();
	const errors: Diagnostic[] = [];
	const later: Diagnostic[] = [];
	const map = points(text);
	const cp = (at: number) => (map ? map[at] : at);
	const lines = layout(text, errors, cp);
	const read = (line: Logical, rule = 'Line') => {
		const cut = torn(text.slice(line.start, line.end));
		if (cut) {
			// The statement is not read: its tree would hold the line end inside the literal.
			const [from, to] = [line.start + cut[0], line.start + cut[1]];
			errors.push(tornAt(text, from, to, cp));
		} else {
			const r = readRule(only(text, line), rule, (m) => m.decl() as Line, spans, map);
			// A statement that stops short fails where its line ends: what follows it in the file is blank here.
			for (const e of r.errors) if (e.span.start > cp(line.end)) e.span = { text: '', start: cp(line.end), end: cp(line.end) };
			// The header ends in `->` and the name of the output (tables.md §2): a row of cells that does not is
			// refused as a whole, since no cell of it is the one that is wrong.
			if (rule === 'TableHead' && r.errors.length && !readRule(only(text, line), 'RowLine', () => undefined, new WeakMap(), map).errors.length)
				errors.push({ code: 'R000', span: { text: text.slice(line.start, line.end), start: cp(line.start), end: cp(line.end) }, args: ['a header that ends in `->` and a name'] });
			else errors.push(...r.errors);
			later.push(...r.reserved);
			line.read = r.value;
		}
		// The lines under a `table` are its header and its rows, each read by its own rule (tables.md §2).
		const table = line.read?.line === 'table';
		line.block.forEach((child, i) => read(child, table ? (i === 0 ? 'TableHead' : 'TableRow') : 'Line'));
	};
	for (const line of lines) read(line);
	if (errors.length) return { diagnostics: errors.sort(inOrder), spans };

	const refuse = (line: Logical, expected: string, to = line.start + /^\S+/.exec(text.slice(line.start, line.end))![0].length) =>
		errors.push({ code: 'R000', span: { text: text.slice(line.start, to), start: cp(line.start), end: cp(to) }, args: [expected] });
	const misplaced = (line: Logical, parent: string) => refuse(line, WHAT[parent]);
	/** A line that takes no block: each line under it is an R000, so that none is left out of the tree. */
	const leaf = (line: Logical) => {
		for (const c of line.block) refuse(c, 'no line under this one');
	};
	/** The lines of a block that its parent allows, none of which takes a block; the others are an R000 each. */
	const under = (line: Logical, kind: string): Line[] => {
		// `unless` is a clause or a block of `when` lines (§11): a bare one with nothing under it is neither, and
		// would be an empty list of clauses in the tree.
		if (kind === 'unless' && !line.block.length) refuse(line, '`when` under it');
		return line.block.flatMap((c) => (ALLOWED[kind].includes(c.read!.line) ? (leaf(c), [c.read!]) : (misplaced(c, kind), [])));
	};
	const strip = <T>(l: Line): T => {
		const { line: _line, ...rest } = l;
		// The declaration keeps the place of the line it came from.
		const span = spans.get(l);
		if (span) spans.set(rest, span);
		return rest as T;
	};
	const version = (line: Logical): VersionDecl => (leaf(line), strip<VersionDecl>(line.read!));
	const table = (line: Logical, header: 'table' | 'facts') => {
		const rows = line.block.filter((c) => ALLOWED[header].includes(c.read!.line) || (misplaced(c, header), false)).map((c) => c.read!.cells as (Expr | '-' | { out: Expr })[]);
		for (const c of line.block) leaf(c);
		return rows;
	};
	/** A decision table: its header, then its rows, each with one cell for each input (tables.md §2). */
	const decision = (line: Logical, of: string): Table | undefined => {
		const [head, ...rows] = line.block;
		// Nothing stands under a line of a table: a statement there would be dropped unseen.
		for (const c of line.block) leaf(c);
		if (!head) return void refuse(line, 'a header under it: `| input | -> name |`');
		const { inputs, output } = head.read as unknown as { inputs: Expr[]; output: { name: string } };
		for (const c of rows) if ((c.read!.tests as unknown[]).length !== inputs.length) refuse(c, `${inputs.length} cells and a value`, c.end);
		// The name after `->` is the derived value's own (tables.md §2).
		if (output.name !== of) later.push({ code: 'R001', span: spans.get(output)!, args: [output.name], suggest: [of] });
		const decl: Table = { table: line.read!.table as Table['table'], inputs, output: output.name, rows: rows.map((c) => strip<TableRow>(c.read!)) };
		spans.set(decl, spans.get(line.read!)!);
		return decl;
	};
	const derived = (line: Logical): DerivedDecl => {
		const decl = strip<DerivedDecl>(line.read!);
		for (const c of line.block) {
			const r = c.read!;
			if (!ALLOWED.derived.includes(r.line)) misplaced(c, 'derived');
			else if (r.line === 'version') (decl.versions ??= []).push(version(c));
			else if (r.line === 'unless') {
				if (r.clause) leaf(c);
				(decl.unless ??= []).push(r.clause ? [r.clause as Clause] : under(c, 'unless').map((w) => w.clause as Clause));
			} else if (decl.table) refuse(c, 'one `table`'); // A second table would replace the first one unseen.
			else {
				const read = decision(c, decl.derived);
				if (read) decl.table = read;
				// A table is the whole definition (v0 §11): beside `=`, `unless` or a version one of them would win unseen.
				if (decl.value || line.block.some((o) => o.read!.line === 'unless' || o.read!.line === 'version')) refuse(c, 'a `table` alone under its derived value');
			}
		}
		// Only a table's value is proven known (tables.md §4): `total` on another value would be a claim nobody checks.
		if (decl.totality && !line.block.some((c) => c.read!.line === 'table')) refuse(line, 'a `table` under a `total` value');
		return decl;
	};

	const module: Module = { pack: '', use: [], decls: [] };
	let stage = bare ? 2 : 0; // 0: before `pack`; 1: after it, `use` lines; 2: declarations
	for (const line of lines) {
		const r = line.read!;
		if (r.line === 'rezono' && stage === 0 && module.rezono === undefined && !module.decls.length) {
			leaf(line);
			module.rezono = r.rezono as string;
			continue;
		}
		if (r.line === 'pack' && stage === 0) {
			leaf(line);
			module.pack = r.pack as string;
			stage = 1;
			continue;
		}
		if (r.line === 'use' && stage === 1) {
			leaf(line);
			module.use.push(strip(r));
			continue;
		}
		if (stage === 0 || !ALLOWED.top.includes(r.line)) {
			const word = /^\S+/.exec(text.slice(line.start, line.end))![0];
			errors.push({ code: 'R000', span: { text: word, start: cp(line.start), end: cp(line.start + word.length) }, args: [stage === 0 ? '`pack`' : WHAT.top] });
			continue;
		}
		stage = 2;
		switch (r.line) {
			case 'param': {
				const decl = strip<ParamDecl>(r);
				const versions: VersionDecl[] = [];
				for (const c of line.block) {
					if (c.read!.line === 'version') versions.push(version(c));
					else misplaced(c, 'param');
				}
				if (versions.length) decl.versions = versions;
				module.decls.push(decl);
				break;
			}
			case 'kind': {
				const decl: KindDecl = { ...strip<KindDecl>(r), slots: [], derived: [] };
				spans.set(decl, spans.get(r)!);
				for (const c of line.block) {
					const k = c.read!;
					if (!ALLOWED.kind.includes(k.line)) misplaced(c, 'kind');
					else if (k.line === 'derived') decl.derived.push(derived(c));
					// A kind has one `applies` and one `sealed` (§5a): a second one would replace the first unseen.
					else if (k.line === 'sealed' ? decl.sealed !== undefined : k.line === 'applies' && decl.applies) refuse(c, `one \`${k.line}\``);
					else {
						leaf(c);
						if (k.line === 'slot') {
							if (k.identifier && decl.embedded) refuse(c, 'no identifier in an embedded kind');
							else if (k.identifier && decl.slots.some((slot) => slot.identifier)) refuse(c, 'one identifier per kind');
							else decl.slots.push(strip(k));
						}
						else if (k.line === 'sealed') decl.sealed = k.slot as string;
						else decl.applies = strip<NonNullable<KindDecl['applies']>>(k);
					}
				}
				module.decls.push(decl);
				break;
			}
			case 'extend': {
				const decl: ExtendDecl = { ...strip<ExtendDecl>(r), derived: [] };
				spans.set(decl, spans.get(r)!);
				for (const c of line.block) {
					if (c.read!.line === 'derived') decl.derived.push(derived(c));
					else misplaced(c, 'extend');
				}
				module.decls.push(decl);
				break;
			}
			case 'facts': {
				const [head = [], ...rows] = table(line, 'facts');
				// A fact table is a header of names and rows with one value for each: a header cell that is no name
				// would be a column without one, and a short row a value that is not there and has no state.
				const value = (cell: unknown) => typeof cell === 'object' && cell !== null && !('out' in cell);
				line.block
					.filter((c) => c.read!.line === 'row')
					.forEach((c, i) => {
						const cells = c.read!.cells as unknown[];
						if (i === 0 ? !cells.every((cell) => value(cell) && 'path' in (cell as object)) : cells.length !== head.length || !cells.every(value))
							refuse(c, i === 0 ? 'a row of column names' : `${head.length} values`, c.end);
					});
				const decl: FactTable = { ...strip<{ fact: string }>(r), columns: head.map((c) => (typeof c === 'object' && 'path' in c ? c.path.join('.') : '')), rows: rows as Expr[][] };
				spans.set(decl, spans.get(r)!);
				module.decls.push(decl);
				break;
			}
			case 'fact': {
				const decl: FactRow = { ...strip<Omit<FactRow, 'set'>>(r), set: under(line, 'fact').map((a) => a.set as FactRow['set'][number]) };
				spans.set(decl, spans.get(r)!);
				module.decls.push(decl);
				break;
			}
			case 'check':
				leaf(line);
				module.decls.push(r.check as CheckDecl);
				break;
			default:
				leaf(line);
				module.decls.push(strip(r));
		}
	}
	if (!bare && !module.pack && !errors.length) errors.push({ code: 'R000', span: { text: '', start: 0, end: 0 }, args: ['`pack`'] });
	if (errors.length) return { diagnostics: errors.sort(inOrder), spans };
	return { module, diagnostics: [...later, ...versionGaps(module, spans)].sort(inOrder), spans };
}

/** W108: a declaration whose versions all start at a `valid` date has no value before the earliest one. */
function versionGaps(module: Module, spans: WeakMap<object, Span>): Diagnostic[] {
	const out: Diagnostic[] = [];
	const look = (decl: ParamDecl | DerivedDecl, name: string) => {
		const versions = decl.versions;
		if (!versions?.length || versions.some((v) => !v.valid)) return;
		const first = versions.map((v) => v.valid![0]).sort()[0];
		const span = spans.get(decl);
		if (span) out.push({ code: 'W108', span, args: [name, first] });
	};
	for (const decl of module.decls) {
		if ('param' in decl) look(decl, decl.param);
		if ('derived' in decl && Array.isArray(decl.derived)) for (const d of decl.derived) look(d, d.derived);
	}
	return out;
}
