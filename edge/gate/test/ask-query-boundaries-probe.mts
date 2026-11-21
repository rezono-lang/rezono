import { createHash } from 'node:crypto';
import { mkdir, mkdtemp, readdir, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import type { Bundle } from '../../../contracts/typescript/generated/bundle.ts';
import { ask as evalAsk, roleSchema, type Asking } from '../src/expr.ts';
import { openLocalGate } from '../src/local.ts';

type Reply = { status: number; body: unknown };

async function postJson(
	gate: (req: Request) => Promise<Response>,
	path: string,
	payload: unknown,
	method = 'POST'
): Promise<Reply> {
	const res = await gate(new Request('http://rezono.local' + path, {
		method,
		body: JSON.stringify(payload)
	}));
	const text = await res.text();
	try {
		return { status: res.status, body: JSON.parse(text) };
	} catch {
		return { status: res.status, body: text };
	}
}

async function storeFingerprint(root: string): Promise<string> {
	const entries: [string, string][] = [];
	const walk = async (dir: string, rel: string) => {
		const items = (await readdir(dir, { withFileTypes: true })).sort((a, b) => (a.name < b.name ? -1 : a.name > b.name ? 1 : 0));
		for (const item of items) {
			const full = join(dir, item.name);
			const next = rel ? `${rel}/${item.name}` : item.name;
			if (item.isDirectory()) await walk(full, next);
			else {
				const bytes = await readFile(full);
				entries.push([next, createHash('sha256').update(bytes).digest('hex')]);
			}
		}
	};
	await walk(root, '');
	return createHash('sha256').update(JSON.stringify(entries)).digest('hex');
}

function makeWriter(root: string, pack: string) {
	const write = async (key: string, value: unknown) => {
		const path = join(root, key);
		await mkdir(dirname(path), { recursive: true });
		const bytes = JSON.stringify(value);
		await writeFile(path, bytes);
		return createHash('sha256').update(bytes).digest('hex');
	};
	const object = async (data: unknown) => {
		const sha256 = createHash('sha256').update(JSON.stringify(data)).digest('hex');
		const key = `${pack}/objects/${sha256}.json`;
		await write(key, data);
		return { uri: `s3://test-store/${key}`, sha256 };
	};
	const snap = async (relation: string, role: string, full: boolean, keys: string[][]) => ({
		relation,
		role,
		complete: full,
		full,
		format: 'json',
		...await object(keys.map((key) => ({ key })))
	});
	return { write, object, snap };
}

async function runGrouped() {
	const pack = 'sample';
	const root = await mkdtemp(join(tmpdir(), 'gate-ask-grouped-'));
	try {
		const { write, snap } = makeWriter(root, pack);
		const bundle = {
			pack: { id: pack, base: 'https://example.org/sample/' },
			kinds: [
				{ id: 'bucket', class: 'Bucket', world: 'closed', id_type: 'text' },
				{ id: 'entry', class: 'Entry', world: 'closed', id_type: 'text' }
			],
			arrows: [
				{
					id: 'entry.bucket', kind: 'entry', name: 'bucket', table: 'entry__bucket',
					target: 'bucket', required: false, multivalued: false, world: 'closed'
				}
			],
			attributes: [
				{
					id: 'entry.weight', kind: 'entry', name: 'weight', table: 'entry__weight',
					type: 'integer', schema_type: 'integer', minimum: '0', maximum: '1000',
					required: false, multivalued: false, world: 'closed'
				},
				{
					id: 'entry.score', kind: 'entry', name: 'score', table: 'entry__score',
					type: 'integer', schema_type: 'integer', minimum: '0', maximum: '1000',
					required: true, multivalued: false, world: 'closed'
				},
				{
					id: 'entry.partial_weight', kind: 'entry', name: 'partial_weight', table: 'entry__partial_weight',
					type: 'integer', schema_type: 'integer', minimum: '0', maximum: '1000',
					required: false, multivalued: false, world: 'closed'
				}
			],
			enums: [],
			questions: []
		};
		const snapshots = [
			await snap('bucket', 'reader', true, [['g-absent'], ['g-invalid'], ['g-ok'], ['g-unknown']]),
			await snap('entry', 'reader', true, [
				['e1'], ['e2'], ['e3'], ['e4'], ['e5'], ['e6'], ['e7'], ['e8'], ['e9']
			]),
			// e9 has no bucket -> absent (n/a) group key, must be counted in not_applicable, never grouped.
			await snap('entry__bucket', 'reader', true, [
				['e1', 'g-ok'], ['e2', 'g-ok'],
				['e3', 'g-absent'], ['e4', 'g-absent'],
				['e5', 'g-unknown'], ['e6', 'g-unknown'],
				['e7', 'g-invalid'], ['e8', 'g-invalid']
			]),
			// e4 omits optional weight -> n/a; e7 has weight=0 for invalid 100 / weight.
			await snap('entry__weight', 'reader', true, [
				['e1', '10'], ['e2', '30'],
				['e3', '20'],
				['e5', '5'], ['e6', '15'],
				['e7', '0'], ['e8', '2'],
				['e9', '7']
			]),
			// e6 omits required score -> unknown.
			await snap('entry__score', 'reader', true, [
				['e1', '10'], ['e2', '30'],
				['e3', '20'], ['e4', '40'],
				['e5', '5'],
				['e7', '1'], ['e8', '2'],
				['e9', '7']
			]),
			// Partial snapshot for reader: aggregates over partial_weight must be refused with R004.
			await snap('entry__partial_weight', 'reader', false, [['e1', '10']]),
			// Scoped role reads only partial entry snapshot (e1 only).
			await snap('bucket', 'scoped', true, [['g-ok']]),
			await snap('entry', 'scoped', false, [['e1']]),
			await snap('entry__bucket', 'scoped', false, [['e1', 'g-ok']]),
			await snap('entry__weight', 'scoped', false, [['e1', '10']])
		];
		const bundleKey = `${pack}/bundles/definition.json`;
		const manifest = {
			id: 'm-1',
			epoch: 1,
			access_semantics: 2,
			knowledge_time: '2026-01-01T00:00:00Z',
			snapshots,
			compiled: [{
				file: 'bundle/schema-bundle.json',
				uri: `s3://test-store/${bundleKey}`,
				sha256: await write(bundleKey, bundle)
			}]
		};
		const manifestSha = await write(`${pack}/manifests/m-1.json`, manifest);
		await write(`${pack}/heads/9999999999999999998.json`, {
			format: 'rezono.head/1', manifest: 'm-1', epoch: 1, sha256: manifestSha
		});

		const reader = await openLocalGate(root, 'reader');
		const scoped = await openLocalGate(root, 'scoped');

		return {
			baseline_ok: await postJson(reader, '/sample/m-1/ask', {
				text: 'ask Entry where weight > 10 show weight'
			}),
			baseline_unknown_kind: await postJson(scoped, '/sample/m-1/ask', {
				text: 'ask Entry where score > 0 show score'
			}),
			grouped_weight: await postJson(reader, '/sample/m-1/ask', {
				text: 'ask e: Entry where true show e.bucket, count(), sum(e.weight), min(e.weight), max(e.weight) group by e.bucket'
			}),
			grouped_score_unknown: await postJson(reader, '/sample/m-1/ask', {
				text: 'ask e: Entry where true show e.bucket, sum(e.score), min(e.score), max(e.score) group by e.bucket'
			}),
			grouped_invalid_div: await postJson(reader, '/sample/m-1/ask', {
				text: 'ask e: Entry where true show e.bucket, sum(100 / e.weight), min(100 / e.weight), max(100 / e.weight) group by e.bucket'
			}),
			counter_partial_slot: await postJson(reader, '/sample/m-1/ask', {
				text: 'ask e: Entry where true show e.bucket, sum(e.partial_weight) group by e.bucket'
			}),
			counter_scoped_partial: await postJson(scoped, '/sample/m-1/ask', {
				text: 'ask e: Entry where true show e.bucket, count(), sum(e.weight) group by e.bucket'
			})
		};
	} finally {
		await rm(root, { recursive: true, force: true });
	}
}

async function runCrossPack() {
	const pack = 'composite';
	const root = await mkdtemp(join(tmpdir(), 'gate-ask-cross-pack-'));
	try {
		const { write, object, snap } = makeWriter(root, pack);
		const bundle = {
			pack: { id: pack, base: 'https://example.org/composite/' },
			imports: [
				{ name: 'pack_alpha', sha256: 'a'.repeat(64) },
				{ name: 'pack_beta', sha256: 'b'.repeat(64) }
			],
			kinds: [{ id: 'item', class: 'Item', world: 'closed', id_type: 'text' }],
			attributes: [],
			arrows: [],
			enums: [],
			relations: [
				{
					id: 'alpha_tag',
					world: 'closed',
					columns: [
						{ name: 'item', type: 'string', semantic: { case: 'ref', base: 'string', target: 'item' } },
						{ name: 'tag', type: 'string' }
					]
				},
				{
					id: 'beta_metric',
					world: 'closed',
					columns: [
						{ name: 'item', type: 'string', semantic: { case: 'ref', base: 'string', target: 'item' } },
						{ name: 'tier', type: 'string' }
					]
				}
			],
			questions: []
		};
		const rulesIr = {
			relations: [
				{ name: 'item', key: [{ name: 'id' }] },
				{ name: 'alpha_tag', key: [{ name: 'item' }, { name: 'tag' }] },
				{ name: 'beta_metric', key: [{ name: 'item' }, { name: 'tier' }] }
			],
			rules: [
				{ id: 'pack_alpha.tag_rule', body: [{ relation: 'item', terms: ['?x'], polarity: 'positive' }] },
				{ id: 'pack_beta.metric_rule', body: [{ relation: 'item', terms: ['?x'], polarity: 'positive' }] }
			]
		};
		const witnessI1Alpha = {
			conclusion: { relation: 'alpha_tag', key: '["i-1","gold"]' },
			rule_id: 'pack_alpha.tag_rule',
			bindings: [{ variable: '?x', value: 'i-1' }],
			premises: [{ row: { relation: 'item', key: '["i-1"]' }, polarity: 'positive', stratum: 0 }]
		};
		const witnessI2Alpha = {
			conclusion: { relation: 'alpha_tag', key: '["i-2","silver"]' },
			rule_id: 'pack_alpha.tag_rule',
			bindings: [{ variable: '?x', value: 'i-2' }],
			premises: [{ row: { relation: 'item', key: '["i-2"]' }, polarity: 'positive', stratum: 0 }]
		};
		const witnessI1Beta = {
			conclusion: { relation: 'beta_metric', key: '["i-1","high"]' },
			rule_id: 'pack_beta.metric_rule',
			bindings: [{ variable: '?x', value: 'i-1' }],
			premises: [{ row: { relation: 'item', key: '["i-1"]' }, polarity: 'positive', stratum: 0 }]
		};
		const witnessI2Beta = {
			conclusion: { relation: 'beta_metric', key: '["i-2","low"]' },
			rule_id: 'pack_beta.metric_rule',
			bindings: [{ variable: '?x', value: 'i-2' }],
			premises: [{ row: { relation: 'item', key: '["i-2"]' }, polarity: 'positive', stratum: 0 }]
		};

		const snapshots = [
			await snap('item', 'reader', true, [['i-1'], ['i-2']]),
			await snap('alpha_tag', 'reader', true, [['i-1', 'gold'], ['i-2', 'silver']]),
			await snap('beta_metric', 'reader', true, [['i-1', 'high'], ['i-2', 'low']]),
			// Role `alpha` reads only pack_alpha's relation, never pack_beta's.
			await snap('item', 'alpha', true, [['i-1'], ['i-2']]),
			await snap('alpha_tag', 'alpha', true, [['i-1', 'gold'], ['i-2', 'silver']]),
			// Role `narrow` reads both imported relations but only for i-1.
			await snap('item', 'narrow', false, [['i-1']]),
			await snap('alpha_tag', 'narrow', false, [['i-1', 'gold']]),
			await snap('beta_metric', 'narrow', false, [['i-1', 'high']])
		];
		const readerWitnesses = await object({
			witnesses: [witnessI1Alpha, witnessI2Alpha, witnessI1Beta, witnessI2Beta],
			hidden: []
		});
		const alphaWitnesses = await object({
			witnesses: [witnessI1Alpha, witnessI2Alpha],
			hidden: []
		});
		const narrowWitnesses = await object({
			witnesses: [witnessI1Alpha, witnessI1Beta],
			hidden: []
		});
		const bundleKey = `${pack}/bundles/definition.json`;
		const rulesKey = `${pack}/bundles/rules.json`;
		const manifest = {
			id: 'm-1',
			epoch: 1,
			access_semantics: 2,
			knowledge_time: '2026-01-01T00:00:00Z',
			snapshots,
			witnesses: [
				{ role: 'reader', ...readerWitnesses },
				{ role: 'alpha', ...alphaWitnesses },
				{ role: 'narrow', ...narrowWitnesses }
			],
			compiled: [
				{ file: 'bundle/schema-bundle.json', uri: `s3://test-store/${bundleKey}`, sha256: await write(bundleKey, bundle) },
				{ file: 'ir/rules.json', uri: `s3://test-store/${rulesKey}`, sha256: await write(rulesKey, rulesIr) }
			]
		};
		const manifestSha = await write(`${pack}/manifests/m-1.json`, manifest);
		await write(`${pack}/heads/9999999999999999998.json`, {
			format: 'rezono.head/1', manifest: 'm-1', epoch: 1, sha256: manifestSha
		});

		const reader = await openLocalGate(root, 'reader');
		const alpha = await openLocalGate(root, 'alpha');
		const narrow = await openLocalGate(root, 'narrow');

		const joinQuery = 'ask a: AlphaTag, b: BetaMetric where a.item = b.item show a.item, a.tag, b.tier';
		return {
			baseline_single_pack: await postJson(reader, '/composite/m-1/ask', {
				text: 'ask AlphaTag where tag = "gold" show item, tag'
			}),
			baseline_unauthorized_single: await postJson(alpha, '/composite/m-1/ask', {
				text: 'ask BetaMetric where true show item'
			}),
			reader_join: await postJson(reader, '/composite/m-1/ask', { text: joinQuery }),
			alpha_only_join: await postJson(alpha, '/composite/m-1/ask', { text: joinQuery }),
			narrow_join: await postJson(narrow, '/composite/m-1/ask', { text: joinQuery })
		};
	} finally {
		await rm(root, { recursive: true, force: true });
	}
}

async function runLocalRule() {
	const pack = 'sample';
	const root = await mkdtemp(join(tmpdir(), 'gate-ask-local-rule-'));
	try {
		const { write, snap } = makeWriter(root, pack);
		const bundle = {
			pack: { id: pack, base: 'https://example.org/sample/' },
			kinds: [{ id: 'item', class: 'Item', world: 'closed', id_type: 'text' }],
			attributes: [
				{
					id: 'item.score', kind: 'item', name: 'score', table: 'item__score',
					type: 'integer', schema_type: 'integer', minimum: '0', maximum: '1000',
					required: true, multivalued: false, world: 'closed'
				},
				{
					id: 'item.secret', kind: 'item', name: 'secret', table: 'item__secret',
					type: 'boolean', required: false, multivalued: false, world: 'closed'
				}
			],
			arrows: [],
			enums: [],
			questions: []
		};
		const snapshots = [
			await snap('item', 'reader', true, [['i-1'], ['i-2'], ['i-3'], ['i-4']]),
			// i-4 omits required score -> unknown.
			await snap('item__score', 'reader', true, [['i-1', '80'], ['i-2', '30'], ['i-3', '95']]),
			await snap('item__secret', 'reader', true, [['i-1', 'true'], ['i-2', 'false'], ['i-3', 'true']]),
			// Scoped role cannot see i-3 and has no access to item__secret.
			await snap('item', 'scoped', false, [['i-1'], ['i-2'], ['i-4']]),
			await snap('item__score', 'scoped', false, [['i-1', '80'], ['i-2', '30']])
		];
		const bundleKey = `${pack}/bundles/definition.json`;
		const manifest = {
			id: 'm-1',
			epoch: 1,
			access_semantics: 2,
			knowledge_time: '2026-01-01T00:00:00Z',
			snapshots,
			compiled: [{
				file: 'bundle/schema-bundle.json',
				uri: `s3://test-store/${bundleKey}`,
				sha256: await write(bundleKey, bundle)
			}]
		};
		const manifestSha = await write(`${pack}/manifests/m-1.json`, manifest);
		await write(`${pack}/heads/9999999999999999998.json`, {
			format: 'rezono.head/1', manifest: 'm-1', epoch: 1, sha256: manifestSha
		});

		const beforeStore = await storeFingerprint(root);
		const reader = await openLocalGate(root, 'reader');
		const scoped = await openLocalGate(root, 'scoped');

		const baselineOk = await postJson(reader, '/sample/m-1/ask', {
			text: 'ask Item where score >= 50 show score'
		});
		const baselineWriteRefused = await postJson(reader, '/sample/proposals', { delta: {} });
		const baselineSupposeInAskRefused = await postJson(reader, '/sample/m-1/ask', {
			text: '+ i-2.score = 99'
		});

		const readerLocalRule = await postJson(reader, '/sample/m-1/ask', {
			rules: ['rule high_score(x: Item) when x in Item and x.score >= 50'],
			text: 'ask x: Item where high_score(x) show x.score'
		});
		const scopedLocalRule = await postJson(scoped, '/sample/m-1/ask', {
			rules: ['rule high_score(x: Item) when x in Item and x.score >= 50'],
			text: 'ask x: Item where high_score(x) show x.score'
		});
		const counterWriteInRules = await postJson(reader, '/sample/m-1/ask', {
			rules: ['+ i-2.score = 99'],
			text: 'ask x: Item where x.score >= 50 show x.score'
		});
		const counterUnauthorizedSlot = await postJson(scoped, '/sample/m-1/ask', {
			rules: ['rule leaked(x: Item) when x in Item and x.secret'],
			text: 'ask x: Item where leaked(x) show x.score'
		});
		const counterUnstratified = await postJson(reader, '/sample/m-1/ask', {
			rules: ['rule bad(x: Item) when x in Item and not bad(x)'],
			text: 'ask x: Item where bad(x) show x.score'
		});

		// Direct bounded-step check through expr.ask with a tiny step limit.
		const view = roleSchema(bundle as unknown as Bundle, [
			{ relation: 'item', complete: true, full: true },
			{ relation: 'item__score', complete: true, full: true }
		]);
		const tables: Record<string, string[][]> = {
			item: [['i-1'], ['i-2'], ['i-3'], ['i-4']],
			item__score: [['i-1', '80'], ['i-2', '30'], ['i-3', '95']]
		};
		const budgetCut = await evalAsk({
			text: 'ask x: Item where high_score(x) show x.score',
			rules: ['rule high_score(x: Item) when x in Item and x.score >= 50'],
			manifest: 'm-1',
			view,
			read: async (relation: string) => ({ rows: (tables[relation] ?? []).map((key) => ({ key })) }),
			budget: { rows: 100, steps: 2 },
			limit: 50
		} as Asking & { rules: string[] });

		const afterStore = await storeFingerprint(root);
		return {
			store_unchanged: beforeStore === afterStore,
			baseline_ok: baselineOk,
			baseline_write_refused: baselineWriteRefused,
			baseline_suppose_in_ask_refused: baselineSupposeInAskRefused,
			reader_local_rule: readerLocalRule,
			scoped_local_rule: scopedLocalRule,
			counter_write_in_rules: counterWriteInRules,
			counter_unauthorized_slot: counterUnauthorizedSlot,
			counter_unstratified: counterUnstratified,
			budget_cut: budgetCut
		};
	} finally {
		await rm(root, { recursive: true, force: true });
	}
}

const mode = process.argv[2];
let out: unknown;
if (mode === 'grouped') out = await runGrouped();
else if (mode === 'cross_pack') out = await runCrossPack();
else if (mode === 'local_rule') out = await runLocalRule();
else throw new Error(`unknown probe mode: ${String(mode)}`);

process.stdout.write(JSON.stringify(out) + '\n');
