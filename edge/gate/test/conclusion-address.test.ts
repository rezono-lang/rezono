import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';
import type { Schema } from '../../../rezono/src/index.ts';
import { AskError } from '../src/ask.ts';
import {
	conclusionIri,
	isWitnessIri,
	parsePinnedIri,
	pinIri,
	spellSegment,
	unspellSegment
} from '../src/conclusion-address.ts';
import { openLocalGate } from '../src/local.ts';

const REPO_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '../../..');
const VECTORS_PATH = join(REPO_ROOT, 'contracts/fixtures/conclusion-address-vectors.json');

const PACK = 'demo';
const BASE = 'https://rezono.example/demo/';

const sha256 = (bytes: string) => createHash('sha256').update(bytes).digest('hex');

async function put(root: string, rel: string, value: unknown): Promise<string> {
	const text = JSON.stringify(value);
	const full = join(root, rel);
	await mkdir(dirname(full), { recursive: true });
	await writeFile(full, text, 'utf8');
	return sha256(text);
}

function headKey(epoch: number): string {
	return `${PACK}/heads/${(10n ** 19n - 1n - BigInt(epoch)).toString().padStart(19, '0')}.json`;
}

function buildBundle() {
	return {
		pack: { id: PACK, base: BASE },
		kinds: [
			{ id: 'service', class: 'Service', world: 'closed' },
			{ id: 'edge_service', class: 'EdgeService', parent: 'service', world: 'closed' }
		],
		attributes: [],
		arrows: [],
		relations: [
			{
				id: 'flow_drift',
				world: 'closed',
				columns: [
					{ name: 'src', type: 'string' },
					{ name: 'dst', type: 'string' },
					{ name: 'kind', type: 'string' }
				]
			},
			{
				id: 'complete_sweep',
				world: 'closed',
				columns: [{ name: 'relation', type: 'string' }]
			}
		]
	};
}

interface SnapshotSpec {
	relation: string;
	role: string;
	complete: boolean;
	full?: boolean;
	rows: { key: string[]; [k: string]: unknown }[];
}

async function writeEpoch(
	root: string,
	bundleRef: { file: string; uri: string; sha256: string },
	epoch: number,
	knowledgeTime: string,
	specs: SnapshotSpec[],
	roleDatasets: Record<string, string>
): Promise<{ manifestSha: string; datasets: Record<string, string> }> {
	const manifestId = `m-${epoch}`;
	const snapshots: { relation: string; role: string; format: 'json'; complete: boolean; full?: boolean; uri: string; sha256: string }[] = [];
	for (const spec of specs) {
		const snapSha = sha256(JSON.stringify(spec.rows));
		const relPath = `${PACK}/objects/${snapSha}.json`;
		await put(root, relPath, spec.rows);
		snapshots.push({
			relation: spec.relation,
			role: spec.role,
			format: 'json',
			complete: spec.complete,
			...(spec.full !== undefined && { full: spec.full }),
			uri: `s3://local/${relPath}`,
			sha256: snapSha
		});
	}
	const manifest = {
		id: manifestId,
		epoch,
		knowledge_time: knowledgeTime,
		access_semantics: 2,
		definition_sha256: '1'.repeat(64),
		checks: [{ name: 'rezono:proofs', status: 'green' }],
		compiled: [bundleRef],
		snapshots
	};
	const manifestSha = await put(root, `${PACK}/manifests/${manifestId}.json`, manifest);
	await put(root, headKey(epoch), { format: 'rezono.head/1', manifest: manifestId, epoch, sha256: manifestSha });

	for (const [role, dataset] of Object.entries(roleDatasets)) {
		const sources = snapshots
			.filter((s) => s.role === role)
			.map(({ relation, sha256: s }) => ({ relation, sha256: s }))
			.sort((a, b) => (a.relation < b.relation ? -1 : a.relation > b.relation ? 1 : 0));
		await put(root, `${PACK}/${manifestId}/${role}/publication/index.json`, {
			format: 'rezono.publication-form/1',
			pack: PACK,
			manifest: { id: manifestId, epoch, knowledge_time: knowledgeTime },
			role,
			schema: 's-' + '2'.repeat(64),
			dataset,
			sources,
			objects: []
		});
	}

	return { manifestSha, datasets: roleDatasets };
}

