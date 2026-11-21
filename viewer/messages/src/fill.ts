import type { MessageResource } from '../../../contracts/typescript/generated/bundle.ts';

export type MessageArgs = Readonly<Record<string, string | number | boolean | undefined>>;

/** Raised when an MF2 message references a variable that has no argument value. */
export class MissingMessageArgument extends Error {
	argument: string;
	messageId?: string;

	constructor(argument: string, messageId?: string) {
		super(
			messageId
				? `Missing message argument "${argument}" for "${messageId}"`
				: `Missing message argument "${argument}"`,
		);
		this.name = 'MissingMessageArgument';
		this.argument = argument;
		this.messageId = messageId;
	}
}

interface BoundValue {
	value: string | number | boolean;
	func?: string;
}

interface Variant {
	keys: string[];
	pattern: string;
}

const ENTRY_START = /^([A-Za-z0-9_.-]+)\s*=\s*(.*)$/;
const VAR_NAME = /^[A-Za-z_][A-Za-z0-9_.]*/;
const NUMERIC_KEY = /^-?\d+(?:\.\d+)?$/;
const PLURAL_KEYS = new Set(['zero', 'one', 'two', 'few', 'many', 'other']);
const pluralRulesCache = new Map<string, Intl.PluralRules | null>();

function pluralCategory(lang: string, value: number): string {
	let rules = pluralRulesCache.get(lang);
	if (rules === undefined) {
		try {
			rules = new Intl.PluralRules(lang);
		} catch {
			rules = null;
		}
		pluralRulesCache.set(lang, rules);
	}
	return rules ? rules.select(value) : 'other';
}

function resourceBody(resource: string): string {
	const normalized = resource.replace(/\r\n?/g, '\n');
	if (normalized.startsWith('---\n')) {
		return normalized.slice('---\n'.length);
	}
	const sep = normalized.indexOf('\n---\n');
	return sep >= 0 ? normalized.slice(sep + '\n---\n'.length) : normalized;
}

function findEntry(resources: readonly MessageResource[], lang: string, id: string): string | undefined {
	let found: string | undefined;
	for (const entry of resources) {
		if (!entry || entry.lang !== lang || typeof entry.resource !== 'string') continue;
		const lines = resourceBody(entry.resource).split('\n');
		let currentId: string | undefined;
		let currentLines: string[] = [];
		const flush = (): void => {
			if (currentId === id) {
				found = currentLines.join('\n');
			}
			currentId = undefined;
			currentLines = [];
		};
		for (const line of lines) {
			const match = ENTRY_START.exec(line);
			if (match) {
				flush();
				currentId = match[1];
				currentLines = [match[2]];
			} else if (currentId !== undefined && (line === '' || line.startsWith(' ') || line.startsWith('\t'))) {
				currentLines.push(line);
			} else {
				flush();
			}
		}
		flush();
	}
	return found;
}

function skipWs(text: string, pos: number): number {
	while (pos < text.length && /\s/.test(text[pos])) {
		pos++;
	}
	return pos;
}

function readBraced(text: string, start: number): { inner: string; end: number } {
	// Start sits on '{'; track nested quoted literals |...| so literal braces inside them do not close early.
	let pos = start + 1;
	let inQuoted = false;
	while (pos < text.length) {
		const ch = text[pos];
		if (ch === '\\') {
			pos += 2;
			continue;
		}
		if (ch === '|') {
			inQuoted = !inQuoted;
			pos++;
			continue;
		}
		if (!inQuoted && ch === '}') {
			return { inner: text.slice(start + 1, pos), end: pos + 1 };
		}
		pos++;
	}
	return { inner: text.slice(start + 1), end: text.length };
}

function readQuotedPattern(text: string, start: number): { pattern: string; end: number } {
	let pos = start + 2;
	while (pos < text.length) {
		const ch = text[pos];
		if (ch === '\\') {
			pos += 2;
			continue;
		}
		if (ch === '{') {
			if (text[pos + 1] === '{') {
				pos += 2;
				continue;
			}
			pos = readBraced(text, pos).end;
			continue;
		}
		if (ch === '}' && text[pos + 1] === '}') {
			return { pattern: text.slice(start + 2, pos), end: pos + 2 };
		}
		pos++;
	}
	return { pattern: text.slice(start + 2), end: text.length };
}

