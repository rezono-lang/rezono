import { named, optSrc, optTree, printSource, printValue, type Build, type Line, type Logical, type ModuleComponent } from './module-support.ts';
import { refused, run, spanOf, type Diagnostic, type Span } from './parse-support.ts';
import type { Node } from 'ohm-js';
import type { Module } from './module.ts';
import type { ParamDecl } from './module-parameter.ts';
import type { DefinitionDecl, DerivedDecl } from './module-derived.ts';
import type { Expr } from './tree.ts';

/** Span of the version number after `replaces`, keyed by the version line / VersionDecl object. */
const replacedSpans = new WeakMap<object, Span>();

/** A validity range as written: a start and an end exclusive, or a start alone for an open range (§3). */
export type Valid = [string] | [string, string];
export interface VersionDecl {
	version: string;
	/** The number of the version this one replaces, as text (decisions/language-parameters.md). */
	replaces?: string;
	valid?: Valid;
	known?: string;
	value?: Expr;
	source?: string;
	/** The definitions of a version of a derived value written without `= value`: the block under its line. */
	definitions?: DefinitionDecl[];
}

/** A stage context: one stage, or a range from a stage, closed at an exclusive end stage or open. */
export type During = { stage: string } | { from: string; until?: string };
export interface Contexts {
	valid?: Valid;
	during?: During;
	in?: string[];
	known?: string;
}

export function contexts(nodes: Node): Contexts {
	const out: Contexts = {};
	for (const c of nodes.children) {
		const context = c.decl() as Contexts;
		// A second `valid` or `known` would replace the first one unseen.
		if (Object.keys(context).some((axis) => axis in out)) refused(c, 'R018', Object.keys(context));
		Object.assign(out, context);
	}
	return out;
}

/**
 * A version line. Under a derived value, `readDefinitions` reads the block of a version without `= value`: its
 * definitions (decisions/language-calculations.md, Versions with definitions). Any other version is one line.
 */
export function readVersion(
	line: Logical,
	build: Build,
	readDefinitions?: (lines: Logical[], build: Build) => DefinitionDecl[] | undefined
): VersionDecl {
	const decl = build.strip<VersionDecl>(line.read!);
	const replacedSpan = replacedSpans.get(line.read!);
	if (replacedSpan) replacedSpans.set(decl, replacedSpan);
	if (!readDefinitions || decl.value !== undefined || !line.block.length) {
		build.leaf(line);
		return decl;
	}
	const definitions = readDefinitions(line.block, build);
	if (definitions) decl.definitions = definitions;
	return decl;
}

const printDuring = (d: During) => ('stage' in d ? d.stage : `${d.from}..${d.until === undefined ? '' : `<${d.until}`}`);
export const printContexts = (c: Contexts) =>
	`${c.valid ? `, valid ${c.valid[0]}..${c.valid.length === 2 ? `<${c.valid[1]}` : ''}` : ''}${c.during ? `, during ${printDuring(c.during)}` : ''}${c.in ? `, in ${c.in.join(' | ')}` : ''}${c.known !== undefined ? `, known ${c.known}` : ''}`;
export const printVersion = (v: VersionDecl) =>
	`version ${v.version}${v.replaces !== undefined ? ` replaces ${v.replaces}` : ''}${printContexts(v)}${printValue(v.value)}${printSource(v.source)}`;

function eachVersionedDecl(module: Module, visit: (decl: ParamDecl | DerivedDecl, name: string) => void): void {
	for (const decl of module.decls) {
		if ('param' in decl) visit(decl, decl.param);
		else if ('derived' in decl) {
			if (Array.isArray(decl.derived)) for (const d of decl.derived) visit(d, d.derived);
			else visit(decl, decl.derived);
		}
	}
}

/** R021: a `replaces` number that names no version of the same declaration, or `replaces` lines that form a cycle. */
export function versionReplacements(module: Module): Diagnostic[] {
	const out: Diagnostic[] = [];
	const check = (decl: ParamDecl | DerivedDecl, name: string) => {
		const versions = decl.versions;
		if (!versions?.length) return;
		const byNumber = new Map<string, number[]>();
		versions.forEach((v, i) => {
			const group = byNumber.get(v.version);
			if (group) group.push(i);
			else byNumber.set(v.version, [i]);
		});
		const state = new Uint8Array(versions.length); // 0: unvisited, 1: active, 2: done
		const reported = new Set<number>();
		const stack: number[] = [];
		const visit = (node: number): void => {
			const v = versions[node];
			if (v.replaces !== undefined && !byNumber.has(v.replaces)) {
				const span = replacedSpans.get(v);
				if (span) out.push({ code: 'R021', span, args: [v.version, v.replaces, name] });
				state[node] = 2;
				return;
			}
			state[node] = 1;
			stack.push(node);
			const targets = v.replaces !== undefined ? (byNumber.get(v.replaces) ?? []) : [];
			for (const next of targets) {
				if (state[next] === 0) {
					visit(next);
				} else if (state[next] === 1) {
					const cycle = stack.slice(stack.indexOf(next));
					const firstIndex = Math.min(...cycle);
					if (!reported.has(firstIndex)) {
						reported.add(firstIndex);
						const first = versions[firstIndex];
						const span = replacedSpans.get(first);
						if (span) out.push({ code: 'R021', span, args: [first.version, first.replaces!, name] });
					}
				}
			}
			stack.pop();
			state[node] = 2;
		};
		for (let i = 0; i < versions.length; i++) {
			if (state[i] === 0) visit(i);
		}
	};
	eachVersionedDecl(module, check);
	return out;
}

