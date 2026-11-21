import assert from 'node:assert/strict';
import { test } from 'node:test';
import { compareAsKnown } from '../src/compare-knowledge.ts';
import { parseModule, type KindDecl } from '../src/module.ts';

test('compareAsKnown: table unique enforces unique policy, bare enum values, conflict, and undecided rows', () => {
	// Bare enum tests and outputs + conflict when two rows apply + undecided row when one row applies.
	const src = `rezono 1
pack sample
enum Tier = low | mid | high
param cut: Int
  version 1, valid 2026-01-01..<2027-01-01, known 2026-01-01 = 5
  version 2 replaces 1, valid 2026-01-01..<2027-01-01, known 2026-02-01 = 10
kind Item world closed
  tier: Tier
  score: Int
  flag: Bool
  derived label: Tier
    table unique
      | tier | -> label |
      | low  | mid      |
      | mid  | high     |
      | high | high     |
  derived unique_overlap: Tier
    table unique
      | score >= cut | flag | -> unique_overlap |
      | true         | -    | high              |
      | -            | true | low               |
fact Item
  | id | tier | score | flag |
  | i1 | low  | 8     | true |
  | i2 | mid  | 8     | unknown missing_flag |
`;

	// Before known 2026-02-01: cut = 5, so score (8) >= 5 is true.
	// - i1: label = mid (bare enum test+output works without NotEvaluated).
	//       unique_overlap: both row 1 (score>=5) and row 2 (flag=true) apply -> invalid exception_conflict!
	// - i2: unique_overlap: row 1 applies (score>=5), row 2 is unknown -> MUST stay unknown (not ignore undecided row)!
	// After known 2026-02-01: cut = 10, so score (8) >= 10 is false.
	// - i1: unique_overlap: only row 2 applies -> known low!
	// - i2: unique_overlap: row 1 is false, row 2 is unknown -> unknown missing_flag.
	const res = compareAsKnown(src, {
		question: 'ask Item at 2026-06-01 where label = mid or label = high show label, unique_overlap',
		beforeKnown: '2026-01-15',
		afterKnown: '2026-02-15',
	});

	assert.equal(res.format, 'rezono.turns/1');
	const byKey = new Map(res.turns.map((t) => [t.key, t]));

	// i1 turned from invalid exception_conflict -> known low
	const t1 = byKey.get('i1');
	assert.ok(t1, 'i1 should turn when conflict resolves to low');
	assert.equal(t1.before.values?.label, 'mid');
	assert.deepEqual(t1.before.states?.unique_overlap, { state: 'invalid', reason: 'exception_conflict' });
	assert.equal(t1.after.values?.unique_overlap, 'low');
	assert.deepEqual(t1.after.states?.unique_overlap, { state: 'known' });

	// i2 stayed unknown missing_flag both before (when row 1 applied + row 2 undecided) and after (when row 1 false + row 2 undecided)
	assert.equal(byKey.has('i2'), false, 'i2 must remain undecided on before snapshot when an undecided row could conflict');
});

test('compareAsKnown: table collect gathers all applying rows and undecided members', () => {
	const src = `rezono 1
pack sample
enum Tag = a | b
param cut: Int
  version 1, valid 2026-01-01..<2027-01-01, known 2026-01-01 = 5
  version 2 replaces 1, valid 2026-01-01..<2027-01-01, known 2026-02-01 = 15
kind Item world closed
  score: Int
  derived tags: Tag*
    table collect
      | score >= 1 | score >= cut | -> tags |
      | true       | -            | a       |
      | -          | true         | b       |
  derived tag_count: Int = tags.count()
fact Item
  | id | score |
  | i1 | 10    |
`;
	const res = compareAsKnown(src, {
		question: 'ask Item at 2026-06-01 where score > 0 show tag_count',
		beforeKnown: '2026-01-15',
		afterKnown: '2026-02-15',
	});

	assert.equal(res.turns.length, 1);
	assert.equal(res.turns[0].key, 'i1');
	assert.equal(res.turns[0].before.values?.tag_count, '2');
	assert.equal(res.turns[0].after.values?.tag_count, '1');
});

test('compareAsKnown: omitting validAt and ask at does not conflate valid-time changes with knowledge-time changes', () => {
	// Both versions were already known on 2026-01-01; only valid-time changes on 2026-03-01.
	// Comparing known 2026-02-01 vs known 2026-04-01 without explicit validAt must use a single
	// consistent validAt for both snapshots, so no turn is reported.
	const src = `rezono 1
pack sample
param rate: Int
  version 1, valid 2026-01-01..<2026-03-01, known 2026-01-01 = 10
  version 2, valid 2026-03-01..<2027-01-01, known 2026-01-01 = 20
kind Item world closed
  units: Int
  derived fee: Int = units * rate
fact Item
  | id | units |
  | i1 | 3     |
`;
	const res = compareAsKnown(src, {
		question: 'ask Item where fee >= 0 show fee',
		beforeKnown: '2026-02-01',
		afterKnown: '2026-04-01',
	});

	assert.equal(res.turns.length, 0, 'valid-time boundary with no knowledge change must produce 0 turns');
});