function unescapeText(raw: string): string {
	return raw.replace(/\\([\\{}|])/g, '$1');
}

function resolveArg(
	name: string,
	args: MessageArgs,
	env: ReadonlyMap<string, BoundValue>,
	id: string,
): BoundValue {
	const bound = env.get(name);
	if (bound !== undefined) {
		return bound;
	}
	if (Object.hasOwn(args, name)) {
		const value = args[name];
		if (value !== undefined && value !== null) {
			return { value };
		}
	}
	throw new MissingMessageArgument(name, id);
}

function parseExpression(
	inner: string,
	args: MessageArgs,
	env: ReadonlyMap<string, BoundValue>,
	id: string,
): BoundValue {
	const trimmed = inner.trim();
	if (trimmed.startsWith('$')) {
		const match = VAR_NAME.exec(trimmed.slice(1));
		if (!match) {
			throw new MissingMessageArgument('', id);
		}
		const name = match[0];
		const rest = trimmed.slice(1 + name.length).trim();
		const funcMatch = /^:([A-Za-z0-9_.-]+)/.exec(rest);
		const existing = resolveArg(name, args, env, id);
		return {
			value: existing.value,
			func: funcMatch ? funcMatch[1] : existing.func,
		};
	}
	if (trimmed.startsWith('|')) {
		const end = trimmed.lastIndexOf('|');
		const content = end > 0 ? trimmed.slice(1, end) : trimmed.slice(1);
		return { value: unescapeText(content) };
	}
	return { value: trimmed };
}

function renderPattern(
	pattern: string,
	args: MessageArgs,
	env: ReadonlyMap<string, BoundValue>,
	id: string,
): string {
	let out = '';
	let pos = 0;
	while (pos < pattern.length) {
		const ch = pattern[pos];
		if (ch === '\\') {
			const next = pattern[pos + 1];
			if (next === '\\' || next === '{' || next === '}' || next === '|') {
				out += next;
				pos += 2;
			} else {
				out += ch;
				pos++;
			}
			continue;
		}
		if (ch === '{') {
			const { inner, end } = readBraced(pattern, pos);
			out += String(parseExpression(inner, args, env, id).value);
			pos = end;
			continue;
		}
		out += ch;
		pos++;
	}
	return out;
}

function readKey(text: string, start: number): { key: string; end: number } {
	let pos = skipWs(text, start);
	if (text[pos] === '|') {
		pos++;
		let out = '';
		while (pos < text.length) {
			if (text[pos] === '\\' && pos + 1 < text.length) {
				out += text[pos + 1];
				pos += 2;
				continue;
			}
			if (text[pos] === '|') {
				return { key: out, end: pos + 1 };
			}
			out += text[pos];
			pos++;
		}
		return { key: out, end: pos };
	}
	let end = pos;
	while (end < text.length && !/\s/.test(text[end]) && text[end] !== '{') {
		end++;
	}
	return { key: text.slice(pos, end), end };
}

function keyScore(key: string, selector: BoundValue, lang: string): number {
	if (key === '*') return 0;
	if (selector.func === 'number') {
		const num = Number(selector.value);
		if (!Number.isNaN(num)) {
			if (NUMERIC_KEY.test(key) && Number(key) === num) return 2;
			if (PLURAL_KEYS.has(key) && pluralCategory(lang, num) === key) return 1;
		}
		return -1;
	}
	return String(selector.value) === key ? 2 : -1;
}

function selectVariant(variants: Variant[], selectors: BoundValue[], lang: string): string {
	let bestPattern: string | undefined;
	let bestScores: number[] | undefined;
	for (const variant of variants) {
		const scores: number[] = [];
		let matched = true;
		for (let i = 0; i < selectors.length; i++) {
			const score = keyScore(variant.keys[i], selectors[i], lang);
			if (score < 0) {
				matched = false;
				break;
			}
			scores.push(score);
		}
		if (!matched) continue;
		if (!bestScores || scores.some((s, i) => s !== bestScores![i] && s > bestScores![i])) {
			// Compare tuples lexicographically from left to right.
			if (!bestScores) {
				bestScores = scores;
				bestPattern = variant.pattern;
			} else {
				for (let i = 0; i < scores.length; i++) {
					if (scores[i] > bestScores[i]) {
						bestScores = scores;
						bestPattern = variant.pattern;
						break;
					}
					if (scores[i] < bestScores[i]) break;
				}
			}
		}
	}
	if (bestPattern === undefined) {
		throw new Error('No matching MF2 variant found');
	}
	return bestPattern;
}

