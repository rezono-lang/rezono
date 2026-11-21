// Ask the local reader of edge/gate in process, as the REPL and the page do: one JSON request on standard
// input ({store, role, requests: [path | {path, method?, body?}]}), one JSON result on standard output ([{status, body}]).
import { readFileSync } from 'node:fs';
import { openLocalGate } from '../../edge/gate/src/local.ts';

const { store, role, requests } = JSON.parse(readFileSync(0, 'utf8'));
const handle = await openLocalGate(store, role);
const out = [];
for (const entry of requests) {
	const request = typeof entry === 'string'
		? new Request('http://localhost' + entry)
		: new Request('http://localhost' + entry.path, {
			method: entry.method ?? 'GET',
			...(entry.body !== undefined ? { body: JSON.stringify(entry.body) } : {})
		});
	const response = await handle(request);
	const text = await response.text();
	let body;
	try { body = JSON.parse(text); } catch { body = text; }
	out.push({ status: response.status, body });
}
process.stdout.write(JSON.stringify(out));
