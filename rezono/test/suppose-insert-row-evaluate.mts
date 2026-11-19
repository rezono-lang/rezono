import { answer, check, isError, load, suppose, type Schema } from '../src/index.ts';

// Neutral schema exercising required, optional, reference, inverse and empty-brace whole-record insertions
// (decisions/language-safe-steps.md §1).
const schema: Schema = {
	rezono: '1.0',
	pack: 'safe_steps_probe',
	base: 'https://rezono.example/safe-steps-probe/',
	kinds: {
		Zone: {
			world: 'closed',
			id: { type: 'Text' },
			slots: {
				policies: { ref: 'Policy', card: '*', states: ['known'], inverse: 'zone' },
			},
		},
		Policy: {
			world: 'closed',
			id: { type: 'Text' },
			slots: {
				mode: { type: 'Text', card: '1', states: ['known'] },
				zone: { ref: 'Zone', card: '1', states: ['known'] },
				note: { type: 'Text', card: '?', states: ['known', 'not_applicable'] },
			},
		},
	},
};

const base = load(schema, [
	{ $kind: 'Zone', $id: 'zone-a' },
	{ $kind: 'Policy', $id: 'policy-a', mode: 'audit', zone: { $ref: 'zone-a' } },
]);

const errorsOf = (source: string) =>
	check(source, schema)
		.diagnostics.filter(isError)
		.map((d) => ({ code: d.code, text: d.span.text }));

const issues: unknown[] = [];

// 1. Valid insertion with required slots and reference; base data stays untouched.
{
	const line = '+ Policy policy-b {mode = "enforce", zone = Zone:`zone-a`}';
	const checked = check(line, schema);
	const errs = checked.diagnostics.filter(isError);
	if (errs.length) {
		issues.push({ case: 'valid-insert-check', errors: errs.map((d) => d.code) });
	} else {
		try {
			const updated = suppose(base, checked, schema);
			const q = check('ask Policy where mode = "enforce" show zone', schema);
			const after = await answer(q, schema, updated);
			const before = await answer(q, schema, base);
			const afterIds = after?.rows.map((r) => [r.$id, r.c1]) ?? null;
			const beforeIds = before?.rows.map((r) => r.$id) ?? null;
			if (JSON.stringify(afterIds) !== JSON.stringify([['policy-b', { $ref: 'zone-a' }]])) {
				issues.push({ case: 'valid-insert-answer', actual: afterIds });
			}
			if (JSON.stringify(beforeIds) !== JSON.stringify([])) {
				issues.push({ case: 'valid-insert-mutated-base', actual: beforeIds });
			}
		} catch (error) {
			issues.push({ case: 'valid-insert-apply', thrown: String(error) });
		}
	}
}

// 2. Empty braces allowed when the kind has no required slot other than its identifier.
{
	const line = '+ Zone zone-b {}';
	const checked = check(line, schema);
	const errs = checked.diagnostics.filter(isError);
	if (errs.length) {
		issues.push({ case: 'empty-braces-check', errors: errs.map((d) => d.code) });
	} else {
		try {
			const updated = suppose(base, checked, schema);
			const q = check('ask Zone where true', schema);
			const after = await answer(q, schema, updated);
			const ids = after?.rows.map((r) => r.$id) ?? null;
			if (JSON.stringify(ids) !== JSON.stringify(['zone-a', 'zone-b'])) {
				issues.push({ case: 'empty-braces-answer', actual: ids });
			}
		} catch (error) {
			issues.push({ case: 'empty-braces-apply', thrown: String(error) });
		}
	}
}

// 3. Counter-cases: schema diagnostics on invalid whole-record insertions (must NOT be R015 unimplemented).
const refusedAtCheck: [string, string][] = [
	['missing-required-slot', '+ Policy policy-c {zone = Zone:`zone-a`}'],
	['unknown-slot', '+ Policy policy-d {mode = "enforce", zone = Zone:`zone-a`, bogus = "x"}'],
	['duplicate-slot', '+ Policy policy-e {mode = "enforce", mode = "audit", zone = Zone:`zone-a`}'],
	['wrong-slot-type', '+ Policy policy-f {mode = 42, zone = Zone:`zone-a`}'],
	['readonly-inverse-slot', '+ Zone zone-c {policies = Policy:`policy-a`}'],
	['identifier-slot', '+ Policy policy-g {id = "policy-g", mode = "enforce", zone = Zone:`zone-a`}'],
	['unknown-kind', '+ Ghost ghost-a {}'],
];
for (const [name, source] of refusedAtCheck) {
	const errs = errorsOf(source);
	if (!errs.length || errs.every((e) => e.code === 'R015')) {
		issues.push({ case: name, actual: errs });
	}
}

// 4. Counter-case: freshness — inserting an already existing key is refused even when values agree.
{
	const line = '+ Policy policy-a {mode = "audit", zone = Zone:`zone-a`}';
	const checked = check(line, schema);
	if (checked.diagnostics.some(isError)) {
		issues.push({ case: 'existing-key-check', errors: checked.diagnostics.filter(isError).map((d) => d.code) });
	} else {
		let refused = false;
		try {
			suppose(base, checked, schema);
		} catch {
			refused = true;
		}
		if (!refused) {
			issues.push({ case: 'existing-key-not-refused' });
		}
	}
}

process.stdout.write(JSON.stringify(issues));
