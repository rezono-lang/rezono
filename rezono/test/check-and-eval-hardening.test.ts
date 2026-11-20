// Counterexamples for expression checking, evaluation, grammar, and version separation bugs.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import {
	answer,
	check,
	declare,
	isError,
	load,
	parse,
	parseModule,
	type Schema
} from '../src/index.ts';
import { checkNativeRules, type NativeRuleEnvironment, type NativeRuleForm } from '../src/native-rule-check.ts';

const fixture = JSON.parse(readFileSync(new URL('fixture.schema.json', import.meta.url), 'utf8')) as Schema;

function schemaWith(change: (s: Schema) => void): Schema {
	const s = structuredClone(fixture);
	change(s);
	return s;
}

const errorCodes = (text: string, schema = fixture): string[] =>
	check(text, schema)
		.diagnostics.filter(isError)
		.map((d) => `${d.code} at ${d.span.text}`);

test('1. `is` state tests clear open-world propagation (no false R004)', async () => {
	assert.deepEqual(errorCodes('ask Host where not (Team.any(true) is unknown)'), []);
	assert.deepEqual(errorCodes('ask Host where not (Team.any(true) is known)'), []);
	assert.deepEqual(errorCodes('ask Host where not (Team.any(true) is invalid)'), []);
	assert.deepEqual(errorCodes('ask Host where not (Team.any(true) is n/a)'), []);

	const openFits = schemaWith((s) => {
		s.rules!.fits.world = 'open';
	});
	assert.deepEqual(errorCodes('ask Plan where (fits(host-b, plan) is known) => plan.memory > 1 GiB', openFits), []);

	// Direct negation / implication over an open relation without `is` still produces R004.
	assert.deepEqual(errorCodes('ask Host where not Team.any(true)'), ['R004 at not Team.any(true)']);
	assert.deepEqual(errorCodes('ask Plan where fits(host-b, plan) => plan.memory > 1 GiB', openFits), ['R004 at fits(host-b, plan) => plan.memory > 1 GiB']);

	// Evaluation of `not (Team.any(true) is unknown)` on an empty open Team succeeds and returns known false.
	const checked = check('ask Host where not (Team.any(true) is unknown)', fixture);
	const data = load(fixture, [{ $kind: 'Host', $id: 'h1', provider: 'cherry', memory_need: '64 GiB' }]);
	const res = (await answer(checked, fixture, data))!;
	assert.equal(res.rows.length, 0);
	assert.equal(res.undecided.length, 0);
});

test('2. aggregates and filters require a set base, and min/max require an ordered type', () => {
	assert.deepEqual(errorCodes('ask Host where memory_need.count() = 1'), ['R003 at memory_need.count()']);
	assert.deepEqual(errorCodes('ask Host where memory_need.sum() > 0 GiB'), ['R003 at memory_need.sum()']);
	assert.deepEqual(errorCodes('ask Host where memory_need.any(true)'), ['R003 at memory_need.any(true)']);
	assert.deepEqual(errorCodes('ask Host where memory_need.one() > 0 GiB'), ['R003 at memory_need.one()']);
	assert.deepEqual(errorCodes('ask Host where (memory_need where it > 1 GiB).count() = 1'), ['R003 at memory_need where it > 1 GiB']);
	assert.deepEqual(errorCodes('ask Host where memory_need.where(it > 1 GiB).count() = 1'), ['R003 at memory_need.where(it > 1 GiB)']);

	const extended = schemaWith((s) => {
		s.types!.Tier = { of: 'Enum' };
		s.enums = { Tier: ['low', 'high'] };
		s.kinds.Host.slots.label = { type: 'Text', card: '1', states: ['known'] };
		s.kinds.Host.slots.tier = { type: 'Tier', card: '1', states: ['known'] };
		s.kinds.Host.slots.created = { type: 'DateTime', card: '1', states: ['known'] };
	});
	assert.deepEqual(errorCodes('ask Host where Host.min() = host', extended), ['R003 at Host.min()']);
	assert.deepEqual(errorCodes('ask Host where Host.max() = host', extended), ['R003 at Host.max()']);
	assert.deepEqual(errorCodes('ask Host where Host.min(it.owner) = team-platform', extended), ['R003 at it.owner']);
	assert.deepEqual(errorCodes('ask Host where Host.min(it.label) = "a"', extended), ['R003 at it.label']);
	assert.deepEqual(errorCodes('ask Host where Host.max(it.tier) = high', extended), ['R003 at it.tier']);

	// Ordered element types still pass.
	assert.deepEqual(errorCodes('ask Host where Host.min(it.memory_need) > 0 GiB', extended), []);
	assert.deepEqual(errorCodes('ask Host where Host.max(it.created) > 2026-01-01T00:00:00Z', extended), []);
});

