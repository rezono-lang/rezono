import { readFile, writeFile } from 'node:fs/promises';
import { createInterface, type AsyncCompleter } from 'node:readline';
import { fileURLToPath } from 'node:url';
import { parseArgs } from 'node:util';
import { local, remote } from './client.ts';
import { hashes, PROMPT, Recorder, replay } from './record.ts';
import { classOf, Session } from './session.ts';
import { ReplError, terminalLine } from './text.ts';

const USAGE = "usage: rezono-repl (--store <dir|file: URL> | --gate <url>) --role <role> [--use '<pack> <manifest|latest>'] [-c <input>] [--record <file>] | (--store … | --gate …) --role <role> --replay <file> | --class -c <input>";
const write = (lines: string[]) => process.stdout.write(lines.map((line) => `${terminalLine(line)}\n`).join(''));
const failed = (lines: string[]) => lines.length === 1 && lines[0].startsWith('error: ');

function storePath(path: string): string {
	if (/^file:/i.test(path)) {
		const file = new URL(path);
		if (file.host) throw new ReplError('the store must be a local directory');
		return fileURLToPath(file);
	}
	if (/^[a-z][a-z0-9+.-]*:\/\//i.test(path)) throw new ReplError('the store must be a local directory');
	return path;
}

async function main(): Promise<number> {
	const { values } = parseArgs({
		options: {
			store: { type: 'string' },
			gate: { type: 'string' },
			role: { type: 'string' },
			use: { type: 'string' },
			c: { type: 'string', short: 'c' },
			class: { type: 'boolean' },
			record: { type: 'string' },
			replay: { type: 'string' }
		}
	});
	if (values.class && values.c !== undefined) {
		write([classOf(values.c)]);
		return 0;
	}
	if (!values.role || (values.store === undefined) === (values.gate === undefined) ||
		(values.replay !== undefined && (values.c !== undefined || values.use !== undefined || values.record !== undefined))) {
		process.stderr.write(`${USAGE}\n`);
		return 2;
	}

	const connection = values.store === undefined
		? remote(values.gate!, process.env.REZONO_GATE_TOKEN)
		: local(storePath(values.store));
	const session = new Session(connection, values.role);
	if (values.replay !== undefined) {
		const result = await replay(await readFile(values.replay, 'utf8'), session);
		write(result.same ? [`same ${result.session_sha256}`] : result.diff);
		return result.same ? 0 : 1;
	}

	const recorder = values.record === undefined ? undefined : new Recorder(session);
	const exec = (line: string) => recorder ? recorder.exec(line) : session.exec(line);
	const finish = async (code: number) => {
		if (recorder && values.record !== undefined) {
			const text = recorder.text();
			await writeFile(values.record, text, 'utf8');
			const hash = hashes(text);
			process.stderr.write(`session_sha256 ${hash.session_sha256}\ninput_sha256 ${hash.input_sha256}\n`);
		}
		return code;
	};
	if (values.use !== undefined) {
		const result = await exec(`:use ${values.use}`);
		if (values.c === undefined || failed(result)) write(result);
		if (failed(result)) return finish(1);
	}
	if (values.c !== undefined) {
		const result = await exec(values.c);
		write(result);
		return finish(failed(result) ? 1 : 0);
	}

	const terminal = Boolean(process.stdin.isTTY);
	const complete: AsyncCompleter = (line, callback) => {
		session.completions(line).then(
			({ hits, word }) => callback(null, [hits, word]),
			() => callback(null, [[], line])
		);
	};
	const readline = createInterface({ input: process.stdin, output: process.stdout, terminal, prompt: PROMPT, ...(terminal ? { completer: complete } : {}) });
	if (terminal) readline.prompt();
	for await (const line of readline) {
		if (!terminal) write([`${PROMPT}${line}`]);
		write(await exec(line));
		if (session.done) break;
		if (terminal) readline.prompt();
	}
	readline.close();
	return finish(0);
}

main().then((code) => { process.exitCode = code; }, (error: unknown) => {
	process.stderr.write(`error: ${error instanceof ReplError ? terminalLine(error.message) : 'cannot run the session'}\n`);
	process.exitCode = 2;
});
