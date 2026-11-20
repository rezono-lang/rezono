import type { Node } from 'ohm-js';

/** The 15 hard expression keywords reserved as bare identifiers in expression and declaration-name positions. */
export const keywords = [
	'when', 'then', 'else', 'unless', 'where', 'show',
	'not', 'and', 'or', 'in', 'is', 'at', 'as', 'true', 'false'
] as const;

export const aggregates = ['sum', 'count', 'min', 'max', 'any', 'all', 'none', 'one'] as const;
const reservedNames = new Set<string>(keywords);
const aggregateNames = new Set<string>(aggregates);

export function readRuleName(node: Node): string {
	const text = node.sourceString;
	return text.startsWith('`') ? text.slice(1, -1) : text;
}

export function spellName(name: string, callMember = false): string {
	return reservedNames.has(name) || (callMember && aggregateNames.has(name)) ? `\`${name}\`` : name;
}

export function spellQualifiedName(name: string, call = false): string {
	const parts = name.split('.');
	return parts.map((part, at) => spellName(part, call && at > 0 && at === parts.length - 1)).join('.');
}
