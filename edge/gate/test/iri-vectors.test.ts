// The gate's canonical IRIs against the vectors the Python side writes (contracts/fixtures/iri/vectors.json,
// publication/tests/iri_vectors.py): spelling, pins, witness IRIs, and the conclusion spaces of a role's schema.
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import type { Bundle } from '../../../contracts/typescript/generated/bundle.ts';
import { conclusionIri, IriError, parsePin, pinIri, spell, splitConclusion, unspell, witnessDigest, witnessHash, witnessIri } from '../src/iri.ts';
import { roleSchema, type Listed } from '../src/expr.ts';

type Vectors = {
	spell: { id: string; segment: string }[];
	spell_refused: string[];
	unspell_refused: string[];
	pin: { iri: string; dataset: string; manifest?: string; pinned: string }[];
	pin_refused: { iri: string; dataset: string; manifest?: string }[];
	parse: { iri: string; unpinned: string; pin?: { dataset: string; manifest?: string } }[];
	parse_refused: string[];
	witness: { base: string; witness: unknown; iri: string; pinned: string }[];
	base_refused: string[];
	spaces: { about: string; bundle: Bundle; snapshots: Listed[]; conclusions: { kind: string; id: string; iri: string; pinned: string }[] }[];
};

const vectors = JSON.parse(readFileSync(new URL('../../../contracts/fixtures/iri/vectors.json', import.meta.url), 'utf8')) as Vectors;
const refused = (call: () => unknown, what: string) => assert.throws(call, IriError, what);

test('an id spells as one segment, and a segment unspells to its id only when it is its spelling', () => {
	for (const { id, segment } of vectors.spell) {
		assert.equal(spell(id), segment, JSON.stringify(id));
		assert.equal(unspell(segment), id, segment);
	}
	for (const id of vectors.spell_refused) refused(() => spell(id), JSON.stringify(id));
	for (const segment of vectors.unspell_refused) refused(() => unspell(segment), JSON.stringify(segment));
});

test('a pin is written and read as the Python side does, and refused where it refuses', () => {
	for (const { iri, dataset, manifest, pinned } of vectors.pin) assert.equal(pinIri(iri, { dataset, manifest }), pinned);
	for (const { iri, dataset, manifest } of vectors.pin_refused) refused(() => pinIri(iri, { dataset, manifest }), `${iri} ${manifest}`);
	for (const { iri, unpinned, pin } of vectors.parse) assert.deepEqual(parsePin(iri), pin ? { iri: unpinned, pin } : { iri: unpinned }, iri);
	for (const iri of vectors.parse_refused) refused(() => parsePin(iri), JSON.stringify(iri));
	assert.ok(vectors.parse_refused.some((iri) => iri.includes('m-01@')), 'm-01 is refused on both sides');
});

test('a witness IRI is <base>witness/<canonical sha256>, and a bad base is refused, never repaired', () => {
	for (const { base, witness, iri, pinned } of vectors.witness) {
		assert.equal(witnessIri(base, witness), iri);
		assert.equal(witnessIri(base, witness, parsePin(pinned).pin), pinned);
		assert.equal(witnessDigest(base, iri), witnessHash(witness));
	}
	for (const base of vectors.base_refused) refused(() => witnessIri(base, {}), JSON.stringify(base));
	// An independent check of the canonical form, written by hand (docs/contracts.md#canonical-hash): sorted keys,
	// no spaces, an integer as decimal text. Its sha256 is the digest the Python side put in the first vector.
	const canonical = '{"aggregates":[],"bindings":[{"value":"p-1","variable":"?p"}],"conclusion":{"key":"[\\"p-1\\"]","relation":"eligible"},'
		+ '"premises":[{"polarity":"positive","row":{"key":"[\\"p-1\\"]","relation":"member"},"stratum":"0"},'
		+ '{"polarity":"positive","row":{"key":"[\\"p-1\\"]","relation":"income_ok"},"stratum":"0"}],"rule_id":"r_income"}';
	assert.equal(vectors.witness[0].iri, `${vectors.witness[0].base}witness/${createHash('sha256').update(canonical, 'utf8').digest('hex')}`);
});

test('the IRI space of each kind a role reads comes from its schema: a subkind shares its root, also a hidden root', () => {
	for (const { about, bundle, snapshots, conclusions } of vectors.spaces) {
		const { spaces } = roleSchema(bundle, snapshots);
		assert.ok(spaces, about);
		assert.deepEqual([...spaces.keys()].sort(), conclusions.map((c) => c.kind).sort(), about);
		for (const { kind, id, iri, pinned } of conclusions) {
			assert.equal(conclusionIri(spaces.get(kind)!, id), iri, `${about}: ${kind}`);
			assert.equal(conclusionIri(spaces.get(kind)!, id, parsePin(pinned).pin), pinned, `${about}: ${kind}`);
			assert.deepEqual(splitConclusion(iri), { space: spaces.get(kind), id }, `${about}: ${kind}`);
		}
	}
});
