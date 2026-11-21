"""Staircase reading withdrawal isolation across unreadable earlier epochs
(decisions/bitemporal-staircase-reading.md)."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

GATE_ROOT = Path(__file__).resolve().parents[1]

PROBE_JS = r"""
import { createHash } from 'node:crypto';
import { mkdir, mkdtemp, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { openLocalGate } from './src/local.ts';

const pack = 'sample';
const defA = 'a'.repeat(64);
const defB = 'b'.repeat(64);

const bundle = {
	pack: { id: pack, base: 'https://example.org/sample/' },
	kinds: [{ id: 'entry', class: 'Entry', world: 'closed' }],
	relations: [{
		id: 'outcome',
		world: 'closed',
		columns: [
			{ name: 'entry', type: 'string' },
			{ name: 'at', type: 'string' },
			{ name: 'state', type: 'string' },
			{ name: 'value', type: 'string' },
			{ name: 'reason', type: 'string' }
		]
	}],
	channels: {
		staircases: [{
			id: 'bitemporal',
			title_message: 'staircase.bitemporal',
			subject: 'entry',
			relation: 'outcome',
			valid_time_column: 'at',
			state_column: 'state',
			value_column: 'value',
			reason_column: 'reason'
		}]
	},
	attributes: [],
	enums: [],
	questions: []
};

function makeWitness(rowKey) {
	return {
		conclusion: { relation: 'outcome', key: JSON.stringify(rowKey) },
		rule_id: 'r_outcome',
		bindings: [
			{ variable: '?e', value: rowKey[0] },
			{ variable: '?at', value: rowKey[1] },
			{ variable: '?st', value: rowKey[2] },
			{ variable: '?v', value: rowKey[3] },
			{ variable: '?r', value: rowKey[4] }
		],
		premises: [
			{ row: { relation: 'entry', key: JSON.stringify([rowKey[0]]) }, polarity: 'positive', stratum: 0 }
		],
		aggregates: []
	};
}

async function runScenario(spec) {
	const root = await mkdtemp(join(tmpdir(), 'gate-staircase-wd-'));
	try {
		const write = async (key, value) => {
			const path = join(root, key);
			await mkdir(dirname(path), { recursive: true });
			const bytes = JSON.stringify(value);
			await writeFile(path, bytes);
			return createHash('sha256').update(bytes).digest('hex');
		};
		const object = async (data) => {
			const sha256 = createHash('sha256').update(JSON.stringify(data)).digest('hex');
			const key = pack + '/objects/' + sha256 + '.json';
			await write(key, data);
			return { uri: 's3://test-store/' + key, sha256 };
		};
		const bundleKey = pack + '/bundles/definition.json';
		const bundleSha = await write(bundleKey, bundle);

		for (const ep of spec.epochs) {
			const id = 'm-' + ep.epoch;
			const snapshots = [];
			const witnesses = [];
			for (const roleSpec of ep.roles) {
				snapshots.push({
					relation: 'entry',
					role: roleSpec.role,
					complete: roleSpec.complete,
					full: roleSpec.full,
					format: 'json',
					...await object(roleSpec.entries.map((k) => ({ key: [k] })))
				});
				snapshots.push({
					relation: 'outcome',
					role: roleSpec.role,
					complete: roleSpec.complete,
					full: roleSpec.full,
					format: 'json',
					...await object(roleSpec.outcomes.map((key) => ({ key })))
				});
				const witnessRef = await object({
					witnesses: roleSpec.outcomes.map(makeWitness),
					hidden: []
				});
				witnesses.push({ role: roleSpec.role, ...witnessRef });
			}
			const manifest = {
				id,
				epoch: ep.epoch,
				access_semantics: 2,
				definition_sha256: ep.definition,
				knowledge_time: ep.knowledgeTime,
				checks: [{ name: 'rezono:proofs', status: 'green' }],
				snapshots,
				witnesses,
				compiled: [{
					file: 'bundle/schema-bundle.json',
					uri: 's3://test-store/' + bundleKey,
					sha256: bundleSha
				}]
			};
			const manifestSha = await write(pack + '/manifests/' + id + '.json', manifest);
			const head = pack + '/heads/' + (10n ** 19n - 1n - BigInt(ep.epoch)).toString().padStart(19, '0') + '.json';
			await write(head, { format: 'rezono.head/1', manifest: id, epoch: ep.epoch, sha256: manifestSha });
		}

		for (const wd of spec.withdrawals) {
			await write(pack + '/withdrawals/' + wd.id + '.json', wd);
		}

		const gate = await openLocalGate(root, 'tenant');
		const response = await gate(new Request('http://rezono.local/sample/m-2/readings/staircase?subject=s-1'));
		const text = await response.text();
		return { status: response.status, body: JSON.parse(text), raw: text };
	} finally {
		await rm(root, { recursive: true, force: true });
	}
}

const m2TenantRole = {
	role: 'tenant',
	complete: false,
	full: false,
	entries: ['s-1'],
	outcomes: [['s-1', '2026-01-01', 'known', '100', '']]
};

const results = {
	baseline_absent_no_withdrawal: await runScenario({
		epochs: [
			{
				epoch: 1,
				definition: defA,
				knowledgeTime: '2026-01-01T00:00:00Z',
				roles: [{
					role: 'admin',
					complete: true,
					full: true,
					entries: ['s-admin'],
					outcomes: [['s-admin', '2026-01-01', 'known', '999', '']]
				}]
			},
			{
				epoch: 2,
				definition: defA,
				knowledgeTime: '2026-02-01T00:00:00Z',
				roles: [m2TenantRole]
			}
		],
		withdrawals: []
	}),
	absent_m1_withdrawn: await runScenario({
		epochs: [
			{
				epoch: 1,
				definition: defA,
				knowledgeTime: '2026-01-01T00:00:00Z',
				roles: [{
					role: 'admin',
					complete: true,
					full: true,
					entries: ['s-admin'],
					outcomes: [['s-admin', '2026-01-01', 'known', '999', '']]
				}]
			},
			{
				epoch: 2,
				definition: defA,
				knowledgeTime: '2026-02-01T00:00:00Z',
				roles: [m2TenantRole]
			}
		],
		withdrawals: [{
			format: 'rezono.withdrawal/1',
			id: 'wd-confidential-m1-absent',
			state: 'withdrawn',
			decider: ['confidential-audit-board'],
			decided_on: '2026-02-10',
			reason: 'confidential-m1-absent-withdrawal-reason',
			epochs: ['m-1']
		}]
	}),
	unreadable_m1_withdrawn: await runScenario({
		epochs: [
			{
				epoch: 1,
				definition: defA,
				knowledgeTime: '2026-01-01T00:00:00Z',
				roles: [{
					role: 'tenant',
					complete: true,
					full: false,
					entries: ['s-1', 's-revoked'],
					outcomes: [
						['s-1', '2026-01-01', 'known', '50', ''],
						['s-revoked', '2026-01-01', 'known', '75', '']
					]
				}]
			},
			{
				epoch: 2,
				definition: defB,
				knowledgeTime: '2026-02-01T00:00:00Z',
				roles: [{
					role: 'tenant',
					complete: false,
					full: false,
					entries: ['s-1'],
					outcomes: [['s-1', '2026-01-01', 'known', '200', '']]
				}]
			}
		],
		withdrawals: [{
			format: 'rezono.withdrawal/1',
			id: 'wd-confidential-m1-unreadable',
			state: 'withdrawn',
			decider: ['confidential-review-committee'],
			decided_on: '2026-02-11',
			reason: 'confidential-m1-unreadable-withdrawal-reason',
			epochs: ['m-1']
		}]
	}),
	readable_m1_withdrawn_control: await runScenario({
		epochs: [
			{
				epoch: 1,
				definition: defA,
				knowledgeTime: '2026-01-01T00:00:00Z',
				roles: [{
					role: 'tenant',
					complete: true,
					full: true,
					entries: ['s-1'],
					outcomes: [['s-1', '2026-01-01', 'known', '50', '']]
				}]
			},
			{
				epoch: 2,
				definition: defA,
				knowledgeTime: '2026-02-01T00:00:00Z',
				roles: [{
					role: 'tenant',
					complete: true,
					full: true,
					entries: ['s-1'],
					outcomes: [['s-1', '2026-01-01', 'known', '100', '']]
				}]
			}
		],
		withdrawals: [{
			format: 'rezono.withdrawal/1',
			id: 'wd-readable-m1-control',
			state: 'withdrawn',
			decider: ['records-office'],
			decided_on: '2026-02-12',
			reason: 'readable-m1-retracted',
			epochs: ['m-1']
		}]
	})
};

process.stdout.write(JSON.stringify(results) + '\n');
"""


def _node_command() -> list[str]:
    version = subprocess.run(["node", "--version"], capture_output=True, encoding="utf-8", check=True)
    major = int(version.stdout.strip().lstrip("v").split(".", 1)[0])
    cmd = ["node"]
    if major < 23:
        cmd.append("--experimental-strip-types")
    cmd.extend(["--input-type=module", "-e", PROBE_JS])
    return cmd


def _run_probe() -> dict:
    result = subprocess.run(
        _node_command(),
        cwd=GATE_ROOT,
        capture_output=True,
        encoding="utf-8",
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"node probe exited {result.returncode}: {result.stderr}")
    return json.loads(result.stdout)


def test_staircase_isolates_withdrawn_unreadable_earlier_epochs():
    got = _run_probe()

    # Baseline sanity control: without withdrawals, m-2 serves 200 OK when m-1 is absent for role tenant.
    baseline = got["baseline_absent_no_withdrawal"]
    assert baseline["status"] == 200, baseline
    assert baseline["body"]["format"] == "rezono.staircase/1", baseline
    assert len(baseline["body"]["cells"]) == 1, baseline
    assert baseline["body"]["cells"][0]["manifest"] == "m-2", baseline
    assert baseline["body"]["cells"][0]["value"] == "100", baseline

    # Negative control: withdrawal on a READABLE earlier epoch must still return 410 Gone.
    control = got["readable_m1_withdrawn_control"]
    assert control["status"] == 410, control
    assert control["body"]["error"] == "withdrawn", control
    assert control["body"]["withdrawal"]["id"] == "wd-readable-m1-control", control

    # Case A: m-1 is absent for role tenant (loadEpoch('m-1') -> undefined) and withdrawn.
    absent = got["absent_m1_withdrawn"]
    assert absent["status"] == 200, absent
    for secret in (
        "wd-confidential-m1-absent",
        "confidential-m1-absent-withdrawal-reason",
        "confidential-audit-board",
    ):
        assert secret not in absent["raw"], f"leaked secret {secret!r} in staircase response"
    assert absent["body"]["format"] == "rezono.staircase/1", absent
    assert absent["body"]["manifest"] == "m-2", absent
    assert [kt["manifest"] for kt in absent["body"]["knowledge_times"]] == ["m-2"], absent
    assert len(absent["body"]["cells"]) == 1, absent
    assert absent["body"]["cells"][0]["manifest"] == "m-2", absent
    assert absent["body"]["cells"][0]["state"] == "known", absent
    assert absent["body"]["cells"][0]["value"] == "100", absent

    # Case B: m-1 fails stillReadable(m-1, m-2) for role tenant and is withdrawn.
    unreadable = got["unreadable_m1_withdrawn"]
    assert unreadable["status"] == 200, unreadable
    for secret in (
        "wd-confidential-m1-unreadable",
        "confidential-m1-unreadable-withdrawal-reason",
        "confidential-review-committee",
    ):
        assert secret not in unreadable["raw"], f"leaked secret {secret!r} in staircase response"
    assert unreadable["body"]["format"] == "rezono.staircase/1", unreadable
    assert unreadable["body"]["manifest"] == "m-2", unreadable
    assert [kt["manifest"] for kt in unreadable["body"]["knowledge_times"]] == ["m-2"], unreadable
    assert len(unreadable["body"]["cells"]) == 1, unreadable
    assert unreadable["body"]["cells"][0]["manifest"] == "m-2", unreadable
    assert unreadable["body"]["cells"][0]["state"] == "known", unreadable
    assert unreadable["body"]["cells"][0]["value"] == "200", unreadable
