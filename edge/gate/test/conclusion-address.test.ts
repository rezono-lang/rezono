import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { mkdir, mkdtemp, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { test } from 'node:test';
import { canonicalJson } from '../../../viewer/src/lib/canon.ts';
import {
	canonicalWitnessIri,
	conclusionIri,
	parsePinnedIri,
	pinIri,
	spellSegment,
	unspellSegment
} from '../src/conclusion-address.ts';
import { openLocalGate } from '../src/local.ts';

const PACK = 'flow-drift';
const BASE = 'https://rezono.org/example/flow-drift/';

const SCHEMA = {
	pack: { id: PACK, base: BASE },
	kinds: [
		{ id: 'service', class: 'Service', world: 'closed' }
	],
	relations: [
		{ id: 'flow_drift', world: 'closed', columns: [{ name: 'run', type: 'text' }] },
		{ id: 'complete_sweep', world: 'closed', columns: [{ name: 'run', type: 'text' }] }
	],
	attributes: [],
	enums: [],
	questions: []
};

async function buildFlowDriftStore() {
	const root = await mkdtemp(join(tmpdir(), 'gate-conclusion-'));
	const write = async (key: string, value: unknown) => {
		const path = join(root, key);
		await mkdir(dirname(path), { recursive: true });
		const bytes = JSON.stringify(value);
		await writeFile(path, bytes);
		return createHash('sha256').update(bytes).digest('hex');
	};
	const object = async (data: unknown) => {
		const sha256 = createHash('sha256').update(JSON.stringify(data)).digest('hex');
		const key = PACK + '/objects/' + sha256 + '.json';
		await write(key, data);
		return { uri: 's3://test-store/' + key, sha256 };
	};
	const bundleKey = PACK + '/bundles/schema-bundle.json';
	const bundleSha = await write(bundleKey, SCHEMA);

	const serviceRow = { key: ['svc-gw'] };
	const driftRowMatched = {
		key: ['run-1', 'hubble', 'win-1', 'svc-gw', 'svc-auth', 'tcp', '443', 'matched', 'valid', 'allow/1', 'obs/1']
	};
	const driftRowExcess = {
		key: ['run-1', 'hubble', 'win-1', 'svc-orders', 'svc-secrets', 'tcp', '8200', 'excess', 'violated', 'policy/base', 'obs/2']
	};
	const sweepRow = {
		key: ['run-1', 'hubble', 'win-1', 'sweep/win-1']
	};

	const witness = await object({ witnesses: [], hidden: [] });

	// Epoch 1: operator sees service + both matched & excess + complete_sweep; tenant sees only service & matched (zero leak).
	const m1 = {
		id: 'm-1',
		epoch: 1,
		access_semantics: 2,
		knowledge_time: '2026-11-20T21:00:00Z',
		definition_sha256: bundleSha,
		checks: [{ name: 'rezono:proofs', status: 'green' }],
		snapshots: [
			{ relation: 'service', role: 'operator', complete: true, full: true, format: 'json', ...(await object([serviceRow])) },
			{ relation: 'flow_drift', role: 'operator', complete: true, full: true, format: 'json', ...(await object([driftRowMatched, driftRowExcess])) },
			{ relation: 'complete_sweep', role: 'operator', complete: true, full: true, format: 'json', ...(await object([sweepRow])) },
			{ relation: 'service', role: 'tenant', complete: false, full: false, format: 'json', ...(await object([serviceRow])) },
			{ relation: 'flow_drift', role: 'tenant', complete: false, full: false, format: 'json', ...(await object([driftRowMatched])) }
		],
		witnesses: [
			{ role: 'operator', ...witness },
			{ role: 'tenant', ...witness }
		],
		compiled: [{ file: 'bundle/schema-bundle.json', uri: 's3://test-store/' + bundleKey, sha256: bundleSha }]
	};
	const m1Sha = await write(PACK + '/manifests/m-1.json', m1);
	await write(PACK + '/heads/' + (10n ** 19n - 1n - 1n).toString().padStart(19, '0') + '.json', {
		format: 'rezono.head/1', manifest: 'm-1', epoch: 1, sha256: m1Sha
	});

	// Epoch 2: drift resolved for operator; tenant still sees service & matched row.
	const m2 = {
		id: 'm-2',
		epoch: 2,
		access_semantics: 2,
		knowledge_time: '2026-11-20T21:40:00Z',
		definition_sha256: bundleSha,
		checks: [{ name: 'rezono:proofs', status: 'green' }],
		snapshots: [
			{ relation: 'service', role: 'operator', complete: true, full: true, format: 'json', ...(await object([serviceRow])) },
			{ relation: 'flow_drift', role: 'operator', complete: true, full: true, format: 'json', ...(await object([driftRowMatched])) },
			{ relation: 'complete_sweep', role: 'operator', complete: true, full: true, format: 'json', ...(await object([sweepRow])) },
			{ relation: 'service', role: 'tenant', complete: false, full: false, format: 'json', ...(await object([serviceRow])) },
			{ relation: 'flow_drift', role: 'tenant', complete: false, full: false, format: 'json', ...(await object([driftRowMatched])) }
		],
		witnesses: [
			{ role: 'operator', ...witness },
			{ role: 'tenant', ...witness }
		],
		compiled: [{ file: 'bundle/schema-bundle.json', uri: 's3://test-store/' + bundleKey, sha256: bundleSha }]
	};
	const m2Sha = await write(PACK + '/manifests/m-2.json', m2);
	await write(PACK + '/heads/' + (10n ** 19n - 1n - 2n).toString().padStart(19, '0') + '.json', {
		format: 'rezono.head/1', manifest: 'm-2', epoch: 2, sha256: m2Sha
	});

	return { root, m1Sha, m2Sha, driftRowMatched, driftRowExcess, sweepRow };
}

test('L0 §3.4 segment spelling and pinned IRI parsing enforce strict bijective rules', () => {
	for (const sample of ['abc', 'a.b_c-1', '.', '..', 'tilde~here', '["run-1","a/b"]', 'café € 12']) {
		const spelled = spellSegment(sample);
		assert.equal(unspellSegment(spelled), sample);
	}
	assert.equal(spellSegment('.'), '~2E');
	assert.equal(spellSegment('..'), '~2E~2E');
	assert.throws(() => unspellSegment('~41'), /non-canonical/);

	const hex = 'a'.repeat(64);
	const iri = conclusionIri(BASE, { id: 'flow_drift', class: 'FlowDrift' }, '["run-1"]');
	const pinned = pinIri(iri, { manifest: 'm-2', dataset: hex });
	assert.deepEqual(parsePinnedIri(pinned), { iri, pin: { manifest: 'm-2', dataset: hex } });
	assert.deepEqual(parsePinnedIri(pinIri(iri, { dataset: hex })), { iri, pin: { dataset: hex } });
	assert.deepEqual(parsePinnedIri(iri), { iri, pin: null });

	const wIri = canonicalWitnessIri(BASE, { rule_id: 'r1', conclusion: { relation: 'x', key: '["a"]' } });
	assert.match(wIri, /^https:\/\/rezono\.org\/example\/flow-drift\/witness\/[0-9a-f]{64}$/);
	assert.throws(() => canonicalWitnessIri('https://rezono.org/no-slash', { rule_id: 'r1' }), /ending in "\/"/);
	assert.throws(() => canonicalWitnessIri('https://rezono.org/bad?q=1/', { rule_id: 'r1' }), /without query/);

	// Refused pins per decisions/publication-conclusion-addresses.md §3
	assert.throws(() => parsePinnedIri(iri + '?pin=m-1'), /without dataset hash/);
	assert.throws(() => parsePinnedIri(iri + '#frag'), /fragments/);
	assert.throws(() => parsePinnedIri(iri + '?other=1'), /unknown query/);
	assert.throws(() => parsePinnedIri(iri + '?pin=d-nothex'), /malformed/);
});

test('local gate lists multi-epoch manifests and resolves pinned conclusion IRIs with strict pin verification and role isolation', async (t) => {
	const { root, m1Sha, m2Sha, driftRowMatched, driftRowExcess, sweepRow } = await buildFlowDriftStore();
	t.after(() => rm(root, { recursive: true, force: true }));

	const operator = await openLocalGate(root, 'operator');
	const tenant = await openLocalGate(root, 'tenant');

	// Multi-epoch manifest listing (m-1, m-2)
	const listRes = await operator(new Request(`http://rezono.local/${PACK}/manifests`));
	assert.equal(listRes.status, 200);
	const listBody = await listRes.json();
	assert.deepEqual(listBody.manifests.map((m: { id: string }) => m.id), ['m-1', 'm-2']);
	assert.equal(listBody.manifests[0].manifest_sha256, m1Sha);
	assert.equal(listBody.manifests[1].manifest_sha256, m2Sha);

	// Resolve keyed kind (`bundle.kinds`: Service) strictly by single key, refusing tuple JSON
	const svcPinned = conclusionIri(BASE, { id: 'service', class: 'Service' }, 'svc-gw', { manifest: 'm-2', dataset: m2Sha });
	const resSvc = await operator(new Request(`http://rezono.local/${PACK}/resolve?iri=${encodeURIComponent(svcPinned)}`));
	assert.equal(resSvc.status, 200);
	assert.deepEqual((await resSvc.json()).key, ['svc-gw']);

	const svcTupleMismatch = conclusionIri(BASE, { id: 'service', class: 'Service' }, '["svc-gw"]', { manifest: 'm-2', dataset: m2Sha });
	assert.equal((await operator(new Request(`http://rezono.local/${PACK}/resolve?iri=${encodeURIComponent(svcTupleMismatch)}`))).status, 404);

	// Resolve tuple-keyed derived relation (`bundle.relations`: flow_drift -> FlowDrift) at current epoch (m-2)
	const matchedId = canonicalJson(driftRowMatched.key);
	const matchedPinnedM2 = conclusionIri(BASE, { id: 'flow_drift', class: 'FlowDrift' }, matchedId, {
		manifest: 'm-2',
		dataset: m2Sha
	});
	const resMatched = await operator(new Request(`http://rezono.local/${PACK}/resolve?iri=${encodeURIComponent(matchedPinnedM2)}`));
	assert.equal(resMatched.status, 200);
	const matchedBody = await resMatched.json();
	assert.equal(matchedBody.manifest, 'm-2');
	assert.equal(matchedBody.relation, 'flow_drift');
	assert.deepEqual(matchedBody.key, driftRowMatched.key);
	assert.equal(matchedBody.pinned_iri, matchedPinnedM2);

	// Resolve historical epoch (m-1) drift row via its m-1 pin
	const excessId = canonicalJson(driftRowExcess.key);
	const excessPinnedM1 = conclusionIri(BASE, { id: 'flow_drift', class: 'FlowDrift' }, excessId, {
		manifest: 'm-1',
		dataset: m1Sha
	});
	const resExcessM1 = await operator(new Request(`http://rezono.local/${PACK}/resolve?iri=${encodeURIComponent(excessPinnedM1)}`));
	assert.equal(resExcessM1.status, 200);
	assert.equal((await resExcessM1.json()).manifest, 'm-1');

	// Mismatched hash pin is refused (409), never answered with another row
	const badPin = conclusionIri(BASE, { id: 'flow_drift', class: 'FlowDrift' }, matchedId, {
		manifest: 'm-2',
		dataset: '0'.repeat(64)
	});
	const resBadPin = await operator(new Request(`http://rezono.local/${PACK}/resolve?iri=${encodeURIComponent(badPin)}`));
	assert.equal(resBadPin.status, 409);

	// Role isolation: tenant resolves matched row (200) but gets 404 for excess drift and complete_sweep
	const tenantOk = await tenant(new Request(`http://rezono.local/${PACK}/resolve?iri=${encodeURIComponent(matchedPinnedM2)}`));
	assert.equal(tenantOk.status, 200);

	const tenantDeniedDrift = await tenant(new Request(`http://rezono.local/${PACK}/resolve?iri=${encodeURIComponent(excessPinnedM1)}`));
	assert.equal(tenantDeniedDrift.status, 404);

	const sweepIri = conclusionIri(BASE, { id: 'complete_sweep', class: 'CompleteSweep' }, canonicalJson(sweepRow.key), {
		manifest: 'm-2',
		dataset: m2Sha
	});
	const opSweep = await operator(new Request(`http://rezono.local/${PACK}/resolve?iri=${encodeURIComponent(sweepIri)}`));
	assert.equal(opSweep.status, 200);
	const tenantSweep = await tenant(new Request(`http://rezono.local/${PACK}/resolve?iri=${encodeURIComponent(sweepIri)}`));
	assert.equal(tenantSweep.status, 404);
});
