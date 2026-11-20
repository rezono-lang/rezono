import assert from 'node:assert/strict';
import { test } from 'node:test';
import type { Bundle } from '../../../contracts/typescript/generated/bundle.ts';
import { AskError } from '../src/ask.ts';
import { ask, roleSchema, rowsOf } from '../src/expr.ts';

test('roleSchema places integer min/max on schema.types and asNumber emits JSON numbers for bounded integers', async () => {
	const bundle = {
		pack: { id: 'sample', base: 'https://example.org/sample/' },
		kinds: [{ id: 'item', class: 'Item', world: 'closed', id_type: 'text' }],
		attributes: [
			{
				id: 'item.score', kind: 'item', name: 'score', table: 'item__score',
				type: 'integer', schema_type: 'integer', minimum: '1', maximum: '200',
				required: false, multivalued: false, world: 'closed'
			},
			{
				id: 'item.total', kind: 'item', name: 'total', table: 'item__total',
				type: 'integer', schema_type: 'total_units', minimum: '0',
				required: false, multivalued: false, world: 'closed'
			},
			{
				id: 'item.raw', kind: 'item', name: 'raw', table: 'item__raw',
				type: 'integer', schema_type: 'integer',
				required: false, multivalued: false, world: 'closed'
			}
		]
	};
	const view = roleSchema(bundle as unknown as Bundle, [
		{ relation: 'item', complete: true, full: true },
		{ relation: 'item__score', complete: true, full: true },
		{ relation: 'item__total', complete: true, full: true },
		{ relation: 'item__raw', complete: true, full: true }
	]);

	// Bounds belong on schema.types[slot.type], never on the slot itself.
	const slots = view.schema.kinds.Item.slots;
	assert.equal(slots.score.type, 'ItemScore');
	assert.equal('min' in slots.score, false);
	assert.equal('max' in slots.score, false);
	assert.deepEqual(view.schema.types?.ItemScore, { of: 'Integer', min: '1', max: '200' });

	assert.equal(slots.total.type, 'TotalUnits');
	assert.equal('min' in slots.total, false);
	assert.equal('max' in slots.total, false);
	assert.deepEqual(view.schema.types?.TotalUnits, { of: 'Integer', min: '0', max: '9223372036854775807' });

	assert.equal(slots.raw.type, 'ItemRaw');
	assert.deepEqual(view.schema.types?.ItemRaw, { of: 'Integer', min: '-9223372036854775808', max: '9223372036854775807' });

	// Bounded integer within safe JSON range emits a JSON number via asNumber(); unbounded BIGINT stays text.
	const tables: Record<string, string[][]> = {
		item: [['a']],
		item__score: [['a', '42']],
		item__total: [['a', '9007199254740993']],
		item__raw: [['a', '7']]
	};
	const read = async (relation: string) => ({ rows: (tables[relation] ?? []).map((key) => ({ key })) });
	const rows = await rowsOf(view, new Map([['Item', new Set(['score', 'total', 'raw'])]]), read, { left: 100 });
	assert.deepEqual(rows, [{ $kind: 'Item', $id: 'a', score: 42, total: '9007199254740993', raw: '7' }]);
	assert.equal(typeof rows[0].score, 'number');
	assert.equal(typeof rows[0].total, 'string');
	assert.equal(typeof rows[0].raw, 'string');

	const res = await ask({
		text: 'ask Item where score > 10 show score',
		manifest: 'm-1',
		view,
		read,
		budget: { rows: 100, steps: 10_000 },
		limit: 50
	});
	assert.ok('answer' in res, JSON.stringify(res));
	assert.deepEqual(res.answer.nodes.map((n) => JSON.parse(n.key)), [['a']]);
});

test('roleSchema names pattern-text types after schema_type and refuses colliding patterns', () => {
	const bundle = {
		pack: { id: 'sample', base: 'https://example.org/sample/' },
		kinds: [{ id: 'item', class: 'Item', world: 'closed', id_type: 'text' }],
		attributes: [
			{
				id: 'item.code', kind: 'item', name: 'code', table: 'item__code',
				type: 'text', schema_type: 'item_code', patterns: ['^[a-z]+$'],
				required: false, multivalued: false, world: 'closed'
			},
			{
				id: 'item.alias', kind: 'item', name: 'alias', table: 'item__alias',
				type: 'text', schema_type: 'item_code', patterns: ['^[a-z]+$'],
				required: false, multivalued: false, world: 'closed'
			}
		]
	};
	const view = roleSchema(bundle as unknown as Bundle, [
		{ relation: 'item', complete: true, full: true },
		{ relation: 'item__code', complete: true, full: true },
		{ relation: 'item__alias', complete: true, full: true }
	]);
	assert.equal(view.schema.kinds.Item.slots.code.type, 'ItemCode');
	assert.equal(view.schema.kinds.Item.slots.alias.type, 'ItemCode');
	assert.deepEqual(view.schema.types, { ItemCode: { of: 'Text', pattern: '^[a-z]+$' } });

	const colliding = {
		...bundle,
		attributes: [
			{ ...bundle.attributes[0], schema_type: 'string', patterns: ['^[a-z]+$'] },
			{ ...bundle.attributes[1], schema_type: 'string', patterns: ['^[0-9]+$'] }
		]
	};
	assert.throws(
		() => roleSchema(colliding as unknown as Bundle, [
			{ relation: 'item', complete: true, full: true },
			{ relation: 'item__code', complete: true, full: true },
			{ relation: 'item__alias', complete: true, full: true }
		]),
		(err: unknown) => err instanceof AskError && err.status === 501 && /second type named String/.test(err.message)
	);
});

