#!/usr/bin/env node
import { readFileSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { parseArgs } from 'node:util';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StdioClientTransport } from '@modelcontextprotocol/sdk/client/stdio.js';
import { z } from 'zod';
import type { Pin } from './server.ts';

const CALL = z.object({
	tool: z.enum(['ask', 'gap', 'grounds', 'kinds', 'more', 'reach', 'row', 'schema', 'search', 'suppose', 'sweep']),
	args: z.record(z.string(), z.unknown()),
}).strict();
const PLAN = z.object({
	pack: z.string().min(1),
	calls: z.array(CALL),
}).strict();
const RECORDING = PLAN.extend({
	format: z.literal('rezono-mcp.recording/1'),
	role: z.string().min(1),
	manifest: z.string().min(1),
	calls: z.array(CALL.extend({ error: z.boolean(), text: z.string() })),
});
export type Call = z.infer<typeof CALL>;
export type Recording = z.infer<typeof RECORDING>;
type Recorded = Recording['calls'][number];

/** Record the output and refusal status that an MCP client receives for each call. */
export async function run(client: Client, calls: Call[]): Promise<Recorded[]> {
	const out: Recorded[] = [];
	for (const call of calls) {
		const { tool, args } = CALL.parse(call);
		const response = await client.callTool({ name: tool, arguments: args });
		const content = response.content;
		if (!Array.isArray(content) || content.some(item => item?.type !== 'text' || typeof item.text !== 'string')) {
			throw new Error(`${tool}: expected a text tool result`);
		}
		out.push({ tool, args, error: response.isError === true, text: content.map(item => item.text).join('\n') });
	}
	return out;
}

export function compare(expected: Recorded[], actual: Recorded[]): string[] {
	if (expected.length !== actual.length) {
		return [`${actual.length} calls replayed, ${expected.length} recorded`];
	}
	return expected.flatMap((call, index) => {
		const got = actual[index];
		const context = `call ${index + 1} ${call.tool}`;
		if (got.tool !== call.tool || JSON.stringify(got.args) !== JSON.stringify(call.args)) {
			return [`${context}: request differs`];
		}
		if (got.error !== call.error || got.text !== call.text) return [`${context}: response differs`];
		return [];
	});
}

async function latest(store: string, pack: string, role: string): Promise<Pin> {
	const { local } = await import('../../repl/src/client.ts');
	const { Session } = await import('../../repl/src/session.ts');
	const connection = await local(store.startsWith('file:') ? fileURLToPath(store) : store);
	const session = new Session(connection, role);
	const lines = await session.exec(`:use ${JSON.stringify(pack)} latest as ${JSON.stringify(role)}`);
	const pin = session.pin;
	if (!pin || pin.pack !== pack) throw new Error(lines.join('\n'));
	return { pack, manifest: pin.manifest };
}

async function spawned(store: string, role: string, pin: Pin): Promise<Client> {
	const main = fileURLToPath(new URL('./main.ts', import.meta.url));
	const args = [
		...process.execArgv, main, '--store', store, '--role', role, '--pack', pin.pack, '--manifest', pin.manifest,
	];
	const transport = new StdioClientTransport({ command: process.execPath, args, stderr: 'inherit' });
	const client = new Client({ name: 'rezono-mcp-replay', version: '0.1.0' });
	await client.connect(transport);
	return client;
}

const USAGE = 'usage: replay.ts record <calls.json> <recording.json> --store file:///dir --role <role>\n'
	+ '       replay.ts replay <recording.json> --store file:///dir';

async function main(argv: string[]): Promise<number> {
	const { values, positionals } = parseArgs({
		args: argv, allowPositionals: true, options: { store: { type: 'string' }, role: { type: 'string' } },
	});
	const [mode, input, output, ...rest] = positionals;
	const { store, role } = values;
	if (!store || !input || rest.length || !(mode === 'record' ? output && role : mode === 'replay' && !output && !role)) {
		process.stderr.write(USAGE + '\n');
		return 2;
	}
	const source: unknown = JSON.parse(readFileSync(input, 'utf8'));
	if (mode === 'record') {
		const plan = PLAN.parse(source);
		const pin = await latest(store, plan.pack, role!);
		const client = await spawned(store, role!, pin);
		try {
			const recording: Recording = { format: 'rezono-mcp.recording/1', ...pin, role: role!, calls: await run(client, plan.calls) };
			writeFileSync(output, JSON.stringify(recording, null, '\t') + '\n', { flag: 'wx' });
			process.stdout.write(`recorded ${recording.calls.length} calls as ${recording.role} on ${pin.pack} ${pin.manifest}\n`);
		} finally {
			await client.close();
		}
		return 0;
	}

	const recording = RECORDING.parse(source);
	const client = await spawned(store, recording.role, recording);
	try {
		const calls = recording.calls.map(({ tool, args }) => ({ tool, args }));
		const failures = compare(recording.calls, await run(client, calls));
		for (const failure of failures) process.stderr.write(`failed: ${failure}\n`);
		if (failures.length) return 1;
		process.stdout.write(`replay ok: ${calls.length} calls as ${recording.role} on ${recording.pack} ${recording.manifest}\n`);
		return 0;
	} finally {
		await client.close();
	}
}

if (process.argv[1] && fileURLToPath(import.meta.url) === resolve(process.argv[1])) {
	main(process.argv.slice(2)).then(
		code => { if (code) process.exit(code); },
		(error: unknown) => {
			process.stderr.write(`replay: ${error instanceof Error ? error.message : String(error)}\n`);
			process.exit(1);
		},
	);
}
