#!/usr/bin/env node
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { parseArgs } from 'node:util';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import { local, remote } from '../../repl/src/client.ts';
import { Session } from '../../repl/src/session.ts';
import { mcpServer, proposalAccess } from './server.ts';

const USAGE = 'usage: rezono-mcp (--store file:///dir | --gate <url>) --role <role> [--pack <pack> --manifest <id>]';

export async function main(argv: string[]): Promise<number> {
	let values;
	try {
		({ values } = parseArgs({ args: argv, options: {
			store: { type: 'string' }, gate: { type: 'string' }, role: { type: 'string' },
			pack: { type: 'string' }, manifest: { type: 'string' },
		} }));
	} catch {
		process.stderr.write(USAGE + '\n');
		return 2;
	}
	const { store, gate, role, pack, manifest } = values;
	if (!role || (store === undefined) === (gate === undefined) || (pack === undefined) !== (manifest === undefined)
		|| (gate !== undefined && !/^https?:\/\//.test(gate))) {
		process.stderr.write(USAGE + '\n');
		return 2;
	}
	const credential = process.env.REZONO_GATE_TOKEN;
	const connection = store !== undefined ? await local(store.startsWith('file:') ? fileURLToPath(store) : store)
		: remote(gate!, credential);
	const fetch = await connection.open(role);
	const lockedPin = pack === undefined ? undefined : { pack, manifest: manifest! };
	const access = gate === undefined
		? { mode: 'store' as const }
		: { mode: 'gate' as const, proposal: lockedPin ? undefined : await proposalAccess(fetch, role, !!credential?.trim()) };
	const session = new Session(connection, role, lockedPin);
	if (lockedPin) await session.use(lockedPin.pack, lockedPin.manifest);
	await mcpServer(session, role, { access, lockedPin }).connect(new StdioServerTransport());
	return 0;
}

if (process.argv[1] && fileURLToPath(import.meta.url) === resolve(process.argv[1])) {
	main(process.argv.slice(2)).then(
		(code) => { if (code) process.exit(code); },
		(error: unknown) => {
			process.stderr.write(`rezono-mcp: ${error instanceof Error ? error.message : String(error)}\n`);
			process.exit(1);
		},
	);
}
