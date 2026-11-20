// Renders deterministic light and dark syntax-highlighted SVGs for the opening excerpt of rezono/README.md
// using Rezono's generated TextMate grammar (syntax-grammar.ts) and rezono/highlight-theme.json.
//
//   node src/render-excerpt-svg.ts [--out-dir <dir>]
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { generateSyntaxGrammar } from './syntax-grammar.ts';
import type { TextMateGrammar, TextMateRule } from './syntax-grammar.ts';

export const TOKEN_KINDS = [
	'comment',
	'function',
	'identifier',
	'keyword',
	'number',
	'operator',
	'punctuation',
	'source',
	'state',
	'string',
	'type',
] as const;

export type TokenKind = (typeof TOKEN_KINDS)[number];

export interface ThemePalette {
	background: string;
	border: string;
	foreground: string;
	tokens: Record<TokenKind, string>;
}

export interface HighlightThemeFile {
	themes: {
		light: ThemePalette;
		dark: ThemePalette;
	};
}

export interface HighlightSpan {
	text: string;
	kind: TokenKind | null;
}

interface CompiledRule {
	regex: RegExp;
	scope: string | undefined;
	captures: Record<string, { name: string }> | undefined;
}

const HERE = dirname(fileURLToPath(import.meta.url));
const REZONO_DIR = resolve(HERE, '..');
const DEFAULT_GUIDE = join(REZONO_DIR, 'README.md');
const DEFAULT_THEME = join(REZONO_DIR, 'highlight-theme.json');
const DEFAULT_OUT_DIR = join(REZONO_DIR, 'assets');
const FENCE_RE = /^```[^\n]*\n([\s\S]*?)^```$/m;

const SCOPE_TO_KIND: ReadonlyArray<[prefix: string, kind: TokenKind]> = [
	['comment.', 'comment'],
	['string.', 'string'],
	['constant.character.escape.', 'string'],
	['variable.other.quoted.', 'string'],
	['entity.name.source.', 'source'],
	['constant.numeric.', 'number'],
	['constant.other.token.', 'number'],
	['constant.language.', 'state'],
	['support.function.', 'function'],
	['entity.name.function.', 'function'],
	['entity.name.type.', 'type'],
	['support.type.', 'type'],
	['keyword.control.', 'keyword'],
	['keyword.operator.logical.', 'keyword'],
	['keyword.operator.word.', 'keyword'],
	['keyword.operator.', 'operator'],
	['variable.language.wildcard.', 'operator'],
	['punctuation.', 'punctuation'],
	['constant.other.id.', 'identifier'],
	['variable.other.', 'identifier'],
];

/** Map a TextMate scope name from `syntax-grammar.ts` to one of the eleven theme token kinds. */
export function scopeToTokenKind(scope: string | undefined): TokenKind | null {
	if (!scope) return null;
	for (const [prefix, kind] of SCOPE_TO_KIND) {
		if (scope.startsWith(prefix)) return kind;
	}
	return null;
}

function escapeXml(text: string): string {
	return text
		.replace(/&/g, '&amp;')
		.replace(/</g, '&lt;')
		.replace(/>/g, '&gt;')
		.replace(/"/g, '&quot;');
}

function compileLeafRule(rule: TextMateRule): CompiledRule[] {
	if (rule.match) {
		return [{
			regex: new RegExp(rule.match, 'duy'),
			scope: rule.name,
			captures: rule.captures,
		}];
	}
	if (rule.begin === '"' && rule.end === '"') {
		return [{
			regex: /"(?:\\.|[^"\\])*"/duy,
			scope: rule.name,
			captures: undefined,
		}];
	}
	return [];
}

function flattenGrammarRules(grammar: TextMateGrammar): CompiledRule[] {
	const compiled: CompiledRule[] = [];
	const visit = (rule: TextMateRule): void => {
		if (rule.include && rule.include.startsWith('#')) {
			const entry = grammar.repository[rule.include.slice(1)];
			if (entry) visit(entry);
			return;
		}
		if (rule.patterns) {
			for (const nested of rule.patterns) visit(nested);
			return;
		}
		compiled.push(...compileLeafRule(rule));
	};
	for (const top of grammar.patterns) visit(top);
	return compiled;
}

function splitCapturedMatch(
	line: string,
	start: number,
	end: number,
	outerScope: string | undefined,
	captures: Record<string, { name: string }> | undefined,
	indices: ReadonlyArray<[number, number] | undefined> | undefined,
): HighlightSpan[] {
	const outerKind = scopeToTokenKind(outerScope);
	if (!captures || !indices) {
		return [{ text: line.slice(start, end), kind: outerKind }];
	}
	const regions: Array<{ start: number; end: number; kind: TokenKind | null }> = [];
	for (const [groupKey, capture] of Object.entries(captures)) {
		const idx = Number(groupKey);
		const range = indices[idx];
		if (!range) continue;
		const [cStart, cEnd] = range;
		if (cStart >= start && cEnd <= end && cEnd > cStart) {
			regions.push({ start: cStart, end: cEnd, kind: scopeToTokenKind(capture.name) ?? outerKind });
		}
	}
	regions.sort((a, b) => a.start - b.start);
	const spans: HighlightSpan[] = [];
	let cursor = start;
	for (const region of regions) {
		if (region.start > cursor) {
			const gap = line.slice(cursor, region.start);
			spans.push({ text: gap, kind: /^\s+$/.test(gap) ? null : outerKind });
		}
		spans.push({ text: line.slice(region.start, region.end), kind: region.kind });
		cursor = region.end;
	}
	if (cursor < end) {
		const tail = line.slice(cursor, end);
		spans.push({ text: tail, kind: /^\s+$/.test(tail) ? null : outerKind });
	}
	return spans;
}

