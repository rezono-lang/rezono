import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { mkdir, mkdtemp, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { test } from 'node:test';
import { openLocalGate } from '../src/local.ts';
import { rowQueryScope, rowQuestion } from '../src/row-query.ts';
import { StoreLimit } from '../src/store.ts';

const subject = ['area', 'a'];
const neighbor = ['area', 'ab'];
const bundle = {
	pack: { id: 'sample' },
	kinds: [{ id: 'parent', class: 'Parent', world: 'closed' }, { id: 'item', class: 'Item', parent: 'parent' },
		{ id: 'hidden', class: 'Hidden' }],
	attributes: [
		{ id: 'amount', kind: 'parent', name: 'amount', table: 'parent__amount', type: 'integer', currency: 'EUR', required: true },
		{ id: 'note', kind: 'parent', name: 'note', table: 'parent__note', type: 'text' },
		{ id: 'hint', kind: 'item', name: 'hint', table: 'item__hint', type: 'text' },
		{ id: 'signal', kind: 'item', name: 'signal', table: 'item__signal', type: 'text', world: 'open' },
		{ id: 'tags', kind: 'item', name: 'tags', table: 'item__tags', type: 'text', multivalued: true },
		{ id: 'secret', kind: 'item', name: 'secret', table: 'item__secret', type: 'text' }
	].map((slot) => ({ required: false, multivalued: false, ...slot })),
	arrows: [{ id: 'arrow', kind: 'item', name: 'hidden', table: 'item__hidden', target: 'hidden', required: false, multivalued: false }],
	relations: ['capacity', 'unused'].map((id) => ({ id, outcome: 'parent', columns:
		['area', 'identity', 'state', 'reason'].map((name) => ({ name, type: 'symbol' })) }))
};

async function published(root: string) {
	const write = async (path: string, value: unknown) => {
		const file = join(root, path);
		const json = JSON.stringify(value);
		await mkdir(dirname(file), { recursive: true });
		await writeFile(file, json);
		return createHash('sha256').update(json).digest('hex');
	};
	const ref = (path: string, sha256: string) => ({ uri: `s3://test-store/${path}`, sha256 });
	const snapshot = async (role: string, relation: string, tuples: string[][], complete = true) => {
		const rows = tuples.map((key) => ({ key }));
		const sha = createHash('sha256').update(JSON.stringify(rows)).digest('hex');
		const path = 'sample/objects/' + sha + '.json';
		return { role, relation, complete, format: 'json', ...ref(path, await write(path, rows)) };
	};
	const publishedBundle = 'sample/bundles/definition.json';
	const compiled = [{ file: 'bundle/schema-bundle.json', ...ref(publishedBundle, await write(publishedBundle, bundle)) }];
	const publish = async (epoch: number, items: string[][]) => {
		const tags = [[...subject, 'one'], [...subject, 'two'], [...neighbor, 'unrelated']];
		const snapshots = [
			await snapshot('reader', 'item', items, false), await snapshot('other', 'item', [neighbor], false),
			await snapshot('reader', 'parent__amount', [[...subject, '9007199254740993']]),
			await snapshot('reader', 'parent__note', []), await snapshot('reader', 'item__hint', [], false),
			await snapshot('reader', 'item__signal', []), await snapshot('reader', 'item__tags', tags),
			await snapshot('reader', 'capacity', [[...subject, 'unknown', 'pending'], [...subject, 'unknown', 'unverified']]),
			await snapshot('reader', 'unused', [[...neighbor, 'known', '']]),
			await snapshot('reader', 'item__hidden', [[...subject, 'private-target']]),
			await snapshot('other', 'item__secret', [[...neighbor, 'private-value']]),
			await snapshot('reviewer', 'item', [subject]), await snapshot('reviewer', 'item__tags', tags)
		];
		const id = 'm-' + epoch;
		const sha256 = await write(`sample/manifests/${id}.json`, { id, epoch, access_semantics: 2, compiled, snapshots });
		const head = (10n ** 19n - 1n - BigInt(epoch)).toString().padStart(19, '0');
		await write(`sample/heads/${head}.json`, { format: 'rezono.head/1', manifest: id, epoch, sha256 });
	};
	await publish(1, [subject, neighbor]);
	return publish;
}

test('one ordinary row query reads typed values, outcome reasons, and continuations under its fixed role', async (t) => {
	const root = await mkdtemp(join(tmpdir(), 'row-fixture-'));
	t.after(() => rm(root, { recursive: true, force: true }));
	const publish = await published(root);
	const reader = await openLocalGate(root, 'reader');
	const other = await openLocalGate(root, 'other');
	const reviewer = await openLocalGate(root, 'reviewer');
	const query = async (gate = reader, key = subject, options: { continuation?: string; after?: string; manifest?: string } = {}) => {
		const response = await gate(new Request(`http://rezono.local/sample/${options.manifest ?? 'm-1'}/ask`, {
			method: 'POST', headers: { 'x-role': 'other' },
			body: JSON.stringify({ scope: 'row', text: rowQuestion, limit: 3, after: options.after,
				row: { kind: 'Item', key, source_limit: 1, continuation: options.continuation } })
		}));
		return { status: response.status, value: await response.json() };
	};
	const first = await query();
	assert.equal(first.status, 200, JSON.stringify(first.value));
	const second = await query(reader, subject, { after: first.value.next });
	assert.equal(second.status, 200);
	const cells = (answer: typeof first.value) => answer.dataset.rows;
	const [amount, hint, note, signal, tags, capacity] = [...cells(first.value), ...cells(second.value)];
	assert.deepEqual([amount.c1, amount.c3, amount.c4, amount.c5, amount.c6, amount.c8, amount.c9, amount.c11],
		['amount', 'item', '["area","a"]', '["area","a","9007199254740993"]', 'amount', '9007199254740993', 'EUR', '1']);
	assert.deepEqual([hint.c1, hint.c12, hint.c13, hint.c14], ['hint', 'partial', 'unknown', 'not_read_in_full']);
	assert.deepEqual([note.c1, note.c12, note.c13], ['note', 'full', 'not_applicable']);
	assert.deepEqual([signal.c1, signal.c12, signal.c13], ['signal', 'full', 'unknown']);
	assert.deepEqual([tags.c1, tags.c7, tags.c11], ['tags', 'one', '*']);
	assert.deepEqual([capacity.c1, capacity.c13, capacity.c14], ['capacity', 'unknown', 'pending']);
	assert.equal(second.value.next, undefined);
	const tagCursor = tags.c15;
	const outcomeCursor = capacity.c15;
	const continuedTags = (await query(reader, subject, { continuation: tagCursor })).value;
	const continuedOutcome = (await query(reader, subject, { continuation: outcomeCursor })).value;
	assert.deepEqual(cells(continuedTags).map((cell: typeof tags) => [cell.c1, cell.c5, cell.c7]),
		[['tags', '["area","a","two"]', 'two']]);
	assert.deepEqual(cells(continuedOutcome).map((cell: typeof capacity) => [cell.c1, cell.c13, cell.c14]),
		[['capacity', 'unknown', 'unverified']]);
	assert.deepEqual(await query(other, subject), await query(other, ['area', 'absent']));
	assert.equal((await query(reader, ['area'])).status, 404);
	assert.equal((await query(reader, neighbor, { continuation: tagCursor })).status, 400);
	assert.equal((await query(other, neighbor, { continuation: tagCursor })).status, 400);
	assert.equal((await query(reviewer, subject)).status, 200);
	assert.equal((await query(reviewer, subject, { continuation: tagCursor })).status, 400);
	await publish(2, [subject, neighbor, ['area', 'new']]);
	assert.deepEqual(await query(), first);
	assert.deepEqual((await query(reader, subject, { continuation: tagCursor })).value, continuedTags);
	assert.equal((await query(reader, subject, { continuation: tagCursor, manifest: 'm-2' })).status, 400);
	await publish(3, [neighbor]);
	assert.deepEqual(await query(), { status: 404, value: { error: 'not found' } });
});

test('a cut source query does not report an empty or complete projection', async () => {
	const snapshots = [{ relation: 'item', complete: false }];
	await assert.rejects(rowQueryScope(bundle, snapshots, async () => ({ rows: [{ key: subject }] }), 1,
		{ kind: 'Item', key: subject, source_limit: 1 }, { manifest: 'm-1', role: 'reader' }), StoreLimit);
});
