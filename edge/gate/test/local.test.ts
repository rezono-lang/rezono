import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { mkdir, mkdtemp, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { test } from 'node:test';
import { catalogueKindsQuestion, catalogueSchemaQuestion } from '../src/catalogue-questions.ts';
import { openLocalGate } from '../src/local.ts';

const pack = 'sample';
const schema = {
	pack: { id: pack, base: 'https://example.org/sample/' },
	kinds: [{ id: 'item', class: 'Item', world: 'closed' },
		{ id: 'unseen', class: 'Unseen', parent: 'item' }],
	attributes: [{ id: 'item__label', kind: 'item', name: 'label', table: 'item__label', type: 'text', required: false },
		{ id: 'unseen__code', kind: 'unseen', name: 'code', table: 'unseen__code', type: 'enum', enum: 'internal' }],
	enums: [{ id: 'internal', values: ['internal.sample'] }],
	questions: [{ term: 'reach', start: 'present', steps: [{ trace: { direction: 'forward', depth: '3' } }],
		answer: 'rings', limit: 10 }]
};

async function fixture() {
	const root = await mkdtemp(join(tmpdir(), 'gate-fixture-'));
	const write = async (key: string, value: unknown) => {
		const path = join(root, key);
		await mkdir(dirname(path), { recursive: true });
		const bytes = JSON.stringify(value);
		await writeFile(path, bytes);
		return createHash('sha256').update(bytes).digest('hex');
	};
	const object = async (data: unknown) => {
		const sha256 = createHash('sha256').update(JSON.stringify(data)).digest('hex');
		const key = pack + '/objects/' + sha256 + '.json';
		await write(key, data);
		return { uri: 's3://test-store/' + key, sha256 };
	};
	const role = async (role: string, inputs: string[][]) => [
		{ relation: 'item', role, complete: false, full: false, format: 'json',
			...await object(inputs.map(([id]) => ({ key: [id] }))) },
		{ relation: 'item__label', role, complete: false, full: false, format: 'json',
			...await object(inputs.filter(([, label]) => label).map(([id, label]) => ({ key: [id, label] }))) }
	];
	const reader = await role('reader', [['a', 'visible'], ['ab', 'visible'], ['unset']]);
	const other = await role('other', [['ax', 'private']]);
	other.push({ relation: 'unseen', role: 'other', complete: false, full: false, format: 'json',
		...await object([{ key: ['unlisted'] }]) });
	const witness = await object({ witnesses: [], hidden: [] });
	const sources = await object([{row: {relation: 'item', key: '["a"]'},
		sources: [{kind: 'file', name: 'fixture', position: 'a'}]}]);
	const bundleKey = pack + '/bundles/definition.json';
	const manifest = {
		id: 'm-1', epoch: 1, access_semantics: 2, knowledge_time: '2026-01-01T00:00:00Z',
		pack_sha256: 'private-data-hash', snapshots: [...reader, ...other], witnesses: [{ role: 'reader', ...witness }],
		fact_sources: [{ role: 'reader', ...sources }],
		compiled: [{ file: 'bundle/schema-bundle.json', uri: 's3://test-store/' + bundleKey,
			sha256: await write(bundleKey, schema) }]
	};
	const manifestKey = pack + '/manifests/m-1.json';
	await write(pack + '/heads/9999999999999999998.json', {
		format: 'rezono.head/1', manifest: 'm-1', epoch: 1, sha256: await write(manifestKey, manifest)
	});
	return { root, write, object, manifestKey, manifest };
}

const route = '/sample/m-1';
const request = (path: string, body?: unknown) => new Request('http://rezono.local' + path, {
	headers: { 'x-role': 'other' },
	...(body === undefined ? {} : { method: 'POST', body: JSON.stringify(body) })
});

test('fixed local role scopes metadata, snapshots, pagination and absence', async (t) => {
	const { root } = await fixture();
	t.after(() => rm(root, { recursive: true, force: true }));
	const reader = await openLocalGate(root, 'reader');
	const other = await openLocalGate(root, 'other');
	assert.deepEqual(await (await reader(request('/packs'))).json(), ['sample']);
	const head = await (await reader(request('/sample/head?role=other'))).text();
	assert.ok(head.includes('"role":"reader"'));
	assert.ok(!/other|private-data-hash|s3:/.test(head));

	const catalogue = await (await reader(request('/sample/bundle?m=m-1'))).json();
	assert.deepEqual(catalogue.kinds, [{ id: 'item', class: 'Item', world: 'open' }]);
	assert.deepEqual(catalogue.enums, []);
	assert.ok(!JSON.stringify(catalogue).includes('unseen'));
	assert.ok(!Object.hasOwn(catalogue, 'questions'));

	const start = await (await reader(request(route + '/rows/item?starts=a&limit=1'))).json();
	assert.deepEqual(start, { rows: [{ key: ['a'] }], next: ['a'] });
	const after = new URLSearchParams({ starts: 'a', after: JSON.stringify(start.next), limit: '1' });
	assert.deepEqual(await (await reader(request(route + '/rows/item?' + after))).json(), { rows: [{ key: ['ab'] }] });
	assert.deepEqual(await (await other(request(route + '/snapshots/item'))).json(), [{ key: ['ax'] }]);

	const named = async (id: string) => {
		const query = new URLSearchParams({ relation: 'item', key: JSON.stringify([id]) });
		const response = await reader(request(route + '/ask/reach?' + query));
		return [response.status, await response.text()] as const;
	};
	assert.deepEqual(await named('ax'), await named('absent'));
	const [status, visible] = await named('a');
	assert.equal(status, 200, visible);
	assert.equal(JSON.parse(visible).format, 'rezono.answer/1');
});

test('language ask stays read-only and returns an undecided partial row', async (t) => {
	const { root } = await fixture();
	t.after(() => rm(root, { recursive: true, force: true }));
	const reader = await openLocalGate(root, 'reader');
	const answer = await reader(request(route + '/ask', { text: 'ask Item where label = "visible"' }));
	const value = await answer.json();
	assert.equal(answer.status, 200, JSON.stringify(value));
	assert.equal(value.format, 'rezono.answer/1');
	assert.deepEqual(value.nodes.map((node: { key: string }) => JSON.parse(node.key)), [['a'], ['ab']]);
	assert.deepEqual(value.undecided.map((row: { binder: string; state: string }) => [row.binder, row.state]),
		[['unset', 'unknown']]);
	assert.equal((await reader(request(route + '/ask', { text: 'ask Item', role: 'other' }))).status, 400);
	assert.equal((await reader(request('/sample/proposals', {}))).status, 405);
});

test('a stale or corrupt manifest cannot replace the verified current role view', async (t) => {
	const { root, write, manifestKey, manifest } = await fixture();
	t.after(() => rm(root, { recursive: true, force: true }));
	const reader = await openLocalGate(root, 'reader');
	assert.equal((await reader(request('/sample/m-0/snapshots/item'))).status, 404);
	await write(manifestKey, { ...manifest, id: 'm-2' });
	const reply = await reader(request('/sample/head'));
	assert.equal(reply.status, 500);
	assert.deepEqual(await reply.json(), { error: 'publication unavailable' });
});

test('an exact retained recording keeps its bytes after a new authorized head', async (t) => {
	const { root, write, object, manifest } = await fixture();
	t.after(() => rm(root, { recursive: true, force: true }));
	const reader = await openLocalGate(root, 'reader');
	const record = async () => {
		const replies = await Promise.all([
			reader(request('/sample/manifests/m-1')),
			reader(request('/sample/head?m=m-1')),
			reader(request('/sample/bundle?m=m-1')),
			reader(request(route + '/rows/item?starts=a&limit=1')),
			reader(request(route + '/ask', { scope: 'catalogue', text: catalogueKindsQuestion })),
			reader(request(route + '/ask/reach?' + new URLSearchParams({ relation: 'item', key: '["a"]' }))),
			reader(request(route + '/ask', { text: 'ask Item where label = "visible"' }))
		]);
		return Promise.all(replies.map(async (reply) => [reply.status, await reply.text()]));
	};
	const original = await record();
	assert.ok(original.every(([status]) => status === 200));

	const publish = async (epoch: number, ids: string[]) => {
		const data = await object(ids.map((id) => ({ key: [id] })));
		const snapshots = manifest.snapshots.map((e) => e.relation === 'item' && e.role === 'reader' ? { ...e, ...data } : e);
		const id = 'm-' + epoch;
		const sha256 = await write(pack + '/manifests/' + id + '.json', { ...manifest, id, epoch, snapshots });
		const key = pack + '/heads/' + (10n ** 19n - 1n - BigInt(epoch)).toString().padStart(19, '0') + '.json';
		await write(key, { format: 'rezono.head/1', manifest: id, epoch, sha256 });
	};
	await publish(2, ['a', 'ab', 'added', 'unset']);
	assert.equal((await (await reader(request('/sample/head'))).json()).id, 'm-2');
	assert.deepEqual(await record(), original);
	const earlierHead = pack + '/heads/9999999999999999998.json';
	const sha256 = await write(pack + '/manifests/m-1.json', manifest);
	await write(earlierHead, { format: 'rezono.head/1', manifest: 'm-1', epoch: 1, sha256: '0'.repeat(64) });
	assert.equal((await reader(request('/sample/manifests/m-1'))).status, 500);
	await write(earlierHead, { format: 'rezono.head/1', manifest: 'm-1', epoch: 1, sha256 });
	await publish(3, ['ab', 'added', 'unset']);
	const refused = await reader(request(route + '/rows/item'));
	assert.equal(refused.status, 404);
	assert.deepEqual(await refused.json(), { error: 'not found' });
	assert.equal((await reader(request('/sample/manifests/m-0'))).status, 404);
});
test('catalogue aliases use one role-scoped typed question with ordinary answers and pages', async (t) => {
	const { root, write, object, manifestKey, manifest } = await fixture();
	t.after(() => rm(root, { recursive: true, force: true }));
	const reader = await openLocalGate(root, 'reader');
	const other = await openLocalGate(root, 'other');
	const definedKinds = [
		{ id: 'full_empty', class: 'FullEmpty' }, { id: 'partial_empty', class: 'PartialEmpty' },
		{ id: 'unseen', class: 'Unseen', parent: 'item' }
	];
	const publicSchema = { ...schema, kinds: [schema.kinds[0], ...definedKinds], arrows: [{
		id: 'item.link', kind: 'item', table: 'item__link', name: 'link', target: 'unseen', required: false
	}], relations: [
		{ id: 'unseen_outcome', columns: [{ name: 'key', type: 'string' }], outcome: 'unseen' },
		{ id: 'item_outcome', columns: [{ name: 'key', type: 'string' }], outcome: 'item' }
	] };
	const snap = async (relation: string, role: string, full: boolean, keys: string[][] = []) => ({
		relation, role, complete: false, full, format: 'json', ...await object(keys.map((key) => ({ key })))
	});
	const snapshots = [
		...manifest.snapshots,
		await snap('full_empty', 'reader', true), await snap('full_empty', 'other', true),
		await snap('partial_empty', 'reader', false), await snap('partial_empty', 'other', false),
		await snap('item__link', 'reader', false), await snap('item__link', 'other', false, [['ax', 'unlisted']]),
		await snap('unseen__code', 'other', false, [['unlisted', 'internal.sample']]),
		await snap('unseen_outcome', 'other', false, [['unlisted']]),
		await snap('item_outcome', 'reader', false), await snap('item_outcome', 'other', false)
	];
	const publish = async (bundle: typeof publicSchema, scoped: typeof snapshots) => {
		const key = 'sample/bundles/definition.json';
		const compiled = [{ ...manifest.compiled[0], sha256: await write(key, bundle) }];
		const sha256 = await write(manifestKey, { ...manifest, snapshots: scoped, compiled });
		await write('sample/heads/9999999999999999998.json',
			{ format: 'rezono.head/1', manifest: 'm-1', epoch: 1, sha256 });
	};
	const ask = async (handle: typeof reader, text: string, limit = 50, after?: string) => {
		const response = await handle(request(route + '/ask', { scope: 'catalogue', text, limit, after }));
		const value = await response.json();
		assert.equal(response.status, 200, JSON.stringify(value));
		assert.equal(value.format, 'rezono.answer/1');
		assert.equal(value.manifest_id, 'm-1');
		assert.ok(value.expression.text.startsWith('ask entry: CatalogueEntry'));
		return value;
	};
	const ids = (value: { dataset: { rows: { $id: string }[] } }) => value.dataset.rows.map(({ $id }) => $id);

	await publish(publicSchema, snapshots);
	const listed = await ask(reader, catalogueKindsQuestion);
	assert.deepEqual(ids(listed), ['kind/full_empty', 'kind/item']);
	assert.deepEqual(listed.dataset.rows[0].c5, 'full');
	assert.deepEqual(listed.dataset.rows[0].c6, 'empty');
	assert.deepEqual(ids(await ask(other, catalogueKindsQuestion)), ['kind/full_empty', 'kind/item', 'kind/unseen']);

	const itemSchema = await ask(reader, catalogueSchemaQuestion('Item'));
	assert.deepEqual(ids(itemSchema), ['kind/item', 'outcome/item/item_outcome', 'slot/item/label']);
	assert.deepEqual(ids(await ask(reader, catalogueSchemaQuestion('item'))), ids(itemSchema));
	assert.deepEqual(ids(await ask(other, catalogueSchemaQuestion('item'))), [
		'kind/item', 'outcome/item/item_outcome', 'slot/item/label', 'slot/item/link'
	]);
	const descendant = await ask(other, catalogueSchemaQuestion('Unseen'));
	assert.deepEqual(ids(descendant), [
		'kind/unseen', 'outcome/unseen/item_outcome', 'outcome/unseen/unseen_outcome',
		'slot/unseen/code', 'slot/unseen/label', 'slot/unseen/link'
	]);
	assert.equal(descendant.dataset.rows.find((row: { $id: string }) => row.$id === 'slot/unseen/code').c7, 'internal');
	assert.deepEqual(ids(await ask(reader, catalogueSchemaQuestion('unseen'))), []);
	assert.deepEqual(ids(await ask(reader, catalogueSchemaQuestion('absent'))), []);
	assert.ok(!JSON.stringify({ listed, itemSchema }).includes('internal'));

	const first = await ask(reader, catalogueKindsQuestion, 1);
	assert.ok(first.next);
	const second = await ask(reader, catalogueKindsQuestion, 1, first.next);
	assert.deepEqual([...ids(first), ...ids(second)], ids(listed));
	assert.equal(second.next, undefined);
	assert.equal((await reader(request(route + '/ask', { text: catalogueKindsQuestion, scope: 'unknown' }))).status, 400);
	assert.equal((await reader(request(route + '/ask', { text: catalogueKindsQuestion }))).status, 400);

	const absentWorld = { ...publicSchema, kinds: publicSchema.kinds.filter(({ id }) => id !== 'unseen'),
		attributes: publicSchema.attributes.filter(({ kind }) => kind !== 'unseen'), arrows: [],
		relations: publicSchema.relations.filter(({ outcome }) => outcome !== 'unseen'), enums: [] };
	await publish(absentWorld, snapshots.filter(({ relation, role }) =>
		role === 'reader' && relation !== 'item__link'));
	assert.deepEqual(await ask(reader, catalogueKindsQuestion), listed);
	assert.deepEqual(await ask(reader, catalogueSchemaQuestion('Item')), itemSchema);
});
