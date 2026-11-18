import assert from 'node:assert/strict';
import { test } from 'node:test';
import { catalogueKindsQuestion, catalogueSchemaQuestion } from '../../../edge/gate/src/catalogue-questions.ts';
import { rowQuestion } from '../../../edge/gate/src/row-query.ts';
import { type Connection } from '../src/client.ts';
import { hashes, inputs, Recorder, replay } from '../src/record.ts';
import { Session } from '../src/session.ts';

const bundle = 'a'.repeat(64);
const manifest = { id: 'm-1', epoch: 1, compiled: [{ file: 'bundle/schema-bundle.json', sha256: bundle }] };
const text = '  ask Item  where true show detail';
const root = '/pack/m-1';
const role = 'reader';

function transport() {
	const seen: { path: string; method?: string; body?: unknown }[] = [];
	let head = manifest;
	let moveOnSearch = false;
	let moveOnSweepList = false;
	const move = () => { head = { ...manifest, id: `m-${head.epoch + 1}`, epoch: head.epoch + 1 }; };
	const connection: Connection = {
		async open(opened) {
			assert.equal(opened, role);
			return async (path, init) => {
				const body = typeof init?.body === 'string' ? JSON.parse(init.body) : undefined;
				seen.push({ path, method: init?.method, body });
				if (path === '/pack/head') return Response.json(head);
				if (path === '/pack/manifests/m-1') return Response.json(manifest);
				const { pathname, searchParams } = new URL(path, 'http://rezono.local');
				if (pathname === '/pack/sweeps') {
					assert.equal(searchParams.get('m'), 'm-1');
					if (moveOnSweepList) move();
					return Response.json({ manifest_id: 'm-1', sweeps: [{ name: 'sizes' }] });
				}
				if (pathname === `${root}/rows/item`) {
					assert.equal(searchParams.get('starts'), 'a');
					assert.equal(searchParams.get('limit'), '50');
					if (moveOnSearch) move();
					return Response.json({ rows: [{ key: ['a'] }, { key: ['a and b'] }] });
				}
				if (pathname === `${root}/ask` || pathname === `${root}/ask/grounds`) {
					if (body && body.scope === undefined) assert.equal(body.text, text);
					if (body?.scope === 'row') {
						assert.equal(body.text, rowQuestion);
						if (body.row.key[0] === 'cut') return Response.json({ cut: { budget: 'rows' } }, { status: 422 });
						if (body.row.continuation === 'invalid') return Response.json({ error: 'invalid row continuation' }, { status: 400 });
						const rows = [{ $kind: 'Answer', $id: 'slot', c1: 'tags', c7: 'open', c13: 'unknown',
							c14: 'not_read_in_full', c15: 'opaque-source' }];
						const slots = { c1: { expr: 'cell.name' }, c7: { expr: 'cell.text_value' }, c13: { expr: 'cell.state' },
							c14: { expr: 'cell.reason' }, c15: { expr: 'cell.continuation' } };
						return Response.json({
							format: 'rezono.answer/1', question: 'ask', manifest_id: 'm-1', nodes: [],
							dataset: { schema: { kinds: { Answer: { slots } } }, rows },
							...(!body.after && !body.row.continuation ? { next: 'answer-next' } : {})
						});
					}
					const after = body?.after ?? searchParams.get('after');
					const nodes = [{ relation: 'item', key: '["a"]', distance: 0 }];
					return Response.json({
						format: 'rezono.answer/1',
						question: body ? 'ask' : 'grounds',
						manifest_id: 'm-1',
						nodes,
						dataset: { rows: [{ $kind: 'Answer', $id: 'a', c1: { $unknown: 'not_read_in_full' } }] },
						undecided: [{ binder: 'b', state: 'invalid', reason: 'conflict' }],
						...(!after ? { next: 'cursor/=' } : {})
					});
				}
				return new Response(null, { status: 404 });
			};
		}
	};
	return { connection, seen, move, moveOnSearch: () => { moveOnSearch = true; },
		moveOnSweepList: () => { moveOnSweepList = true; } };
}

