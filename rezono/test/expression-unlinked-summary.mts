// Check that the TypeScript native rule checker refuses a predicate summary that does not say which relation and
// owner it was linked for, as Python lowering does: native_rule_lowering compares the summary's `relation` and
// `owner` with the called relation and its signature, and an absent member never matches.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { parse } from 'yaml';
import { moduleForm } from '../src/module-json.ts';
import { checkNativeRules } from '../src/native-rule-check.ts';
import type { Schema, World } from '../src/schema.ts';

interface Summary {
	relation?: string;
	owner?: string;
	columns: { name: string; logical: string; physical: string }[];
	world: World;
	stratum: number;
	states: string[];
	reads: string[];
}

interface Case {
	input: { consumer: string };
	expect: {
		value: { summaries: Record<string, Summary> };
		witness: { primary: { file: string; at: string } };
	};
}

const path = new URL('../../tests/conformance/expression-negated-call.yaml', import.meta.url);
const { input, expect } = parse(readFileSync(path, 'utf8')) as Case;
const { settled } = expect.value.summaries;
assert.equal(settled.relation, 'settled');
assert.ok(settled.owner);
const schema: Schema = {
	rezono: '1.0', pack: 'gauge-case', base: 'https://example.org/gauge/',
	kinds: { Gauge: { id: { type: 'Text' }, world: 'closed', slots: {
		level: { type: 'Integer', card: '1', states: ['known', 'unknown'] },
	} } },
};
const columns = [{ name: 'g', type: 'Gauge' }];
const marker = { columns, world: 'closed', role: 'derived' } as const;
const { relation: _relation, ...withoutRelation } = settled;
const { owner: _owner, ...withoutOwner } = settled;
const { relation: _r, owner: _o, ...bare } = settled;

// Each sample negates the decided relation `settled`. Only the control links its summary for `settled` and its
// owner on both sides; every other sample leaves out a member that proves where the summary came from.
const samples: { id: string; owner?: string; predicate: Summary; error?: string }[] = [
	{ id: 'no-relation', owner: settled.owner, predicate: withoutRelation, error: 'R047' },
	{ id: 'no-owner', owner: settled.owner, predicate: withoutOwner, error: 'R047' },
	{ id: 'no-signature-owner', predicate: settled, error: 'R047' },
	{ id: 'bare', predicate: bare, error: 'R047' },
	{ id: 'genuine', owner: settled.owner, predicate: settled },
];

const differences: unknown[] = [];
for (const sample of samples) {
	const source = input.consumer.replace('GUARD', 'not settled(g)');
	const { form, diagnostics } = moduleForm(source);
	assert.deepEqual(diagnostics, []);
	assert.ok(form?.format === 'rezono.module/3');
	const span = form.spans.find(place => place.at === expect.witness.primary.at);
	assert.ok(span);
	const declaration = {
		columns, world: sample.predicate.world, role: 'derived',
		...(sample.owner ? { owner: sample.owner } : {}), predicate: { ...sample.predicate },
	} as const;
	const actual = checkNativeRules({ ...form, file: expect.witness.primary.file }, {
		schema, relations: { marker, settled: declaration } as never,
	});
	const positions = actual.map(({ code, span, related }) => ({ code, span, related: related ?? [] }));
	// As for a forged summary, an unlinked one explains nothing about the callee, so it has no related places.
	const expected = sample.error ? [{ code: sample.error, span, related: [] }] : [];
	try {
		assert.deepEqual(positions, expected);
	} catch (error) {
		if (!(error instanceof assert.AssertionError)) throw error;
		differences.push({ case: sample.id, actual: positions, expected });
	}
}
process.stdout.write(JSON.stringify(differences));
