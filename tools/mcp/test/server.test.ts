import assert from 'node:assert/strict';
import { test, type TestContext } from 'node:test';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { InMemoryTransport } from '@modelcontextprotocol/sdk/inMemory.js';
import { compare, run, type Call } from '../src/replay.ts';
import { mcpServer, proposalAccess, type Pin, type SessionInput } from '../src/server.ts';

const PACK = 'example-pack';
const ROLE = 'reader';
const ASK = 'ask Widget where widget.weight > 2 show widget.weight';
const CALLS: Call[] = [
	{ tool: 'ask', args: { pack: PACK, text: ASK } },
	{ tool: 'search', args: { pack: PACK, kind: 'widget', prefix: 'we' } },
	{ tool: 'grounds', args: { pack: PACK, target: ['widget', 'missing'] } },
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
	assert.deepEqual(tools.map(tool => tool.name).sort(), ['ask', 'grounds', 'kinds', 'more', 'reach', 'row', 'schema', 'search', 'sweep']);
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
		':grounds "widget" "missing"', ':more', ':kinds', ':schema ' + JSON.stringify('Widget "A"'),
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