test('language ask and :more preserve exact text, method, cursor and manifest', async () => {
	const { connection, seen } = transport();
	const session = new Session(connection, role, undefined, { pageSize: 1 });
	assert.deepEqual(await session.exec(':use pack latest'), ['using pack m-1 as reader']);
	assert.match((await session.exec(text)).join('\n'), /unknown \(not_read_in_full\)[\s\S]*undecided:[\s\S]*invalid  conflict/);
	assert.match((await session.exec(':more')).join('\n'), /unknown \(not_read_in_full\)/);
	assert.deepEqual(seen.filter(({ path }) => path === `${root}/ask`), [
		{ path: `${root}/ask`, method: 'POST', body: { text, limit: 1 } },
		{ path: `${root}/ask`, method: 'POST', body: { text, limit: 1, after: 'cursor/=' } }
	]);
	assert.deepEqual(await session.exec(':more'), ['error: no further page']);
});

test('catalogue aliases send the shared questions and keep catalogue scope on continuation', async () => {
	const { connection, seen } = transport();
	const session = new Session(connection, role, undefined, { pageSize: 1 });
	await session.use('pack', 'latest');
	for (const input of [':kinds', ':more', ':schema "Kind with a space"', ':more'])
		assert.match((await session.exec(input)).join('\n'), /unknown \(not_read_in_full\)/);
	const schema = catalogueSchemaQuestion('Kind with a space');
	const asked = seen.filter(({ path }) => path === `${root}/ask`);
	assert.deepEqual(asked.map(({ method, body }) => [method, body]), [
		['POST', { text: catalogueKindsQuestion, limit: 1, scope: 'catalogue' }],
		['POST', { text: catalogueKindsQuestion, limit: 1, after: 'cursor/=', scope: 'catalogue' }],
		['POST', { text: schema, limit: 1, scope: 'catalogue' }],
		['POST', { text: schema, limit: 1, after: 'cursor/=', scope: 'catalogue' }]
	]);
});

test('row preserves composite key parts and delegates both cursor forms to the same Gate question', async () => {
	const { connection, seen } = transport();
	const session = new Session(connection, role, undefined, { pageSize: 1, rowSourceLimit: 2 });
	await session.use('pack', 'latest');
	const input = ':row Item area "a with spaces"';
	const initial = await session.exec(input);
	assert.match(initial[0], /name +text_value +state +reason +continuation/);
	assert.match(initial[1], /unknown +not_read_in_full +opaque-source/);
	assert.equal(initial.at(-1), 'next: answer-next');
	assert.deepEqual(await session.exec(':more'), initial.slice(0, -1));
	assert.deepEqual(await session.exec(':more "opaque-source"'), initial.slice(0, -1));
	const row = { kind: 'Item', key: ['area', 'a with spaces'], source_limit: 2 };
	const sent = seen.filter(({ path }) => path === `${root}/ask`);
	assert.deepEqual(sent.map(({ method, body }) => [method, body]), [
		['POST', { text: rowQuestion, limit: 1, scope: 'row', row }],
		['POST', { text: rowQuestion, limit: 1, after: 'answer-next', scope: 'row', row }],
		['POST', { text: rowQuestion, limit: 1, scope: 'row', row: { ...row, continuation: 'opaque-source' } }]
	]);
	assert.deepEqual(await session.exec(':more invalid'), ['error: bad request']);
	assert.deepEqual(await session.exec(':row Item cut'), ['error: question exceeded the read budget']);
	assert.deepEqual(await session.exec(':more opaque-source'), ['error: no further page']);
});

test('named questions use the canonical key and lose their cursor when the head changes', async () => {
	const fixture = transport();
	const session = new Session(fixture.connection, role);
	await session.use('pack', 'latest');
	await session.exec(':grounds item "with a space"');
	const named = new URL(fixture.seen.find(({ path }) => path.startsWith(`${root}/ask/grounds`))!.path, 'http://rezono.local');
	assert.equal(named.searchParams.get('key'), '["with a space"]');
	assert.equal(named.searchParams.get('relation'), 'item');
	fixture.move();
	assert.deepEqual(await session.exec(':more'), ['error: the publication changed since the last page; ask again']);
	assert.equal(fixture.seen.filter(({ path }) => path.startsWith(`${root}/ask/grounds`)).length, 1);
});

