// The viewer Worker of profile edge alone, in workerd through the Miniflare API: the bundle `wrangler deploy
// --dry-run` makes, its variables from viewer/wrangler.jsonc, and the binding GATE as a function that answers
// from a gate elsewhere (REDE_GATE_ORIGIN, the Node gate of profile.sh) and logs every subrequest: path,
// status, bytes and milliseconds. No Access, no wrangler dev registry: the viewer is measured on its own.
//   node harness.mjs <bundled _worker.js> <viewer/wrangler.jsonc> <subrequest log>
// Serves on 127.0.0.1:8787, inspector on 127.0.0.1:9229; prints "harness ready" when it is.
import { appendFileSync, readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { basename, dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const [script, config, log] = process.argv.slice(2);
// Miniflare comes with the locked deploy tooling (deploy/profiles/edge/tools).
const tools = join(dirname(fileURLToPath(import.meta.url)), 'tools', 'package.json');
const { Miniflare, Response: MfResponse } = await import(pathToFileURL(createRequire(tools).resolve('miniflare')).href);

const cfg = JSON.parse(readFileSync(config, 'utf8').replace(/^\s*\/\/.*$/gm, ''));
const origin = process.env.REDE_GATE_ORIGIN ?? 'http://127.0.0.1:8788';

// Miniflare 5 (the version wrangler 4.151 locks): one worker as `config`, bindings in `config.env`, a function
// binding as `{type: 'fetcher', handler}` (its index.d.ts, MiniflareWorkerConfigSchema).
async function gate(request) {
	const url = new URL(request.url);
	appendFileSync(log, `-> ${request.method} ${url.pathname}${url.search}\n`);
	const t0 = performance.now();
	try {
		const res = await fetch(`${origin}${url.pathname}${url.search}`, { method: request.method, headers: Object.fromEntries(request.headers) });
		const body = await res.arrayBuffer();
		appendFileSync(log, `<- ${res.status} ${body.byteLength} B ${(performance.now() - t0).toFixed(0)} ms\n`);
		return new MfResponse(body, { status: res.status, headers: { 'content-type': res.headers.get('content-type') ?? 'application/json' } });
	} catch (e) {
		appendFileSync(log, `<- error ${e?.stack ?? e}\n`);
		throw e;
	}
}

const mf = new Miniflare({
	host: '127.0.0.1',
	port: 8787,
	inspectorPort: 9229,
	inspectorHost: '127.0.0.1',
	workers: [
		{
			config: {
				name: cfg.name,
				compatibilityDate: cfg.compatibility_date,
				compatibilityFlags: cfg.compatibility_flags,
				manifest: {
					mainModule: basename(script),
					modulesRoot: dirname(script),
					modules: { [basename(script)]: { type: 'esm', contents: readFileSync(script, 'utf8') } }
				},
				env: {
					...Object.fromEntries(Object.entries(cfg.vars ?? {}).map(([k, v]) => [k, { type: 'text', value: String(v) }])),
					GATE: { type: 'fetcher', handler: gate },
					// Static files are not what is measured here.
					ASSETS: { type: 'fetcher', handler: () => new MfResponse('not found', { status: 404 }) }
				}
			}
		}
	]
});
await mf.ready;
appendFileSync(log, `bindings: ${Object.keys(await mf.getBindings()).sort().join(', ')}\n`);
console.log('harness ready');