test('compareAsKnown: diffCauses fallback preserves fact key and slot when fact appears only on one side', () => {
	const src = `rezono 1
pack sample
kind Item world closed
  active: Bool
  units: Int
  derived fee: Int = units * 10
    unless not active then 0
fact Item
  | id | active |
  | i1 | false  |
fact item i1, valid 2026-01-01.., known 2026-02-01
  active = true
  units = 5
`;
	// Before 2026-02-01: active=false (from base table), so `units` is never evaluated (short-circuited by unless).
	// After 2026-02-01: active=true (versioned fact), units=5 (versioned fact only evaluated on after side).
	const res = compareAsKnown(src, {
		question: 'ask Item at 2026-06-01 where fee >= 0 show fee',
		beforeKnown: '2026-01-15',
		afterKnown: '2026-02-15',
	});

	assert.equal(res.turns.length, 1);
	const turn = res.turns[0];
	assert.equal(turn.key, 'i1');
	assert.equal(turn.before.values?.fee, '0');
	assert.equal(turn.after.values?.fee, '50');
	const factCauses = turn.causes.filter((c) => c.target === 'fact');
	assert.ok(factCauses.length >= 1, 'should include fact amendment cause');
	for (const fc of factCauses) {
		assert.equal(fc.key, 'i1');
		assert.ok(fc.slot, 'fact cause must carry slot');
	}
});

test('compareAsKnown: undecided definition overriding every conflicting winner yields undecided instead of exception_conflict', () => {
	const src = `rezono 1
pack sample
kind Item world closed
  a: Bool
  b: Bool
  c: Bool
  d: Bool
  derived resolved: Int
    definition first when a then 10
    definition second when b then 20
    definition mid when false then 30 overrides first because "mid beats first" overrides second because "mid beats second"
    definition top when c then 40 overrides mid because "top transitively beats both"
  derived partial_override: Int
    definition first when a then 10
    definition second when b then 20
    definition only_first when d then 30 overrides first because "only beats first"
fact Item
  | id | a    | b    | c               | d               |
  | i1 | true | true | unknown pending | unknown pending |
fact item i1, valid 2026-01-01.., known 2026-02-01
  c = true
`;
	// Before 2026-02-01:
	// - resolved: first and second both apply, but top (unknown pending) transitively overrides both -> unknown pending!
	// - partial_override: first and second both apply, and only_first (unknown) does NOT override second -> invalid exception_conflict!
	// After 2026-02-01:
	// - resolved: c = true so top wins -> known 40!
	const res = compareAsKnown(src, {
		question: 'ask Item at 2026-06-01 where a show resolved, partial_override',
		beforeKnown: '2026-01-15',
		afterKnown: '2026-02-15',
	});

	assert.equal(res.turns.length, 1);
	const turn = res.turns[0];
	assert.equal(turn.key, 'i1');
	assert.deepEqual(turn.before.states?.resolved, { state: 'unknown', reason: 'pending' });
	assert.equal(turn.after.values?.resolved, '40');
	assert.deepEqual(turn.after.states?.resolved, { state: 'known' });
	assert.deepEqual(turn.before.states?.partial_override, { state: 'invalid', reason: 'exception_conflict' });
	assert.deepEqual(turn.after.states?.partial_override, { state: 'invalid', reason: 'exception_conflict' });
});

test('compareAsKnown: table priority does not let non-enum or non-known outputs outrank valid enum entries', () => {
	const src = `rezono 0
pack sample
enum Tier = high | low
kind Item world closed
  a: Bool
  b: Bool
  derived tier: Tier
    table priority
      | a    | b    | -> tier |
      | true | -    | high    |
      | -    | true | "other" |
fact Item
  | id | a    | b     |
  | i1 | true | false |
  | i2 | true | false |
fact item i1, valid 2026-01-01.., known 2026-02-01
  b = true
fact item i2, valid 2026-01-01.., known 2026-02-01
  b = unknown pending
`;
	// Row 1 gives the highest-priority valid enum value `high` (rank 0).
	// Row 2 gives `"other"`, which is not in `Tier` (indexOf === -1) and must rank after all valid entries (+Infinity).
	// Neither applying row 2 (i1) nor an undecided row 2 (i2) may beat `high`.
	const res = compareAsKnown(src, {
		question: 'ask Item at 2026-06-01 where a show tier',
		beforeKnown: '2026-01-15',
		afterKnown: '2026-02-15',
	});

	assert.equal(res.turns.length, 0, 'invalid/out-of-enum priority output must not beat valid enum entry high');
});

