import assert from 'node:assert/strict';
import { test } from 'node:test';
import { runExamples } from '../src/examples.ts';
import { parseModule } from '../src/module.ts';

function run(src: string) {
	const parsed = parseModule(src);
	assert.ok(parsed.module, parsed.diagnostics.map((d) => `${d.code}: ${d.span.text}`).join('; '));
	return runExamples(parsed.module);
}

test('examples: evalDefs preserves non-overridden unknown/invalid definitions and applies overrides transitively', () => {
	const src = `rezono 1
pack sample
kind Item world closed
  a: Bool
  b: Bool
  c: Bool
  derived tier: Int
    definition base when a then 10
    definition mid when b then 20 overrides base because "mid beats base"
    definition top when c then 30 overrides mid because "top beats mid"
example "non-overridden unknown definition blocks single applying definition"
  given
    i1.a = true
    i1.b = unknown pending
    i1.c = false
  expect
    i1.tier is unknown
example "overridden unknown definition does not block overriding winner"
  given
    i2.a = unknown pending
    i2.b = true
    i2.c = false
  expect
    i2.tier = 20
example "transitive override lets top override base when mid is false"
  given
    i3.a = true
    i3.b = false
    i3.c = true
  expect
    i3.tier = 30
`;
	const res = run(src);
	assert.deepEqual(res.failures, []);
	assert.equal(res.passed, 3);
});

test('examples: multi-hop given traverses >=2 ref hops and does not corrupt on broken hop', () => {
	const src = `rezono 1
pack sample
kind Leaf world closed
  val: Int
kind Mid world closed
  leaf: Leaf
  val: Int
kind Root world closed
  mid: Mid
example "two ref hops write to leaf"
  given
    r1.mid = m1
    m1.leaf = l1
    r1.mid.leaf.val = 42
  expect
    l1.val = 42
example "broken intermediate hop does not overwrite earlier kind slot of same name"
  given
    r2.mid = m2
    m2.val = 7
    r2.mid.leaf.val = 99
  expect
    m2.val = 7
`;
	const res = run(src);
	assert.deepEqual(res.failures, []);
	assert.equal(res.passed, 2);
});

test('examples: single-valued given overrides base fact row instead of conflicting', () => {
	const src = `rezono 1
pack sample
kind Item world closed
  amount: Int
  derived doubled: Int = amount * 2
fact Item
  | id | amount |
  | i1 | 10     |
example "given overrides base fact"
  given
    i1.amount = 25
  expect
    i1.amount = 25
    i1.doubled = 50
`;
	const res = run(src);
	assert.deepEqual(res.failures, []);
	assert.equal(res.passed, 1);
});

test('examples: parseUnitDef gives money minor scale 0', () => {
	const src = `rezono 1
pack sample
unit Yen = money minor JPY
kind Order world closed
  price: Yen
  note: Int
  derived half: Yen = round(price / 2, half_up)
fact Order
  | id | price | note |
  | o1 | 3     | 0    |
example "money minor rounds to integer scale 0 rather than scale 2"
  given
    o1.note = 1
  expect
    o1.half = o1.price - o1.price / 3
`;
	const res = run(src);
	assert.deepEqual(res.failures, []);
	assert.equal(res.passed, 1);
});

test('examples: evalExpr filters R002/R003 only for actually patched nodes', () => {
	const src = `rezono 1
pack sample
kind A world closed
  shared: Int
  only_a: Int
kind B world closed
  shared: Int
  only_b: Int
example "patched ambiguous path passes when expression is well-typed"
  given
    a1.shared = 10
    a1.only_a = 1
    b1.shared = 20
    b1.only_b = 2
  expect
    a1.shared = 10
example "genuine R003 elsewhere in expression is not swallowed when another node is patched"
  given
    a1.shared = 10
    a1.only_a = 1
    b1.shared = 20
    b1.only_b = 2
  expect
    a1.shared = 10 and b1.only_b = "bad"
example "genuine R002 on unpatched id is not swallowed when another node is patched"
  given
    a1.shared = 10
    a1.only_a = 1
  expect
    a1.shared = 10 and orphan-1 = orphan-2
`;
	const res = run(src);
	assert.equal(res.passed, 1);
	assert.equal(res.failures.length, 2);
	assert.match(res.failures[0].reason, /type error R003/);
	assert.match(res.failures[1].reason, /type error R002/);
});

test('examples: check with none aggregate records invalid subject in badIds', () => {
	const src = `rezono 1
pack sample
kind Item world closed
  flag: Bool
check no_flagged: Item.none(flag)
example "invalid predicate under none matches violation on subject"
  given
    i1.flag = invalid bad_input
  expect
    violation no_flagged on i1
`;
	const res = run(src);
	assert.deepEqual(res.failures, []);
	assert.equal(res.passed, 1);
});
