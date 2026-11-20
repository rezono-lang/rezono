import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { readdirSync, readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { test } from 'node:test';
import { parse as yaml } from 'yaml';
import { answer, check, isAsk, isCheck, isError, load, outputSchema, publish, type Schema, type SlotDef, type StateName, type World } from '../src/index.ts';

interface Case {
	id: string;
	status: 'settled';
	input: {
		rows: Record<string, unknown>[];
		select?: { kind: string; id: string };
		language?: string;
		check?: string;
		ask?: string;
		role?: string;
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
	})
	.filter((entry) => entry.input.language !== undefined || entry.input.check !== undefined || entry.input.ask !== undefined);

test('the shared conformance corpus has a case for the language', () => {
	assert.ok(cases.some((entry) => entry.unsupported?.language === undefined));
});

// A reason that starts with PENDING names the task that makes the language answer its case
// (rezono/test/test_conformance_language_outcomes.py). Such a case is compared, not skipped. While its task is an
// expected failure the comparison is a todo whatever its result, so that only the task's own pull request, which
// lifts its strict xfail, turns the comparison into a passing one. The task needs no change to this runner or to
// the case file; its reason can be removed afterwards.
const PENDING = 'Waits for rezono/test/test_conformance_language_outcomes.py--';
const QUESTIONS_AND_CHECKS_TASK = 'rezono/test/test_conformance_language_outcomes.py--test_language_compares_question_and_check_cases';
const board = JSON.parse(execFileSync('python', ['scripts/red_list.py', '--json'], {
	cwd: fileURLToPath(new URL('../../', import.meta.url)), encoding: 'utf8',
})) as { id: string }[];
const expectedRed = new Set(board.map((task) => task.id));
const pendingTask = (reason: string | undefined) =>
	reason?.startsWith(PENDING) ? reason.slice('Waits for '.length).split(':')[0].trim() : undefined;

const schema = readFixture();
for (const { id, input, expect, unsupported } of cases) {
	const isQuestionOrCheck = input.language === undefined && (input.check !== undefined || input.ask !== undefined);
	const task = pendingTask(unsupported?.language) ?? (isQuestionOrCheck && unsupported?.language === undefined ? QUESTIONS_AND_CHECKS_TASK : undefined);
	const skip = task === undefined ? unsupported?.language : undefined;
	const run = () => (input.language !== undefined ? compare(input, expect) : compareQuestionOrCheck(id, input, expect));
	test(`shared conformance: ${id}`, { skip }, async (t) => {
		if (task !== undefined && expectedRed.has(task)) {
			try {
				await run();
				t.todo(`${id} passes; ${task} can lift its strict xfail`);
			} catch (error) {
				t.todo(`${task}: ${error instanceof Error ? error.message : String(error)}`);
			}
			return;
		}
		await run();
	});
}

async function compareQuestionOrCheck(id: string, input: Case['input'], expect: Case['expect']) {
	if (input.ask !== undefined) {
		const checked = check(input.ask, schema);
		assert.deepEqual(checked.diagnostics.filter(isError), []);
		assert.ok(checked.tree && isAsk(checked.tree));
		const answerSchema = await outputSchema(checked.tree, checked, schema);
		assert.ok(answerSchema);
		const columns = Object.fromEntries(
			Object.entries(answerSchema.kinds.Answer.slots).map(([name, slot]) => [
				name,
				slot.ref !== undefined ? `ref ${slot.ref.replace(/^p\./, '')}` : slot.type!.toLowerCase(),
			])
		);
		assert.deepEqual(columns, (expect.value as { columns: Record<string, string> }).columns);
		assert.equal(expect.state, 'known');
		assert.equal(expect.reason, null);
		return;
	}
	assert.ok(typeof input.check === 'string' && input.check.trim(), 'a check case gives its check statement');
	const checked = check(input.check, schema);
	assert.deepEqual(checked.diagnostics.filter(isError), []);
	assert.ok(checked.tree && isCheck(checked.tree));
	const pub = publish(checked, schema, load(schema, input.rows));
	assert.ok(pub);
	const expectedValue = expect.value as Record<string, unknown>;
	const blocked = pub.outcome === 'blocked';
	if (id === 'value-warn-never-blocks') {
		assert.ok(pub.violations.length > 0, 'warning case must include a false row');
		assert.ok(pub.undecided.some((u) => u.state === 'unknown'), 'warning case must include an unknown row');
		assert.ok(pub.undecided.some((u) => u.state === 'invalid'), 'warning case must include an invalid row');
		assert.deepEqual({ false: blocked, unknown: blocked, invalid: blocked }, expectedValue.publication_blocked);
	} else if ('publication_blocked' in expectedValue) {
		assert.equal(blocked, expectedValue.publication_blocked);
	}
	if ('violations' in expectedValue) {
		assert.deepEqual(pub.violations, expectedValue.violations);
	}
	if ('undecided' in expectedValue) {
		assert.deepEqual(
			pub.undecided.map((u) => ({ subject: u.id, state: u.state, reason: u.reason })),
			expectedValue.undecided
		);
	}
	if ('count_per_role' in expectedValue) {
		assert.equal(String(pub.undecided.length), expectedValue.count_per_role);
	}
	const expectedWitness = expect.witness as { undecided?: unknown[] } | null;
	if (expectedWitness && 'undecided' in expectedWitness) {
		assert.deepEqual(
			pub.undecided.map((u) => u.cause),
			expectedWitness.undecided
		);
	}
	const topState = !('undecided' in expectedValue) && pub.undecided.length === 1 ? pub.undecided[0].state : 'known';
	const topReason = !('undecided' in expectedValue) && pub.undecided.length === 1 ? pub.undecided[0].reason : null;
	assert.deepEqual({ state: topState, reason: topReason }, { state: expect.state, reason: expect.reason });
}

async function compare(input: Case['input'], expect: Case['expect']) {
	const { language, select } = input;
	assert.ok(typeof language === 'string' && language.trim(), 'a language case gives its question');
	assert.ok(select, 'a language case gives its selected subject');
	const checked = check(language, schema);
	assert.deepEqual(checked.diagnostics.filter(isError), []);
	assert.equal(checked.answer?.kind, select.kind);
	assert.equal(checked.answer?.shown.length, 1);
	const result = await answer(checked, schema, load(schema, input.rows));
	assert.ok(result);
	const projected = result.rows.find((row) => row.$id === select.id);
	const undecided = result.undecided.find((row) => row.$id === select.id);
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
}
