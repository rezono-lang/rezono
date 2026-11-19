// Ask the local reader of edge/gate in process, as the REPL and the page do: one JSON request on standard
// input ({store, role, requests: [path]}), one JSON result on standard output ([{status, body}]).
import { readFileSync } from 'node:fs';
import { openLocalGate } from '../../edge/gate/src/local.ts';

const { store, role, requests } = JSON.parse(readFileSync(0, 'utf8'));
const handle = await openLocalGate(store, role);
const out = [];
for (const path of requests) {
	const response = await handle(new Request('http://localhost' + path));
	const text = await response.text();
	let body;
	try { body = JSON.parse(text); } catch { body = text; }
	out.push({ status: response.status, body });
}
process.stdout.write(JSON.stringify(out));
