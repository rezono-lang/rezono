import { declaration, leafDeclaration, named, type ModuleComponent } from './module-support.ts';

type ReasonDecl = { reason: string; text: string };

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