test('3. single ordered(ty) definition, UTC DateTime comparison, and Date arithmetic dimension check', async () => {
	const extended = schemaWith((s) => {
		s.types!.Tier = { of: 'Enum' };
		s.types!.Month = { of: 'Quantity', dimension: 'calendar', unit: 'month', storage_unit: 'month', factor: '1' };
		s.enums = { Tier: ['low', 'high'] };
		s.kinds.Host.slots.label = { type: 'Text', card: '1', states: ['known'] };
		s.kinds.Host.slots.tier = { type: 'Tier', card: '1', states: ['known'] };
		s.kinds.Host.slots.created = { type: 'DateTime', card: '1', states: ['known'] };
		s.kinds.Host.slots.due = { type: 'Date', card: '1', states: ['known'] };
	});

	// Text and unordered Enum are not ordered in check.ts.
	assert.deepEqual(errorCodes('ask Host where label < "z"', extended), ['R003 at label < "z"']);
	assert.deepEqual(errorCodes('ask Host where "a" < "b"', extended), ['R003 at "a" < "b"']);
	assert.deepEqual(errorCodes('ask Host where tier < high', extended), ['R003 at tier < high']);
	assert.deepEqual(errorCodes('ask Host where tier in tier..high', extended), ['R003 at tier..high']);

	// Date and DateTime are ordered in check.ts and table.ts.
	assert.deepEqual(errorCodes('ask Host where due < 2026-12-31', extended), []);
	assert.deepEqual(errorCodes('ask Host where created < 2026-12-31T00:00:00Z', extended), []);
	const dtTable = declare(
		[
			'extend Host',
			'  derived bucket: Text',
			'    table unique',
			'      | created | -> bucket |',
			'      | ..<2026-01-01T11:00:00Z | "early" |',
			'      | 2026-01-01T11:00:00Z.. | "late" |',
			''
		].join('\n'),
		extended
	);
	assert.deepEqual(dtTable.diagnostics.filter(isError), []);

	// native-rule-check.ts agrees on ordered(ty): Date/DateTime ordered, Text/Enum unordered.
	const nativeEnv: NativeRuleEnvironment = {
		schema: extended,
		relations: {
			check_dt: { role: 'derived', owner: 'fixture', world: 'closed', columns: [{ name: 'h', type: 'Host' }] },
			check_txt: { role: 'derived', owner: 'fixture', world: 'closed', columns: [{ name: 'h', type: 'Host' }] },
			ts: { role: 'input', world: 'closed', columns: [{ name: 'h', type: 'Host' }, { name: 'a', type: 'DateTime' }, { name: 'b', type: 'DateTime' }] },
			lbl: { role: 'input', world: 'closed', columns: [{ name: 'h', type: 'Host' }, { name: 'a', type: 'Text' }, { name: 'b', type: 'Text' }] }
		}
	};
	const dtRuleForm: NativeRuleForm = {
		format: 'rezono.module/3',
		module: {
			decls: [
				{
					rule: 'check_dt',
					args: [{ path: ['h'] }],
					when: {
						and: [
							{ call: ['ts', [{ path: ['h'] }, { path: ['a'] }, { path: ['b'] }]] },
							{ cmp: ['<', { path: ['a'] }, { path: ['b'] }] }
						]
					}
				}
			]
		},
		spans: [
			{ at: '/decls/0', line: '1', start: '0', end: '1' },
			{ at: '/decls/0/when/and/1', line: '1', start: '0', end: '1' }
		]
	};
	assert.deepEqual(checkNativeRules(dtRuleForm, nativeEnv), []);

	const txtRuleForm: NativeRuleForm = {
		format: 'rezono.module/3',
		module: {
			decls: [
				{
					rule: 'check_txt',
					args: [{ path: ['h'] }],
					when: {
						and: [
							{ call: ['lbl', [{ path: ['h'] }, { path: ['a'] }, { path: ['b'] }]] },
							{ cmp: ['<', { path: ['a'] }, { path: ['b'] }] }
						]
					}
				}
			]
		},
		spans: [
			{ at: '/decls/0', line: '1', start: '0', end: '1' },
			{ at: '/decls/0/when/and/1', line: '1', start: '0', end: '1' }
		]
	};
	assert.deepEqual(
		checkNativeRules(txtRuleForm, nativeEnv).map((d) => d.code),
		['R003']
	);

	// DateTime comparison in evaluate.ts compares by UTC instant, not UTF-8 bytes.
	const data = load(extended, [
		{
			$kind: 'Host',
			$id: 'h1',
			provider: 'cherry',
			memory_need: '64 GiB',
			label: '2026-01-01T12:00:00+02:00',
			tier: 'low',
			created: '2026-01-01T12:00:00+02:00',
			due: '2026-01-01'
		}
	]);
	// 12:00+02:00 is 10:00Z, which is earlier than 11:00Z and equal to 10:00Z.
	const earlier = (await answer(check('ask Host where created < 2026-01-01T11:00:00Z', extended), extended, data))!;
	assert.deepEqual(earlier.rows.map((r) => r.$id), ['h1']);
	const equalInstant = (await answer(check('ask Host where created = 2026-01-01T10:00:00Z', extended), extended, data))!;
	assert.deepEqual(equalInstant.rows.map((r) => r.$id), ['h1']);
	// Text equality must still compare raw text, not UTC instants.
	const textEq = (await answer(check('ask Host where label = "2026-01-01T10:00:00Z"', extended), extended, data))!;
	assert.deepEqual(textEq.rows.map((r) => r.$id), []);

	// Date ± num requires dimension `time` or `calendar`.
	assert.deepEqual(errorCodes('ask Host where 2026-11-01 + 5 GiB > 2026-11-02', extended), ['R003 at 2026-11-01 + 5 GiB']);
	assert.deepEqual(errorCodes('ask Host where 2026-11-01 - 5 GiB < 2026-11-02', extended), ['R003 at 2026-11-01 - 5 GiB']);
	assert.deepEqual(errorCodes('ask Host where 2026-11-01 + 3 > 2026-11-02', extended), ['R003 at 2026-11-01 + 3']);
	assert.deepEqual(errorCodes('ask Host where 2026-11-01 + € 5 > 2026-11-02', extended), ['R003 at 2026-11-01 + € 5']);
	assert.deepEqual(errorCodes('ask Host where 2026-11-01 + 24 h > 2026-11-02', extended), []);
	assert.deepEqual(errorCodes('ask Host where 2026-11-01 + 1 month > 2026-11-02', extended), []);
});

