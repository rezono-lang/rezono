import { declaration, leafDeclaration, named, type ModuleComponent } from './module-support.ts';
import { refused } from './parse-support.ts';
import type { Node } from 'ohm-js';

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

const day = (date: Node): string => {
	if (!isCalendarDay(date.sourceString)) refused(date, 'R012', [date.sourceString]);
	return date.sourceString;
};

export const context = {
	lineRules: ['ContextLine'],
	grammar: String.raw`
  ContextLine = asOfWords date known date
  asOfWords = as hsp+ "of" wordEnd
  `,
	actions: {
		ContextLine: (words, asOf, _known, known) => named(words, { line: 'context', asOf: day(asOf), known: day(known) }),
		asOfWords: (_as, _space, _of, _end) => undefined
	},
	declarations: { context: declaration<ContextDecl>('asOf', leafDeclaration, d => [`as of ${d.asOf} known ${d.known}`]) }
} satisfies ModuleComponent;
