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
//   R021  a `replaces` number that names no version of the same declaration, or `replaces` lines that form a cycle
//   R015  a reserved construct
//   R029  a state literal whose quoted label is the label of no `reason` declaration of the module
//   W107  a schema header line that writes its default (`import "linkml:types"` alone, `default range Text`,
//         or `annotation layer = ...`)
//   W108  a declaration with versions has none before the earliest `valid` date: there its value is
//         `unknown no_version_applies` (§5a rule 4). Only that first gap is reported here; a gap between two
//         versions needs the order of their contexts, which the checker gives later.
// As in a question, an R000, R014, R016, R018, R021 or R029 leaves no module and no other diagnostic.
import { grammar } from './grammar.ts';
import { blockSyntax, declarationActions, declarations, verbatimBlocks, type Decl } from './module-components.ts';
import type { Deprecation } from './module-deprecation.ts';
import { layout, only, type Logical } from './module-layout.ts';
import { readSchema, type SchemaMetadata } from './module-metadata.ts';
import { undeclaredReasonLabels } from './module-reason.ts';
import type { BlockSyntax, Build, Line } from './module-support.ts';
import { versionGaps, versionReplacements } from './module-version.ts';
import { inOrder, points, readRule, semantics, torn, tornAt, type Diagnostic, type Span } from './parse.ts';

export type { Decl } from './module-components.ts';
export type { Deprecation } from './module-deprecation.ts';
export type { DerivedDecl } from './module-derived.ts';
export type { FactRow, FactTable } from './module-facts.ts';
export type { ExtendDecl, KindDecl } from './module-kind.ts';
export type { ParamDecl } from './module-parameter.ts';
export type { SlotDecl } from './module-slot.ts';
export type { StepChange, StepConfirm, StepDecl, StepEffect, StepForbid, StepSlot } from './module-step.ts';
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
	const lines = layout(text, errors, cp, code => {
		const keyword = code.split(/\s/, 1)[0];
		return verbatimBlocks.some(block => block.keyword === keyword && grammar.match(code, block.header).succeeded());
	});
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
		const tag = line.read?.line;
		if (verbatimBlocks.some(block => block.tag === tag)) return;
		const block = tag === undefined ? undefined : blockSyntax.get(tag);
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
	let pendingDeprecated: { line: Logical; note?: string; until: string } | undefined;
	const clearPendingDeprecated = (reason = 'a kind or an enum declaration') => {
		if (!pendingDeprecated) return;
		build.refuse(pendingDeprecated.line, reason);
		pendingDeprecated = undefined;
	};
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
			clearPendingDeprecated();
			build.leaf(line);
			module.use.push(build.strip(r));
			continue;
		}
		if (r.line === 'schema' && stage === 1) {
			clearPendingDeprecated();
			if (module.schema !== undefined) build.refuse(line, 'one schema identity');
			else readSchema(module, line, build);
			continue;
		}
		if (r.line === 'deprecated') {
			if (stage === 0) {
				build.refuse(line, '`pack`');
				continue;
			}
			build.leaf(line);
			if (pendingDeprecated) {
				// Two deprecated lines above one declaration: refuse at the second keyword.
				build.refuse(line, 'a kind or an enum declaration');
				continue;
			}
			if (typeof r.note !== 'string') build.refuse(line, 'a JSON string');
			pendingDeprecated = { line, note: typeof r.note === 'string' ? r.note : undefined, until: r.until as string };
			continue;
		}
		const declaration = declarations.get(r.line);
		if (stage === 0 || !declaration) {
			clearPendingDeprecated();
			build.refuse(line, stage === 0 ? '`pack`' : 'a declaration');
			continue;
		}
		// A dataset follows the declarations that its tables read, and nothing follows it.
		if ((r.line === 'dataset' && bare) || module.decls.some(decl => 'dataset' in decl)) {
			clearPendingDeprecated();
			build.refuse(line, 'one dataset, after the other declarations of a module');
			continue;
		}
		if (r.line === 'context' && module.decls.some(decl => 'asOf' in decl)) {
			clearPendingDeprecated();
			build.refuse(line, 'one evaluation date in a module');
			continue;
		}
		let deprecated: Deprecation | undefined;
		if (pendingDeprecated) {
			const direct = (r.line === 'kind' || r.line === 'enum')
				&& text.slice(pendingDeprecated.line.end, line.start).split('\n').length === 2;
			if (!direct) clearPendingDeprecated('a kind or an enum declaration directly below `deprecated`');
			else {
				if (pendingDeprecated.note !== undefined) deprecated = { note: pendingDeprecated.note, until: pendingDeprecated.until };
				pendingDeprecated = undefined;
			}
		}
		stage = 2;
		const decl = declaration.read(line, build) as Decl;
		if (deprecated && ('kind' in decl || 'enum' in decl)) decl.deprecated = deprecated;
		module.decls.push(decl);
	}
	clearPendingDeprecated();
	if (!bare && !module.pack && !errors.length) errors.push({ code: 'R000', span: { text: '', start: 0, end: 0 }, args: ['`pack`'] });
	errors.push(...versionReplacements(module));
	errors.push(...undeclaredReasonLabels(module, spans));
	if (errors.length) return { diagnostics: errors.sort(inOrder), spans };
	return {
		module,
		diagnostics: [...later, ...versionGaps(module, spans)].sort(inOrder),
		spans
	};
}
