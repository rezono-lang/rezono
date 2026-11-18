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