test('4. reject 1.5/3 in grammar, reject 1/0 with R012, and align 3/4 with 3 / 4', () => {
	// Decimal in rational literal rejected at parse time.
	for (const bad of [
		'ask Host where 1.5/3 = 0.5',
		'ask Host where 1.5/3 GiB = 1 GiB',
		'ask Host where € 1.5/3 = € 1',
		'ask Host where 1.5/3 % = 50 %'
	]) {
		const parsed = parse(bad);
		assert.equal(parsed.tree, undefined, bad);
		assert.ok(parsed.diagnostics.some((d) => d.code === 'R000'), bad);
	}
	// Spaced division with a decimal operand remains valid.
	assert.equal(parse('ask Host where 1.5 / 3 = 0.5').diagnostics.length, 0);

	// Zero denominator rational literals rejected with R012 in check.ts.
	assert.deepEqual(errorCodes('ask Team where 1/0 = 0'), ['R012 at 1/0']);
	assert.deepEqual(errorCodes('ask Team where 1/0 % = 0'), ['R012 at 1/0 %']);
	assert.deepEqual(errorCodes('ask Host where memory_need = 1/0 GiB'), ['R012 at 1/0 GiB']);
	assert.deepEqual(errorCodes('ask Plan where monthly_price = € 1/0'), ['R012 at € 1/0']);

	// 3/4 and 3 / 4 agree on inexact, states, and W105 for constant non-zero divisor.
	const inspect = (expr: string) => {
		const c = check(`ask Plan where true show ${expr}`, fixture);
		assert.deepEqual(c.diagnostics.filter(isError), [], expr);
		const shown = c.answer!.shown[0];
		return {
			inexact: shown.typed.inexact,
			states: [...shown.typed.states].sort(),
			w105: c.diagnostics.filter((d) => d.code === 'W105').length
		};
	};
	assert.deepEqual(inspect('3/4'), inspect('3 / 4'));
	assert.deepEqual(inspect('3/4 GiB'), inspect('3 GiB / 4'));
	assert.deepEqual(inspect('€ 1/3'), inspect('€ 1 / 3'));
	assert.deepEqual(inspect('monthly_price * 3/4'), inspect('monthly_price * (3 / 4)'));
	// Constant non-zero divisor does not add `invalid`; zero divisor still does.
	assert.equal(inspect('3 / 4').states.includes('invalid'), false);
	assert.equal(inspect('3 / 0').states.includes('invalid'), true);
});

