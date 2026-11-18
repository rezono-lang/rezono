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
import { blockSyntax, declarationActions, declarations, type Decl } from './module-components.ts';
import { layout, only, type Logical } from './module-layout.ts';
import { readSchema, type SchemaMetadata } from './module-metadata.ts';
import type { BlockSyntax, Build, Line } from './module-support.ts';
import { versionGaps } from './module-version.ts';
import { inOrder, points, readRule, semantics, torn, tornAt, type Diagnostic, type Span } from './parse.ts';

export type { Decl } from './module-components.ts';
export type { DerivedDecl } from './module-derived.ts';
export type { FactRow, FactTable } from './module-facts.ts';
export type { ExtendDecl, KindDecl } from './module-kind.ts';
export type { ParamDecl } from './module-parameter.ts';
export type { SlotDecl } from './module-slot.ts';
export type { Card, World } from './module-support.ts';
export type { Table, TableRow, TableTest, TableValue } from './module-table.ts';
export type { Clause } from './module-unless.ts';
export type { Valid, VersionDecl } from './module-version.ts';

semantics.addOperation<unknown>('decl', declarationActions);

export interface Module extends SchemaMetadata {
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
	const read = (line: Logical, rule = 'Line', invalidFirst?: BlockSyntax['invalidFirst']) => {
		const cut = torn(text.slice(line.start, line.end));
		if (cut) {
			// A newline inside a literal would become part of that value.
			errors.push(tornAt(text, line.start + cut[0], line.start + cut[1], cp));
		} else {
			const statement = only(text, line);
			const syntax = rule === 'Line' && /^rule(?![A-Za-z0-9_-])/.test(text.slice(line.start, line.end)) ? 'NativeRuleLine' : rule;
			const r = readRule(statement, syntax, (m) => m.decl() as Line, spans, map);
			// The rest of the source is blank here. An incomplete statement fails where its line ends.
			for (const e of r.errors) if (e.span.start > cp(line.end)) e.span = { text: '', start: cp(line.end), end: cp(line.end) };
			const alternative = r.errors.length && invalidFirst?.(text, line, cp, (rule) =>
				!readRule(statement, rule, () => undefined, new WeakMap(), map).errors.length
			);
			if (alternative) errors.push(alternative);
			else errors.push(...r.errors);
			later.push(...r.reserved);
			line.read = r.value;
		}
		const block = line.read && blockSyntax.get(line.read.line);
		line.block.forEach((child, i) => read(child, i === 0 ? block?.first : block?.rest, i === 0 ? block?.invalidFirst : undefined));
	};
	for (const line of lines) read(line);
	if (errors.length) return { diagnostics: errors.sort(inOrder), spans };

	const build: Build = {
		spans,
		later,
		refuse(line, expected, to = line.start + /^\S+/.exec(text.slice(line.start, line.end))![0].length) {
			errors.push({ code: 'R000', span: { text: text.slice(line.start, to), start: cp(line.start), end: cp(to) }, args: [expected] });
		},
		leaf(line) {
			for (const child of line.block) build.refuse(child, 'no line under this one');
		},
		leaves(line, tag, expected) {
			return line.block.flatMap(child => {
				if (child.read!.line !== tag) {
					build.refuse(child, expected);
					return [];
				}
				build.leaf(child);
				return [child.read!];
			});
		},
		strip<T>(line: Line): T {
			const { line: _line, ...rest } = line;
			const span = spans.get(line);
			if (span) spans.set(rest, span);
			return rest as T;
		}
	};

	const module: Module = { pack: '', use: [], decls: [] };
	let stage = bare ? 2 : 0; // 0: before `pack`; 1: after it, `use` lines; 2: declarations
	for (const line of lines) {
		const r = line.read!;
		if (r.line === 'rezono' && stage === 0 && module.rezono === undefined && !module.decls.length) {
			build.leaf(line);
			module.rezono = r.rezono as string;
			continue;
		}
		if (r.line === 'pack' && stage === 0) {
			build.leaf(line);
			module.pack = r.pack as string;
			stage = 1;
			continue;
		}
		if (r.line === 'use' && stage === 1) {
			build.leaf(line);
			module.use.push(build.strip(r));
			continue;
		}
		if (r.line === 'schema' && stage === 1) {
			if (module.schema !== undefined) build.refuse(line, 'one schema identity');
			else readSchema(module, line, build);
			continue;
		}
		const declaration = declarations.get(r.line);
		if (stage === 0 || !declaration) {
			build.refuse(line, stage === 0 ? '`pack`' : 'a declaration');
			continue;
		}
		stage = 2;
		module.decls.push(declaration.read(line, build) as Decl);
	}
	if (!bare && !module.pack && !errors.length) errors.push({ code: 'R000', span: { text: '', start: 0, end: 0 }, args: ['`pack`'] });
	if (errors.length) return { diagnostics: errors.sort(inOrder), spans };
	return { module, diagnostics: [...later, ...versionGaps(module, spans)].sort(inOrder), spans };
}
