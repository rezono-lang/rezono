// CPU and heap profiles of GET requests on the viewer, with every isolate named in REZONO_INSPECTORS (the viewer
// and the gate of profile.sh) profiled during the same request, through the DevTools protocol of their
// inspectors. Per path, in order (the first request meets a cold isolate): <n>-<path>-<worker>.cpuprofile and
// .heapprofile (open in Chrome DevTools), and summary.md: the heap after start, before and after each request,
// the status, the wall time, and the top functions by CPU self time and by sampled live allocations.
// With REZONO_SUBREQUESTS (the log harness.mjs writes), each request must reach the gate through GATE and must
// not fail (status 5xx); the GATE calls and the bytes they read are counted per path. results.json holds the
// numbers per path for a check to compare.
//   REZONO_INSPECTORS="viewer=9229 gate=9230" node profile.mjs <out dir> <path> [path ...]
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

const [out, ...paths] = process.argv.slice(2);
const VIEWER = 'http://127.0.0.1:8787';
const SUBREQUESTS = process.env.REZONO_SUBREQUESTS;
const logged = () => (SUBREQUESTS && existsSync(SUBREQUESTS) ? readFileSync(SUBREQUESTS, 'utf8') : '');
const STORE_LOG = process.env.REZONO_STORE_LOG;
const storeLog = () => (STORE_LOG && existsSync(STORE_LOG) ? readFileSync(STORE_LOG, 'utf8') : '');
// name=port of each inspector; every isolate is profiled during the same request.
const INSPECTORS = (process.env.REZONO_INSPECTORS ?? 'viewer=9229').split(/\s+/).filter(Boolean).map((p) => p.split('='));
mkdirSync(out, { recursive: true });

async function session(name, port) {
	const inspector = `http://127.0.0.1:${port}`;
	const targets = await (await fetch(`${inspector}/json`)).json();
	console.log(`${name} inspector targets:`, JSON.stringify(targets));
	const target = targets.find((t) => `${t.id} ${t.title} ${t.url}`.includes(name)) ?? targets[0];
	if (!target?.webSocketDebuggerUrl) throw new Error(`${name}: no inspector target`);
	// wrangler's inspector proxy checks the Origin of a DevTools connection: a local origin passes.
	const connect = async (init) => {
		const socket = new WebSocket(target.webSocketDebuggerUrl, init);
		await new Promise((ok, fail) => {
			socket.onopen = ok;
			socket.onerror = (e) => fail(new Error(`${name} inspector: ${e.message ?? e.error?.message ?? 'connection failed'}`));
		});
		return socket;
	};
	const ws = await connect({ headers: { origin: inspector } }).catch((e) => (console.log(`${e.message}; again without an origin`), connect()));
	let next = 1;
	const waiting = new Map();
	ws.onmessage = (e) => {
		const m = JSON.parse(e.data);
		if (m.id && waiting.has(m.id)) {
			const { ok, fail } = waiting.get(m.id);
			waiting.delete(m.id);
			m.error ? fail(new Error(`${m.error.message}`)) : ok(m.result);
		}
	};
	const send = (method, params = {}) =>
		new Promise((ok, fail) => {
			const id = next++;
			waiting.set(id, { ok, fail });
			ws.send(JSON.stringify({ id, method, params }));
		});
	// A domain the runtime lacks is reported, not fatal: the other measurements still count.
	const tryTo = async (method, params) => send(method, params).catch((e) => ({ error: e.message }));
	return { name, ws, tryTo };
}

const mb = (b) => (b / 1048576).toFixed(1);
const where = (f) => `${f.functionName || '(anonymous)'} ${f.url ? f.url.split('/').slice(-2).join('/') : ''}:${f.lineNumber + 1}`;

/** CPU self time per function, from a V8 cpuprofile (samples × interval). */
function cpuTop(profile, n = 25) {
	const byId = new Map(profile.nodes.map((node) => [node.id, node]));
	const ticks = new Map();
	for (const id of profile.samples) ticks.set(id, (ticks.get(id) ?? 0) + 1);
	const total = profile.endTime - profile.startTime;
	const per = profile.samples.length ? total / profile.samples.length : 0;
	const self = new Map();
	for (const [id, count] of ticks) {
		const key = where(byId.get(id).callFrame);
		self.set(key, (self.get(key) ?? 0) + count * per);
	}
	return { totalMs: total / 1000, top: [...self].sort((a, b) => b[1] - a[1]).slice(0, n).map(([k, us]) => [k, us / 1000]) };
}

/** Bytes allocated per function (self), from a V8 sampling heap profile. */
function heapTop(profile, n = 25) {
	const self = new Map();
	const walk = (node) => {
		const key = where(node.callFrame);
		self.set(key, (self.get(key) ?? 0) + node.selfSize);
		node.children.forEach(walk);
	};
	walk(profile.head);
	const total = [...self.values()].reduce((a, b) => a + b, 0);
	return { totalBytes: total, top: [...self].sort((a, b) => b[1] - a[1]).slice(0, n) };
}

