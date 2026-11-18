import assert from 'node:assert/strict';
import { readdirSync, readFileSync } from 'node:fs';
import { test } from 'node:test';
import { parse as yaml } from 'yaml';
import { answer, check, isError, load, type Schema, type SlotDef, type StateName, type World } from '../src/index.ts';

interface Case {
	id: string;
	status: 'settled';
	input: {
		rows: Record<string, unknown>[];
		select: { kind: string; id: string };
		language?: string;
	};
	expect: { value: unknown; state: StateName; reason: string | null; witness: unknown };
	unsupported?: { language?: string };
}

interface Attribute {
	range?: string;
	identifier?: boolean;
	required?: boolean;
	multivalued?: boolean;
	annotations?: { world?: World };
}

interface NeutralFixture {
	id: string;
	name: string;
	default_range: string;
	classes: Record<string, {
		annotations?: { world?: World };
		attributes: Record<string, Attribute>;
	}>;
}

// Read the shared fixture's elementary LinkML declarations for the language's role schema.
function readFixture(): Schema {
	const fixture = yaml(readFileSync(new URL('../../tests/fixtures/neutral/schema/neutral.yaml', import.meta.url), 'utf8')) as NeutralFixture;
	const schema: Schema = { rezono: '1.0', pack: fixture.name, base: new URL('./', `${fixture.id}/`).href, kinds: {} };
	for (const [kind, declaration] of Object.entries(fixture.classes)) {
		const world = declaration.annotations?.world ?? 'closed';
		const slots: Record<string, SlotDef> = {};
		for (const [name, attribute] of Object.entries(declaration.attributes)) {
			if (attribute.identifier) continue;
			const range = attribute.range ?? fixture.default_range;
			const slotWorld = attribute.annotations?.world ?? world;
			const card = attribute.multivalued ? (attribute.required ? '+' : '*') : (attribute.required ? '1' : '?');
			const states: StateName[] = ['known'];
			if (!attribute.multivalued) {
				if (!attribute.required) states.push('not_applicable');
				if (attribute.required || slotWorld === 'open') states.push('unknown');
			}
			const slot = { card, states, ...(slotWorld === world ? {} : { world: slotWorld }) } as const;
			if (Object.hasOwn(fixture.classes, range)) slots[name] = { ...slot, ref: range };
			else {
				assert.ok(range === 'string' || range === 'integer', `unsupported neutral range: ${kind}.${name} (${range})`);
				slots[name] = { ...slot, type: range === 'integer' ? 'Integer' : 'Text' };
			}
		}
		schema.kinds[kind] = { world, id: { type: 'Text' }, slots };
	}
	return schema;
}

const stateMembers = {
	$na: 'not_applicable',
	$unknown: 'unknown',
	$invalid: 'invalid'
} as const;

function shownValue(cell: unknown): Pick<Case['expect'], 'value' | 'state' | 'reason'> {
	if (cell !== null && typeof cell === 'object') {
		for (const member of Object.keys(stateMembers) as (keyof typeof stateMembers)[]) {
			if (!Object.hasOwn(cell, member)) continue;
			const reason = (cell as Record<string, unknown>)[member];
			assert.ok(typeof reason === 'string');
			return { value: null, state: stateMembers[member], reason: reason || null };
		}
	}
	return { value: cell, state: 'known', reason: null };
}

const root = new URL('../../tests/conformance/', import.meta.url);
const cases = readdirSync(root)
	.filter((file) => file.endsWith('.yaml') && file !== 'sources.yaml')
	.sort()
	.map((file) => {
		const entry = yaml(readFileSync(new URL(file, root), 'utf8')) as Case;
		assert.equal(`${entry.id}.yaml`, file);
		assert.equal(entry.status, 'settled');
		const reason = entry.unsupported?.language;
		if (reason !== undefined) assert.ok(typeof reason === 'string' && reason.trim(), `${entry.id}: give the specific language limitation`);
		return entry;
	});

test('the shared conformance corpus has a case for the language', () => {
	assert.ok(cases.some((entry) => entry.unsupported?.language === undefined));
});

const schema = readFixture();
for (const { id, input, expect, unsupported } of cases) {
	test(`shared conformance: ${id}`, { skip: unsupported?.language }, async () => {
		assert.ok(typeof input.language === 'string' && input.language.trim(), 'a language case gives its question');
		const checked = check(input.language, schema);
		assert.deepEqual(checked.diagnostics.filter(isError), []);
		assert.equal(checked.answer?.kind, input.select.kind);
		assert.equal(checked.answer?.shown.length, 1);
		const result = await answer(checked, schema, load(schema, input.rows));
		assert.ok(result);
		const projected = result.rows.find((row) => row.$id === input.select.id);
		const undecided = result.undecided.find((row) => row.$id === input.select.id);
		const expected = { value: expect.value, state: expect.state, reason: expect.reason };
		if (undecided) {
			assert.deepEqual({ value: null, state: undecided.state, reason: undecided.reason || null }, expected);
			// The answer exposes a source row as the cause of an undecided predicate.
			if (undecided.cause_relation) {
				assert.deepEqual({ relation: undecided.cause_relation, key: JSON.parse(undecided.cause_key) }, expect.witness);
			}
		} else {
			assert.ok(projected && Object.hasOwn(projected, 'c1'), 'the selected answer supplies its projected value');
			assert.deepEqual(shownValue(projected.c1), expected);
		}
	});
}
