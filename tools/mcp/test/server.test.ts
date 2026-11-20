import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test, type TestContext } from 'node:test';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { InMemoryTransport } from '@modelcontextprotocol/sdk/inMemory.js';
import type { Connection } from '../../repl/src/client.ts';
import { Session, type Answer } from '../../repl/src/session.ts';
import { compare, run, type Call } from '../src/replay.ts';
import { mcpServer, proposalAccess, type Pin, type SessionInput } from '../src/server.ts';

const PACK = 'example-pack';
const ROLE = 'reader';
const ASK = 'ask Widget where widget.weight > 2 show widget.weight';
const CALLS: Call[] = [
	{ tool: 'ask', args: { pack: PACK, text: ASK } },
	{ tool: 'search', args: { pack: PACK, kind: 'widget', prefix: 'we' } },
	{ tool: 'grounds', args: { pack: PACK, target: ['widget', 'missing'] } },
	{ tool: 'gap', args: { pack: PACK, target: ['widget', 'weight-a', null] } },
	{ tool: 'gap', args: { pack: PACK, target: ['widget', 'weight-a', '_'] } },
	{ tool: 'suppose', args: { pack: PACK, proposal: 'prop-1' } },
	{ tool: 'suppose', args: { pack: PACK, variant: 'var-1', impact: true } },
	{ tool: 'more', args: {} },
	{ tool: 'kinds', args: { pack: PACK } },
	{ tool: 'schema', args: { pack: PACK, kind: 'Widget "A"' } },
	{ tool: 'sweep', args: { pack: PACK } },
	{ tool: 'sweep', args: { pack: PACK, name: 'size_scale' } },
	{ tool: 'row', args: { pack: PACK, kind: 'Widget', id: 'weight-a' } },
	{ tool: 'row', args: { pack: PACK, kind: 'Widget', key: ['shop a', 'weight-b'] } },
	{ tool: 'more', args: { cursor: 'row-cursor-token' } },
];

class FixtureSession implements SessionInput {
	pin?: Pin;
	lines: string[] = [];
	role?: string;

	async exec(line: string): Promise<string[]> {
		this.lines.push(line);
		const use = /^:use "([^"]+)" "([^"]+)" as "([^"]+)"$/.exec(line);
		if (use) {
			await Promise.resolve();
			this.pin = { pack: use[1], manifest: use[2] === 'latest' ? 'm-1' : use[2] };
			this.role = use[3];
			return [`using ${this.pin.pack} ${this.pin.manifest} as ${this.role}`];
		}
		if (line === ASK) return [this.pin!.pack, `weight ${this.role === ROLE ? '3' : '5'}`];
		if (line === ':gap "widget" "weight-a" "_"') return ['gap summary'];
		if (line === ':suppose "proposal" "prop-1"') return ['scenario summary'];
		if (line === ':suppose "variant" "var-1" "impact"') return ['impact summary'];
		if (line === ':more') return ['error: no further page'];
		if (line === ':kinds') return ['catalogue kinds'];
		if (line === ':schema ' + JSON.stringify('Widget "A"')) return ['catalogue schema'];
		if (line === ':sweep' || line === ':sweep "size_scale"') return ['published sweep'];
		if (line === ':row "Widget" "weight-a"' || line === ':row "Widget" "shop a" "weight-b"') return ['published row'];
		if (line === ':more "row-cursor-token"') return ['more cells'];
		return ['error: not found (or outside your view)'];
	}

	async search(relation: string, prefix: string): Promise<string[]> {
		this.lines.push(`search ${relation} ${prefix}`);
		return prefix === 'we' ? ['weight-a'] : [];
	}
}

async function connected(t: TestContext, session: SessionInput, options?: Parameters<typeof mcpServer>[2], role = ROLE) {
	const server = mcpServer(session, role, options);
	const client = new Client({ name: 'test', version: '0.1.0' });
	const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
	await server.connect(serverTransport);
	await client.connect(clientTransport);
	t.after(async () => {
		await client.close();
		await server.close();
	});
	return client;
}

