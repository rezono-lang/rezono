import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { parse as yaml } from 'yaml';
import { moduleForm } from '../src/module-json.ts';
import { checkNativeRules, type NativeRuleEnvironment } from '../src/native-rule-check.ts';

type Failure = { source: string; diagnostic: { code: string; text: string } };
type Relation = {
	name: string;
	role: 'base' | 'derived';
	key: { name: string; type: 'string' | 'integer' }[];
};
type Fixture = {
	input: { native_filter: {
		source: string;
		declaration: object;
		relations: Relation[];
		wrong_type: Failure;
		unbound: Failure;
	} };
};
const { input: { native_filter: fixture } } = yaml(readFileSync(
	new URL('../../tests/conformance/expression-filtered-count.yaml', import.meta.url), 'utf8',
)) as Fixture;
const environment: NativeRuleEnvironment = {
	schema: { rezono: '1.0', pack: 'measurement', base: 'https://example.org/measurement/', kinds: {} },
	relations: Object.fromEntries(fixture.relations.map(relation => [relation.name, {
		role: relation.role === 'base' ? 'input' : 'derived',
		world: 'closed',
		columns: relation.key.map(column => ({ name: column.name, type: column.type === 'string' ? 'Text' : 'Int' })),
	}])),
};

function diagnose(source: string, expectedTree?: object) {
	const { form, diagnostics } = moduleForm(source);
	assert.deepEqual(diagnostics, []);
	assert.ok(form && form.format === 'rezono.module/3');
	if (expectedTree) assert.deepEqual(form.module.decls, [expectedTree]);
	return checkNativeRules(form, environment).map(({ code, span }) => ({
		code, text: [...source].slice(Number(span.start), Number(span.end)).join(''),
	}));
}

const positive = diagnose(fixture.source, fixture.declaration);
const oldAggregateRefusal = [{
	code: 'R044', text: '(entry(_, _, _) where it.zone = a and b = it.band).count()',
}];
if (positive.length) {
	assert.deepEqual(positive, oldAggregateRefusal);
	process.stdout.write(JSON.stringify('filtered aggregate rejected'));
} else {
	for (const { source, diagnostic } of [fixture.wrong_type, fixture.unbound]) {
		assert.deepEqual(diagnose(fixture.source.replace('it.zone = a', source)), [diagnostic]);
	}
	process.stdout.write('null');
}
