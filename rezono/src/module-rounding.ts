import { declaration, leafDeclaration, named, type ModuleComponent } from './module-support.ts';

type RoundingDecl = { rounding: 'date' | 'money'; mode: string };

export const rounding = {
	lineRules: ['RoundingLine'],
	grammar: String.raw`
  RoundingLine = kw<"rounding"> (kw<"date"> | kw<"money">) name
  `,
	actions: {
		RoundingLine: (_k, what, mode) => named(what, { line: 'rounding', rounding: what.sourceString, mode: mode.sourceString })
	},
	declarations: { rounding: declaration<RoundingDecl>('rounding', leafDeclaration, d => [`rounding ${d.rounding} ${d.mode}`]) }
} satisfies ModuleComponent;
