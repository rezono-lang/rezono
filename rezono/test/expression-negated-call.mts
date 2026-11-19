import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { parse } from 'yaml';
import { moduleForm } from '../src/module-json.ts';
import { checkNativeRules } from '../src/native-rule-check.ts';
import type { Schema, World } from '../src/schema.ts';

interface Location {
	file: string;
	at: string;
	line: string;
	column: string;
}

interface Predicate {
	relation: string;
	owner: string;
	columns: { name: string; logical: string; physical: string }[];
	world: World;
	stratum: number;
	states: ('known' | 'not_applicable' | 'unknown' | 'invalid')[];
	reads: string[];
	related?: Location[];
}

interface Case {
	input: {
		consumer: string;
		cases: { id: string; relation: string; guard: string; summary?: string; error?: string; lowering_only?: true }[];
	};
	expect: {
		value: { summaries: Record<string, Predicate> };
		witness: { primary: Location; related: Location[] };
	};
}

const path = new URL('../../tests/conformance/expression-negated-call.yaml', import.meta.url);
const { input, expect } = parse(readFileSync(path, 'utf8')) as Case;
const schema: Schema = {
	rezono: '1.0', pack: 'gauge-case', base: 'https://example.org/gauge/',
	kinds: { Gauge: { id: { type: 'Text' }, world: 'closed', slots: {
		level: { type: 'Integer', card: '1', states: ['known', 'unknown'] },
	} } },
};
const columns = [{ name: 'g', type: 'Gauge' }];
const marker = { columns, world: 'closed', role: 'derived' } as const;
const differences: unknown[] = [];
const relatedSpans = expect.witness.related.map(({ file, at, line, column }) => ({ file, at, line, column }));

for (const sample of input.cases.filter(entry => !entry.lowering_only)) {
	// A case without a summary checks a derived relation whose predicate states were never linked.
	const predicate = sample.summary ? { ...expect.value.summaries[sample.summary] } : undefined;
	if (predicate && sample.summary === 'active') predicate.related = relatedSpans;
	// The signature names the owner of the called relation, which a linked summary must repeat with its relation.
	const owner = expect.value.summaries[sample.relation].owner;
	const declaration = predicate
		? { columns, world: predicate.world, role: 'derived', owner, predicate } as const
		: { columns, world: 'closed', role: 'derived', owner } as const;
	const source = input.consumer.replace('GUARD', sample.guard);
	const { form, diagnostics } = moduleForm(source);
	assert.deepEqual(diagnostics, []);
	assert.ok(form?.format === 'rezono.module/3');
	const span = form.spans.find(place => place.at === expect.witness.primary.at);
	assert.ok(span);
	assert.equal(span.line, expect.witness.primary.line);
	const start = Number(span.start);
	assert.equal(start - source.lastIndexOf('\n', start - 1), Number(expect.witness.primary.column));
	assert.equal(source.slice(start, Number(span.end)), sample.guard);

	const located = { ...form, file: expect.witness.primary.file };
	const actual = checkNativeRules(located, {
		schema, relations: { marker, [sample.relation]: declaration },
	});
	const expected = sample.error ? [{
		code: sample.error,
		span,
		related: sample.error === 'R047' && predicate ? relatedSpans : [],
	}] : [];
	const positions = actual.map(({ code, span, related }) => ({ code, span, related: related ?? [] }));
	try {
		assert.deepEqual(positions, expected);
	} catch (error) {
		if (!(error instanceof assert.AssertionError)) throw error;
		differences.push({ case: sample.id, actual: positions, expected });
	}
}
process.stdout.write(JSON.stringify(differences));