test('shared Python-generated vectors agree on spelling, pin parsing, and root-kind conclusion IRIs', async () => {
	const vectors = JSON.parse(await readFile(VECTORS_PATH, 'utf8')) as {
		schema: Schema;
		spell_valid: { raw: string; spelled: string }[];
		unspell_invalid: string[];
		pin_valid: { iri: string; pin: { manifest?: string; dataset: string }; pinned: string }[];
		pin_invalid: string[];
		conclusion_iri: { kind: string; row_id: string; pin: { manifest?: string; dataset: string } | null; expected: string }[];
	};

	for (const c of vectors.spell_valid) {
		assert.equal(spellSegment(c.raw), c.spelled);
		assert.equal(unspellSegment(c.spelled), c.raw);
	}
	for (const seg of vectors.unspell_invalid) {
		assert.throws(() => unspellSegment(seg), AskError);
	}
	for (const c of vectors.pin_valid) {
		assert.equal(pinIri(c.iri, c.pin), c.pinned);
		assert.deepEqual(parsePinnedIri(c.pinned), { iri: c.iri, pin: c.pin });
	}
	for (const bad of vectors.pin_invalid) {
		assert.throws(() => parsePinnedIri(bad), AskError);
	}
	for (const c of vectors.conclusion_iri) {
		assert.equal(conclusionIri(vectors.schema, c.kind, c.row_id, c.pin ?? undefined), c.expected);
	}
	assert.equal(isWitnessIri(BASE, `${BASE}witness/${'a'.repeat(64)}`), true);
	assert.equal(isWitnessIri(BASE, `${BASE}witness/not-hex`), false);
});