test('5. missing T+ slot evaluates to unknown, not known([])', async () => {
	const plusSchema = schemaWith((s) => {
		s.kinds.Host.slots.tags = { type: 'Text', card: '+', states: ['known', 'unknown'] };
		s.kinds.Host.slots.opt_tags = { type: 'Text', card: '*', states: ['known'] };
		s.kinds.Host.slots.backup_teams = { ref: 'Team', card: '+', states: ['known', 'unknown'] };
		s.kinds.Team.world = 'closed';
		s.kinds.Team.slots.backed_hosts = { ref: 'Host', card: '*', states: ['known'], inverse: 'backup_teams' };
	});
	const data = load(plusSchema, [
		{ $kind: 'Host', $id: 'h1', provider: 'cherry', memory_need: '64 GiB' },
		{ $kind: 'Team', $id: 't1' }
	]);

	// Missing T+ slot is unknown, so `tags.count() = 0` is undecided, `tags is unknown` is true.
	const plusCount = (await answer(check('ask Host where tags.count() = 0', plusSchema), plusSchema, data))!;
	assert.equal(plusCount.rows.length, 0);
	assert.deepEqual(plusCount.undecided.map((u) => [u.$id, u.state]), [['h1', 'unknown']]);

	const plusIsUnknown = (await answer(check('ask Host where tags is unknown', plusSchema), plusSchema, data))!;
	assert.deepEqual(plusIsUnknown.rows.map((r) => r.$id), ['h1']);

	// Missing T* slot is still known([]).
	const starCount = (await answer(check('ask Host where opt_tags.count() = 0', plusSchema), plusSchema, data))!;
	assert.deepEqual(starCount.rows.map((r) => r.$id), ['h1']);

	// Inverse of a missing T+ forward slot also surfaces uncertainty instead of silently returning 0.
	const invCount = (await answer(check('ask Team where backed_hosts.count() = 0', plusSchema), plusSchema, data))!;
	assert.equal(invCount.rows.length, 0);
	assert.deepEqual(invCount.undecided.map((u) => [u.$id, u.state]), [['t1', 'unknown']]);
});

test('6. rezono 0 vs rezono 1 separation and expandPeriod year 9999 boundary', () => {
	// Dotted `use` is refused with R028 in rezono 1, still accepted in rezono 0.
	const r1Use = parseModule('rezono 1\npack sample\nuse std.units\n');
	assert.equal(r1Use.module, undefined);
	assert.deepEqual(r1Use.diagnostics.map((d) => d.code), ['R028']);
	const r0Use = parseModule('rezono 0\npack sample\nuse std.units\n');
	assert.ok(r0Use.module);
	assert.deepEqual(r0Use.diagnostics, []);

	// Missing `rezono` header gives W106 by default (read as rezono 0), and R028 in a rezono 1 pack.
	const missingDefault = parseModule('pack sample\nkind Item\n  x: Int\n');
	assert.ok(missingDefault.module);
	assert.deepEqual(missingDefault.diagnostics.map((d) => d.code), ['W106']);

	const missingInR1 = parseModule('pack sample\nkind Item\n  x: Int\n', { packVersion: '1' });
	assert.equal(missingInR1.module, undefined);
	assert.deepEqual(missingInR1.diagnostics.map((d) => d.code), ['R028']);

	// Digit grouping (`_`) and period abbreviations (`valid 2026`, `valid 2026-03`) are rejected in rezono 0.
	for (const src of [
		'rezono 0\npack sample\nparam cap: Int = 1_000\n',
		'rezono 0\npack sample\nkind Item\n  amount: Money<EUR>\n  derived high: Bool = amount > € 38_520.50\n',
		'rezono 0\npack sample\nparam cap: Int\n  version 1, valid 2026 = 1\n',
		'rezono 0\npack sample\nparam cap: Int\n  version 1, valid 2026-03 = 1\n'
	]) {
		const res = parseModule(src);
		assert.equal(res.module, undefined, src);
		assert.ok(res.diagnostics.some((d) => d.code === 'R000'), src);
	}

	// expandPeriod rejects year 9999 overflow cleanly as R000 instead of generating "10000-01-01".
	for (const src of [
		'rezono 1\npack sample\nparam cap: Int\n  version 1, valid 9999 = 1\n',
		'rezono 1\npack sample\nparam cap: Int\n  version 1, valid 9999-12 = 1\n'
	]) {
		const res = parseModule(src);
		assert.equal(res.module, undefined, src);
		assert.ok(res.diagnostics.some((d) => d.code === 'R000'), src);
	}

	// 9999-11 expands to a valid 4-digit exclusive end (9999-12-01).
	const nov9999 = parseModule('rezono 1\npack sample\nparam cap: Int\n  version 0 = 0\n  version 1, valid 9999-11 = 1\n');
	assert.ok(nov9999.module);
	assert.deepEqual(nov9999.diagnostics, []);
});
