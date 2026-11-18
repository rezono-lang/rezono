import { named, type ModuleComponent } from './module-support.ts';

export type PatternConstraint = { pattern: string };

export function printSlotPattern({ pattern }: PatternConstraint): string {
	return `pattern "${pattern.replace(/["\\]/g, '\\$&')}"`;
}

export const slotPattern = {
	lineRules: ['SlotPatternLine'],
	grammar: String.raw`
  SlotPatternLine = kw<"pattern"> text
  `,
	actions: {
		SlotPatternLine(keyword, text) {
			const pattern = text.sourceString.slice(1, -1).replace(/\\(.)/gs, '$1');
			return named(keyword, { line: 'slot-pattern', pattern });
		}
	}
} satisfies ModuleComponent;
