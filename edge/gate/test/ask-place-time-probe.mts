import { createHash } from 'node:crypto';
import { mkdir, mkdtemp, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { canonicalJson } from '../../../viewer/src/lib/canon.ts';
import { openLocalGate } from '../src/local.ts';

const pack = 'sample';
const definitionSha = 'a'.repeat(64);

const bundle = {
	pack: { id: pack, base: 'https://example.org/sample/' },
	kinds: [
		{ id: 'entry', class: 'Entry', world: 'closed', id_type: 'text' }
	],
	attributes: [
		{ id: 'entry__place', kind: 'entry', name: 'place', table: 'entry__place', type: 'text', required: false },
		{ id: 'entry__valid_from', kind: 'entry', name: 'valid_from', table: 'entry__valid_from', type: 'date', required: false },
		{ id: 'entry__valid_until', kind: 'entry', name: 'valid_until', table: 'entry__valid_until', type: 'date', required: false },
		{ id: 'entry__amount', kind: 'entry', name: 'amount', table: 'entry__amount', type: 'integer', required: false },
		{ id: 'entry__status', kind: 'entry', name: 'status', table: 'entry__status', type: 'text', required: false },
		{ id: 'entry__flag', kind: 'entry', name: 'flag', table: 'entry__flag', type: 'boolean', required: false }
	],
	relations: [
		{
			id: 'eligible',
			world: 'closed',
			columns: [
				{ name: 'entry', type: 'string', semantic: { case: 'ref', base: 'string', target: 'entry' } },
				{ name: 'place', type: 'string' },
				{ name: 'valid_from', type: 'string' },
				{ name: 'valid_until', type: 'string' },
				{ name: 'amount', type: 'integer' }
			]
		}
	],
	enums: [],
	questions: []
};

const ruleDoc = {
	relations: [
		{ name: 'entry', key: [{ name: 'id' }] },
		{ name: 'entry__place', key: [{ name: 'id' }, { name: 'place' }] },
		{ name: 'entry__valid_from', key: [{ name: 'id' }, { name: 'valid_from' }] },
		{ name: 'entry__valid_until', key: [{ name: 'id' }, { name: 'valid_until' }] },
		{ name: 'entry__amount', key: [{ name: 'id' }, { name: 'amount' }] },
		{
			name: 'eligible',
			key: [
				{ name: 'entry' },
				{ name: 'place' },
				{ name: 'valid_from' },
				{ name: 'valid_until' },
				{ name: 'amount' }
			]
		}
	],
	rules: [
		{
			id: 'r_eligible',
			body: [
				{ relation: 'entry', terms: ['?e'], polarity: 'positive' },
				{ relation: 'entry__place', terms: ['?e', '?p'], polarity: 'positive' },
				{ relation: 'entry__valid_from', terms: ['?e', '?vf'], polarity: 'positive' },
				{ relation: 'entry__valid_until', terms: ['?e', '?vu'], polarity: 'positive' },
				{ relation: 'entry__amount', terms: ['?e', '?a'], polarity: 'positive' }
			]
		}
	]
};

interface EpochSpec {
	epoch: number;
	knowledgeTime: string;
	tables: Record<string, { keys: string[][]; full?: boolean }>;
	witnesses: unknown[];
	sources: unknown[];
}

function eligibleWitness(id: string, place: string, validFrom: string, validUntil: string, amount: string) {
	return {
		conclusion: {
			relation: 'eligible',
			key: canonicalJson([id, place, validFrom, validUntil, amount])
		},
		rule_id: 'r_eligible',
		bindings: [
			{ variable: '?e', value: id },
			{ variable: '?p', value: place },
			{ variable: '?vf', value: validFrom },
			{ variable: '?vu', value: validUntil },
			{ variable: '?a', value: amount }
		],
		premises: [
			{ row: { relation: 'entry', key: canonicalJson([id]) }, polarity: 'positive', stratum: 0 },
			{ row: { relation: 'entry__place', key: canonicalJson([id, place]) }, polarity: 'positive', stratum: 0 },
			{ row: { relation: 'entry__valid_from', key: canonicalJson([id, validFrom]) }, polarity: 'positive', stratum: 0 },
			{ row: { relation: 'entry__valid_until', key: canonicalJson([id, validUntil]) }, polarity: 'positive', stratum: 0 },
			{ row: { relation: 'entry__amount', key: canonicalJson([id, amount]) }, polarity: 'positive', stratum: 0 }
		],
		aggregates: []
	};
}

async function withStore<T>(epochs: EpochSpec[], fn: (ask: (manifest: string, text: string) => Promise<{ status: number; body: unknown }>) => Promise<T>): Promise<T> {
	const root = await mkdtemp(join(tmpdir(), 'gate-ask-restrictions-'));
	try {
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
		const bundleKey = pack + '/bundles/definition.json';
		const bundleSha = await write(bundleKey, bundle);
		const rulesKey = pack + '/bundles/rules.json';
		const rulesSha = await write(rulesKey, ruleDoc);

		for (const spec of epochs) {
			const id = 'm-' + spec.epoch;
			const snapshots = [];
			for (const [relation, entry] of Object.entries(spec.tables)) {
				const full = entry.full ?? true;
				snapshots.push({
					relation,
					role: 'reader',
					complete: full,
					full,
					format: 'json',
					...await object(entry.keys.map((key) => ({ key })))
				});
			}
			const witnessRef = await object({ witnesses: spec.witnesses, hidden: [] });
			const sourcesRef = await object(spec.sources);
			const manifest = {
				id,
				epoch: spec.epoch,
				access_semantics: 2,
				definition_sha256: definitionSha,
				knowledge_time: spec.knowledgeTime,
				checks: [{ name: 'rezono:proofs', status: 'green' }],
				snapshots,
				witnesses: [{ role: 'reader', ...witnessRef }],
				fact_sources: [{ role: 'reader', ...sourcesRef }],
				compiled: [
					{ file: 'bundle/schema-bundle.json', uri: 's3://test-store/' + bundleKey, sha256: bundleSha },
					{ file: 'ir/rules.json', uri: 's3://test-store/' + rulesKey, sha256: rulesSha }
				]
			};
			const manifestSha = await write(pack + '/manifests/' + id + '.json', manifest);
			const head = pack + '/heads/' + (10n ** 19n - 1n - BigInt(spec.epoch)).toString().padStart(19, '0') + '.json';
			await write(head, { format: 'rezono.head/1', manifest: id, epoch: spec.epoch, sha256: manifestSha });
		}

		const gate = await openLocalGate(root, 'reader');
		const ask = async (manifest: string, text: string) => {
			const response = await gate(new Request(`http://rezono.local/${pack}/${manifest}/ask`, {
				method: 'POST',
				body: JSON.stringify({ text })
			}));
			return { status: response.status, body: await response.json() };
		};
		return await fn(ask);
	} finally {
		await rm(root, { recursive: true, force: true });
	}
}

async function runAsKnownScenario() {
	const epochs: EpochSpec[] = [
		{
			epoch: 1,
			knowledgeTime: '2026-01-15T00:00:00Z',
			tables: {
				entry: { keys: [['e-1'], ['e-2']] },
				entry__place: { keys: [['e-1', 'north'], ['e-2', 'south']] },
				entry__valid_from: { keys: [['e-1', '2026-01-01'], ['e-2', '2026-01-01']] },
				entry__valid_until: { keys: [['e-1', '2026-07-01'], ['e-2', '2026-07-01']] },
				entry__amount: { keys: [['e-1', '100'], ['e-2', '200']] },
				eligible: {
					keys: [
						['e-1', 'north', '2026-01-01', '2026-07-01', '100'],
						['e-2', 'south', '2026-01-01', '2026-07-01', '200']
					]
				}
			},
			witnesses: [
				eligibleWitness('e-1', 'north', '2026-01-01', '2026-07-01', '100'),
				eligibleWitness('e-2', 'south', '2026-01-01', '2026-07-01', '200')
			],
			sources: [
				{
					row: { relation: 'entry__amount', key: canonicalJson(['e-1', '100']) },
					sources: [{ kind: 'file', name: 'facts-v1', position: 'e-1', revision: 'v1' }]
				}
			]
		},
		{
			epoch: 2,
			knowledgeTime: '2026-03-01T00:00:00Z',
			tables: {
				entry: { keys: [['e-1'], ['e-2']] },
				entry__place: { keys: [['e-1', 'north'], ['e-2', 'south']] },
				entry__valid_from: { keys: [['e-1', '2026-01-01'], ['e-2', '2026-01-01']] },
				entry__valid_until: { keys: [['e-1', '2026-07-01'], ['e-2', '2026-07-01']] },
				entry__amount: { keys: [['e-1', '150'], ['e-2', '200']] },
				eligible: {
					keys: [
						['e-1', 'north', '2026-01-01', '2026-07-01', '150'],
						['e-2', 'south', '2026-01-01', '2026-07-01', '200']
					]
				}
			},
			witnesses: [
				eligibleWitness('e-1', 'north', '2026-01-01', '2026-07-01', '150'),
				eligibleWitness('e-2', 'south', '2026-01-01', '2026-07-01', '200')
			],
			sources: [
				{
					row: { relation: 'entry__amount', key: canonicalJson(['e-1', '150']) },
					sources: [{ kind: 'file', name: 'facts-v2', position: 'e-1', revision: 'v2' }]
				}
			]
		}
	];

	return await withStore(epochs, async (ask) => ({
		current_default: await ask('m-2', 'ask Eligible where entry = e-1 show amount'),
		as_known_earlier: await ask('m-2', 'ask Eligible as known on 2026-02-01 where entry = e-1 show amount'),
		at_north: await ask('m-2', 'ask Eligible at north where true show entry, amount'),
		before_first_known: await ask('m-2', 'ask Eligible as known on 2026-01-01 where entry = e-1 show amount')
	}));
}

async function runDuringScenario() {
	const epochs: EpochSpec[] = [
		{
			epoch: 1,
			knowledgeTime: '2026-01-15T00:00:00Z',
			tables: {
				entry: { keys: [['e-1']] },
				entry__place: { keys: [['e-1', 'north']] },
				entry__valid_from: { keys: [['e-1', '2026-01-01']] },
				entry__valid_until: { keys: [['e-1', '2026-07-01']] },
				entry__amount: { keys: [['e-1', '100']] },
				eligible: { keys: [['e-1', 'north', '2026-01-01', '2026-07-01', '100']] }
			},
			witnesses: [
				eligibleWitness('e-1', 'north', '2026-01-01', '2026-07-01', '100')
			],
			sources: []
		}
	];

	return await withStore(epochs, async (ask) => ({
		baseline: await ask('m-1', 'ask Eligible where entry = e-1 show amount'),
		outside_positive: await ask('m-1', 'ask Eligible during 2027-01-01..<2027-04-01 where entry = e-1 show amount'),
		outside_negated: await ask('m-1', 'ask Eligible during 2027-01-01..<2027-04-01 where not (amount = 100) show amount'),
		inside_valid: await ask('m-1', 'ask Eligible during 2026-03-01..<2026-04-01 where entry = e-1 show amount')
	}));
}

async function runExtentScenario() {
	const twoPlaceEpochs: EpochSpec[] = [
		{
			epoch: 1,
			knowledgeTime: '2026-01-15T00:00:00Z',
			tables: {
				entry: { keys: [['e-north'], ['e-south']], full: true },
				entry__place: { keys: [['e-north', 'north'], ['e-south', 'south']], full: true },
				entry__valid_from: { keys: [['e-north', '2026-01-01'], ['e-south', '2026-01-01']], full: true },
				entry__valid_until: { keys: [['e-north', '2026-07-01'], ['e-south', '2026-07-01']], full: true },
				entry__status: { keys: [['e-north', 'open']], full: false }
			},
			witnesses: [],
			sources: []
		}
	];

	const fourStateEpochs: EpochSpec[] = [
		{
			epoch: 1,
			knowledgeTime: '2026-01-15T00:00:00Z',
			tables: {
				entry: { keys: [['e-north'], ['e-south'], ['e-east'], ['e-west']], full: true },
				entry__place: {
					keys: [
						['e-north', 'north'],
						['e-south', 'south'],
						['e-east', 'east'],
						['e-west', 'west']
					],
					full: true
				},
				entry__valid_from: {
					keys: [
						['e-north', '2026-01-01'],
						['e-south', '2026-01-01'],
						['e-east', '2026-01-01'],
						['e-west', '2026-01-01']
					],
					full: true
				},
				entry__valid_until: {
					keys: [
						['e-north', '2026-07-01'],
						['e-south', '2026-07-01'],
						['e-east', '2026-07-01'],
						['e-west', '2026-07-01']
					],
					full: true
				},
				entry__status: {
					keys: [
						['e-north', 'open'],
						['e-east', 'open'],
						['e-west', 'open']
					],
					full: false
				},
				entry__flag: {
					keys: [
						['e-north', 'true'],
						['e-south', 'true'],
						['e-west', 'true']
					],
					full: true
				}
			},
			witnesses: [],
			sources: []
		}
	];

	const constructive = await withStore(twoPlaceEpochs, async (ask) => ({
		baseline: await ask('m-1', 'ask Entry where status = "open"'),
		extent: await ask('m-1', 'ask Entry where status = "open" show extent')
	}));

	const fourStates = await withStore(fourStateEpochs, async (ask) => ({
		baseline: await ask('m-1', 'ask Entry where when place = "west" then invalid conflict_detected else (status = "open" and flag)'),
		extent: await ask('m-1', 'ask Entry where when place = "west" then invalid conflict_detected else (status = "open" and flag) show extent')
	}));

	return { constructive, four_states: fourStates };
}

const mode = process.argv[2];
let output: unknown;
if (mode === 'as_known') output = await runAsKnownScenario();
else if (mode === 'during') output = await runDuringScenario();
else if (mode === 'extent') output = await runExtentScenario();
else throw new Error(`unknown probe mode: ${mode}`);

process.stdout.write(JSON.stringify(output) + '\n');
