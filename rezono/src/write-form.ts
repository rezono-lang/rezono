// The command that writes the JSON form of a module to a file (module-json.ts):
//
//   node src/write-form.ts <module.rezono> <form.json>
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

/** Formats and writes diagnostics for `source` with 1-based line numbers from `text`. */
export function reportDiagnostics(
	source: string,
	text: string,
	diagnostics: readonly Diagnostic[],
	say: (line: string) => void = console.error,
): void {
	if (!diagnostics.length) return;
	const sentences = JSON.parse(readFileSync(new URL('../messages/en.json', import.meta.url), 'utf8')) as Record<string, string>;
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

if (process.argv[1] === fileURLToPath(import.meta.url)) {
	const [source, target, ...more] = process.argv.slice(2);
	if (!source || !target || more.length) {
		console.error('usage: node src/write-form.ts <module.rezono> <form.json>');
		process.exitCode = 2;
	} else process.exitCode = writeForm(source, target);
}