test('compareAsKnown: table priority propagates non-known applying and undecided row outcomes instead of swallowing them', () => {
	const makeModule = (row0Lit: string, row1Lit: string, extraFacts = '') => {
		const src = `rezono 0
pack sample
enum Tier = high | low
kind Item world closed
  a: Bool
  b: Bool
  derived tier: Tier
    table priority
      | a    | b    | -> tier |
      | true | -    | high    |
      | -    | true | low     |
fact Item
  | id | a     | b     |
  | i1 | true  | false |
  | i2 | false | true  |
${extraFacts}`;
		const parsed = parseModule(src);
		assert.ok(parsed.module, JSON.stringify(parsed.diagnostics));
		const kindDecl = parsed.module.decls.find((d): d is KindDecl => 'kind' in d && d.kind === 'Item');
		assert.ok(kindDecl);
		kindDecl.derived[0].table!.rows[0].value = { lit: row0Lit };
		kindDecl.derived[0].table!.rows[1].value = { lit: row1Lit };
		return parsed.module;
	};

	// 1. Applying unknown output must NOT be beaten by applying lower-priority known `low`,
	//    and undecided row with unknown output must block applying `low`.
	{
		const mod = makeModule(
			'unknown missing',
			'low',
			`fact item i1, valid 2026-01-01.., known 2026-02-01
  b = true
fact item i2, valid 2026-01-01.., known 2026-02-01
  a = unknown pending
`
		);
		const res = compareAsKnown(mod, {
			question: 'ask Item at 2026-06-01 where a or b show tier',
			beforeKnown: '2026-01-15',
			afterKnown: '2026-02-15',
		});
		const byKey = new Map(res.turns.map((t) => [t.key, t]));
		// i1 stays unknown missing both before (only row 1) and after (row 1 + row 2 low) -> no turn.
		assert.equal(byKey.has('i1'), false, 'applying low must not swallow applying unknown missing');
		// i2 turns from known low to unknown pending when row 1 becomes undecided with unknown output.
		const t2 = byKey.get('i2');
		assert.ok(t2, 'undecided row with non-known output must block applying low');
		assert.equal(t2.before.values?.tier, 'low');
		assert.deepEqual(t2.after.states?.tier, { state: 'unknown', reason: 'pending' });
	}

	// 2. Applying invalid output must propagate invalid even against highest-priority `high` (rank 0)
	//    and against applying `unknown`, and undecided row with invalid output must block `high`.
	{
		const mod = makeModule(
			'invalid bad',
			'high',
			`fact item i1, valid 2026-01-01.., known 2026-02-01
  b = true
fact item i2, valid 2026-01-01.., known 2026-02-01
  a = unknown pending
`
		);
		const res = compareAsKnown(mod, {
			question: 'ask Item at 2026-06-01 where a or b show tier',
			beforeKnown: '2026-01-15',
			afterKnown: '2026-02-15',
		});
		const byKey = new Map(res.turns.map((t) => [t.key, t]));
		assert.equal(byKey.has('i1'), false, 'applying high must not swallow applying invalid bad');
		const t2 = byKey.get('i2');
		assert.ok(t2, 'undecided row with invalid output must block applying high');
		assert.equal(t2.before.values?.tier, 'high');
		assert.deepEqual(t2.after.states?.tier, { state: 'unknown', reason: 'pending' });
	}

	// 3. Applying unknown + applying invalid must yield invalid (worstOf severity: invalid > unknown),
	//    and undecided invalid condition with higher-priority output must beat applying unknown output.
	{
		const mod = makeModule(
			'unknown missing',
			'invalid bad',
			`fact item i1, valid 2026-01-01.., known 2026-02-01
  b = true
`
		);
		const res = compareAsKnown(mod, {
			question: 'ask Item at 2026-06-01 where a or b show tier',
			beforeKnown: '2026-01-15',
			afterKnown: '2026-02-15',
		});
		const byKey = new Map(res.turns.map((t) => [t.key, t]));
		const t1 = byKey.get('i1');
		assert.ok(t1, 'i1 should turn from unknown missing to invalid bad when invalid row also applies');
		assert.deepEqual(t1.before.states?.tier, { state: 'unknown', reason: 'missing' });
		assert.deepEqual(t1.after.states?.tier, { state: 'invalid', reason: 'bad' });
	}

	// 4. Applying n/a output propagates strictly per Appendix A.3 instead of being swallowed by low.
	{
		const mod = makeModule(
			'n/a',
			'low',
			`fact item i1, valid 2026-01-01.., known 2026-02-01
  b = true
fact item i2, valid 2026-01-01.., known 2026-02-01
  a = unknown pending
`
		);
		const res = compareAsKnown(mod, {
			question: 'ask Item at 2026-06-01 where a or b show tier',
			beforeKnown: '2026-01-15',
			afterKnown: '2026-02-15',
		});
		const byKey = new Map(res.turns.map((t) => [t.key, t]));
		assert.equal(byKey.has('i1'), false, 'applying low must not swallow applying n/a');
		const t2 = byKey.get('i2');
		assert.ok(t2, 'undecided row with n/a output must block applying low');
		assert.equal(t2.before.values?.tier, 'low');
		assert.deepEqual(t2.after.states?.tier, { state: 'unknown', reason: 'pending' });
	}
});