test('the local server offers only working read tools', async (t) => {
	const client = await connected(t, new FixtureSession(), { access: { mode: 'store' } });
	const { tools } = await client.listTools();
	assert.deepEqual(
		tools.map(tool => tool.name).sort(),
		['ask', 'gap', 'grounds', 'kinds', 'more', 'reach', 'row', 'schema', 'search', 'suppose', 'sweep'],
	);
	assert.ok(tools.every(tool => tool.annotations?.readOnlyHint === true));
});

test('ask, search, refusals and cursor calls use the same session and replay exactly', async (t) => {
	const session = new FixtureSession();
	const lockedPin = { pack: PACK, manifest: 'm-7' };
	const first = await run(await connected(t, session, { lockedPin }), CALLS);
	assert.deepEqual(first.map(({ text, error }) => [text, error]), [
		['example-pack\nweight 3', false],
		['weight-a', false],
		['error: not found (or outside your view)', true],
		['gap summary', false],
		['gap summary', false],
		['scenario summary', false],
		['impact summary', false],
		['error: no further page', true],
		['catalogue kinds', false],
		['catalogue schema', false],
		['published sweep', false],
		['published sweep', false],
		['published row', false],
		['published row', false],
		['more cells', false],
	]);
	assert.deepEqual(session.lines, [
		':use "example-pack" "m-7" as "reader"', ASK, 'search widget we',
		':grounds "widget" "missing"', ':gap "widget" "weight-a" "_"', ':gap "widget" "weight-a" "_"',
		':suppose "proposal" "prop-1"', ':suppose "variant" "var-1" "impact"',
		':more', ':kinds', ':schema ' + JSON.stringify('Widget "A"'),
		':sweep', ':sweep "size_scale"',
		':row "Widget" "weight-a"', ':row "Widget" "shop a" "weight-b"', ':more "row-cursor-token"',
	]);
	const replayed = await run(await connected(t, new FixtureSession(), { lockedPin }), CALLS);
	assert.deepEqual(compare(first, replayed), []);
	const otherRole = await run(await connected(t, new FixtureSession(), { lockedPin }, 'observer'), CALLS);
	assert.deepEqual(compare(first, otherRole), ['call 1 ask: response differs']);
});

test('two concurrent turns keep their own selected pack', async (t) => {
	const client = await connected(t, new FixtureSession());
	const asks = ['first-pack', 'second-pack'].map(pack => run(client, [{ tool: 'ask', args: { pack, text: ASK } }]));
	const replies = (await Promise.all(asks)).flat();
	assert.deepEqual(replies.map(result => result.text), ['first-pack\nweight 3', 'second-pack\nweight 3']);
});

test('a gate flag alone offers no proposal tool for anonymous or denied identities', async (t) => {
	const seen: string[] = [];
	const anonymous = await proposalAccess(async path => {
		seen.push(path);
		return Response.json({ role: ROLE, rights: ['propose'] });
	}, ROLE, false);
	assert.equal(anonymous, undefined);
	assert.deepEqual(seen, []);
	const denied = await proposalAccess(async path => {
		seen.push(path);
		return Response.json({ role: ROLE, rights: [] });
	}, ROLE, true);
	assert.equal(denied, undefined);
	assert.deepEqual(seen, ['/whoami']);
	for (const proposal of [anonymous, denied]) {
		const client = await connected(t, new FixtureSession(), { access: { mode: 'gate', proposal } });
		assert.ok((await client.listTools()).tools.every(tool => tool.name !== 'propose'));
	}
	for (const refused of [
		Response.json({ role: ROLE, rights: ['propose'] }, { status: 401 }),
		Response.json({ role: 'observer', rights: ['propose'] }),
		Response.json({ role: ROLE, rights: 'propose' }),
	]) {
		assert.equal(await proposalAccess(async () => refused, ROLE, true), undefined);
	}
});

