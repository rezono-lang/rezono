import { declaration, named, type Build, type Logical, type ModuleComponent } from './module-support.ts';

export interface ContextDecl {
	asOf: string;
	known: string;
}

/** Whether a date as written is a day of the calendar. */
export function isCalendarDay(date: string): boolean {
	const [y, m, d] = date.split('-').map(Number);
	const at = new Date(Date.UTC(y, m - 1, d));
	at.setUTCFullYear(y);
	return at.getUTCMonth() === m - 1 && at.getUTCDate() === d;
}

function readContext(line: Logical, build: Build): ContextDecl {
	build.leaf(line);
	const decl = build.strip<ContextDecl>(line.read!);
	for (const date of [decl.asOf, decl.known]) if (!isCalendarDay(date)) build.refuse(line, 'a day of the calendar');
	return decl;
}

export const context = {
	lineRules: ['ContextLine'],
	grammar: String.raw`
  ContextLine = asOfWords date known date
  asOfWords = as hsp+ "of" wordEnd
  `,
	actions: {
		ContextLine: (words, asOf, _known, known) => named(words, { line: 'context', asOf: asOf.sourceString, known: known.sourceString }),
		asOfWords: (_as, _space, _of, _end) => undefined
	},
	declarations: { context: declaration<ContextDecl>('asOf', readContext, d => [`as of ${d.asOf} known ${d.known}`]) }
} satisfies ModuleComponent;
