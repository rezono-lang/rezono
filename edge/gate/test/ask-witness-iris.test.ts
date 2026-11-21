// The witness of an answer carries its canonical IRI (decisions/publication-conclusion-addresses.md §2). The
// expected IRIs are the Python side's (contracts/fixtures/iri/vectors.json); tests/slip/test_grounds_witness_iris.py
// asks the same of a store the publisher built, through the local reader.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import type { Witness } from '../../../contracts/typescript/generated/proof.ts';
import { ask, memoryGraph, type Edge, type Question } from '../src/ask.ts';
import { IriError } from '../src/iri.ts';

const GROUNDS: Question = { term: 'grounds', start: 'present', steps: [{ trace: { direction: 'back', depth: 'all' } }], answer: 'route', limit: 64 };
const vectors = JSON.parse(readFileSync(new URL('../../../contracts/fixtures/iri/vectors.json', import.meta.url), 'utf8')) as {
	witness: { base: string; witness: Witness; iri: string }[];
	base_refused: string[];
};

function graphOf(w: Witness) {
	const edges: Edge[] = (w.premises ?? []).map((p, position) => ({ c: w.conclusion, p: p.row, how: p.polarity, position }));
	return memoryGraph([w], edges);
}

test('each witness of an answer is the published one, unchanged, with the IRI the Python side gives', async () => {
	for (const { base, witness, iri } of vectors.witness.filter((v) => (v.witness.premises ?? []).length)) {
		const answer = await ask(graphOf(witness), GROUNDS, 'm-1', witness.conclusion, { limit: 64 }, base);
		assert.ok(answer);
		assert.equal(answer.witnesses.length, 1);
		const { iri: shown, ...rest } = answer.witnesses[0];
		assert.equal(shown, iri);
		assert.deepEqual(rest, witness);
		for (const step of answer.steps) assert.deepEqual(Object.keys(step).sort(), ['conclusion', 'how', 'position', 'premise']);
	}
});

test('a base that is not an absolute IRI ending in "/" is refused before anything is read, never repaired', async () => {
	const { witness } = vectors.witness[0];
	for (const base of vectors.base_refused) {
		await assert.rejects(ask(graphOf(witness), GROUNDS, 'm-1', witness.conclusion, { limit: 64 }, base), IriError, JSON.stringify(base));
	}
});