test('a gate authenticates the proposer, checks permission again, and pins the delta', async (t) => {
	const posted: unknown[] = [];
	let permitted = true;
	const proposal = await proposalAccess(async (path, request) => {
		if (path === '/whoami') {
			assert.equal(request?.cache, 'no-store');
			return Response.json({ role: ROLE, rights: permitted ? ['propose'] : [] });
		}
		assert.equal(path, `/${PACK}/proposals`);
		assert.equal(request?.method, 'POST');
		posted.push(JSON.parse(String(request?.body)));
		return Response.json({ state: 'pending' }, { status: 202 });
	}, ROLE, true);
	assert.ok(proposal);
	const client = await connected(t, new FixtureSession(), { access: { mode: 'gate', proposal } });
	const { tools } = await client.listTools();
	assert.equal(tools.find(tool => tool.name === 'propose')?.annotations?.readOnlyHint, false);
	const input = { pack: PACK, kind: 'widget', id: 'weight-a', slot: 'weight', value: '4', title: 'Adjust weight' };
	const response = await client.callTool({ name: 'propose', arguments: input });
	assert.equal(response.isError, undefined);
	assert.deepEqual(posted, [{
		title: 'Adjust weight',
		delta: {
			format: 'rezono.delta/1', pack: PACK, base_manifest: 'm-1',
			changes: [{ op: 'set', kind: 'widget', key: 'weight-a', slot: 'weight', value: '4' }],
		},
	}]);

	permitted = false;
	const error = await client.callTool({ name: 'propose', arguments: input });
	assert.equal(error.isError, true);
	assert.deepEqual(error.content, [{ type: 'text', text: 'error: role reader may not propose' }]);
	const locked = await connected(t, new FixtureSession(), {
		access: { mode: 'gate', proposal }, lockedPin: { pack: PACK, manifest: 'm-1' },
	});
	assert.ok((await locked.listTools()).tools.every(tool => tool.name !== 'propose'));
	await assert.rejects(run(locked, [{ tool: 'propose', args: input } as unknown as Call]));
	assert.equal(posted.length, 1);
});

test('replay distinguishes a changed refusal, request, and call count', () => {
	const [call] = CALLS;
	const before = { ...call, error: true, text: 'error: not found (or outside your view)' };
	assert.deepEqual(compare([before], []), ['0 calls replayed, 1 recorded']);
	assert.deepEqual(compare([before], [{ ...before, args: {} }]), ['call 1 ask: request differs']);
	assert.deepEqual(compare([before], [{ ...before, error: false }]), ['call 1 ask: response differs']);
});

