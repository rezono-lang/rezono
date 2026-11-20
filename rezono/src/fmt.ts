// The command that formats Rezono modules into their canonical form (print.ts):
//
//   node src/fmt.ts [--check] <module.rezono>...
//
// Without `--check`, each valid file is written in place in the normal form of `printModule`.
// With `--check`, files are left untouched; exit code 0 means all files are already canonical,
// and 1 means at least one file differs. Invalid or unreadable files are never modified and
// report diagnostics on stderr with a non-zero exit code.
import { readFileSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { isError } from './check.ts';
import { parseModule } from './module.ts';
import { printModule } from './print.ts';
import { reportDiagnostics } from './write-form.ts';

export interface FormatOptions {
	check?: boolean;
	say?: (line: string) => void;
}

/** Formats one Rezono module in place, or checks canonical form when `check` is set. */
export function formatFile(source: string, { check = false, say = console.error }: FormatOptions = {}): 0 | 1 | 2 {
	let text: string;
	try {
		text = readFileSync(source, 'utf8');
	} catch (error) {
		const message = error instanceof Error ? error.message : String(error);
		say(`${source}: ${message}`);
		return 2;
	}
	const { module, diagnostics } = parseModule(text);
	const errors = diagnostics.filter(isError);
	if (!module || errors.length) {
		if (errors.length) reportDiagnostics(source, text, errors, say);
		else say(`${source}: could not parse module`);
		return 1;
	}
	const formatted = printModule(module);
	const again = parseModule(formatted);
	const roundtripErrors = again.diagnostics.filter(isError);
	if (!again.module || roundtripErrors.length) {
		if (roundtripErrors.length) reportDiagnostics(source, formatted, roundtripErrors, say);
		else say(`${source}: formatted output could not be re-parsed`);
		return 1;
	}
	if (text === formatted) return 0;
	if (check) {
		say(`${source}: not formatted`);
		return 1;
	}
	writeFileSync(source, formatted, 'utf8');
	return 0;
}

/** Runs the `rezono fmt` CLI on `argv`, returning the process exit code. */
export function runFmt(argv: readonly string[], say: (line: string) => void = console.error): 0 | 1 | 2 {
	let check = false;
	let stopFlags = false;
	const files: string[] = [];
	for (const arg of argv) {
		if (!stopFlags && arg === '--') {
			stopFlags = true;
		} else if (!stopFlags && arg === '--check') {
			check = true;
		} else if (!stopFlags && arg.startsWith('-')) {
			say(`unknown option: ${arg}`);
			say('usage: node src/fmt.ts [--check] <module.rezono>...');
			return 2;
		} else {
			files.push(arg);
		}
	}
	if (!files.length) {
		say('usage: node src/fmt.ts [--check] <module.rezono>...');
		return 2;
	}
	let status: 0 | 1 | 2 = 0;
	for (const file of files) {
		const code = formatFile(file, { check, say });
		if (code > status) status = code;
	}
	return status;
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
	process.exitCode = runFmt(process.argv.slice(2));
}