test('roleSchema preserves derived column types, semantic refs, and tuple_key', async () => {
	const bundle = {
		pack: { id: 'sample', base: 'https://example.org/sample/' },
		kinds: [{ id: 'stage', class: 'Stage', world: 'closed', id_type: 'text' }],
		attributes: [],
		relations: [{
			id: 'ranked',
			world: 'closed',
			columns: [
				{ name: 'stage', type: 'string', semantic: { case: 'ref', base: 'string', target: 'stage' } },
				{ name: 'count', type: 'integer', semantic: { case: 'scalar', base: 'integer' } },
				{ name: 'label', type: 'string' }
			]
		}]
	};
	const view = roleSchema(bundle as unknown as Bundle, [
		{ relation: 'stage', complete: true, full: true },
		{ relation: 'ranked', complete: true, full: true }
	]);
	assert.deepEqual(view.schema.kinds.Ranked, {
		world: 'closed',
		id: { type: 'Text' },
		tuple_key: ['stage', 'count', 'label'],
		slots: {
			stage: { ref: 'Stage', card: '1', states: ['known'], derived: true },
			count: {
				type: 'Integer',
				min: '-9223372036854775808',
				max: '9223372036854775807',
				card: '1',
				states: ['known'],
				derived: true
			},
			label: { type: 'Text', card: '1', states: ['known'], derived: true }
		}
	});

	const rows = await rowsOf(
		view,
		new Map([['Ranked', new Set(['stage', 'count', 'label'])]]),
		async (relation) => ({
			rows: relation === 'ranked' ? [{ key: ['s-1', '9007199254740993', 'first'] }] : []
		}),
		{ left: 100 }
	);
	assert.deepEqual(rows, [{
		$kind: 'Ranked',
		$id: '["s-1","9007199254740993","first"]',
		stage: { $ref: 's-1' },
		count: '9007199254740993',
		label: 'first'
	}]);

	const badCol = {
		...bundle,
		relations: [{ id: 'ranked', world: 'closed', columns: [{ name: 'flag', type: 'boolean' }] }]
	};
	assert.throws(
		() => roleSchema(badCol as unknown as Bundle, [
			{ relation: 'stage', complete: true, full: true },
			{ relation: 'ranked', complete: true, full: true }
		]),
		(err: unknown) => err instanceof AskError && err.status === 501
	);
});

test('roleSchema preserves control plane/owner when full and drops them when decision is partial', () => {
	const bundle = {
		pack: { id: 'sample', base: 'https://example.org/sample/' },
		kinds: [
			{ id: 'policy', class: 'Policy', world: 'closed', id_type: 'text', plane: 'control', owner: 'stewards' },
			{ id: 'detail', class: 'Detail', parent: 'policy', id_type: 'text' }
		],
		attributes: [{
			id: 'policy.decision', kind: 'policy', name: 'decision', table: 'policy__decision',
			type: 'text', schema_type: 'string', required: true, multivalued: false, world: 'closed'
		}]
	};
	const fullView = roleSchema(bundle as unknown as Bundle, [
		{ relation: 'policy', complete: true, full: true },
		{ relation: 'detail', complete: true, full: true },
		{ relation: 'policy__decision', complete: true, full: true }
	]);
	for (const kind of ['Policy', 'Detail']) {
		assert.equal(fullView.schema.kinds[kind].plane, 'control');
		assert.equal(fullView.schema.kinds[kind].owner, 'stewards');
		assert.deepEqual(fullView.schema.kinds[kind].slots.decision.states, ['known']);
	}

	const partialDecision = roleSchema(bundle as unknown as Bundle, [
		{ relation: 'policy', complete: false, full: true },
		{ relation: 'detail', complete: false, full: true },
		{ relation: 'policy__decision', complete: false, full: false }
	]);
	for (const kind of ['Policy', 'Detail']) {
		assert.equal(partialDecision.schema.kinds[kind].plane, undefined);
		assert.equal(partialDecision.schema.kinds[kind].owner, undefined);
		assert.deepEqual(partialDecision.schema.kinds[kind].slots.decision.states, ['known', 'unknown']);
	}
});

test('roleSchema includes unknown state on optional slots whose relation is declared open', async () => {
	const bundle = {
		pack: { id: 'sample', base: 'https://example.org/sample/' },
		kinds: [{ id: 'item', class: 'Item', world: 'closed', id_type: 'text' }],
		attributes: [
			{
				id: 'item.open_note', kind: 'item', name: 'open_note', table: 'item__open_note',
				type: 'text', schema_type: 'string', required: false, multivalued: false, world: 'open'
			},
			{
				id: 'item.closed_note', kind: 'item', name: 'closed_note', table: 'item__closed_note',
				type: 'text', schema_type: 'string', required: false, multivalued: false, world: 'closed'
			}
		]
	};
	const view = roleSchema(bundle as unknown as Bundle, [
		{ relation: 'item', complete: true, full: true },
		{ relation: 'item__open_note', complete: true, full: true },
		{ relation: 'item__closed_note', complete: true, full: true }
	]);
	assert.deepEqual(view.schema.kinds.Item.slots.open_note.states, ['known', 'not_applicable', 'unknown']);
	assert.equal(view.schema.kinds.Item.slots.open_note.world, 'open');
	assert.deepEqual(view.schema.kinds.Item.slots.closed_note.states, ['known', 'not_applicable']);
	assert.equal(view.schema.kinds.Item.slots.closed_note.world, undefined);

	const rows = await rowsOf(
		view,
		new Map([['Item', new Set(['open_note', 'closed_note'])]]),
		async (relation) => ({ rows: relation === 'item' ? [{ key: ['a'] }] : [] }),
		{ left: 100 }
	);
	assert.deepEqual(rows, [{ $kind: 'Item', $id: 'a', open_note: { $unknown: '' }, closed_note: { $na: '' } }]);
});
