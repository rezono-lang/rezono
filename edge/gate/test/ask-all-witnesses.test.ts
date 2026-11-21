import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { mkdtemp, mkdir, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import {
	ask,
	canonicalWitnessHash,
	canonicalWitnessIri,
	memoryGraph,
	type Edge,
	type Graph,
	type Question
} from '../src/ask.ts';
import { openLocalGate } from '../src/local.ts';
import type { Witness } from '../../../contracts/typescript/generated/proof.ts';

const GROUNDS: Question = {
	term: 'grounds',
	start: 'present',
	steps: [{ trace: { direction: 'back', depth: 'all' } }],
	answer: 'route',
	limit: 64
};

const sha256 = (text: string) => createHash('sha256').update(text, 'utf8').digest('hex');

async function buildTwoRoleStore(root: string, baseIri: string, w1: Witness, w2: Witness) {
	const pack = 'demo';
	const write = async (key: string, value: unknown) => {
		const full = join(root, key);
		await mkdir(dirname(full), { recursive: true });
		const bytes = JSON.stringify(value);
		await writeFile(full, bytes, 'utf8');
		return sha256(bytes);
	};
	const object = async (data: unknown) => {
		const digest = sha256(JSON.stringify(data));
		const key = `${pack}/objects/${digest}.json`;
		await write(key, data);
		return { uri: `s3://test-store/${key}`, sha256: digest };
	};
	const snap = async (role: string, relation: string, rows: string[][]) => ({
		relation,
		role,
		complete: true,
		full: true,
		format: 'json',
		...(await object(rows.map((key) => ({ key }))))
	});

	const readerSnaps = [
		await snap('reader', 'eligible', [['p-1']]),
		await snap('reader', 'member', [['p-1']]),
		await snap('reader', 'income_ok', [['p-1']]),
		await snap('reader', 'grant_ok', [['p-1']])
	];
	// Restricted role `other` cannot read `eligible` or `grant_ok`.
	const otherSnaps = [await snap('other', 'member', [['p-1']])];

	const readerWitnesses = await object({ witnesses: [w1, w2], hidden: [] });
	const otherWitnesses = await object({ witnesses: [], hidden: [] });

	const bundleKey = `${pack}/bundles/schema-bundle.json`;
	const rulesKey = `${pack}/bundles/rules.json`;
	const manifest = {
		id: 'm-1',
		epoch: 1,
		access_semantics: 2,
		knowledge_time: '2026-01-01T00:00:00Z',
		pack_sha256: '1'.repeat(64),
		witness_check: 'green',
		compiled: [
			{
				file: 'bundle/schema-bundle.json',
				uri: `s3://test-store/${bundleKey}`,
				sha256: await write(bundleKey, {
					pack: { id: pack, base: baseIri },
					kinds: [],
					relations: [
						// Untyped derived column (no `type`, like tests/fixtures/slip's `busy.group`): must still serve 200 with canonical IRI.
						{ id: 'eligible', columns: [{ name: 'p' }] },
						{ id: 'member', columns: [{ name: 'p', type: 'string' }] },
						{ id: 'income_ok', columns: [{ name: 'p', type: 'string' }] },
						{ id: 'grant_ok', columns: [{ name: 'p', type: 'string' }] }
					],
					questions: [GROUNDS]
				})
			},
			{
				file: 'ir/rules.json',
				uri: `s3://test-store/${rulesKey}`,
				sha256: await write(rulesKey, {
					relations: [
						{ name: 'eligible', key: [{ name: 'p' }] },
						{ name: 'member', key: [{ name: 'p' }] },
						{ name: 'income_ok', key: [{ name: 'p' }] },
						{ name: 'grant_ok', key: [{ name: 'p' }] }
					],
					rules: [
						{
							id: 'r_income',
							body: [
								{ relation: 'member', terms: ['?p'], polarity: 'positive' },
								{ relation: 'income_ok', terms: ['?p'], polarity: 'positive' }
							]
						},
						{
							id: 'r_grant',
							body: [
								{ relation: 'member', terms: ['?p'], polarity: 'positive' },
								{ relation: 'grant_ok', terms: ['?p'], polarity: 'positive' }
							]
						}
					]
				})
			}
		],
		snapshots: [...readerSnaps, ...otherSnaps],
		witnesses: [
			{ role: 'reader', ...readerWitnesses },
			{ role: 'other', ...otherWitnesses }
		]
	};
	const manifestKey = `${pack}/manifests/m-1.json`;
	await write(`${pack}/heads/9999999999999999998.json`, {
		format: 'rezono.head/1',
		manifest: 'm-1',
		epoch: 1,
		sha256: await write(manifestKey, manifest)
	});
}

test('openLocalGate serves canonical <base>witness/<64 hex> IRIs, retains all distinct witnesses in reader order, enforces role isolation, and never fabricates load_bearing', async () => {
	const conclusion = { relation: 'eligible', key: '["p-1"]' };
	const sharedPremise = { relation: 'member', key: '["p-1"]' };
	const altIncome = { relation: 'income_ok', key: '["p-1"]' };
	const altGrant = { relation: 'grant_ok', key: '["p-1"]' };

	const w1: Witness = {
		conclusion,
		rule_id: 'r_income',
		bindings: [{ variable: '?p', value: 'p-1' }],
		premises: [
			{ row: sharedPremise, polarity: 'positive', stratum: 0 },
			{ row: altIncome, polarity: 'positive', stratum: 0 }
		],
		aggregates: []
	};
	const w2: Witness = {
		conclusion,
		rule_id: 'r_grant',
		bindings: [{ variable: '?p', value: 'p-1' }],
		premises: [
			{ row: sharedPremise, polarity: 'positive', stratum: 0 },
			{ row: altGrant, polarity: 'positive', stratum: 0 }
		],
		aggregates: []
	};

	// Independent RFC 8785 / rezono_canon expectations (integers encoded as decimal text "0", UTF-16 sorted keys).
	const baseIri = 'https://example.org/demo/';
	const expectedW1Hash = sha256(
		'{"aggregates":[],"bindings":[{"value":"p-1","variable":"?p"}],"conclusion":{"key":"[\\"p-1\\"]","relation":"eligible"},' +
		'"premises":[{"polarity":"positive","row":{"key":"[\\"p-1\\"]","relation":"member"},"stratum":"0"},' +
		'{"polarity":"positive","row":{"key":"[\\"p-1\\"]","relation":"income_ok"},"stratum":"0"}],"rule_id":"r_income"}'
	);
	const expectedW2Hash = sha256(
		'{"aggregates":[],"bindings":[{"value":"p-1","variable":"?p"}],"conclusion":{"key":"[\\"p-1\\"]","relation":"eligible"},' +
		'"premises":[{"polarity":"positive","row":{"key":"[\\"p-1\\"]","relation":"member"},"stratum":"0"},' +
		'{"polarity":"positive","row":{"key":"[\\"p-1\\"]","relation":"grant_ok"},"stratum":"0"}],"rule_id":"r_grant"}'
	);

	const root = await mkdtemp(join(tmpdir(), 'rezono-gate-witness-iri-'));
	try {
		await buildTwoRoleStore(root, baseIri, w1, w2);
		const reader = await openLocalGate(root, 'reader');
		const other = await openLocalGate(root, 'other');

		const res = await reader(
			new Request('http://local/demo/m-1/ask/grounds?relation=eligible&key=%5B%22p-1%22%5D')
		);
		assert.equal(res.status, 200);
		const answer = (await res.json()) as {
			witnesses: (Witness & { iri: string })[];
			steps: Record<string, unknown>[];
		};

		assert.equal(answer.witnesses.length, 2, 'must retain both distinct published witnesses');
		assert.deepEqual(
			answer.witnesses.map((w) => w.rule_id),
			['r_income', 'r_grant'],
			'must preserve deterministic reader order'
		);
		assert.equal(answer.witnesses[0]!.iri, `${baseIri}witness/${expectedW1Hash}`);
		assert.equal(answer.witnesses[1]!.iri, `${baseIri}witness/${expectedW2Hash}`);
		// Gate must NOT fabricate load_bearing (publisher derives, checker verifies, per #1445).
		for (const step of answer.steps) {
			assert.equal('load_bearing' in step, false, 'gate must not derive load_bearing itself');
		}

		// Role isolation: `other` cannot read `eligible`, gets 404 without leaking witnesses.
		const denied = await other(
			new Request('http://local/demo/m-1/ask/grounds?relation=eligible&key=%5B%22p-1%22%5D')
		);
		assert.equal(denied.status, 404);
	} finally {
		await rm(root, { recursive: true, force: true });
	}
});

test('witness-iri enforces strict baseIri validation, strict canon (no silent undefined stripping), and backward-compatible Graph', async () => {
	const conclusion = { relation: 'ok', key: '["x"]' };
	const premise = { relation: 'fact', key: '["x"]' };
	const w: Witness = {
		conclusion,
		rule_id: 'r_ok',
		bindings: [],
		premises: [{ row: premise, polarity: 'positive', stratum: 0 }],
		aggregates: []
	};
	const expectedHash = sha256(
		'{"aggregates":[],"bindings":[],"conclusion":{"key":"[\\"x\\"]","relation":"ok"},' +
		'"premises":[{"polarity":"positive","row":{"key":"[\\"x\\"]","relation":"fact"},"stratum":"0"}],"rule_id":"r_ok"}'
	);

	// Strict baseIri: refuses missing trailing '/', query '?', fragment '#', or missing scheme.
	assert.throws(() => canonicalWitnessIri(w, 'https://example.org/pack'), /ending in '\/'/);
	assert.throws(() => canonicalWitnessIri(w, 'https://example.org/pack/?bad=1'), /invalid schema base IRI/);
	assert.throws(() => canonicalWitnessIri(w, 'https://example.org/pack/#frag'), /invalid schema base IRI/);
	assert.throws(() => canonicalWitnessIri(w, 'pack/'), /invalid schema base IRI/);

	// Strict canon: undefined field must be refused by canon.ts (not silently stripped).
	const malformed = { ...w, extra: undefined } as unknown as Witness;
	assert.throws(() => canonicalWitnessHash(malformed), /null/);

	// Standalone without schema base uses rezono:w/<64 hex>; annotated witness re-hashes identically.
	const annotated = { ...w, iri: `https://example.org/pack/witness/${expectedHash}` };
	assert.equal(canonicalWitnessHash(annotated), expectedHash);

	const legacyGraph: Graph = {
		async *edges(direction, node) {
			if (direction === 'back' && node.relation === 'ok') {
				yield { c: conclusion, p: premise, how: 'positive', position: 0 };
			}
		},
		witness: async (c) => (c.relation === 'ok' ? w : undefined)
	};
	const standalone = await ask(legacyGraph, GROUNDS, 'm-1', conclusion, { limit: 64 });
	assert.ok(standalone);
	assert.equal(standalone.witnesses.length, 1);
	assert.equal(standalone.witnesses[0]!.iri, `rezono:w/${expectedHash}`);
	assert.equal('load_bearing' in standalone.steps[0]!, false);

	// Exact duplicate witnesses in memoryGraph are deduplicated.
	const dupGraph = memoryGraph([w, structuredClone(w)], [{ c: conclusion, p: premise, how: 'positive', position: 0 }]);
	assert.equal((await dupGraph.witnesses?.(conclusion))?.length, 1);
});
