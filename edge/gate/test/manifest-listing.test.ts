// The epoch listing of a pack (GET /<pack>/manifests) beyond one page of heads: newest first, with a cursor, and
// nothing left out. tests/slip/test_conclusion_addresses_local.py holds the listing and /<pack>/resolve to a store
// the publisher built; this store is written by hand because the publisher would take long to publish 1,002 epochs.
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { mkdir, mkdtemp, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { test } from 'node:test';
import { openLocalGate } from '../src/local.ts';

const PACK = 'many';
const EPOCHS = 1002; // more heads than the store lists at once (1,000)

test('the listing pages past a thousand heads with a cursor and drops no epoch', async (t) => {
	const root = await mkdtemp(join(tmpdir(), 'gate-listing-'));
	t.after(() => rm(root, { recursive: true, force: true }));
	const write = async (key: string, value: unknown) => {
		const path = join(root, key);
		await mkdir(dirname(path), { recursive: true });
		const bytes = JSON.stringify(value);
		await writeFile(path, bytes);
		return createHash('sha256').update(bytes).digest('hex');
	};
	const bundleKey = `${PACK}/bundles/schema-bundle.json`;
	const bundleSha = await write(bundleKey, { pack: { id: PACK }, kinds: [{ id: 'item', class: 'Item', world: 'closed' }], attributes: [], enums: [], questions: [] });
	const rows = [{ key: ['a'] }];
	const rowsSha = createHash('sha256').update(JSON.stringify(rows)).digest('hex');
	await write(`${PACK}/objects/${rowsSha}.json`, rows);
	for (let epoch = 1; epoch <= EPOCHS; epoch++) {
		const sha256 = await write(`${PACK}/manifests/m-${epoch}.json`, {
			id: `m-${epoch}`, epoch, access_semantics: 2, knowledge_time: '2026-01-01T00:00:00Z', definition_sha256: 'a'.repeat(64),
			snapshots: [{ relation: 'item', role: 'reader', complete: false, full: true, format: 'json', uri: `s3://test/${PACK}/objects/${rowsSha}.json`, sha256: rowsSha }],
			compiled: [{ file: 'bundle/schema-bundle.json', uri: `s3://test/${bundleKey}`, sha256: bundleSha }]
		});
		await write(`${PACK}/heads/${(10n ** 19n - 1n - BigInt(epoch)).toString().padStart(19, '0')}.json`,
			{ format: 'rezono.head/1', manifest: `m-${epoch}`, epoch, sha256 });
	}
	const gate = await openLocalGate(root, 'reader');
	const page = async (query: string) => {
		const response = await gate(new Request(`http://rezono.local/${PACK}/manifests${query}`));
		assert.equal(response.status, 200, query);
		return await response.json() as { manifests: { id: string; standing: string }[]; next?: string };
	};
	const first = await page('');
	assert.equal(first.manifests.length, 1000);
	assert.equal(first.manifests[0].id, `m-${EPOCHS}`);
	assert.equal(first.manifests[0].standing, 'current');
	assert.equal(first.next, 'm-3');
	const rest = await page(`?after=${first.next}`);
	assert.deepEqual(rest.manifests.map((m) => m.id), ['m-2', 'm-1']);
	assert.equal(rest.next, undefined);
	assert.ok(rest.manifests.every((m) => m.standing === 'superseded'));
	// A smaller page crosses the store's own page of heads just the same.
	const across = await page('?after=m-4&limit=2');
	assert.deepEqual(across.manifests.map((m) => m.id), ['m-3', 'm-2']);
	assert.equal(across.next, 'm-2');
	for (const bad of ['m-01', 'm-x', '3', 'm-1.0']) {
		const response = await gate(new Request(`http://rezono.local/${PACK}/manifests?after=${bad}`));
		assert.equal(response.status, 400, bad);
	}
});
