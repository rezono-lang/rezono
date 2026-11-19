// Check that the TypeScript native rule checker refuses a predicate summary linked for another relation or
// owner, as Python lowering does for the `forged` case of tests/conformance/expression-negated-call.yaml.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { parse } from 'yaml';
import { moduleForm } from '../src/module-json.ts';
import { checkNativeRules } from '../src/native-rule-check.ts';
import type { Schema, World } from '../src/schema.ts';

interface Summary {
	relation: string;
	owner: string;
	columns: { name: string; logical: string; physical: string }[];
	world: World;
	stratum: number;
	states: string[];
	reads: string[];
}

interface Case {
	input: {
		consumer: string;
		cases: { id: string; relation: string; guard: string; summary?: string; error?: string }[];
	};
	expect: {
		value: { summaries: Record<string, Summary> };
		witness: { primary: { file: string; at: string } };
	};
}

const path = new URL('../../tests/conformance/expression-negated-call.yaml', import.meta.url);
const { input, expect } = parse(readFileSync(path, 'utf8')) as Case;
const { summaries } = expect.value;
const schema: Schema = {
	rezono: '1.0', pack: 'gauge-case', base: 'https://example.org/gauge/',
	kinds: { Gauge: { id: { type: 'Text' }, world: 'closed', slots: {
		level: { type: 'Integer', card: '1', states: ['known', 'unknown'] },
	} } },
};
const columns = [{ name: 'g', type: 'Gauge' }];
const marker = { columns, world: 'closed', role: 'derived' } as const;

const forged = input.cases.find(entry => entry.id === 'forged');
assert.ok(forged?.summary && forged.error);
assert.notEqual(summaries.settled.owner, summaries.active.owner);
// Each sample calls `relation`, owned by `owner`, with the linked `predicate` summary.
const samples = [
	// The vector's case: the decided summary of `settled` attached to the partial relation `active`.
	{ id: 'forged', relation: forged.relation, owner: summaries[forged.relation].owner, guard: forged.guard,
		predicate: summaries[forged.summary], error: forged.error },
	// A decided summary naming the right relation but another owner proves nothing about this relation.
	{ id: 'forged-owner', relation: 'active', owner: summaries.active.owner, guard: 'not active(g)',
		predicate: { ...summaries.settled, relation: 'active' },
		error: forged.error },
	// Control: the same decided summary on its own relation and owner is a legal anti-join.
	{ id: 'genuine', relation: 'settled', owner: summaries.settled.owner, guard: 'not settled(g)',
		predicate: summaries.settled },
];

const differences: unknown[] = [];
for (const sample of samples) {
	const source = input.consumer.replace('GUARD', sample.guard);
	const { form, diagnostics } = moduleForm(source);
	assert.deepEqual(diagnostics, []);
	assert.ok(form?.format === 'rezono.module/3');
	const span = form.spans.find(place => place.at === expect.witness.primary.at);
	assert.ok(span);
	const declaration = {
		columns, world: sample.predicate.world, role: 'derived', owner: sample.owner, predicate: { ...sample.predicate },
	} as const;
	const actual = checkNativeRules({ ...form, file: expect.witness.primary.file }, {
		schema, relations: { marker, [sample.relation]: declaration } as never,
	});
	const positions = actual.map(({ code, span, related }) => ({ code, span, related: related ?? [] }));
	// As in Python lowering, a forged summary carries no related places: it explains nothing about the callee.
	const expected = sample.error ? [{ code: sample.error, span, related: [] }] : [];
	try {
		assert.deepEqual(positions, expected);
	} catch (error) {
		if (!(error instanceof assert.AssertionError)) throw error;
		differences.push({ case: sample.id, actual: positions, expected });
	}
}
process.stdout.write(JSON.stringify(differences));
