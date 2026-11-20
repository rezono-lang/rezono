// Generates a TextMate (.tmLanguage.json) syntax-highlighting grammar directly from Rezono's Ohm grammar
// (grammar.ts) and reserved/aggregate vocabularies (rule-names.ts), keeping editor highlighting in lockstep
// with the reader.
import { writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import * as ohm from 'ohm-js';
import { grammar } from './grammar.ts';
import { aggregates, keywords } from './rule-names.ts';

export interface TextMateRule {
	name?: string;
	match?: string;
	begin?: string;
	end?: string;
	captures?: Record<string, { name: string }>;
	beginCaptures?: Record<string, { name: string }>;
	endCaptures?: Record<string, { name: string }>;
	patterns?: TextMateRule[];
	include?: string;
}

export interface TextMateGrammar {
	$schema: string;
	name: string;
	scopeName: string;
	fileTypes: string[];
	patterns: TextMateRule[];
	repository: Record<string, TextMateRule>;
}

const LOGICAL_OPERATORS = new Set(['not', 'and', 'or']);
const WORD_OPERATORS = new Set(['in', 'is', 'at', 'as']);
const DECLARATION_MODIFIERS = ['private', 'total', 'abstract', 'embedded', 'relationship'] as const;
const DECLARATION_TARGETS = [
	'kind', 'extend', 'derived', 'rule', 'step', 'param', 'enum', 'unit', 'type',
	'check', 'warn', 'require', 'norm', 'fact', 'dataset', 'source', 'table',
	'view', 'theory', 'example', 'schema',
] as const;
const STANDALONE_DECLARATIONS = ['given', 'expect', 'sealed'] as const;
const EXTRA_DECLARATION_HEADERS = [
	'private', 'suppose', 'propose', 'decide', 'assume', 'theory', 'view', 'exception',
] as const;
const DECLARATION_ENTRY_RULES = [
	'Line', 'Question', 'ExampleSectionLine', 'ExampleExpectLine',
	'StepClauseLine', 'StepEffectLine', 'RuleMeansLine', 'NativeRuleLine',
] as const;

const WORD_BEFORE = '(?<![A-Za-z0-9_])(?<![A-Za-z0-9_]-)';
const WORD_BEFORE_NO_DOT = '(?<![A-Za-z0-9_.])(?<![A-Za-z0-9_]-)';
const WORD_END = '(?![A-Za-z0-9_]|-[A-Za-z0-9_])';
const HEADER_FOLLOW = '(?=[ \\t]+[A-Za-z0-9_"`(])';
const NUMBER_CORE = String.raw`\d+(?:_\d+)*(?:\.\d+(?:_\d+)*)?(?:/\d+(?:_\d+)*)?`;

/** Collect all terminals reachable through an Ohm rule's body. */
function ruleTerminals(ruleName: string): string[] {
	const rule = grammar.rules[ruleName];
	if (!rule) return [];
	const found: string[] = [];
	const visit = (node: unknown) => {
		if (!node || typeof node !== 'object') return;
		if (node instanceof ohm.pexprs.Terminal) {
			const obj = (node as unknown as { obj: unknown }).obj;
			if (typeof obj === 'string') found.push(obj);
			return;
		}
		if (node instanceof ohm.pexprs.Not) return;
		if (node instanceof ohm.pexprs.Alt) node.terms.forEach(visit);
		else if (node instanceof ohm.pexprs.Seq) node.factors.forEach(visit);
		else if (node instanceof ohm.pexprs.Iter || node instanceof ohm.pexprs.Lookahead) {
			visit((node as unknown as { expr: ohm.PExpr }).expr);
		}
	};
	visit(rule.body);
	return found;
}

/** Extract contextual declaration-header keywords from the leading tokens of grammar line rules. */
function extractDeclarationHeaders(hardKeywords: ReadonlySet<string>): string[] {
	const words = new Set<string>(EXTRA_DECLARATION_HEADERS);
	const firstWords = (node: unknown, seen: Set<string>) => {
		if (!node || typeof node !== 'object') return;
		if (node instanceof ohm.pexprs.Apply) {
			const { ruleName, args } = node as unknown as { ruleName: string; args: ohm.PExpr[] };
			if (ruleName === 'kw' && args.length === 1) {
				const arg = args[0];
				if (arg instanceof ohm.pexprs.Terminal) {
					const obj = (arg as unknown as { obj: unknown }).obj;
					if (typeof obj === 'string' && /^[a-z][a-z0-9_]*$/.test(obj)) words.add(obj);
				}
				return;
			}
			if (seen.has(ruleName)) return;
			const next = new Set(seen);
			next.add(ruleName);
			const rule = grammar.rules[ruleName];
			if (rule) firstWords(rule.body, next);
			return;
		}
		if (node instanceof ohm.pexprs.Terminal) {
			const obj = (node as unknown as { obj: unknown }).obj;
			if (typeof obj === 'string' && /^[a-z][a-z0-9_]*$/.test(obj)) words.add(obj);
			return;
		}
		if (node instanceof ohm.pexprs.Alt) {
			for (const term of node.terms) firstWords(term, seen);
		} else if (node instanceof ohm.pexprs.Seq) {
			for (const factor of node.factors) {
				firstWords(factor, seen);
				if (!(factor instanceof ohm.pexprs.Opt || factor instanceof ohm.pexprs.Star)) break;
			}
		} else if (node instanceof ohm.pexprs.Iter) {
			firstWords((node as unknown as { expr: ohm.PExpr }).expr, seen);
		}
	};
	for (const ruleName of DECLARATION_ENTRY_RULES) {
		const rule = grammar.rules[ruleName];
		if (rule) firstWords(rule.body, new Set([ruleName]));
	}
	for (const hard of hardKeywords) words.delete(hard);
	return sortLongestFirst(words);
}

function escapeRegex(literal: string): string {
	return literal.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function escapeCharClass(literal: string): string {
	return literal.replace(/[[\]\\^\-/]/g, '\\$&');
}

/** Sort longest-first, then lexicographically, so regex alternation never shadows a longer token. */
function sortLongestFirst(items: Iterable<string>): string[] {
	return [...new Set(items)].sort((a, b) => b.length - a.length || (a < b ? -1 : a > b ? 1 : 0));
}

function wordAlternation(words: Iterable<string>, guardDot = false): string {
	const sorted = sortLongestFirst(words).map(escapeRegex);
	return `${guardDot ? WORD_BEFORE_NO_DOT : WORD_BEFORE}(?:${sorted.join('|')})${WORD_END}`;
}

function operatorAlternation(ruleNames: string[], extra: string[] = []): string {
	const tokens = new Set<string>(extra);
	for (const name of ruleNames) {
		for (const term of ruleTerminals(name)) {
			if (term !== '>') tokens.add(term);
		}
	}
	// Restore `>` if cmpOp contributed it directly (the `~">"` lookahead in `"=" ~">"` is skipped by ruleTerminals).
	if (ruleNames.includes('cmpOp')) tokens.add('>');
	return `(?:${sortLongestFirst(tokens).map(escapeRegex).join('|')})`;
}

/** Build the TextMate grammar object deterministically from `grammar` and `rule-names`. */
export function generateSyntaxGrammar(): TextMateGrammar {
	const hardKeywords = new Set<string>(keywords);
	const boolWords = new Set(ruleTerminals('boolLit'));
	const stateWords = sortLongestFirst([...ruleTerminals('stateWord'), ...ruleTerminals('known')]);
	const stateAlternation = stateWords.map(escapeRegex).join('|');
	const contextualWords = new Set(ruleTerminals('contextual'));
	const aggregateWords = sortLongestFirst([...aggregates, ...ruleTerminals('aggName')]);
	const nonUnitWords = sortLongestFirst([...hardKeywords, ...contextualWords]).map(escapeRegex).join('|');
	const nonUnitGuard = `(?!(?:${nonUnitWords})${WORD_END})`;

	const logicalOps = [...hardKeywords].filter((w) => LOGICAL_OPERATORS.has(w));
	const wordOps = [...hardKeywords].filter((w) => WORD_OPERATORS.has(w));
	const controlKeywords = [...hardKeywords].filter(
		(w) => !boolWords.has(w) && !LOGICAL_OPERATORS.has(w) && !WORD_OPERATORS.has(w),
	);
	const declarationHeaders = extractDeclarationHeaders(hardKeywords);
	const modifierAlternation = sortLongestFirst(DECLARATION_MODIFIERS).map(escapeRegex).join('|');
	const targetAlternation = sortLongestFirst(DECLARATION_TARGETS).map(escapeRegex).join('|');
	const standaloneAlternation = sortLongestFirst(STANDALONE_DECLARATIONS).map(escapeRegex).join('|');

	const commentPrefix = escapeRegex(ruleTerminals('comment')[0] ?? '--');
	const sourcePrefix = escapeRegex(ruleTerminals('Src')[0] ?? '@');
	const punctChars = ruleTerminals('punct').map(escapeCharClass).join('');
	const symbolClass = String.raw`[^\p{L}\p{N}_\s${punctChars}]`;

	return {
		$schema: 'https://raw.githubusercontent.com/martinring/tmlanguage/master/tmlanguage.json',
		name: 'Rezono',
		scopeName: 'source.rezono',
		fileTypes: ['rezono'],
		patterns: [
			{ include: '#comments' },
			{ include: '#strings' },
			{ include: '#quoted-identifiers' },
			{ include: '#sources' },
			{ include: '#datetimes' },
			{ include: '#dates' },
			{ include: '#numbers' },
			{ include: '#declarations' },
			{ include: '#member-access' },
			{ include: '#constants' },
			{ include: '#aggregates' },
			{ include: '#keywords' },
			{ include: '#operators' },
			{ include: '#calls' },
			{ include: '#identifiers' },
			{ include: '#punctuation' },
		],
		repository: {
			comments: {
				patterns: [
					{
						name: 'comment.line.documentation.rezono',
						match: `${commentPrefix}-.*$`,
					},
					{
						name: 'comment.line.double-dash.rezono',
						match: `${commentPrefix}.*$`,
					},
				],
			},
			strings: {
				name: 'string.quoted.double.rezono',
				begin: '"',
				end: '"',
				patterns: [
					{
						name: 'constant.character.escape.rezono',
						match: '\\\\.',
					},
				],
			},
			'quoted-identifiers': {
				patterns: [
					{
						name: 'constant.other.typed-id.rezono',
						match: '(?<![A-Za-z0-9_])([A-Z][A-Za-z0-9]*):(`[^`\\n]+`)',
						captures: {
							'1': { name: 'entity.name.type.rezono' },
							'2': { name: 'string.other.id.rezono' },
						},
					},
					{
						name: 'variable.other.quoted.rezono',
						match: '`[a-z][a-z0-9_]*`',
					},
				],
			},
			sources: {
				name: 'meta.source.rezono',
				match: `(${sourcePrefix})[ \\t]*([^\\s|]+)`,
				captures: {
					'1': { name: 'punctuation.definition.source.rezono' },
					'2': { name: 'entity.name.source.rezono' },
				},
			},
			datetimes: {
				name: 'constant.numeric.datetime.rezono',
				match: String.raw`(?<![A-Za-z0-9_.-])\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:\d{2})?(?![A-Za-z0-9_]|[-./:][A-Za-z0-9_])`,
			},
			dates: {
				name: 'constant.numeric.date.rezono',
				match: String.raw`(?<![A-Za-z0-9_.-])\d{4}-\d{2}-\d{2}(?![A-Za-z0-9_]|[-./:][A-Za-z0-9_])`,
			},
			numbers: {
				patterns: [
					{
						name: 'constant.numeric.percentage.rezono',
						match: `(?<![A-Za-z0-9_.-])${NUMBER_CORE}[ \\t]*%`,
					},
					{
						name: 'constant.numeric.currency.rezono',
						match: `${symbolClass}+[ \\t]*${NUMBER_CORE}(?:/${nonUnitGuard}[A-Za-z][A-Za-z0-9_]*)?(?![A-Za-z0-9_]|[-./:][A-Za-z0-9_])`,
					},
					{
						name: 'meta.quantity.rezono',
						match: `(?<![A-Za-z0-9_.-])(${NUMBER_CORE})[ \\t]+(${nonUnitGuard}[A-Za-z][A-Za-z0-9_]*)${WORD_END}`,
						captures: {
							'1': { name: 'constant.numeric.rezono' },
							'2': { name: 'support.type.unit.rezono' },
						},
					},
					{
						name: 'constant.numeric.rezono',
						match: `(?<![A-Za-z0-9_.-])${NUMBER_CORE}(?![A-Za-z0-9_]|[-./:][A-Za-z0-9_])`,
					},
					{
						name: 'constant.other.token.rezono',
						match: String.raw`(?<![A-Za-z0-9_.-])\d[A-Za-z0-9_]*(?:[-./:][A-Za-z0-9_]+)*`,
					},
				],
			},
			declarations: {
				patterns: [
					{
						match: `^[ \\t]*(${modifierAlternation})[ \\t]+(${targetAlternation})${WORD_END}${HEADER_FOLLOW}`,
						captures: {
							'1': { name: 'keyword.control.declaration.rezono' },
							'2': { name: 'keyword.control.declaration.rezono' },
						},
					},
					{
						match: `^[ \\t]*(default[ \\t]+range|(?:exact|close|broad)[ \\t]+mapping)${WORD_END}${HEADER_FOLLOW}`,
						captures: {
							'1': { name: 'keyword.control.declaration.rezono' },
						},
					},
					{
						match: `^[ \\t]*(${standaloneAlternation})${WORD_END}(?=[ \\t]*(?:${commentPrefix}|$))`,
						captures: {
							'1': { name: 'keyword.control.declaration.rezono' },
						},
					},
					{
						match: `^[ \\t]*(${declarationHeaders.map(escapeRegex).join('|')})${WORD_END}${HEADER_FOLLOW}`,
						captures: {
							'1': { name: 'keyword.control.declaration.rezono' },
						},
					},
				],
			},
			'member-access': {
				patterns: [
					{
						match: '(?<!\\.)(\\.)(where)(?=\\s*\\()',
						captures: {
							'1': { name: 'punctuation.separator.rezono' },
							'2': { name: 'keyword.control.rezono' },
						},
					},
					{
						match: `(?<!\\.)(\\.)(${aggregateWords.map(escapeRegex).join('|')})(?=\\s*\\()`,
						captures: {
							'1': { name: 'punctuation.separator.rezono' },
							'2': { name: 'support.function.aggregate.rezono' },
						},
					},
					{
						match: '(?<!\\.)(\\.)([a-z][a-z0-9_]*)(?=\\s*\\()',
						captures: {
							'1': { name: 'punctuation.separator.rezono' },
							'2': { name: 'entity.name.function.rezono' },
						},
					},
					{
						match: `(?<!\\.)(\\.)([a-z][a-z0-9_]*)${WORD_END}`,
						captures: {
							'1': { name: 'punctuation.separator.rezono' },
							'2': { name: 'variable.other.member.rezono' },
						},
					},
				],
			},
			constants: {
				patterns: [
					{
						name: 'constant.language.boolean.rezono',
						match: wordAlternation(boolWords, true),
					},
					{
						match: `${WORD_BEFORE_NO_DOT}(is)[ \\t]+(${stateAlternation})${WORD_END}`,
						captures: {
							'1': { name: 'keyword.operator.word.rezono' },
							'2': { name: 'constant.language.state.rezono' },
						},
					},
					{
						match: `${WORD_BEFORE_NO_DOT}(as)[ \\t]+(known)${WORD_END}`,
						captures: {
							'1': { name: 'keyword.operator.word.rezono' },
							'2': { name: 'constant.language.state.rezono' },
						},
					},
					{
						name: 'constant.language.state.rezono',
						match: `${WORD_BEFORE_NO_DOT}n/a${WORD_END}`,
					},
					{
						name: 'constant.language.state.rezono',
						match: `${WORD_BEFORE_NO_DOT}unknown(?=[ \\t]+(?:"|${nonUnitGuard}[a-z][a-z0-9_]*${WORD_END}))`,
					},
					{
						name: 'constant.language.state.rezono',
						match: `${WORD_BEFORE_NO_DOT}invalid(?=[ \\t]+${nonUnitGuard}[a-z][a-z0-9_]*${WORD_END})`,
					},
				],
			},
			aggregates: {
				name: 'support.function.aggregate.rezono',
				match: `(?<![A-Za-z0-9_.])(?:${aggregateWords.map(escapeRegex).join('|')})(?=\\s*\\()`,
			},
			keywords: {
				patterns: [
					{
						name: 'keyword.operator.logical.rezono',
						match: wordAlternation(logicalOps, true),
					},
					{
						name: 'keyword.operator.word.rezono',
						match: wordAlternation(wordOps, true),
					},
					{
						name: 'keyword.control.rezono',
						match: wordAlternation(controlKeywords, true),
					},
				],
			},
			operators: {
				patterns: [
					{
						name: 'keyword.operator.arrow.rezono',
						match: '(?:=>|->)',
					},
					{
						name: 'keyword.operator.range.rezono',
						match: operatorAlternation(['rangeOp']),
					},
					{
						name: 'keyword.operator.comparison.rezono',
						match: operatorAlternation(['cmpOp']),
					},
					{
						name: 'keyword.operator.arithmetic.rezono',
						match: operatorAlternation(['addOp', 'mulOp']),
					},
					{
						name: 'variable.language.wildcard.rezono',
						match: '(?<![A-Za-z0-9_])_(?![A-Za-z0-9_])',
					},
				],
			},
			calls: {
				name: 'entity.name.function.rezono',
				match: '(?<![A-Za-z0-9_.])[a-z][a-z0-9_]*(?=\\s*\\()',
			},
			identifiers: {
				patterns: [
					{
						name: 'constant.other.id.rezono',
						match: '(?<![A-Za-z0-9_-])[A-Za-z][A-Za-z0-9_]*(?:-[A-Za-z0-9_]+)+(?![A-Za-z0-9_-])',
					},
					{
						name: 'entity.name.type.rezono',
						match: `${WORD_BEFORE}[A-Z][A-Za-z0-9]*${WORD_END}`,
					},
					{
						name: 'variable.other.rezono',
						match: `${WORD_BEFORE}[a-z][a-z0-9_]*${WORD_END}`,
					},
				],
			},
			punctuation: {
				patterns: [
					{
						name: 'punctuation.separator.table.rezono',
						match: '\\|',
					},
					{
						name: 'punctuation.separator.rezono',
						match: '[:,.]',
					},
					{
						name: 'keyword.operator.cardinality.rezono',
						match: '[?*+]',
					},
					{
						name: 'punctuation.section.rezono',
						match: '[()\\[\\]{}]',
					},
				],
			},
		},
	};
}

/** Serialize the TextMate grammar deterministically as formatted JSON. */
export function formatSyntaxGrammar(): string {
	return `${JSON.stringify(generateSyntaxGrammar(), null, 2)}\n`;
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
	const [target, ...more] = process.argv.slice(2);
	if (more.length) {
		console.error('usage: node src/syntax-grammar.ts [output.tmLanguage.json]');
		process.exitCode = 2;
	} else {
		const output = formatSyntaxGrammar();
		if (target) writeFileSync(target, output, 'utf8');
		else process.stdout.write(output);
	}
}