test('a sweep discovered under a changed authorization head never starts a named query', async () => {
	const fixture = transport();
	const session = new Session(fixture.connection, role);
	await session.use('pack', 'latest');
	fixture.moveOnSweepList();
	assert.deepEqual(await session.exec(':sweep'), ['error: the publication changed during the question; ask again']);
	assert.ok(fixture.seen.some(({ path }) => path === '/pack/sweeps?m=m-1'));
	assert.ok(!fixture.seen.some(({ path }) => path.startsWith(`${root}/ask/sweep`)));
});

test('completion and shared search read the exact pin and reject a changed authorization head', async () => {
	const fixture = transport();
	const session = new Session(fixture.connection, role);
	await session.use('pack', 'm-1');
	assert.deepEqual(await session.search('item', 'a'), ['a', '"a and b"']);
	assert.deepEqual(await session.exec(':complete :row item a'), ['a', '"a and b"']);
	assert.deepEqual(await session.search('hidden', 'a'), await session.search('absent', 'a'));
	fixture.move();
	assert.deepEqual(await session.search('item', 'a'), ['a', '"a and b"']);
	fixture.moveOnSearch();
	assert.deepEqual(await session.search('item', 'a'), []);
	assert.equal(fixture.seen.filter(({ path }) => path.startsWith(`${root}/rows/item`)).length, 4);
});

test('help exposes command classes and concrete alias questions without submitting a question', async () => {
	const { connection, seen } = transport();
	const session = new Session(connection, role);
	const help = (await session.exec(':help')).join('\n');
	assert.match(help, /:more \[<source-cursor>\] +session/);
	assert.match(help, /:suppose[^\n]+named query +std-explain scenario or impact/);
	assert.match(help, /:kinds[^\n]+language alias +catalogue scope: ask entry: CatalogueEntry/);
	assert.match(help, /:schema[^\n]+language alias +catalogue scope: ask entry: CatalogueEntry/);
	assert.match(help, /:row[^\n]+language alias +row scope: ask cell: RowCell/);
	assert.match(help, /ask \[binder:\][^\n]+language +evaluate the Rezono question/);
	assert.deepEqual(await session.exec(':row Item'), ['error: usage: :row <kind> <key-part>…']);
	assert.deepEqual(seen, []);
});

test('record and replay resolve latest once and fail before a question on role or pin drift', async () => {
	const first = transport();
	const recorder = new Recorder(new Session(first.connection, role, { pack: 'pack', manifest: 'm-1' }));
	assert.deepEqual(await recorder.exec(':use pack latest as writer'), ['error: this session is locked to its startup role']);
	await recorder.exec(':use pack latest');
	await recorder.exec(text);
	const bytes = recorder.text();
	assert.deepEqual(inputs(bytes), [':use pack latest as writer', ':use pack m-1 as reader', text]);
	assert.equal(bytes.includes('\r'), false);
	assert.equal(bytes.includes(`"bundle":"${bundle}"`), true);
	const second = transport();
	assert.deepEqual(await replay(bytes, new Session(second.connection, role)), { same: true, session_sha256: hashes(bytes).session_sha256 });
	assert.equal(second.seen.filter(({ path }) => path === '/pack/manifests/m-1').length, 1);

	const edited = bytes.replace(bundle, 'b'.repeat(64));
	const third = transport();
	const drift = await replay(edited, new Session(third.connection, role));
	assert.equal(drift.same, false);
	assert.equal(third.seen.some(({ path }) => path === `${root}/ask`), false);
	assert.throws(() => inputs(bytes.replace(':use pack m-1 as reader', ':use pack latest as reader')), /invalid session transcript/);
});
