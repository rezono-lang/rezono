import { declaration, leafDeclaration, named, type ModuleComponent } from './module-support.ts';
import type { Module } from './module.ts';
import type { Diagnostic, Span } from './parse.ts';

type ReasonDecl = { reason: string; text: string };

function labelSpan(node: { lit: string }, spans: WeakMap<object, Span>): Span | undefined {
	const span = spans.get(node);
	if (!span) return undefined;
	const at = span.text.indexOf('"');
	if (at < 0) return span;
	const text = span.text.slice(at);
	const start = span.start + [...span.text.slice(0, at)].length;
	return { text, start, end: start + [...text].length };
}

/** R029: a state literal whose quoted label is the label of no `reason` declaration of the module. */
export function undeclaredReasonLabels(module: Module, spans: WeakMap<object, Span>): Diagnostic[] {
	const declared = new Set<string>();
	for (const decl of module.decls) if ('reason' in decl) declared.add(decl.text);
	const diagnostics: Diagnostic[] = [];
	const visit = (value: unknown) => {
		if (Array.isArray(value)) {
			for (const item of value) visit(item);
			return;
		}
		if (typeof value !== 'object' || value === null) return;
		const record = value as Record<string, unknown>;
		if (typeof record.lit === 'string' && Object.keys(record).length === 1 && spans.has(record)) {
			if (record.lit.startsWith('unknown "')) {
				const label = record.lit.slice('unknown '.length);
				if (!declared.has(label)) {
					diagnostics.push({ code: 'R029', span: labelSpan(record as { lit: string }, spans)!, args: [label] });
				}
			}
			return;
		}
		for (const [key, entry] of Object.entries(record)) {
			if (key !== 'annotations') visit(entry);
		}
	};
	visit(module.decls);
	return diagnostics;
}

export const reason = {
	lineRules: ['ReasonLine'],
	grammar: String.raw`
  ReasonLine = kw<"reason"> name "=" text
  `,
	actions: {
		ReasonLine: (_k, n, _eq, text) => named(n, { line: 'reason', reason: n.sourceString, text: text.sourceString })
	},
	declarations: { reason: declaration<ReasonDecl>('reason', leafDeclaration, d => [`reason ${d.reason} = ${d.text}`]) }
} satisfies ModuleComponent;