test('local gate lists manifests (including withdrawn earlier epochs, role-scoped) and resolves pinned conclusion IRIs', async () => {
	const root = await mkdtemp(join(tmpdir(), 'rezono-gate-conclusion-'));
	try {
		const bundle = buildBundle();
		const bundleSha = await put(root, `${PACK}/bundles/schema-bundle.json`, bundle);
		const bundleRef = { file: 'bundle/schema-bundle.json', uri: `s3://local/${PACK}/bundles/schema-bundle.json`, sha256: bundleSha };

		const svcGw = { key: ['svc-gw'] };
		const svcEdge = { key: ['svc-edge'] };
		const svcWithdrawn = { key: ['svc-withdrawn'] };
		const driftExcess = { key: ['svc-gw', 'db-1', 'excess'] };
		const driftMatched = { key: ['svc-gw', 'db-1', 'matched'] };
		const sweepRow = { key: ['flow_drift'] };

		const dOp0 = 'd-' + '10'.repeat(32);
		const dOp1 = 'd-' + '11'.repeat(32);
		const dTn1 = 'd-' + '21'.repeat(32);
		const dOp2 = 'd-' + '12'.repeat(32);
		const dTn2 = 'd-' + '22'.repeat(32);
		const dOp3 = 'd-' + '13'.repeat(32);
		const dTn3 = 'd-' + '23'.repeat(32);

		// Epoch 0: operator only (tenant was never in m-0)
		await writeEpoch(
			root,
			bundleRef,
			0,
			'2026-11-18T10:00:00Z',
			[{ relation: 'service', role: 'operator', complete: true, rows: [svcGw] }],
			{ operator: dOp0 }
		);

		// Epoch 1: operator + tenant; tenant had complete=true on service (later revoked in m-3 -> fails stillReadable)
		await writeEpoch(
			root,
			bundleRef,
			1,
			'2026-11-19T10:00:00Z',
			[
				{ relation: 'service', role: 'operator', complete: true, rows: [svcGw, svcEdge] },
				{ relation: 'edge_service', role: 'operator', complete: true, rows: [svcEdge] },
				{ relation: 'flow_drift', role: 'operator', complete: true, rows: [driftExcess] },
				{ relation: 'service', role: 'tenant', complete: true, rows: [svcGw] }
			],
			{ operator: dOp1, tenant: dTn1 }
		);

		// Epoch 2: operator + tenant, withdrawn by decision
		await writeEpoch(
			root,
			bundleRef,
			2,
			'2026-11-20T10:00:00Z',
			[
				{ relation: 'service', role: 'operator', complete: true, rows: [svcGw] },
				{ relation: 'service', role: 'tenant', complete: false, full: false, rows: [svcGw] }
			],
			{ operator: dOp2, tenant: dTn2 }
		);

		// Epoch 3 (current): operator full + subkind + relations; tenant filtered (complete=false, full=false)
		const ep3 = await writeEpoch(
			root,
			bundleRef,
			3,
			'2026-11-21T10:00:00Z',
			[
				{ relation: 'service', role: 'operator', complete: true, rows: [svcGw, svcEdge, svcWithdrawn] },
				{ relation: 'edge_service', role: 'operator', complete: true, rows: [svcEdge] },
				{ relation: 'flow_drift', role: 'operator', complete: true, rows: [driftMatched] },
				{ relation: 'complete_sweep', role: 'operator', complete: true, rows: [sweepRow] },
				{ relation: 'service', role: 'tenant', complete: false, full: false, rows: [svcGw] },
				{ relation: 'edge_service', role: 'tenant', complete: false, full: false, rows: [] }
			],
			{ operator: dOp3, tenant: dTn3 }
		);

		// Withdraw epoch m-2 and row svc-withdrawn in m-3
		await put(root, `${PACK}/withdrawals/w-epoch-2.json`, {
			format: 'rezono.withdrawal/1',
			id: 'w-epoch-2',
			state: 'withdrawn',
			decider: ['board'],
			decided_on: '2026-11-21',
			reason: 'superseded due to source correction',
			epochs: ['m-2'],
			rows: []
		});
		await put(root, `${PACK}/withdrawals/w-row-3.json`, {
			format: 'rezono.withdrawal/1',
			id: 'w-row-3',
			state: 'withdrawn',
			decider: ['board'],
			decided_on: '2026-11-21',
			reason: 'service entry retracted',
			epochs: [],
			rows: [{ relation: 'service', key: ['svc-withdrawn'], manifest: 'm-3' }]
		});

		const operator = await openLocalGate(root, 'operator');
		const tenant = await openLocalGate(root, 'tenant');
		const outsider = await openLocalGate(root, 'outsider');

		// 1. Operator manifest listing includes superseded, withdrawn earlier epoch, and current with real dataset hashes
		const opListRes = await operator(new Request(`http://rezono.local/${PACK}/manifests`));
		assert.equal(opListRes.status, 200);
		const opList = (await opListRes.json()) as {
			pack: string;
			manifests: { id: string; epoch: number; standing: string; dataset?: string; withdrawal?: { id: string; reason: string } }[];
		};
		assert.equal(opList.pack, PACK);
		assert.deepEqual(
			opList.manifests.map((m) => [m.id, m.standing, m.dataset ?? null]),
			[
				['m-0', 'superseded', dOp0],
				['m-1', 'superseded', dOp1],
				['m-2', 'withdrawn', null],
				['m-3', 'current', dOp3]
			]
		);
		assert.equal(opList.manifests[2]!.withdrawal?.id, 'w-epoch-2');
		assert.equal(opList.manifests[2]!.withdrawal?.reason, 'superseded due to source correction');

		// 2. Tenant manifest listing omits m-0 (never in it) and m-1 (!stillReadable), includes withdrawn m-2 and current m-3
		const tnListRes = await tenant(new Request(`http://rezono.local/${PACK}/manifests`));
		assert.equal(tnListRes.status, 200);
		const tnList = (await tnListRes.json()) as {
			manifests: { id: string; standing: string; dataset?: string }[];
		};
		assert.deepEqual(
			tnList.manifests.map((m) => [m.id, m.standing, m.dataset ?? null]),
			[
				['m-2', 'withdrawn', null],
				['m-3', 'current', dTn3]
			]
		);

		// 3. Resolve keyed root kind with REAL published dataset hash (NOT manifestSha256)
		const svcPinned = `${BASE}Service/svc-gw?pin=m-3@${dOp3}`;
		const svcRes = await operator(new Request(`http://rezono.local/${PACK}/resolve?iri=${encodeURIComponent(svcPinned)}`));
		assert.equal(svcRes.status, 200);
		const svcBody = (await svcRes.json()) as {
			iri: string;
			dataset: string;
			pinned_iri: string;
			manifest: string;
			relation: string;
			key: string[];
		};
		assert.equal(svcBody.iri, `${BASE}Service/svc-gw`);
		assert.equal(svcBody.dataset, dOp3);
		assert.equal(svcBody.pinned_iri, svcPinned);
		assert.equal(svcBody.relation, 'service');
		assert.deepEqual(svcBody.key, ['svc-gw']);

		// Passing manifestSha256 as dataset pin MUST fail with 409
		const manifestShaPin = `${BASE}Service/svc-gw?pin=m-3@d-${ep3.manifestSha}`;
		assert.equal((await operator(new Request(`http://rezono.local/${PACK}/resolve?iri=${encodeURIComponent(manifestShaPin)}`))).status, 409);

		// Passing wrong dataset hash MUST fail with 409
		const wrongDatasetPin = `${BASE}Service/svc-gw?pin=m-3@d-${'0'.repeat(64)}`;
		assert.equal((await operator(new Request(`http://rezono.local/${PACK}/resolve?iri=${encodeURIComponent(wrongDatasetPin)}`))).status, 409);

		// 4. Subkind shares root kind's IRI space; subkind IRI is refused (404)
		const edgeUnderRoot = `${BASE}Service/svc-edge?pin=m-3@${dOp3}`;
		const edgeRootRes = await operator(new Request(`http://rezono.local/${PACK}/resolve?iri=${encodeURIComponent(edgeUnderRoot)}`));
		assert.equal(edgeRootRes.status, 200);
		const edgeUnderSub = `${BASE}EdgeService/svc-edge?pin=m-3@${dOp3}`;
		assert.equal((await operator(new Request(`http://rezono.local/${PACK}/resolve?iri=${encodeURIComponent(edgeUnderSub)}`))).status, 404);

		// 5. Keyed kind rejects tuple-encoded key
		const svcTupleMismatch = `${BASE}Service/${spellSegment('["svc-gw"]')}?pin=m-3@${dOp3}`;
		assert.equal((await operator(new Request(`http://rezono.local/${PACK}/resolve?iri=${encodeURIComponent(svcTupleMismatch)}`))).status, 404);

		// 6. Tuple-keyed derived relations (FlowDrift & CompleteSweep) resolve cleanly via roleSchema
		const driftM3 = `${BASE}FlowDrift/${spellSegment(JSON.stringify(driftMatched.key))}?pin=m-3@${dOp3}`;
		const driftM3Res = await operator(new Request(`http://rezono.local/${PACK}/resolve?iri=${encodeURIComponent(driftM3)}`));
		assert.equal(driftM3Res.status, 200);
		assert.deepEqual(((await driftM3Res.json()) as { key: string[] }).key, driftMatched.key);

		const driftM1 = `${BASE}FlowDrift/${spellSegment(JSON.stringify(driftExcess.key))}?pin=m-1@${dOp1}`;
		const driftM1Res = await operator(new Request(`http://rezono.local/${PACK}/resolve?iri=${encodeURIComponent(driftM1)}`));
		assert.equal(driftM1Res.status, 200);
		assert.equal(driftM1Res.headers.get('x-rezono-standing'), 'superseded');
		assert.equal(driftM1Res.headers.get('x-rezono-superseded-by'), 'm-3');

		const sweepM3 = `${BASE}CompleteSweep/${spellSegment(JSON.stringify(sweepRow.key))}?pin=m-3@${dOp3}`;
		assert.equal((await operator(new Request(`http://rezono.local/${PACK}/resolve?iri=${encodeURIComponent(sweepM3)}`))).status, 200);

		// 7. No 409 vs 404 epoch-existence leak: absent, future, never-in-epoch, and unreadable epochs are indistinguishable (404)
		const absentEpochRes = await tenant(new Request(`http://rezono.local/${PACK}/resolve?iri=${encodeURIComponent(`${BASE}Service/svc-gw?pin=m-999@${dTn3}`)}`));
		const futureEpochRes = await tenant(new Request(`http://rezono.local/${PACK}/resolve?iri=${encodeURIComponent(`${BASE}Service/svc-gw?pin=m-4@${dTn3}`)}`));
		const neverInEpochRes = await tenant(new Request(`http://rezono.local/${PACK}/resolve?iri=${encodeURIComponent(`${BASE}Service/svc-gw?pin=m-0@${dOp0}`)}`));
		const unreadableEpochRes = await tenant(new Request(`http://rezono.local/${PACK}/resolve?iri=${encodeURIComponent(`${BASE}Service/svc-gw?pin=m-1@${dTn1}`)}`));
		for (const res of [absentEpochRes, futureEpochRes, neverInEpochRes, unreadableEpochRes]) {
			assert.equal(res.status, 404);
			assert.deepEqual(await res.json(), { error: 'not found' });
		}

		// 8. Withdrawn epoch (m-2) and withdrawn row (svc-withdrawn in m-3) return 410
		const withdrawnEpochRes = await operator(new Request(`http://rezono.local/${PACK}/resolve?iri=${encodeURIComponent(`${BASE}Service/svc-gw?pin=m-2@${dOp2}`)}`));
		assert.equal(withdrawnEpochRes.status, 410);
		assert.equal(withdrawnEpochRes.headers.get('x-rezono-standing'), 'withdrawn');
		assert.equal(((await withdrawnEpochRes.json()) as { error: string }).error, 'withdrawn');

		const withdrawnRowRes = await operator(new Request(`http://rezono.local/${PACK}/resolve?iri=${encodeURIComponent(`${BASE}Service/svc-withdrawn?pin=m-3@${dOp3}`)}`));
		assert.equal(withdrawnRowRes.status, 410);
		assert.equal(withdrawnRowRes.headers.get('x-rezono-standing'), 'withdrawn');

		// 9. Witness IRIs (§4.4) return 501 for authorized roles, 404 for unauthorized roles
		const witnessIri = `${BASE}witness/${'b'.repeat(64)}`;
		const witnessRes = await operator(new Request(`http://rezono.local/${PACK}/resolve?iri=${encodeURIComponent(witnessIri)}`));
		assert.equal(witnessRes.status, 501);
		const witnessPinnedRes = await operator(new Request(`http://rezono.local/${PACK}/resolve?iri=${encodeURIComponent(`${witnessIri}?pin=m-3@${dOp3}`)}`));
		assert.equal(witnessPinnedRes.status, 501);
		assert.equal((await outsider(new Request(`http://rezono.local/${PACK}/resolve?iri=${encodeURIComponent(witnessIri)}`))).status, 404);

		// 10. Role isolation: tenant cannot resolve FlowDrift
		assert.equal((await tenant(new Request(`http://rezono.local/${PACK}/resolve?iri=${encodeURIComponent(`${BASE}FlowDrift/${spellSegment(JSON.stringify(driftMatched.key))}?pin=m-3@${dTn3}`)}`))).status, 404);
	} finally {
		await rm(root, { recursive: true, force: true });
	}
});
