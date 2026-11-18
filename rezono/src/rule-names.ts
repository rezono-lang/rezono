import type { Node } from 'ohm-js';

/** The bare names reserved by the existing language. */
export const keywords = [
	'pack', 'use', 'as', 'private', 'unit', 'enum', 'param', 'kind', 'extend', 'derived',
	'rule', 'check', 'warn', 'require', 'fact', 'decide', 'assume', 'theory', 'view',
	'example', 'ask', 'suppose', 'propose', 'when', 'then', 'else', 'unless', 'where', 'show',
	'not', 'and', 'or', 'in', 'is', 'version', 'valid', 'known', 'at', 'by', 'on',
	'because', 'until', 'requires', 'sources', 'world', 'open', 'closed', 'inverse', 'rezono',
	'norm', 'exception', 'applies', 'replaces', 'deprecated', 'true', 'false'
] as const;

export const aggregates = ['sum', 'count', 'min', 'max', 'any', 'all', 'none'] as const;
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
