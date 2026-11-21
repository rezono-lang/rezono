import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { mkdir, mkdtemp, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { test } from 'node:test';
import { openLocalGate } from '../src/local.ts';

const origin = 'http://rezono.local/sample';
const HEAD = 'sample/heads/9999999999999999998.json';
const mainKey = 'sample/manifests/m-1.json';
const digest = (bytes: string) => createHash('sha256').update(bytes).digest('hex');

test('reads only SHA-pinned sweep statuses and keeps masked and absent answers uniform', async (t) => {
	const root = await mkdtemp(join(tmpdir(), 'gate-sweep-fixture-'));
	t.after(() => rm(root, { recursive: true, force: true }));
	const write = async (key: string, bytes: string) => {
		const file = join(root, key);
		await mkdir(dirname(file), { recursive: true });
		await writeFile(file, bytes);
		return { uri: 's3://bucket/' + key, sha256: digest(bytes) };
	};
	const object = async (data: unknown) => {
		const bytes = JSON.stringify(data);
		return write('sample/objects/' + digest(bytes) + '.json', bytes);
	};
	const rows = async (role: string, id: string, full: boolean) => Promise.all([
		{ relation: 'item', role, complete: full, full, format: 'json', ...await object([{ key: [id] }]) },
		{ relation: 'item__size', role, complete: full, full, format: 'json', ...await object([{ key: [id, '1'] }]) }
	]);
	const snapshots = [...await rows('checker', 'one', true), ...await rows('partial', 'one', false),
		...await rows('other', 'two', false)];
	const bundle = { pack: { id: 'sample' }, kinds: [{ id: 'item', class: 'Item' }], attributes: [{
		id: 'item.size', kind: 'item', name: 'size', table: 'item__size', type: 'integer'
	}], questions: [{ term: 'sweep', start: 'sweep', steps: [{ suppose: { over: 'sweep' } }], answer: 'series', limit: 64 }] };
	const bundleRef = await write('sample/bundles/definition.json', JSON.stringify(bundle));
	const gridKey = 'sample/bundles/grid.json';
	const gridBytes = '{"format":"rezono.sweeps/1","sweeps":[{"name":"sizes","kind":"item","key":"one","slot":"size",'
		+ '"min":9007199254740993,"max":9007199254740996,"step":1,"count":4}]}';
	const gridRef = await write(gridKey, gridBytes);
	const main = { id: 'm-1', epoch: 1, access_semantics: 2, snapshots,
		compiled: [{ file: 'bundle/schema-bundle.json', ...bundleRef }, { file: 'ir/sweeps.json', ...gridRef }] };
	const { sha256 } = await write(mainKey, JSON.stringify(main));
	await write(HEAD, JSON.stringify({ format: 'rezono.head/1', manifest: 'm-1', epoch: 1, sha256 }));

	const publish = async (index: number, role: string, base: string, validHash = true) => {
		const id = 'v-sizes-' + String(index).padStart(2, '0') + '-2';
		const value = (9007199254740993n + BigInt(index)).toString();
		const body = { ...main, id, epoch: 2, base_manifest: base, variant: {
			sweep: 'sizes', index, value, readers: [role], status_readers: [role]
		}, checks: [{ name: 'shaped', status: 'green' }] };
		const variant = await write('sample/manifests/' + id + '.json', JSON.stringify(body));
		await write('sample/epochs/2/manifests/' + id + '.json', JSON.stringify({
			format: 'rezono.pointer/1', id, sha256: validHash ? variant.sha256 : '0'.repeat(64)
		}));
	};
	await publish(0, 'checker', 'm-1');
	await publish(1, 'checker', 'm-1', false);
	await publish(3, 'other', 'm-1');
	// A sidecar without a manifest digest cannot supply counts to this reader.
	await write('sample/v-sizes-00-2/checker/explain/index.json', '{"counts":{"item":{"changed":42}}}');

	const caller = async (role: string) => {
		const gate = await openLocalGate(root, role);
		return async (url: string) => {
			const result = await gate(new Request(origin + url));
			return { status: result.status, body: await result.json() };
		};
	};
	const check = await caller('checker'), partial = await caller('partial'), other = await caller('other');
	const question = '/m-1/ask/sweep?sweep=sizes';
	const answer = await check(question);
	assert.equal(answer.status, 200);
	assert.deepEqual(answer.body.series, [
		{ index: 0, value: '9007199254740993', status: 'green', manifest: 'v-sizes-00-2' },
		{ index: 1, value: '9007199254740994', status: 'not_computed' },
		{ index: 2, value: '9007199254740995', status: 'not_computed' },
		{ index: 3, value: '9007199254740996', status: 'not_computed' }
	]);
	const bound = await check('/sweeps?m=m-1');
	assert.equal(bound.status, 200);
	assert.deepEqual(bound.body.sweeps[0].cell, { kind: 'item', id: 'one', slot: 'size' });

	const mask = await partial(question);
	assert.equal(mask.status, 200);
	assert.deepEqual(mask.body.series, answer.body.series.map(({ index, value }: {index: number; value: string}) =>
		({ index, value, status: 'unavailable' })));
	assert.deepEqual(await other(question), await other('/m-1/ask/sweep?sweep=missing'));
	assert.deepEqual(await other('/sweeps?m=m-1'), await check('/sweeps?m=m-0'));

	// A well-formed, SHA-pinned object from another main is also unavailable.
	await publish(2, 'checker', 'm-0');
	assert.deepEqual(await check(question), answer);
	assert.deepEqual(await partial(question), mask);
	await write(gridKey, gridBytes + ' ');
	assert.deepEqual(await check('/sweeps?m=m-1'), await other('/sweeps?m=m-1'));
	assert.equal((await check(question)).status, 404);
});

test('start-sweep fails closed to unknown on ambiguous row pairing while preserving absent stops', async (t) => {
	const root = await mkdtemp(join(tmpdir(), 'gate-sweep-ambiguous-'));
	t.after(() => rm(root, { recursive: true, force: true }));
	const write = async (key: string, bytes: string) => {
		const file = join(root, key);
		await mkdir(dirname(file), { recursive: true });
		await writeFile(file, bytes);
		return { uri: 's3://bucket/' + key, sha256: digest(bytes) };
	};
	const object = async (data: unknown) => {
		const bytes = JSON.stringify(data);
		return write('sample/objects/' + digest(bytes) + '.json', bytes);
	};
	const makeSnaps = async (flaggedRows: string[][], taggedRows: string[][]) => Promise.all([
		{ relation: 'item', role: 'checker', complete: true, full: true, format: 'json', ...await object([{ key: ['one'] }]) },
		{ relation: 'item__size', role: 'checker', complete: true, full: true, format: 'json', ...await object([{ key: ['one', '1'] }]) },
		{ relation: 'flagged', role: 'checker', complete: true, full: true, format: 'json', ...await object(flaggedRows.map((key) => ({ key }))) },
		{ relation: 'tagged', role: 'checker', complete: true, full: true, format: 'json', ...await object(taggedRows.map((key) => ({ key }))) }
	]);

	const bundle = {
		pack: { id: 'sample' },
		kinds: [{ id: 'item', class: 'Item' }],
		attributes: [{ id: 'item.size', kind: 'item', name: 'size', table: 'item__size', type: 'integer' }],
		relations: [
			{ id: 'flagged', module: 'm', explain: 'materialize', columns: [{ name: 'i', type: 'string' }, { name: 'a', type: 'integer' }] },
			{ id: 'tagged', module: 'm', explain: 'materialize', columns: [{ name: 'i', type: 'string' }, { name: 't', type: 'string' }] }
		],
		questions: [{ term: 'sweep', start: 'sweep', steps: [{ suppose: { over: 'sweep' } }], answer: 'series', limit: 64 }]
	};
	const bundleRef = await write('sample/bundles/definition.json', JSON.stringify(bundle));
	const gridRef = await write('sample/bundles/grid.json', JSON.stringify({
		format: 'rezono.sweeps/1',
		sweeps: [{ name: 'sizes', kind: 'item', key: 'one', slot: 'size', min: 0, max: 5, step: 1, count: 6 }]
	}));
	const main = {
		id: 'm-1',
		epoch: 1,
		access_semantics: 2,
		snapshots: await makeSnaps([['one', '10']], [['one', 'alpha'], ['one', 'beta']]),
		compiled: [{ file: 'bundle/schema-bundle.json', ...bundleRef }, { file: 'ir/sweeps.json', ...gridRef }]
	};
	const { sha256 } = await write(mainKey, JSON.stringify(main));
	await write(HEAD, JSON.stringify({ format: 'rezono.head/1', manifest: 'm-1', epoch: 1, sha256 }));

	const stopData: Array<{ flagged: string[][]; tagged: string[][] }> = [
		{ flagged: [], tagged: [] },
		{ flagged: [], tagged: [] },
		{ flagged: [['one', '20']], tagged: [['one', 'gamma']] },
		{ flagged: [['one', '30'], ['one', '35']], tagged: [['one', 'delta']] },
		{ flagged: [['one', '40'], ['one', '45']], tagged: [['one', 'alpha'], ['one', 'delta']] },
		{ flagged: [['one', '50']], tagged: [['one', 'alpha']] }
	];
	const variantShas: string[] = [];
	for (let i = 0; i < stopData.length; i++) {
		const id = 'v-sizes-' + String(i).padStart(2, '0') + '-2';
		const body = {
			...main,
			id,
			epoch: 2,
			base_manifest: 'm-1',
			snapshots: await makeSnaps(stopData[i].flagged, stopData[i].tagged),
			variant: { sweep: 'sizes', index: i, value: String(i), readers: ['checker'], status_readers: ['checker'] },
			checks: [{ name: 'shaped', status: 'green' }]
		};
		const variant = await write('sample/manifests/' + id + '.json', JSON.stringify(body));
		variantShas.push(variant.sha256);
		await write('sample/epochs/2/manifests/' + id + '.json', JSON.stringify({
			format: 'rezono.pointer/1', id, sha256: variant.sha256
		}));
	}

	const writeTurns = async (afterIndex: number, turns: Array<{ relation: string; key: string; causes: string[] }>) => {
		const beforeId = 'v-sizes-' + String(afterIndex - 1).padStart(2, '0') + '-2';
		const afterId = 'v-sizes-' + String(afterIndex).padStart(2, '0') + '-2';
		await write('sample/' + afterId + '/checker/turns.json', JSON.stringify({
			format: 'rezono.turns/1',
			pack: 'sample',
			role: 'checker',
			sweep: 'sizes',
			base_manifest: 'm-1',
			before: { index: afterIndex - 1, manifest: beforeId, sha256: variantShas[afterIndex - 1] },
			after: { index: afterIndex, manifest: afterId, sha256: variantShas[afterIndex] },
			turns
		}));
	};
	await writeTurns(1, []);
	await writeTurns(2, [
		{ relation: 'flagged', key: '["one","20"]', causes: ['presence'] },
		{ relation: 'tagged', key: '["one","gamma"]', causes: ['presence'] }
	]);
	await writeTurns(3, []);
	await writeTurns(4, []);
	await writeTurns(5, []);

	const gate = await openLocalGate(root, 'checker');
	const ask = async (relation: string, key: string[]) => {
		const url = origin + '/m-1/ask/sweep?sweep=sizes&relation=' + encodeURIComponent(relation)
			+ '&key=' + encodeURIComponent(JSON.stringify(key));
		const res = await gate(new Request(url));
		assert.equal(res.status, 200);
		return await res.json();
	};

	const flagged = await ask('flagged', ['one', '10']);
	assert.deepEqual(
		flagged.series.map((c: { index: number; turn?: string; causes?: string[]; row?: { key: string } }) => ({
			index: c.index, turn: c.turn, causes: c.causes, row: c.row?.key
		})),
		[
			{ index: 0, turn: undefined, causes: undefined, row: undefined },
			{ index: 1, turn: 'same', causes: undefined, row: undefined },
			{ index: 2, turn: 'turns', causes: ['presence'], row: '["one","20"]' },
			{ index: 3, turn: 'unknown', causes: undefined, row: undefined },
			{ index: 4, turn: 'unknown', causes: undefined, row: undefined },
			{ index: 5, turn: 'unknown', causes: undefined, row: '["one","50"]' }
		]
	);

	const tagged = await ask('tagged', ['one', 'alpha']);
	assert.deepEqual(
		tagged.series.map((c: { index: number; turn?: string; causes?: string[]; row?: { key: string } }) => ({
			index: c.index, turn: c.turn, causes: c.causes, row: c.row?.key
		})),
		[
			{ index: 0, turn: undefined, causes: undefined, row: undefined },
			{ index: 1, turn: 'same', causes: undefined, row: undefined },
			{ index: 2, turn: 'unknown', causes: undefined, row: undefined },
			{ index: 3, turn: 'unknown', causes: undefined, row: undefined },
			{ index: 4, turn: 'unknown', causes: undefined, row: '["one","alpha"]' },
			{ index: 5, turn: 'same', causes: undefined, row: '["one","alpha"]' }
		]
	);
});

test('start-sweep pairs rezono.rules/2 functional relations by domain key and fails closed on duplicates', async (t) => {
	const root = await mkdtemp(join(tmpdir(), 'gate-sweep-functional-'));
	t.after(() => rm(root, { recursive: true, force: true }));
	const write = async (key: string, bytes: string) => {
		const file = join(root, key);
		await mkdir(dirname(file), { recursive: true });
		await writeFile(file, bytes);
		return { uri: 's3://bucket/' + key, sha256: digest(bytes) };
	};
	const object = async (data: unknown) => {
		const bytes = JSON.stringify(data);
		return write('sample/objects/' + digest(bytes) + '.json', bytes);
	};
	const makeSnaps = async (scoreRows: string[][], pairRows: string[][]) => Promise.all([
		{ relation: 'item', role: 'checker', complete: true, full: true, format: 'json', ...await object([{ key: ['one'] }]) },
		{ relation: 'item__size', role: 'checker', complete: true, full: true, format: 'json', ...await object([{ key: ['one', '1'] }]) },
		{ relation: 'score', role: 'checker', complete: true, full: true, format: 'json', ...await object(scoreRows.map((key) => ({ key }))) },
		{ relation: 'pair_score', role: 'checker', complete: true, full: true, format: 'json', ...await object(pairRows.map((key) => ({ key }))) }
	]);

	const bundle = {
		pack: { id: 'sample' },
		kinds: [{ id: 'item', class: 'Item' }],
		attributes: [{ id: 'item.size', kind: 'item', name: 'size', table: 'item__size', type: 'integer' }],
		questions: [{ term: 'sweep', start: 'sweep', steps: [{ suppose: { over: 'sweep' } }], answer: 'series', limit: 64 }]
	};
	const rulesIr = {
		format: 'rezono.rules/2',
		pack: 'sample',
		relations: [
			{ name: 'item', role: 'base', key: [{ name: 'id', type: 'string' }] },
			{
				name: 'score',
				role: 'functional',
				key: [{ name: 'id', type: 'string' }],
				domain: 'item',
				value: { name: 'amount', type: 'integer' },
				conflict_policy: 'publish'
			},
			{
				name: 'pair_score',
				role: 'functional',
				key: [{ name: 'org', type: 'string' }, { name: 'id', type: 'string' }],
				domain: 'item',
				value: { name: 'amount', type: 'integer' },
				conflict_policy: 'publish'
			}
		],
		rules: []
	};
	const bundleRef = await write('sample/bundles/definition.json', JSON.stringify(bundle));
	const rulesRef = await write('sample/bundles/rules.json', JSON.stringify(rulesIr));
	const gridRef = await write('sample/bundles/grid.json', JSON.stringify({
		format: 'rezono.sweeps/1',
		sweeps: [{ name: 'sizes', kind: 'item', key: 'one', slot: 'size', min: 0, max: 4, step: 1, count: 5 }]
	}));
	const main = {
		id: 'm-1',
		epoch: 1,
		access_semantics: 2,
		snapshots: await makeSnaps(
			[['one', 'known', '', '10']],
			[['org-1', 'one', 'known', '', '10'], ['org-1', 'two', 'known', '', '20']]
		),
		compiled: [
			{ file: 'bundle/schema-bundle.json', ...bundleRef },
			{ file: 'ir/rules.json', ...rulesRef },
			{ file: 'ir/sweeps.json', ...gridRef }
		]
	};
	const { sha256 } = await write(mainKey, JSON.stringify(main));
	await write(HEAD, JSON.stringify({ format: 'rezono.head/1', manifest: 'm-1', epoch: 1, sha256 }));

	const stopData: Array<{ score: string[][]; pair: string[][] }> = [
		{
			score: [['one', 'known', '', '12']],
			pair: [['org-1', 'one', 'unknown', 'missing_input', ''], ['org-1', 'two', 'known', '', '20']]
		},
		{
			score: [['one', 'unknown', 'missing_input', '']],
			pair: [['org-1', 'one', 'invalid', 'conflict', ''], ['org-1', 'two', 'known', '', '20']]
		},
		{
			score: [['one', 'invalid', 'conflict', '']],
			pair: [['org-1', 'one', 'known', '', '30'], ['org-1', 'two', 'known', '', '20']]
		},
		{
			score: [['one', 'known', '', '15'], ['one', 'unknown', 'r', '']],
			pair: [['org-1', 'one', 'known', '', '35'], ['org-1', 'two', 'known', '', '20']]
		},
		{
			score: [['one', 'known', '', '10'], ['one', 'unknown', 'r', '']],
			pair: [['org-1', 'two', 'known', '', '20']]
		}
	];
	const variantShas: string[] = [];
	for (let i = 0; i < stopData.length; i++) {
		const id = 'v-sizes-' + String(i).padStart(2, '0') + '-2';
		const body = {
			...main,
			id,
			epoch: 2,
			base_manifest: 'm-1',
			snapshots: await makeSnaps(stopData[i].score, stopData[i].pair),
			variant: { sweep: 'sizes', index: i, value: String(i), readers: ['checker'], status_readers: ['checker'] },
			checks: [{ name: 'shaped', status: 'green' }]
		};
		const variant = await write('sample/manifests/' + id + '.json', JSON.stringify(body));
		variantShas.push(variant.sha256);
		await write('sample/epochs/2/manifests/' + id + '.json', JSON.stringify({
			format: 'rezono.pointer/1', id, sha256: variant.sha256
		}));
	}

	const writeTurns = async (afterIndex: number, turns: Array<{ relation: string; key: string; causes: string[] }>) => {
		const beforeId = 'v-sizes-' + String(afterIndex - 1).padStart(2, '0') + '-2';
		const afterId = 'v-sizes-' + String(afterIndex).padStart(2, '0') + '-2';
		await write('sample/' + afterId + '/checker/turns.json', JSON.stringify({
			format: 'rezono.turns/1',
			pack: 'sample',
			role: 'checker',
			sweep: 'sizes',
			base_manifest: 'm-1',
			before: { index: afterIndex - 1, manifest: beforeId, sha256: variantShas[afterIndex - 1] },
			after: { index: afterIndex, manifest: afterId, sha256: variantShas[afterIndex] },
			turns
		}));
	};
	await writeTurns(1, [
		{ relation: 'pair_score', key: '["org-1","one","invalid","conflict",""]', causes: ['state'] },
		{ relation: 'score', key: '["one","unknown","missing_input",""]', causes: ['state'] }
	]);
	await writeTurns(2, [
		{ relation: 'pair_score', key: '["org-1","one","known","","30"]', causes: ['state'] },
		{ relation: 'score', key: '["one","invalid","conflict",""]', causes: ['state'] }
	]);
	await writeTurns(3, []);
	await writeTurns(4, [
		{ relation: 'pair_score', key: '["org-1","one","known","","35"]', causes: ['presence'] }
	]);

	const gate = await openLocalGate(root, 'checker');
	const ask = async (relation: string, key: string[]) => {
		const url = origin + '/m-1/ask/sweep?sweep=sizes&relation=' + encodeURIComponent(relation)
			+ '&key=' + encodeURIComponent(JSON.stringify(key));
		const res = await gate(new Request(url));
		assert.equal(res.status, 200);
		return await res.json();
	};

	const score = await ask('score', ['one', 'known', '', '10']);
	assert.deepEqual(
		score.series.map((c: { index: number; turn?: string; causes?: string[]; row?: { key: string } }) => ({
			index: c.index, turn: c.turn, causes: c.causes, row: c.row?.key
		})),
		[
			{ index: 0, turn: undefined, causes: undefined, row: '["one","known","","12"]' },
			{ index: 1, turn: 'turns', causes: ['state'], row: '["one","unknown","missing_input",""]' },
			{ index: 2, turn: 'turns', causes: ['state'], row: '["one","invalid","conflict",""]' },
			{ index: 3, turn: 'unknown', causes: undefined, row: undefined },
			{ index: 4, turn: 'unknown', causes: undefined, row: undefined }
		]
	);

	const pair = await ask('pair_score', ['org-1', 'one', 'known', '', '10']);
	assert.deepEqual(
		pair.series.map((c: { index: number; turn?: string; causes?: string[]; row?: { key: string } }) => ({
			index: c.index, turn: c.turn, causes: c.causes, row: c.row?.key
		})),
		[
			{ index: 0, turn: undefined, causes: undefined, row: '["org-1","one","unknown","missing_input",""]' },
			{ index: 1, turn: 'turns', causes: ['state'], row: '["org-1","one","invalid","conflict",""]' },
			{ index: 2, turn: 'turns', causes: ['state'], row: '["org-1","one","known","","30"]' },
			{ index: 3, turn: 'same', causes: undefined, row: '["org-1","one","known","","35"]' },
			{ index: 4, turn: 'turns', causes: ['presence'], row: undefined }
		]
	);
});
