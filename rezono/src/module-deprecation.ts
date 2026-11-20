import { isCalendarDay } from './module-context.ts';
import type { ModuleComponent } from './module-support.ts';
import { refused } from './parse-support.ts';

export interface Deprecation {
	note: string;
	until: string;
}

export function printDeprecated(deprecated?: Deprecation): string[] {
	return deprecated ? [`deprecated ${JSON.stringify(deprecated.note)} until ${deprecated.until}`] : [];
}

export const deprecation = {
	lineRules: ['DeprecatedLine'],
	grammar: String.raw`
  DeprecatedLine = kw<"deprecated"> MetaString kw<"until"> date
  `,
	actions: {
		DeprecatedLine(_kw, note, _until, date) {
			if (!isCalendarDay(date.sourceString)) refused(date, 'R012', [date.sourceString, 'Date']);
			return { line: 'deprecated', note: note.decl(), until: date.sourceString };
		}
	}
} satisfies ModuleComponent;
