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

	const collidingNamed = {
		...bundle,
		attributes: [
			{ ...bundle.attributes[0], schema_type: 'item_code', patterns: ['^[a-z]+$'] },
			{ ...bundle.attributes[1], schema_type: 'item_code', patterns: ['^[0-9]+$'] }
		]
	};
	assert.throws(
		() => roleSchema(collidingNamed as unknown as Bundle, [
			{ relation: 'item', complete: true, full: true },
			{ relation: 'item__code', complete: true, full: true },
			{ relation: 'item__alias', complete: true, full: true }
		]),
		(err: unknown) => err instanceof AskError && err.status === 501 && /second type named ItemCode/.test(err.message)
	);

	// Plain `string` inline patterns share `String` when identical and isolate to `${Kind}${Slot}` when distinct.
	// Slots are processed in sorted `id` order, so `item.alias` claims `String` and `item.code` isolates to `ItemCode`.
	const inlineStrings = {
		...bundle,
		attributes: [
			{ ...bundle.attributes[0], schema_type: 'string', patterns: ['^[a-z]+$'] },
			{ ...bundle.attributes[1], schema_type: 'string', patterns: ['^[0-9]+$'] }
		]
	};
	const inlineView = roleSchema(inlineStrings as unknown as Bundle, [
		{ relation: 'item', complete: true, full: true },
		{ relation: 'item__code', complete: true, full: true },
		{ relation: 'item__alias', complete: true, full: true }
	]);
	assert.equal(inlineView.schema.kinds.Item.slots.alias.type, 'String');
	assert.equal(inlineView.schema.kinds.Item.slots.code.type, 'ItemCode');
	assert.deepEqual(inlineView.schema.types, {
		String: { of: 'Text', pattern: '^[0-9]+$' },
		ItemCode: { of: 'Text', pattern: '^[a-z]+$' }
	});
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
				{ name: 'label', type: 'string' },
				{ name: 'active', type: 'boolean' }
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
		tuple_key: ['stage', 'count', 'label', 'active'],
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
			label: { type: 'Text', card: '1', states: ['known'], derived: true },
			active: { type: 'Bool', card: '1', states: ['known'], derived: true }
		}
	});

	const rows = await rowsOf(
		view,
		new Map([['Ranked', new Set(['stage', 'count', 'label', 'active'])]]),
		async (relation) => ({
			rows: relation === 'ranked' ? [{ key: ['s-1', '9007199254740993', 'first', 'true'] }] : []
		}),
		{ left: 100 }
	);
	assert.deepEqual(rows, [{
		$kind: 'Ranked',
		$id: '["s-1","9007199254740993","first","true"]',
		stage: { $ref: 's-1' },
		count: '9007199254740993',
		label: 'first',
		active: true
	}]);

	await assert.rejects(
		rowsOf(
			view,
			new Map([['Ranked', new Set(['stage', 'count', 'label', 'active'])]]),
			async (relation) => ({
				rows: relation === 'ranked' ? [{ key: ['s-1', '1', 'first', 'yes'] }] : []
			}),
			{ left: 100 }
		),
		(err: unknown) => err instanceof AskError && err.status === 500
	);

	const badCol = {
		...bundle,
		relations: [{ id: 'ranked', world: 'closed', columns: [{ name: 'ratio', type: 'float' }] }]
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

test('rowsOf rejects non-canonical, out-of-range, and malformed bounded integer cells with AskError(500)', async () => {
	const bundle = {
		pack: { id: 'sample', base: 'https://example.org/sample/' },
		kinds: [{ id: 'item', class: 'Item', world: 'closed', id_type: 'text' }],
		attributes: [{
			id: 'item.score', kind: 'item', name: 'score', table: 'item__score',
			type: 'integer', schema_type: 'integer', minimum: '-100', maximum: '100',
			required: false, multivalued: false, world: 'closed'
		}]
	};
	const view = roleSchema(bundle as unknown as Bundle, [
		{ relation: 'item', complete: true, full: true },
		{ relation: 'item__score', complete: true, full: true }
	]);

	// Canonical zero and negative integers parse cleanly.
	const okRows = await rowsOf(
		view,
		new Map([['Item', new Set(['score'])]]),
		async (relation) => ({
			rows: (relation === 'item' ? [['a'], ['b']] : [['a', '0'], ['b', '-42']]).map((key) => ({ key }))
		}),
		{ left: 100 }
	);
	assert.deepEqual(okRows, [
		{ $kind: 'Item', $id: 'a', score: 0 },
		{ $kind: 'Item', $id: 'b', score: -42 }
	]);

	const badCases: string[][][] = [
		[['a', '1.5']],
		[['a', '1e2']],
		[['a', ' 1']],
		[['a', '']],
		[['a', '+1']],
		[['a', '00']],
		[['a', '01']],
		[['a', '-0']],
		[['a', '-01']],
		[['a', '9007199254740992']],
		[['a', '-9007199254740992']],
		[['a']],
		[['a', '1', '2']]
	];
	for (const badRows of badCases) {
		const read = async (relation: string) => ({
			rows: (relation === 'item' ? [['a']] : badRows).map((key) => ({ key }))
		});
		await assert.rejects(
			rowsOf(view, new Map([['Item', new Set(['score'])]]), read, { left: 100 }),
			(err: unknown) => err instanceof AskError && err.status === 500,
			`expected AskError(500) for ${JSON.stringify(badRows)}`
		);
	}
});

test('rowsOf rejects derived rows whose tuple arity differs from declared columns', async () => {
	const bundle = {
		pack: { id: 'sample', base: 'https://example.org/sample/' },
		kinds: [{ id: 'stage', class: 'Stage', world: 'closed', id_type: 'text' }],
		relations: [{
			id: 'ranked',
			world: 'closed',
			columns: [
				{ name: 'stage', type: 'string', semantic: { case: 'ref', base: 'string', target: 'stage' } },
				{ name: 'count', type: 'integer' },
				{ name: 'label', type: 'string' }
			]
		}]
	};
	const view = roleSchema(bundle as unknown as Bundle, [
		{ relation: 'stage', complete: true, full: true },
		{ relation: 'ranked', complete: true, full: true }
	]);

	for (const badKey of [['s-1', '1'], ['s-1', '1', 'first', 'extra']]) {
		await assert.rejects(
			rowsOf(
				view,
				new Map([['Ranked', new Set(['stage', 'count', 'label'])]]),
				async (relation) => ({ rows: relation === 'ranked' ? [{ key: badKey }] : [] }),
				{ left: 100 }
			),
			(err: unknown) => err instanceof AskError && err.status === 500 && /malformed derived row/.test(err.message)
		);
	}
});

test('roleSchema isolates unreadable kinds, slots, enums, derived relations, control parents, and mid-chain subkinds', () => {
	const bundle = {
		pack: { id: 'sample', base: 'https://example.org/sample/' },
		kinds: [
			{ id: 'visible', class: 'Visible', world: 'closed', id_type: 'text' },
			{ id: 'hidden', class: 'Hidden', world: 'closed', id_type: 'text' },
			{ id: 'root', class: 'Root', world: 'closed', id_type: 'text' },
			{ id: 'mid', class: 'Mid', parent: 'root', id_type: 'text' },
			{ id: 'leaf', class: 'Leaf', parent: 'mid', id_type: 'text' },
			{ id: 'control_parent', class: 'ControlParent', world: 'closed', id_type: 'text', plane: 'control', owner: 'stewards' },
			{ id: 'control_child', class: 'ControlChild', parent: 'control_parent', id_type: 'text' }
		],
		attributes: [
			{ id: 'visible.label', kind: 'visible', name: 'label', table: 'visible__label', type: 'text', schema_type: 'string', required: false, multivalued: false, world: 'closed' },
			{ id: 'visible.secret_note', kind: 'visible', name: 'secret_note', table: 'visible__secret_note', type: 'text', schema_type: 'string', required: false, multivalued: false, world: 'closed' },
			{ id: 'hidden.code', kind: 'hidden', name: 'code', table: 'hidden__code', type: 'enum', schema_type: 'secret_enum', enum: 'secret_enum', required: false, multivalued: false, world: 'closed' },
			{ id: 'control_parent.decision', kind: 'control_parent', name: 'decision', table: 'control_parent__decision', type: 'text', schema_type: 'string', required: true, multivalued: false, world: 'closed' }
		],
		arrows: [
			{ id: 'visible.target', kind: 'visible', name: 'target', table: 'visible__target', target: 'hidden', required: false, multivalued: false, world: 'closed' }
		],
		relations: [
			{ id: 'hidden_derived', world: 'closed', columns: [{ name: 'k', type: 'string' }] }
		],
		enums: [
			{ id: 'secret_enum', values: ['secret_enum.priv'] }
		]
	};

	const view = roleSchema(bundle as unknown as Bundle, [
		{ relation: 'visible', complete: true, full: true },
		{ relation: 'visible__label', complete: true, full: true },
		{ relation: 'visible__target', complete: true, full: true },
		{ relation: 'root', complete: true, full: true },
		{ relation: 'leaf', complete: true, full: true },
		{ relation: 'control_child', complete: true, full: true },
		{ relation: 'control_parent__decision', complete: true, full: true }
	]);

	const serialized = JSON.stringify(view.schema);
	assert.equal(serialized.includes('Hidden'), false);
	assert.equal(serialized.includes('secret_note'), false);
	assert.equal(serialized.includes('secret_enum'), false);
	assert.equal(serialized.includes('HiddenDerived'), false);
	assert.equal(serialized.includes('Mid'), false);
	assert.equal(serialized.includes('ControlParent'), false);
	assert.equal(serialized.includes('stewards'), false);
	assert.equal(view.schema.kinds.Visible.slots.target, undefined);
	assert.equal(view.schema.kinds.Leaf.parent, undefined);
	assert.equal(view.schema.kinds.ControlChild.plane, undefined);
	assert.equal(view.schema.kinds.ControlChild.owner, undefined);
	// Root -> Mid (unreadable) -> Leaf keeps Root and Leaf in view.trees consistently with family.
	assert.equal(view.trees.has('Root'), true);
	assert.equal(view.trees.has('Leaf'), true);
	assert.equal(view.trees.has('Mid'), false);
	assert.equal(view.trees.has('Visible'), false);

	// Control kind with partial kind table (even when decision table is full) must not carry plane/owner.
	const partialControl = roleSchema(bundle as unknown as Bundle, [
		{ relation: 'control_parent', complete: false, full: false },
		{ relation: 'control_child', complete: false, full: true },
		{ relation: 'control_parent__decision', complete: false, full: true }
	]);
	assert.equal(partialControl.schema.kinds.ControlParent.plane, undefined);
	assert.equal(partialControl.schema.kinds.ControlParent.owner, undefined);
	assert.equal(partialControl.schema.kinds.ControlChild.plane, undefined);
	assert.equal(partialControl.schema.kinds.ControlChild.owner, undefined);

	// Derived relation with semantic ref targeting an unreadable kind fails closed with AskError(501) without leaking class name.
	const leakingDerived = {
		...bundle,
		relations: [{
			id: 'probe',
			world: 'closed',
			columns: [{ name: 'h', type: 'string', semantic: { case: 'ref', base: 'string', target: 'hidden' } }]
		}]
	};
	assert.throws(
		() => roleSchema(leakingDerived as unknown as Bundle, [
			{ relation: 'visible', complete: true, full: true },
			{ relation: 'probe', complete: true, full: true }
		]),
		(err: unknown) => err instanceof AskError && err.status === 501 && !err.message.includes('Hidden')
	);
});