/** Tokenize one line of Rezono source using the compiled TextMate grammar rules. */
export function tokenizeLine(line: string, rules: readonly CompiledRule[]): HighlightSpan[] {
	const raw: HighlightSpan[] = [];
	let pos = 0;
	while (pos < line.length) {
		let matched = false;
		for (const rule of rules) {
			rule.regex.lastIndex = pos;
			const result = rule.regex.exec(line) as (RegExpExecArray & { indices?: Array<[number, number] | undefined> }) | null;
			if (result && result[0].length > 0) {
				const end = pos + result[0].length;
				raw.push(...splitCapturedMatch(line, pos, end, rule.scope, rule.captures, result.indices));
				pos = end;
				matched = true;
				break;
			}
		}
		if (!matched) {
			raw.push({ text: line[pos], kind: null });
			pos += 1;
		}
	}
	const merged: HighlightSpan[] = [];
	for (const span of raw) {
		const last = merged[merged.length - 1];
		if (last && last.kind === span.kind) last.text += span.text;
		else merged.push({ ...span });
	}
	return merged;
}

/** Extract the opening fenced code block from `rezono/README.md` with normalized LF line endings. */
export function readOpeningExcerpt(guidePath: string = DEFAULT_GUIDE): string {
	const text = readFileSync(guidePath, 'utf8').replace(/\r\n/g, '\n');
	const match = FENCE_RE.exec(text);
	if (!match) {
		throw new Error(`No fenced code block found in ${guidePath}`);
	}
	return match[1].replace(/\n+$/, '');
}

/** Load and validate the light and dark color palettes from `rezono/highlight-theme.json`. */
export function loadThemeFile(themePath: string = DEFAULT_THEME): HighlightThemeFile {
	const parsed = JSON.parse(readFileSync(themePath, 'utf8')) as HighlightThemeFile;
	if (!parsed?.themes?.light || !parsed?.themes?.dark) {
		throw new Error(`Missing light/dark themes in ${themePath}`);
	}
	return parsed;
}

/** Render one deterministic SVG string for `excerpt` using `palette`. */
export function renderExcerptSvg(
	excerpt: string,
	palette: ThemePalette,
	rules: readonly CompiledRule[] = flattenGrammarRules(generateSyntaxGrammar()),
): string {
	const lines = excerpt.split('\n');
	const fontSize = 13;
	const lineHeight = 20;
	const padX = 18;
	const padY = 16;
	const charWidth = 7.8;
	const maxChars = lines.reduce((max, line) => Math.max(max, line.length), 0);
	const width = Math.max(480, Math.ceil(maxChars * charWidth + padX * 2));
	const height = lines.length * lineHeight + padY * 2;
	const fontFamily = 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace';

	const svgLines: string[] = [
		`<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" role="img" aria-label="Rezono syntax-highlighted code excerpt">`,
		`  <rect x="0.5" y="0.5" width="${width - 1}" height="${height - 1}" rx="6" fill="${escapeXml(palette.background)}" stroke="${escapeXml(palette.border)}" />`,
	];

	for (let i = 0; i < lines.length; i += 1) {
		const y = padY + i * lineHeight + fontSize;
		const line = lines[i];
		if (!line.length) {
			svgLines.push(`  <text x="${padX}" y="${y}" fill="${escapeXml(palette.foreground)}" font-family="${fontFamily}" font-size="${fontSize}" xml:space="preserve"></text>`);
			continue;
		}
		const spans = tokenizeLine(line, rules);
		const body = spans
			.map((span) => {
				const color = span.kind ? palette.tokens[span.kind] : palette.foreground;
				return `<tspan fill="${escapeXml(color)}">${escapeXml(span.text)}</tspan>`;
			})
			.join('');
		svgLines.push(`  <text x="${padX}" y="${y}" fill="${escapeXml(palette.foreground)}" font-family="${fontFamily}" font-size="${fontSize}" xml:space="preserve">${body}</text>`);
	}

	svgLines.push('</svg>', '');
	return svgLines.join('\n');
}

/** Generate both `excerpt-light.svg` and `excerpt-dark.svg` into `outDir`. */
export function writeExcerptSvgs(outDir: string = DEFAULT_OUT_DIR): void {
	const excerpt = readOpeningExcerpt();
	const theme = loadThemeFile();
	const rules = flattenGrammarRules(generateSyntaxGrammar());
	mkdirSync(outDir, { recursive: true });
	writeFileSync(join(outDir, 'excerpt-light.svg'), renderExcerptSvg(excerpt, theme.themes.light, rules), 'utf8');
	writeFileSync(join(outDir, 'excerpt-dark.svg'), renderExcerptSvg(excerpt, theme.themes.dark, rules), 'utf8');
}

function parseOutDir(argv: readonly string[]): string | null {
	let outDir = DEFAULT_OUT_DIR;
	for (let i = 0; i < argv.length; i += 1) {
		const arg = argv[i];
		if (arg === '--out-dir') {
			const next = argv[i + 1];
			if (!next) return null;
			outDir = resolve(next);
			i += 1;
		} else {
			return null;
		}
	}
	return outDir;
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
	const outDir = parseOutDir(process.argv.slice(2));
	if (!outDir) {
		console.error('usage: node src/render-excerpt-svg.ts [--out-dir <dir>]');
		process.exitCode = 2;
	} else {
		writeExcerptSvgs(outDir);
	}
}