const sessions = [];
for (const [name, port] of INSPECTORS) sessions.push(await session(name, port));
const lines = ['# Viewer and gate Worker profile', ''];
for (const s of sessions) {
	await s.tryTo('Profiler.enable');
	await s.tryTo('Profiler.setSamplingInterval', { interval: 200 });
	await s.tryTo('HeapProfiler.enable');
	const idle = await s.tryTo('Runtime.getHeapUsage');
	if (!idle.error) lines.push(`- ${s.name}: heap used after start, before any request: ${mb(idle.usedSize)} MB (total ${mb(idle.totalSize)} MB)`);
}
lines.push('');
const results = [];
const failures = [];
for (const [i, path] of paths.entries()) {
	const name = `${i + 1}-${path.replace(/[^A-Za-z0-9]+/g, '_').replace(/^_|_$/g, '') || 'root'}`;
	const before = {};
	for (const s of sessions) {
		before[s.name] = await s.tryTo('Runtime.getHeapUsage');
		await s.tryTo('HeapProfiler.startSampling', { samplingInterval: 16384 });
		await s.tryTo('Profiler.start');
	}
	const offset = logged().length;
	const storeOffset = STORE_LOG ? storeLog().length : 0;
	const t0 = performance.now();
	const res = await fetch(`${VIEWER}${path}`, { signal: AbortSignal.timeout(300_000) }).catch((e) => ({ status: `error ${e.message}`, text: async () => '' }));
	const body = await res.text();
	const wall = performance.now() - t0;
	// The GATE calls of this request: harness.mjs logs `-> METHOD path` on arrival, `<- status N B ms` after.
	const calls = logged().slice(offset).split('\n').filter((l) => l.startsWith('-> ')).length;
	const gateBytes = [...logged().slice(offset).matchAll(/^<- \d+ (\d+) B /gm)].reduce((a, m) => a + Number(m[1]), 0);
	const result = { path, status: res.status, bytes: body.length, wall_ms: Math.round(wall), gate_calls: calls, gate_bytes: gateBytes };
	// Inside the gate: its reads of the store for this request (REZONO_STORE_LOG, written by the Node gate).
	const store = STORE_LOG ? storeLog().slice(storeOffset).split('\n').filter(Boolean) : [];
	if (STORE_LOG) {
		result.store_gets = store.filter((l) => l.startsWith('get ')).length;
		result.store_bytes = store.filter((l) => l.startsWith('get ')).reduce((a, l) => a + Number(l.split(' ')[1]), 0);
		result.store_lists = store.filter((l) => l.startsWith('list ')).length;
		result.store_listed = store.filter((l) => l.startsWith('list ')).reduce((a, l) => a + Number(l.split(' ')[1]), 0);
		// Every object read, with its bytes: the scaling check compares them object by object (scale.py).
		result.store_reads = store.filter((l) => l.startsWith('get ')).map((l) => [l.split(' ').slice(2).join(' '), Number(l.split(' ')[1])]);
	}
	results.push(result);
	lines.push(`## GET ${path}`, '', `- status ${res.status}, ${body.length} bytes, wall ${wall.toFixed(0)} ms`);
	if (SUBREQUESTS) lines.push(`- through GATE: ${calls} calls, ${gateBytes} bytes read`);
	if (STORE_LOG) lines.push(`- in the gate: ${result.store_gets} store reads, ${result.store_bytes} bytes; ${result.store_lists} lists of ${result.store_listed} keys`);
	if (typeof res.status === 'number' && res.status >= 400) lines.push(`- body: \`${body.slice(0, 200).replace(/\s+/g, ' ')}\``);
	if (typeof res.status !== 'number' || res.status >= 500) failures.push(`GET ${path}: status ${res.status}`);
	if (SUBREQUESTS && calls === 0) failures.push(`GET ${path}: GATE was never called (the viewer did not reach the gate through its binding)`);
	for (const s of sessions) {
		const cpu = await s.tryTo('Profiler.stop');
		const heap = await s.tryTo('HeapProfiler.stopSampling');
		const after = await s.tryTo('Runtime.getHeapUsage');
		lines.push('', `### ${s.name}`, '');
		const b = before[s.name];
		if (!b.error && !after.error) lines.push(`- heap used ${mb(b.usedSize)} → ${mb(after.usedSize)} MB (total ${mb(after.totalSize)} MB)`);
		if (!after.error) result[`${s.name}_heap_after_mb`] = Number(mb(after.usedSize));
		if (cpu.profile) {
			result[`${s.name}_cpu_ms`] = Math.round((cpu.profile.endTime - cpu.profile.startTime) / 1000);
			writeFileSync(join(out, `${name}-${s.name}.cpuprofile`), JSON.stringify(cpu.profile));
			const { totalMs, top } = cpuTop(cpu.profile);
			lines.push(`- CPU profile ${totalMs.toFixed(0)} ms`, '', '| CPU self ms | function |', '|---:|---|');
			for (const [k, ms] of top) lines.push(`| ${ms.toFixed(1)} | \`${k}\` |`);
		} else lines.push(`- CPU profile: ${cpu.error}`);
		if (heap.profile) {
			writeFileSync(join(out, `${name}-${s.name}.heapprofile`), JSON.stringify(heap.profile));
			const { totalBytes, top } = heapTop(heap.profile);
			lines.push('', `- sampled live allocations ${mb(totalBytes)} MB`, '', '| MB | allocated in |', '|---:|---|');
			for (const [k, v] of top.slice(0, 15)) lines.push(`| ${mb(v)} | \`${k}\` |`);
		} else lines.push(`- heap profile: ${heap.error}`);
	}
	lines.push('');
}
if (failures.length) lines.push('## Failed', '', ...failures.map((f) => `- ${f}`), '');
writeFileSync(join(out, 'summary.md'), lines.join('\n') + '\n');
writeFileSync(join(out, 'results.json'), JSON.stringify(results, null, 1) + '\n');
console.log(lines.join('\n'));
for (const s of sessions) s.ws.close();
// An open inspector socket or a kept-alive connection would keep node running: the measurement is done.
process.exit(failures.length ? 1 : 0);
