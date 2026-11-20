// Query the local reader in process and return status, lower-cased headers and parsed body per request.
import { readFileSync } from 'node:fs';
import { openLocalGate } from '../../edge/gate/src/local.ts';

const { store, role, requests } = JSON.parse(readFileSync(0, 'utf8'));
const handle = await openLocalGate(store, role);
const out = [];
for (const path of requests) {
	const response = await handle(new Request('http://rezono.local' + path));
	const text = await response.text();
	let body;
	try { body = JSON.parse(text); } catch { body = text; }
	const headers = Object.fromEntries(response.headers.entries());
	out.push({ status: response.status, headers, body });
}
process.stdout.write(JSON.stringify(out));