test('tools return structured JSON alongside text for answers, gap, suppose, search, propose and errors', async (t) => {
	const bundle = 'a'.repeat(64);
	const manifest = { id: 'm-1', epoch: 1, compiled: [{ file: 'bundle/schema-bundle.json', sha256: bundle }] };
	const askAnswer: Answer = {
		format: 'rezono.answer/1',
		question: 'ask',
		manifest_id: 'm-1',
		nodes: [{ relation: 'widget', key: '["weight-a"]', distance: 0 }],
		dataset: { rows: [{ $kind: 'Answer', $id: 'weight-a', c1: '3' }] },
		counts: { rows: 1, undecided: 0, not_applicable: 0 },
	};
	const gapAnswer: Answer = {
		format: 'rezono.answer/1',
		question: 'gap',
		manifest_id: 'm-1',
		nodes: [],
		gap: {
			premises: [{ distance: 0, rule: 'eligible', item: 0, kind: 'positive', relation: 'widget', bindings: [] }],
			candidates: [],
			cut: false,
		},
	};
	const scenarioAnswer: Answer = {
		format: 'rezono.answer/1',
		question: 'scenario',
		manifest_id: 'm-1',
		nodes: [],
		difference: {
			counts: [{ relation: 'eligible', added: 1, removed: 0, changed: 0 }],
			entries: [{ change: 'added', relation: 'eligible', key: '["weight-a"]' }],
		},
	};
	const impactAnswer: Answer = {
		format: 'rezono.answer/1',
		question: 'impact',
		manifest_id: 'm-1',
		nodes: [{ relation: 'eligible', key: '["weight-a"]', distance: 0 }],
		difference: {
			counts: [{ relation: 'eligible', added: 1, removed: 0, changed: 0 }],
		},
	};
	const seen: string[] = [];
	const connection: Connection = {
		async open(opened) {
			assert.equal(opened, ROLE);
			return async (path) => {
				seen.push(path);
				if (path === `/${PACK}/head`) return Response.json(manifest);
				const { pathname, searchParams } = new URL(path, 'http://rezono.local');
				if (pathname === `/${PACK}/m-1/ask`) return Response.json(askAnswer);
				if (pathname === `/${PACK}/m-1/ask/gap`) {
					assert.equal(searchParams.get('relation'), 'eligible');
					assert.equal(searchParams.get('key'), '["weight-a",null]');
					return Response.json(gapAnswer);
				}
				if (pathname === `/${PACK}/m-1/ask/scenario`) {
					assert.equal(searchParams.get('proposal'), 'prop-1');
					return Response.json(scenarioAnswer);
				}
				if (pathname === `/${PACK}/m-1/ask/impact`) {
					assert.equal(searchParams.get('variant'), 'var-1');
					return Response.json(impactAnswer);
				}
				if (pathname === `/${PACK}/m-1/rows/widget`) {
					return Response.json({ rows: [{ key: ['weight-a'] }] });
				}
				return new Response(null, { status: 404 });
			};
		},
	};
	const proposal = await proposalAccess(async (path) => {
		if (path === '/whoami') return Response.json({ role: ROLE, rights: ['propose'] });
		return Response.json({ state: 'pending', id: 'prop-2' }, { status: 202 });
	}, ROLE, true);
	const client = await connected(t, new Session(connection, ROLE), { access: { mode: 'gate', proposal } });

	const asked = await client.callTool({ name: 'ask', arguments: { pack: PACK, text: ASK } });
	assert.equal(asked.isError, undefined);
	assert.equal((asked.content as { type: string; text: string }[])[0].type, 'text');
	assert.deepEqual(asked.structuredContent, {
		tool: 'ask',
		ok: true,
		role: ROLE,
		pack: PACK,
		manifest: 'm-1',
		lines: (asked.content as { text: string }[])[0].text.split('\n'),
		answer: askAnswer,
	});

	const gapped = await client.callTool({ name: 'gap', arguments: { pack: PACK, target: ['eligible', 'weight-a', null] } });
	assert.equal(gapped.isError, undefined);
	assert.deepEqual((gapped.structuredContent as { answer?: unknown }).answer, gapAnswer);
	assert.equal((gapped.structuredContent as { tool: string; ok: boolean }).tool, 'gap');
	assert.equal((gapped.structuredContent as { ok: boolean }).ok, true);

	const supposed = await client.callTool({ name: 'suppose', arguments: { pack: PACK, proposal: 'prop-1' } });
	assert.equal(supposed.isError, undefined);
	assert.deepEqual((supposed.structuredContent as { answer?: unknown }).answer, scenarioAnswer);

	const impacted = await client.callTool({ name: 'suppose', arguments: { pack: PACK, variant: 'var-1', impact: true } });
	assert.equal(impacted.isError, undefined);
	assert.deepEqual((impacted.structuredContent as { answer?: unknown }).answer, impactAnswer);

	const searched = await client.callTool({ name: 'search', arguments: { pack: PACK, kind: 'widget', prefix: 'we' } });
	assert.equal(searched.isError, undefined);
	assert.deepEqual(searched.structuredContent, {
		tool: 'search',
		ok: true,
		role: ROLE,
		pack: PACK,
		manifest: 'm-1',
		lines: ['weight-a'],
		matches: ['weight-a'],
	});

	const proposed = await client.callTool({
		name: 'propose',
		arguments: { pack: PACK, kind: 'widget', id: 'weight-a', slot: 'weight', value: '4', title: 'Adjust weight' },
	});
	assert.equal(proposed.isError, undefined);
	assert.deepEqual(proposed.structuredContent, {
		tool: 'propose',
		ok: true,
		role: ROLE,
		pack: PACK,
		manifest: 'm-1',
		lines: [JSON.stringify({ state: 'pending', id: 'prop-2' })],
		status: 202,
		delta: {
			format: 'rezono.delta/1',
			pack: PACK,
			base_manifest: 'm-1',
			changes: [{ op: 'set', kind: 'widget', key: 'weight-a', slot: 'weight', value: '4' }],
		},
		response: { state: 'pending', id: 'prop-2' },
	});

	const badSuppose = await client.callTool({ name: 'suppose', arguments: { pack: PACK } });
	assert.equal(badSuppose.isError, true);
	assert.deepEqual(badSuppose.structuredContent, {
		tool: 'suppose',
		ok: false,
		role: ROLE,
		pack: PACK,
		manifest: 'm-1',
		error: 'supply either proposal or variant',
		lines: ['error: supply either proposal or variant'],
	});

	const bothSuppose = await client.callTool({ name: 'suppose', arguments: { pack: PACK, proposal: 'p', variant: 'v' } });
	assert.equal(bothSuppose.isError, true);
	assert.equal((bothSuppose.structuredContent as { ok: boolean }).ok, false);

	const badGap = await client.callTool({ name: 'gap', arguments: { pack: PACK, target: [null, 'weight-a'] } });
	assert.equal(badGap.isError, true);
	assert.deepEqual(badGap.structuredContent, {
		tool: 'gap',
		ok: false,
		role: ROLE,
		pack: PACK,
		manifest: 'm-1',
		error: 'supply a relation name first',
		lines: ['error: supply a relation name first'],
	});

	const missing = await client.callTool({ name: 'grounds', arguments: { pack: PACK, target: ['widget', 'missing'] } });
	assert.equal(missing.isError, true);
	assert.equal((missing.structuredContent as { answer?: unknown }).answer, undefined);
	assert.equal((missing.structuredContent as { ok: boolean }).ok, false);
	assert.equal((missing.structuredContent as { error: string }).error, 'not found (or outside your view)');
	assert.ok(seen.some(path => path.startsWith(`/${PACK}/m-1/ask/gap?`)));
	assert.ok(seen.some(path => path.startsWith(`/${PACK}/m-1/ask/scenario?`)));
	assert.ok(seen.some(path => path.startsWith(`/${PACK}/m-1/ask/impact?`)));
});

test('README documents the exact dependency versions pinned in package.json and package-lock.json', () => {
	const readme = readFileSync(new URL('../README.md', import.meta.url), 'utf8');
	const pkg = JSON.parse(readFileSync(new URL('../package.json', import.meta.url), 'utf8')) as {
		dependencies: Record<string, string>;
	};
	const lock = JSON.parse(readFileSync(new URL('../package-lock.json', import.meta.url), 'utf8')) as {
		packages: Record<string, { version?: string }>;
	};
	const sdkVersion = pkg.dependencies['@modelcontextprotocol/sdk'];
	const zodVersion = pkg.dependencies.zod;
	const joseVersion = lock.packages['node_modules/jose']?.version;
	assert.ok(sdkVersion && zodVersion && joseVersion);
	assert.match(readme, new RegExp(`MCP SDK ${sdkVersion.replaceAll('.', '\\.')}\\b`));
	assert.match(readme, new RegExp(`Zod ${zodVersion.replaceAll('.', '\\.')}\\b`));
	assert.match(readme, new RegExp(`Jose ${joseVersion.replaceAll('.', '\\.')}\\b`));
});
