import { readFileSync } from 'node:fs';
import { parse } from 'yaml';
import { answer, check, isError, load, type RuleDef, type Schema } from '../src/index.ts';

// The predicate summary a question receives for a derived relation (decisions/language-expression-semantics.md §2).
type Predicate = RuleDef & { states: string[]; outcome: boolean };
interface Outcome {
	key: string[];
	state: string;
	value?: boolean;
	reason?: string;
	cause?: { relation: string; key: string[] };
}
interface Case {
	input: {
		rows: Record<string, unknown>[];
		role_schema: Schema;
		predicates: Record<string, Predicate>;
		successes: Record<string, string[][]>;
		outcomes: Record<string, Outcome[]>;
		cases: { id: string; question: string; error?: { code: string; text: string } }[];
	};
	expect: { value: Record<string, unknown> };
}

const path = new URL('../../tests/conformance/expression-ask-partial-call.yaml', import.meta.url);
const { input, expect } = parse(readFileSync(path, 'utf8')) as Case;
const schema: Schema = { ...input.role_schema, rules: input.predicates };
// Success rows load as before; a checked keyed outcome is supplied beside them for the relations that publish one.
const data = load(schema, input.rows, { rules: input.successes, outcomes: input.outcomes } as Parameters<typeof load>[2]);
const differences: unknown[] = [];

for (const sample of input.cases) {
	let actual: unknown;
	try {
		const checked = check(sample.question, schema);
		const errors = checked.diagnostics.filter(isError).map(({ code, span }) => ({ code, text: span.text }));
		if (errors.length || sample.error) actual = errors;
		else {
			const result = await answer(checked, schema, data);
			actual = result && {
				rows: result.rows.map(row => row.$id),
				undecided: result.undecided.map(row => ({
					id: row.$id, state: row.state, reason: row.reason,
					cause_relation: row.cause_relation, cause_key: row.cause_key,
				})),
				counts: result.counts,
			};
		}
	} catch (error) {
		actual = { thrown: String(error) };
	}
	const expected = sample.error ? [sample.error] : expect.value[sample.id];
	if (JSON.stringify(actual) !== JSON.stringify(expected)) differences.push({ case: sample.id, actual, expected });
}
process.stdout.write(JSON.stringify(differences));
