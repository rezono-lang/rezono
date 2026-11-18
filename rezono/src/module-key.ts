import { listOf, named, type ModuleComponent } from './module-support.ts';

export interface KeyDecl {
	unique: string;
	slots: string[];
}

export function printKey(key: KeyDecl): string {
	return `unique ${key.unique} = ${key.slots.join(', ')}`;
}

export const key = {
	lineRules: ['KeyLine'],
	grammar: String.raw`
  KeyLine = kw<"unique"> name "=" NonemptyListOf<name, ",">
  `,
	actions: {
		KeyLine(_unique, name, _equals, slots) {
			return named(name, { line: 'key', unique: name.sourceString, slots: listOf(slots) });
		}
	}
} satisfies ModuleComponent;
