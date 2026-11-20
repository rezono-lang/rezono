import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { mkdir, mkdtemp, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { test } from 'node:test';
import type { Bundle } from '../../../contracts/typescript/generated/bundle.ts';
import type { Schema, TypeDef } from '../../../rezono/src/index.ts';
import { AskError } from '../src/ask.ts';
import { ask, roleSchema, rowsOf, type View } from '../src/expr.ts';
import { openLocalGate } from '../src/local.ts';

const pack = 'sample';
const baseBundle = {
	pack: { id: pack, base: 'https://example.org/sample/' },
	kinds: [
		{ id: 'widget', class: 'Widget', world: 'closed' },
		{ id: 'probe_read', class: 'ProbeRead', world: 'closed' }
	],
	attributes: [
		{ id: 'widget__name', kind: 'widget', name: 'name', table: 'widget__name', type: 'text', required: false },
		{ id: 'probe_read__complete', kind: 'probe_read', name: 'complete', table: 'probe_read__complete', type: 'boolean', required: false },
		{ id: 'probe_read__verified', kind: 'probe_read', name: 'verified', table: 'probe_read__verified', type: 'boolean', required: false }
	]
};

async function publishFixture(options: {
	completeRows?: string[][];
	verifiedRows?: string[][];
} = {}) {
	const root = await mkdtemp(join(tmpdir(), 'gate-bool-fixture-'));
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
	const snap = async (relation: string, role: string, full: boolean, keys: string[][]) => ({
		relation,
		role,
		complete: full,
		full,
		format: 'json',
		...await object(keys.map((key) => ({ key })))
	});
	const completeRows = options.completeRows ?? [['r1', 'true'], ['r2', 'false']];
	const verifiedRows = options.verifiedRows ?? [['r1', 'true'], ['r2', 'false']];
	const snapshots = [
		await snap('widget', 'reader', true, [['w-1'], ['w-2']]),
		await snap('widget__name', 'reader', true, [['w-1', 'api'], ['w-2', 'web']]),
		await snap('probe_read', 'reader', true, [['r1'], ['r2'], ['r3']]),
		await snap('probe_read__complete', 'reader', true, completeRows),
		await snap('probe_read__verified', 'reader', false, verifiedRows),
		await snap('widget', 'scoped', true, [['w-1']]),
		await snap('widget__name', 'scoped', true, [['w-1', 'api']])
	];
	const bundleKey = pack + '/bundles/definition.json';
	const manifest = {
		id: 'm-1',
		epoch: 1,
		access_semantics: 2,
		knowledge_time: '2026-01-01T00:00:00Z',
		snapshots,
		compiled: [{
			file: 'bundle/schema-bundle.json',
			uri: 's3://test-store/' + bundleKey,
			sha256: await write(bundleKey, baseBundle)
		}]
	};
	const manifestKey = pack + '/manifests/m-1.json';
	await write(pack + '/heads/9999999999999999998.json', {
		format: 'rezono.head/1',
		manifest: 'm-1',
		epoch: 1,
		sha256: await write(manifestKey, manifest)
	});
	return { root };
}

const postAsk = (text: string) => new Request('http://rezono.local/sample/m-1/ask', {
	method: 'POST',
	body: JSON.stringify({ text })
});

test('bundles with boolean attributes serve /ask on other kinds and on boolean slots', async (t) => {
	const { root } = await publishFixture();
	t.after(() => rm(root, { recursive: true, force: true }));
	const reader = await openLocalGate(root, 'reader');
	const scoped = await openLocalGate(root, 'scoped');

	// Querying a different kind succeeds even though the role schema includes boolean attributes.
	const widgetRes = await reader(postAsk('ask Widget where name = "api"'));
	const widgetAnswer = await widgetRes.json();
	assert.equal(widgetRes.status, 200, JSON.stringify(widgetAnswer));
	assert.deepEqual(widgetAnswer.nodes.map((n: { key: string }) => JSON.parse(n.key)), [['w-1']]);

	// Filtering directly on a closed optional boolean attribute: true matches, false excludes, absent is n/a.
	const trueRes = await reader(postAsk('ask ProbeRead where complete'));
	const trueAnswer = await trueRes.json();
	assert.equal(trueRes.status, 200, JSON.stringify(trueAnswer));
	assert.deepEqual(trueAnswer.nodes.map((n: { key: string }) => JSON.parse(n.key)), [['r1']]);
	assert.equal(trueAnswer.counts.not_applicable, 1);
	assert.deepEqual(trueAnswer.undecided, []);

	const falseRes = await reader(postAsk('ask ProbeRead where complete = false'));
	const falseAnswer = await falseRes.json();
	assert.equal(falseRes.status, 200, JSON.stringify(falseAnswer));
	assert.deepEqual(falseAnswer.nodes.map((n: { key: string }) => JSON.parse(n.key)), [['r2']]);
	assert.equal(falseAnswer.counts.not_applicable, 1);

	const notRes = await reader(postAsk('ask ProbeRead where not complete'));
	const notAnswer = await notRes.json();
	assert.equal(notRes.status, 200, JSON.stringify(notAnswer));
	assert.deepEqual(notAnswer.nodes.map((n: { key: string }) => JSON.parse(n.key)), [['r2']]);

	const naRes = await reader(postAsk('ask ProbeRead where complete is n/a'));
	const naAnswer = await naRes.json();
	assert.equal(naRes.status, 200, JSON.stringify(naAnswer));
	assert.deepEqual(naAnswer.nodes.map((n: { key: string }) => JSON.parse(n.key)), [['r3']]);

	// Showing a boolean slot emits JS booleans under a Bool output slot.
	const showRes = await reader(postAsk('ask ProbeRead where true show complete'));
	const showAnswer = await showRes.json();
	assert.equal(showRes.status, 200, JSON.stringify(showAnswer));
	assert.equal(showAnswer.dataset.schema.kinds.Answer.slots.c1.type, 'Bool');
	assert.deepEqual(
		showAnswer.dataset.rows.map((r: { $id: string; c1: unknown }) => [r.$id, r.c1]),
		[['r1', true], ['r2', false], ['r3', { $na: '' }]]
	);

	// Partial boolean snapshot treats missing rows as unknown not_read_in_full.
	const partialRes = await reader(postAsk('ask ProbeRead where verified'));
	const partialAnswer = await partialRes.json();
	assert.equal(partialRes.status, 200, JSON.stringify(partialAnswer));
	assert.deepEqual(partialAnswer.nodes.map((n: { key: string }) => JSON.parse(n.key)), [['r1']]);
	assert.deepEqual(
		partialAnswer.undecided.map((u: { binder: string; state: string; reason?: string }) => [u.binder, u.state, u.reason]),
		[['r3', 'unknown', 'not_read_in_full']]
	);

	// Role without access to the boolean kind still queries its own kind and cannot see ProbeRead.
	assert.equal((await scoped(postAsk('ask Widget where name = "api"'))).status, 200);
	assert.equal((await scoped(postAsk('ask ProbeRead where complete'))).status, 400);
});

test('invalid boolean cell text fails closed without leaking or coercing', async (t) => {
	for (const bad of ['yes', '1', '0', 'TRUE', 'False', '', ' true']) {
		const { root } = await publishFixture({ completeRows: [['r1', bad]] });
		t.after(() => rm(root, { recursive: true, force: true }));
		const reader = await openLocalGate(root, 'reader');

		// Querying the boolean slot with corrupt cell text returns 500 without exposing raw cell text.
		const res = await reader(postAsk('ask ProbeRead where complete'));
		const body = await res.json();
		assert.equal(res.status, 500, `expected 500 for ${JSON.stringify(bad)}, got ${res.status}`);
		assert.deepEqual(body, { error: 'publication unavailable' });
	}

	// Direct rowsOf / ask check rejects malformed row arities and unexpected text with AskError(500).
	const view = roleSchema(baseBundle as unknown as Bundle, [
		{ relation: 'probe_read', complete: true },
		{ relation: 'probe_read__complete', complete: true }
	]);
	assert.equal(view.schema.kinds.ProbeRead.slots.complete.type, 'Bool');

	const cases: string[][][] = [
		[['r1', 'yes']],
		[['r1', 'TRUE']],
		[['r1']],
		[['r1', 'true', 'extra']]
	];
	for (const badRows of cases) {
		const read = async (relation: string) => ({
			rows: (relation === 'probe_read' ? [['r1']] : badRows).map((key) => ({ key }))
		});
		await assert.rejects(
			rowsOf(view, new Map([['ProbeRead', new Set(['complete'])]]), read, { left: 100 }),
			(err: unknown) => err instanceof AskError && err.status === 500
		);
	}
});

test('multivalued boolean attributes evaluate cleanly', async () => {
	const bundle = {
		pack: { id: 'sample', base: 'https://example.org/sample/' },
		kinds: [{ id: 'item', class: 'Item', world: 'closed' }],
		attributes: [
			{ id: 'item__flags', kind: 'item', name: 'flags', table: 'item__flags', type: 'boolean', required: false, multivalued: true }
		]
	};
	const view = roleSchema(bundle as unknown as Bundle, [
		{ relation: 'item', complete: true },
		{ relation: 'item__flags', complete: true }
	]);
	assert.equal(view.schema.kinds.Item.slots.flags.type, 'Bool');
	assert.equal(view.schema.kinds.Item.slots.flags.card, '*');

	const tables: Record<string, string[][]> = {
		item: [['a'], ['b'], ['c']],
		item__flags: [['a', 'true'], ['a', 'false'], ['b', 'false']]
	};
	const res = await ask({
		text: 'ask Item where true in flags',
		manifest: 'm-1',
		view,
		read: async (relation) => ({ rows: (tables[relation] ?? []).map((key) => ({ key })) }),
		budget: { rows: 100, steps: 10_000 },
		limit: 50
	});
	assert.ok('answer' in res, JSON.stringify(res));
	assert.deepEqual(res.answer.nodes.map((n) => JSON.parse(n.key)), [['a']]);
});

test('multi-hop Bool type aliases parse and evaluate as booleans', async () => {
	const schema: Schema = {
		rezono: '1.0',
		pack: 'sample',
		base: 'https://example.org/sample/',
		types: {
			Flag: { of: 'Bool' },
			MidFlag: { of: 'Flag' },
			DeepFlag: { of: 'MidFlag' }
		},
		kinds: {
			Item: {
				world: 'closed',
				id: { type: 'Text' },
				slots: {
					single_hop: { type: 'Flag', card: '?', states: ['known', 'not_applicable'] },
					multi_hop: { type: 'DeepFlag', card: '?', states: ['known', 'not_applicable'] },
					many_hop: { type: 'DeepFlag', card: '*', states: ['known'] }
				}
			}
		}
	};
	const view: View = {
		schema,
		kinds: new Map([['Item', { relation: 'item' }]]),
		slots: new Map([['Item', new Map([
			['single_hop', { relation: 'item__single_hop', partial: false }],
			['multi_hop', { relation: 'item__multi_hop', partial: false }],
			['many_hop', { relation: 'item__many_hop', partial: false }]
		])]]),
		reads: new Set(['item', 'item__single_hop', 'item__multi_hop', 'item__many_hop']),
		trees: new Set()
	};
	const tables: Record<string, string[][]> = {
		item: [['a'], ['b'], ['c']],
		item__single_hop: [['a', 'true'], ['b', 'false']],
		item__multi_hop: [['a', 'true'], ['b', 'false']],
		item__many_hop: [['a', 'true'], ['a', 'false'], ['b', 'false']]
	};
	const read = async (relation: string) => ({
		rows: (tables[relation] ?? []).map((key) => ({ key }))
	});

	const rows = await rowsOf(view, new Map([['Item', new Set(['single_hop', 'multi_hop', 'many_hop'])]]), read, { left: 100 });
	assert.deepEqual(rows, [
		{ $kind: 'Item', $id: 'a', single_hop: true, multi_hop: true, many_hop: [true, false] },
		{ $kind: 'Item', $id: 'b', single_hop: false, multi_hop: false, many_hop: [false] },
		{ $kind: 'Item', $id: 'c', single_hop: { $na: '' }, multi_hop: { $na: '' }, many_hop: [] }
	]);

	const res = await ask({
		text: 'ask Item where multi_hop and true in many_hop show multi_hop',
		manifest: 'm-1',
		view,
		read,
		budget: { rows: 100, steps: 10_000 },
		limit: 50
	});
	assert.ok('answer' in res, JSON.stringify(res));
	assert.deepEqual(res.answer.nodes.map((n) => JSON.parse(n.key)), [['a']]);
	assert.equal(res.answer.dataset.schema.kinds.Answer.slots.c1.type, 'Bool');
	assert.deepEqual(res.answer.dataset.rows.map((r) => [r.$id, (r as Record<string, unknown>).c1]), [['a', true]]);

	// Invalid cell text on a multi-hop Bool alias still fails closed with AskError(500).
	const badRead = async (relation: string) => ({
		rows: (relation === 'item' ? [['a']] : [['a', 'yes']]).map((key) => ({ key }))
	});
	await assert.rejects(
		rowsOf(view, new Map([['Item', new Set(['multi_hop'])]]), badRead, { left: 100 }),
		(err: unknown) => err instanceof AskError && err.status === 500
	);
});

test('cyclic, prototype, and unknown type chains fail closed without coercing', async () => {
	const readView = async (
		types: Record<string, unknown> | undefined,
		slots: Record<string, string>,
		cell = 'true'
	) => {
		const slotNames = Object.keys(slots);
		const view: View = {
			schema: {
				rezono: '1.0',
				pack: 'sample',
				base: 'https://example.org/sample/',
				...(types ? { types: types as Record<string, TypeDef> } : {}),
				kinds: {
					Item: {
						world: 'closed',
						id: { type: 'Text' },
						slots: Object.fromEntries(slotNames.map((name) => [
							name,
							{ type: slots[name], card: '?' as const, states: ['known' as const, 'not_applicable' as const] }
						]))
					}
				}
			},
			kinds: new Map([['Item', { relation: 'item' }]]),
			slots: new Map([['Item', new Map(slotNames.map((name) => [name, { relation: `item__${name}`, partial: false }]))]]),
			reads: new Set(['item', ...slotNames.map((name) => `item__${name}`)]),
			trees: new Set()
		};
		const read = async (relation: string) => ({
			rows: (relation === 'item' ? [['a']] : [['a', cell]]).map((key) => ({ key }))
		});
		const rows = await rowsOf(view, new Map([['Item', new Set(slotNames)]]), read, { left: 100 });
		assert.equal(rows.length, 1);
		return rows[0];
	};

	// Bool cycles starting at Bool itself, entering Bool, or looping between aliases all fail closed as text.
	assert.deepEqual(
		await readView({ Bool: { of: 'Bool' } }, { self_bool: 'Bool' }),
		{ $kind: 'Item', $id: 'a', self_bool: 'true' }
	);
	assert.deepEqual(
		await readView(
			{
				SelfLoop: { of: 'SelfLoop' },
				LoopA: { of: 'LoopB' },
				LoopB: { of: 'LoopA' },
				CycleBool: { of: 'Bool' },
				Bool: { of: 'CycleBool' },
				AliasToCycleBool: { of: 'Bool' },
				UnknownAlias: { of: 'MissingBase' },
				EmptyOf: { of: '' },
				MissingOf: {}
			},
			{
				self_loop: 'SelfLoop',
				two_loop: 'LoopA',
				direct_bool_cycle: 'Bool',
				cycle_bool: 'CycleBool',
				alias_to_bool_cycle: 'AliasToCycleBool',
				unknown_direct: 'MissingBase',
				unknown_alias: 'UnknownAlias',
				empty_of: 'EmptyOf',
				missing_of: 'MissingOf'
			}
		),
		{
			$kind: 'Item',
			$id: 'a',
			self_loop: 'true',
			two_loop: 'true',
			direct_bool_cycle: 'true',
			cycle_bool: 'true',
			alias_to_bool_cycle: 'true',
			unknown_direct: 'true',
			unknown_alias: 'true',
			empty_of: 'true',
			missing_of: 'true'
		}
	);

	// Prototype keys as slot.type or type.of fail closed even if present as own JSON properties on schema.types.
	const protoTypes = JSON.parse(
		'{"__proto__":{"of":"Bool"},"constructor":{"of":"Bool"},"toString":{"of":"Bool"},"prototype":{"of":"Bool"},'
		+ '"ProtoAlias":{"of":"__proto__"},"CtorAlias":{"of":"constructor"},"ToStringAlias":{"of":"toString"}}'
	) as Record<string, unknown>;
	assert.deepEqual(
		await readView(protoTypes, {
			proto_slot: '__proto__',
			ctor_slot: 'constructor',
			tostring_slot: 'toString',
			prototype_slot: 'prototype',
			proto_alias: 'ProtoAlias',
			ctor_alias: 'CtorAlias',
			tostring_alias: 'ToStringAlias'
		}),
		{
			$kind: 'Item',
			$id: 'a',
			proto_slot: 'true',
			ctor_slot: 'true',
			tostring_slot: 'true',
			prototype_slot: 'true',
			proto_alias: 'true',
			ctor_alias: 'true',
			tostring_alias: 'true'
		}
	);

	// Cycles through Integer itself also fail closed as text.
	assert.deepEqual(
		await readView(
			{ Integer: { of: 'IntLoop', min: '0', max: '100' }, IntLoop: { of: 'Integer' } },
			{ count: 'Integer' },
			'42'
		),
		{ $kind: 'Item', $id: 'a', count: '42' }
	);
});

test('multi-hop integer bounds validate every hop and fail closed on inverted, malformed, or widened bounds', async () => {
	type BoundedType = TypeDef & { min?: unknown; max?: unknown };
	const types: Record<string, BoundedType> = {
		SmallInt: { of: 'Integer', min: '0', max: '100' },
		AliasSmallInt: { of: 'SmallInt' },
		TighterInt: { of: 'SmallInt', min: '10', max: '50' },
		BaseInt: { of: 'Integer' },
		NarrowInt: { of: 'BaseInt', min: '-10', max: '10' },
		WideInt: { of: 'Integer', min: '-9223372036854775808', max: '9223372036854775807' },
		AliasWideInt: { of: 'WideInt' },
		NarrowFromWide: { of: 'WideInt', min: '0', max: '100' },
		ExactSafe: { of: 'Integer', min: '-9007199254740991', max: '9007199254740991' },
		OnlyMin: { of: 'Integer', min: '0' },
		SplitBounds: { of: 'OnlyMin', max: '100' },
		// Invalid / fail-closed cases:
		Inverted: { of: 'Integer', min: '100', max: '0' },
		OutOfRangeInverted: { of: 'Integer', min: '99999999999999999999', max: '10' },
		NegOutOfRangeInverted: { of: 'Integer', min: '-10', max: '-99999999999999999999' },
		LoOutOfSafe: { of: 'Integer', min: '-9007199254740992', max: '0' },
		HiOutOfSafe: { of: 'Integer', min: '0', max: '9007199254740992' },
		EmptyBounds: { of: 'Integer', min: '', max: '' },
		FloatBounds: { of: 'Integer', min: '1.5', max: '10' },
		PaddedBounds: { of: 'Integer', min: ' 0 ', max: '10' },
		NumericBounds: { of: 'Integer', min: 0, max: 10 },
		NullMin: { of: 'Integer', min: null, max: '10' },
		BadParent: { of: 'Integer', min: '1.5', max: '100' },
		ChildOfBadParent: { of: 'BadParent', min: '0', max: '10' },
		NullParent: { of: 'Integer', min: null, max: '100' },
		ChildOfNullParent: { of: 'NullParent', min: '0', max: '10' },
		InvertedParent: { of: 'Integer', min: '100', max: '0' },
		ChildOfInvertedParent: { of: 'InvertedParent', min: '1', max: '5' },
		WidenedLo: { of: 'SmallInt', min: '-1' },
		WidenedHi: { of: 'SmallInt', max: '101' },
		WidenedBoth: { of: 'SmallInt', min: '-5', max: '200' },
		ContradictoryChild: { of: 'OnlyMin', max: '-1' }
	};
	const slotMap: Record<string, string> = {
		inherited_num: 'AliasSmallInt',
		tighter_num: 'TighterInt',
		narrow_num: 'NarrowInt',
		narrow_from_wide: 'NarrowFromWide',
		exact_safe: 'ExactSafe',
		split_bounds: 'SplitBounds',
		wide_num: 'AliasWideInt',
		inverted: 'Inverted',
		out_of_range_inverted: 'OutOfRangeInverted',
		neg_out_of_range_inverted: 'NegOutOfRangeInverted',
		lo_out_of_safe: 'LoOutOfSafe',
		hi_out_of_safe: 'HiOutOfSafe',
		empty_bounds: 'EmptyBounds',
		float_bounds: 'FloatBounds',
		padded_bounds: 'PaddedBounds',
		numeric_bounds: 'NumericBounds',
		null_min: 'NullMin',
		child_of_bad_parent: 'ChildOfBadParent',
		child_of_null_parent: 'ChildOfNullParent',
		child_of_inverted_parent: 'ChildOfInvertedParent',
		widened_lo: 'WidenedLo',
		widened_hi: 'WidenedHi',
		widened_both: 'WidenedBoth',
		contradictory_child: 'ContradictoryChild'
	};
	const slotNames = Object.keys(slotMap);
	const view: View = {
		schema: {
			rezono: '1.0',
			pack: 'sample',
			base: 'https://example.org/sample/',
			types: types as Record<string, TypeDef>,
			kinds: {
				Item: {
					world: 'closed',
					id: { type: 'Text' },
					slots: Object.fromEntries(slotNames.map((name) => [
						name,
						{ type: slotMap[name], card: '?' as const, states: ['known' as const, 'not_applicable' as const] }
					]))
				}
			}
		},
		kinds: new Map([['Item', { relation: 'item' }]]),
		slots: new Map([['Item', new Map(slotNames.map((name) => [name, { relation: `item__${name}`, partial: false }]))]]),
		reads: new Set(['item', ...slotNames.map((name) => `item__${name}`)]),
		trees: new Set()
	};
	const read = async (relation: string) => ({
		rows: (relation === 'item' ? [['a']] : [['a', relation === 'item__narrow_num' ? '-7' : '42']]).map((key) => ({ key }))
	});

	const rows = await rowsOf(view, new Map([['Item', new Set(slotNames)]]), read, { left: 100 });
	assert.deepEqual(rows, [{
		$kind: 'Item',
		$id: 'a',
		// Valid safe bounded integer chains emit JSON numbers:
		inherited_num: 42,
		tighter_num: 42,
		narrow_num: -7,
		narrow_from_wide: 42,
		exact_safe: 42,
		split_bounds: 42,
		// Wide, inverted, malformed, non-integer, bad-parent, and widened bounds fail closed as text:
		wide_num: '42',
		inverted: '42',
		out_of_range_inverted: '42',
		neg_out_of_range_inverted: '42',
		lo_out_of_safe: '42',
		hi_out_of_safe: '42',
		empty_bounds: '42',
		float_bounds: '42',
		padded_bounds: '42',
		numeric_bounds: '42',
		null_min: '42',
		child_of_bad_parent: '42',
		child_of_null_parent: '42',
		child_of_inverted_parent: '42',
		widened_lo: '42',
		widened_hi: '42',
		widened_both: '42',
		contradictory_child: '42'
	}]);
});