function isDirective(text: string, pos: number, keyword: string): boolean {
	if (!text.startsWith(keyword, pos)) return false;
	const next = text[pos + keyword.length];
	return next === undefined || /\s/.test(next) || next === '{';
}

function fillComplex(raw: string, startPos: number, lang: string, id: string, args: MessageArgs): string {
	let pos = startPos;
	const env = new Map<string, BoundValue>();
	while (pos < raw.length) {
		pos = skipWs(raw, pos);
		if (isDirective(raw, pos, '.input')) {
			pos = skipWs(raw, pos + '.input'.length);
			if (raw[pos] !== '{') break;
			const { inner, end } = readBraced(raw, pos);
			pos = end;
			const trimmed = inner.trim();
			if (trimmed.startsWith('$')) {
				const match = VAR_NAME.exec(trimmed.slice(1));
				if (match) {
					env.set(match[0], parseExpression(inner, args, env, id));
				}
			}
			continue;
		}
		if (isDirective(raw, pos, '.local')) {
			pos = skipWs(raw, pos + '.local'.length);
			if (raw[pos] === '$') {
				const match = VAR_NAME.exec(raw.slice(pos + 1));
				if (match) {
					const name = match[0];
					pos = skipWs(raw, pos + 1 + name.length);
					if (raw[pos] === '=') {
						pos = skipWs(raw, pos + 1);
						if (raw[pos] === '{') {
							const { inner, end } = readBraced(raw, pos);
							pos = end;
							env.set(name, parseExpression(inner, args, env, id));
						}
					}
				}
			}
			continue;
		}
		break;
	}

	pos = skipWs(raw, pos);
	if (raw.startsWith('{{', pos)) {
		const { pattern } = readQuotedPattern(raw, pos);
		return renderPattern(pattern, args, env, id);
	}

	if (isDirective(raw, pos, '.match')) {
		pos = skipWs(raw, pos + '.match'.length);
		const selectors: BoundValue[] = [];
		while (pos < raw.length && raw[pos] === '$') {
			const match = VAR_NAME.exec(raw.slice(pos + 1));
			if (!match) break;
			const name = match[0];
			selectors.push(resolveArg(name, args, env, id));
			pos = skipWs(raw, pos + 1 + name.length);
		}
		const variants: Variant[] = [];
		while (pos < raw.length) {
			pos = skipWs(raw, pos);
			if (pos >= raw.length) break;
			const keys: string[] = [];
			for (let i = 0; i < selectors.length; i++) {
				const { key, end } = readKey(raw, pos);
				keys.push(key);
				pos = skipWs(raw, end);
			}
			if (!raw.startsWith('{{', pos)) break;
			const { pattern, end } = readQuotedPattern(raw, pos);
			variants.push({ keys, pattern });
			pos = end;
		}
		const chosen = selectVariant(variants, selectors, lang);
		return renderPattern(chosen, args, env, id);
	}

	return renderPattern(raw.slice(pos).trimEnd(), args, env, id);
}

/** Fill MF2 message `id` in `lang` from `resources`, throwing `MissingMessageArgument` on missing args. */
export function fill(
	resources: readonly MessageResource[],
	lang: string,
	id: string,
	args: MessageArgs = {},
): string | undefined {
	if (!Array.isArray(resources)) {
		return undefined;
	}
	const raw = findEntry(resources, lang, id);
	if (raw === undefined) {
		return undefined;
	}
	const safeArgs: MessageArgs = args ?? {};
	const start = skipWs(raw, 0);
	if (isDirective(raw, start, '.input') || isDirective(raw, start, '.local') || isDirective(raw, start, '.match')) {
		return fillComplex(raw, start, lang, id, safeArgs);
	}
	if (raw.startsWith('{{', start)) {
		const { pattern } = readQuotedPattern(raw, start);
		return renderPattern(pattern, safeArgs, new Map(), id);
	}
	return renderPattern(raw.slice(start).trimEnd(), safeArgs, new Map(), id);
}
