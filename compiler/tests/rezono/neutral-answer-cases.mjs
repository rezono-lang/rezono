import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { answer, check, load, publish } from '../../../rezono/src/index.ts';

const { schema, input } = JSON.parse(readFileSync(0, 'utf8'));

async function evaluate(question, schema, data) {
	const checked = check(question, schema);
	const result = await answer(checked, schema, data);
	assert.ok(result, JSON.stringify(checked.diagnostics));
	return { schema: result.schema, rows: result.rows, undecided: result.undecided, counts: result.counts };
}

const fixture = input.derive && await evaluate(input.derive, schema, load(schema, input.rows));
const questionSchema = fixture?.schema ?? schema;
const questionData = load(questionSchema, fixture?.rows ?? input.rows);
const results = {};
for (const [name, question] of Object.entries(input.questions)) {
	results[name] = await evaluate(question, questionSchema, questionData);
}
for (const [name, statement] of Object.entries(input.publication ?? {})) {
	const checked = check(statement, questionSchema);
	const result = publish(checked, questionSchema, questionData);
	assert.ok(result, JSON.stringify(checked.diagnostics));
	results[name] = result;
}
process.stdout.write(JSON.stringify({ fixture, results }));
