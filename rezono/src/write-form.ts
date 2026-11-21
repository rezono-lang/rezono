// The command that writes the JSON form of a module to a file (module-json.ts):
//
//   node src/write-form.ts <module.rezono> <form.json>
//   node src/write-form.ts --batch <module1.rezono> <form1.json> [<module2.rezono> <form2.json> ...]
//   node src/write-form.ts --batch   (reads a JSON array of [module, form] pairs from stdin)
//
// It writes the canonical JSON and nothing after it, so the bytes of the file are those the form's hash is taken
// over. Each diagnostic is printed with its line and its sentence (messages/en.json). A module with an error
// gets no file, and a file left at `<form.json>` by an earlier run is removed before anything else, so that a
// form never stands beside a text it is not the form of. Exit code 0: written; 1: refused, or the text could
// not be read; 2: not called as above.
import { readFileSync, rmSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { lineOf, moduleForm, moduleToJson } from './module-json.ts';
import type { Diagnostic } from './parse.ts';

let cachedSentences: Record<string, string> | undefined;

function diagnosticSentences(): Record<string, string> {
	if (!cachedSentences) {
		cachedSentences = JSON.parse(readFileSync(new URL('../messages/en.json', import.meta.url), 'utf8')) as Record<string, string>;
	}
	return cachedSentences;
}

/** Formats and writes diagnostics for `source` with 1-based line numbers from `text`. */
export function reportDiagnostics(
	source: string,
	text: string,
	diagnostics: readonly Diagnostic[],
	say: (line: string) => void = console.error,
): void {
	if (!diagnostics.length) return;
	const sentences = diagnosticSentences();
	const line = lineOf(text);
	for (const d of diagnostics) {
		const sentence = (sentences[d.code] ?? '').replace(/\{(\d+)\}/g, (_m, i: string) => d.args[Number(i)] ?? '');
		say(`${source}:${line(d.span.start)}: ${d.code} at \`${d.span.text}\`: ${sentence}`);
	}
}

/** Writes the form of the module at `source` to `target`; the lines it reports go to `say`. */
export function writeForm(source: string, target: string, say: (line: string) => void = console.error): 0 | 1 {
	if (resolve(source) === resolve(target)) throw new Error('the form cannot be written over its own text');
	// Before anything else: whatever happens below, no form of an earlier text is left standing.
	rmSync(target, { force: true });
	const text = readFileSync(source, 'utf8');
	const { form, diagnostics } = moduleForm(text);
	reportDiagnostics(source, text, diagnostics, say);
	if (!form) return 1;
	writeFileSync(target, moduleToJson(form));
	return 0;
}

/** Writes the form of each `[source, target]` pair in order; returns 0 only if every pair succeeded. */
export function writeForms(
	pairs: readonly (readonly [string, string])[],
	say: (line: string) => void = console.error,
): 0 | 1 {
	let status: 0 | 1 = 0;
	for (const [source, target] of pairs) {
		if (writeForm(source, target, say) !== 0) status = 1;
	}
	return status;
}

function parseBatchStdin(raw: string): [string, string][] | null {
	let parsed: unknown;
	try {
		parsed = JSON.parse(raw);
	} catch {
		return null;
	}
	if (!Array.isArray(parsed)) return null;
	const pairs: [string, string][] = [];
	for (const item of parsed) {
		if (Array.isArray(item) && item.length === 2 && typeof item[0] === 'string' && typeof item[1] === 'string') {
			pairs.push([item[0], item[1]]);
		} else if (
			item && typeof item === 'object' && !Array.isArray(item)
			&& typeof (item as Record<string, unknown>).source === 'string'
			&& typeof (item as Record<string, unknown>).target === 'string'
		) {
			pairs.push([(item as Record<string, string>).source, (item as Record<string, string>).target]);
		} else {
			return null;
		}
	}
	return pairs;
}

const USAGE = 'usage: node src/write-form.ts <module.rezono> <form.json> | --batch [<module.rezono> <form.json> ...]';

if (process.argv[1] === fileURLToPath(import.meta.url)) {
	const args = process.argv.slice(2);
	if (args[0] === '--batch') {
		const rest = args.slice(1);
		if (rest.length === 0) {
			const pairs = parseBatchStdin(readFileSync(0, 'utf8'));
			if (pairs === null) {
				console.error(USAGE);
				process.exitCode = 2;
			} else {
				process.exitCode = writeForms(pairs);
			}
		} else if (rest.length % 2 !== 0) {
			console.error(USAGE);
			process.exitCode = 2;
		} else {
			const pairs: [string, string][] = [];
			for (let i = 0; i < rest.length; i += 2) pairs.push([rest[i], rest[i + 1]]);
			process.exitCode = writeForms(pairs);
		}
	} else {
		const [source, target, ...more] = args;
		if (!source || !target || more.length) {
			console.error(USAGE);
			process.exitCode = 2;
		} else process.exitCode = writeForm(source, target);
	}
}
