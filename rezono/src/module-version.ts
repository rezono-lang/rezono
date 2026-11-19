import { named, optSrc, optTree, printSource, printValue, type Build, type Line, type Logical, type ModuleComponent } from './module-support.ts';
import { refused, type Diagnostic, type Span } from './parse-support.ts';
import type { Node } from 'ohm-js';
import type { Module } from './module.ts';
import type { ParamDecl } from './module-parameter.ts';
import type { DerivedDecl } from './module-derived.ts';
import type { Expr } from './tree.ts';

/** A validity range as written: a start and an end exclusive, or a start alone for an open range (§3). */
export type Valid = [string] | [string, string];
export interface VersionDecl {
	version: string;
	valid?: Valid;
	known?: string;
	value?: Expr;
	source?: string;
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

export function readVersion(line: Logical, build: Build): VersionDecl {
	build.leaf(line);
	return build.strip(line.read!);
}

const printDuring = (d: During) => ('stage' in d ? d.stage : `${d.from}..${d.until === undefined ? '' : `<${d.until}`}`);
export const printContexts = (c: Contexts) =>
	`${c.valid ? `, valid ${c.valid[0]}..${c.valid.length === 2 ? `<${c.valid[1]}` : ''}` : ''}${c.during ? `, during ${printDuring(c.during)}` : ''}${c.in ? `, in ${c.in.join(' | ')}` : ''}${c.known !== undefined ? `, known ${c.known}` : ''}`;
export const printVersion = (v: VersionDecl) => `version ${v.version}${printContexts(v)}${printValue(v.value)}${printSource(v.source)}`;

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
	for (const decl of module.decls) {
		if ('param' in decl) look(decl, decl.param);
		if ('derived' in decl && Array.isArray(decl.derived)) for (const d of decl.derived) look(d, d.derived);
	}
	return out;
}

export const version = {
	lineRules: ['VersionLine'],
	grammar: String.raw`
  VersionLine = kw<"version"> number ("," VContext)* ("=" Expr Src?)?
  VContext = kw<"valid"> date "..<" date    -- closed
           | kw<"valid"> date ".."           -- open
           | known date                      -- known
  `,
	actions: {
		VersionLine(_k, n, _commas, ctxs, _eq, value, src) {
			const decl: Line = { line: 'version', version: n.sourceString, ...contexts(ctxs) };
			if (value.numChildren) decl.value = optTree(value);
			const source = optSrc(src);
			if (source !== undefined) decl.source = source;
			return named(n, decl);
		},
		VContext_closed: (_k, from, _op, to) => ({ valid: [from.sourceString, to.sourceString] }),
		VContext_open: (_k, from, _op) => ({ valid: [from.sourceString] }),
		VContext_known: (_k, date) => ({ known: date.sourceString })
	},
} satisfies ModuleComponent;