/** W108: a declaration whose versions all start at a `valid` date has no value before the earliest one. */
export function versionGaps(module: Module, spans: WeakMap<object, Span>): Diagnostic[] {
	const out: Diagnostic[] = [];
	const look = (decl: ParamDecl | DerivedDecl, name: string) => {
		const versions = decl.versions;
		if (!versions?.length || versions.some((v) => !v.valid)) return;
		const first = versions.map((v) => v.valid![0]).sort()[0];
		const span = spans.get(decl);
		if (span) out.push({ code: 'W108', span, args: [name, first] });
	};
	eachVersionedDecl(module, look);
	return out;
}

/** Expand `YYYY` or `YYYY-MM` validity shorthand to `[start, exclusiveEnd]`. Returns undefined when the end would exceed year 9999. */
function expandPeriod(text: string): [string, string] | undefined {
	const parts = text.split('-');
	const year = Number(parts[0]);
	if (parts.length === 1) {
		if (year >= 9999) return undefined;
		return [`${parts[0]}-01-01`, `${String(year + 1).padStart(4, '0')}-01-01`];
	}
	const month = Number(parts[1]);
	const nextYear = month === 12 ? year + 1 : year;
	if (nextYear > 9999) return undefined;
	const nextMonth = month === 12 ? 1 : month + 1;
	return [
		`${text}-01`,
		`${String(nextYear).padStart(4, '0')}-${String(nextMonth).padStart(2, '0')}-01`
	];
}

export const version = {
	lineRules: ['VersionLine'],
	grammar: String.raw`
  VersionLine = kw<"version"> number (kw<"replaces"> number)? ("," VContext)* ("=" Expr Src?)?
  VContext = kw<"valid"> date "..<" date    -- closed
           | kw<"valid"> date ".."           -- open
           | kw<"valid"> yearMonth           -- month
           | kw<"valid"> year                -- year
           | known date                      -- known
  yearMonth = d d d d "-" ("0" "1".."9" | "1" "0".."2") ~tokCont
  year = d d d d ~tokCont
  `,
	actions: {
		VersionLine(_k, n, _r, replaced, _commas, ctxs, _eq, value, src) {
			const decl: Line = { line: 'version', version: n.lit() };
			if (replaced.numChildren) {
				const target = replaced.child(0);
				decl.replaces = target.lit();
				replacedSpans.set(decl, spanOf(target));
			}
			Object.assign(decl, contexts(ctxs));
			if (value.numChildren) decl.value = optTree(value);
			const source = optSrc(src);
			if (source !== undefined) decl.source = source;
			return named(n, decl);
		},
		VContext_closed: (_k, from, _op, to) => ({ valid: [from.sourceString, to.sourceString] }),
		VContext_open: (_k, from, _op) => ({ valid: [from.sourceString] }),
		VContext_month(_k, ym) {
			if (run.version === '0') {
				refused(ym, 'R000', ['a validity range `YYYY-MM-DD..` or `YYYY-MM-DD..<YYYY-MM-DD`']);
				return {};
			}
			const range = expandPeriod(ym.sourceString);
			if (!range) {
				refused(ym, 'R000', ['a period ending on or before 9999-12-01']);
				return {};
			}
			return { valid: range };
		},
		VContext_year(_k, y) {
			if (run.version === '0') {
				refused(y, 'R000', ['a validity range `YYYY-MM-DD..` or `YYYY-MM-DD..<YYYY-MM-DD`']);
				return {};
			}
			const range = expandPeriod(y.sourceString);
			if (!range) {
				refused(y, 'R000', ['a year before 9999']);
				return {};
			}
			return { valid: range };
		},
		VContext_known: (_k, date) => ({ known: date.sourceString })
	},
} satisfies ModuleComponent;
