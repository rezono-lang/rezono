// The parser, the printer and the JSON form on what the conformance cases do not show: every operator's place
// in the precedence, where parentheses are needed and where they are not, the tokens the lexer tells apart, and
// a seeded sweep of generated trees (print, parse, print again; JSON form and back).
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import { check, fromJson, JsonFormError, parse, print, questionHash, toJson, type Ask, type Expr, type Schema } from '../src/index.ts';

/** The condition of `ask Host where <text>`, as a tree. */
function cond(text: string): Expr {
	const { tree, diagnostics } = parse(`ask Host where ${text}`);
	assert.deepEqual(diagnostics, [], text);
	return (tree as Ask).where;
}
/** The normal form of a condition. */
const normal = (text: string) => print(parse(`ask Host where ${text}`).tree!).slice('ask Host where '.length);
const codes = (text: string) => parse(text).diagnostics.map((d) => `${d.code} ${d.span.text}`);

test('precedence, lowest first: when, =>, or, and, not, comparison, range, + -, * /, unary -, postfix', () => {
	assert.deepEqual(cond('a or b and c'), { or: [{ path: ['a'] }, { and: [{ path: ['b'] }, { path: ['c'] }] }] });
	assert.deepEqual(cond('not a and b'), { and: [{ not: { path: ['a'] } }, { path: ['b'] }] });
	assert.deepEqual(cond('not a = b'), { not: { cmp: ['=', { path: ['a'] }, { path: ['b'] }] } });
	assert.deepEqual(cond('a => b => c'), { imply: [{ path: ['a'] }, { imply: [{ path: ['b'] }, { path: ['c'] }] }] });
	assert.deepEqual(cond('a or b => c'), { imply: [{ or: [{ path: ['a'] }, { path: ['b'] }] }, { path: ['c'] }] });
	assert.deepEqual(cond('a + b * c > d'), { cmp: ['>', { arith: ['+', { path: ['a'] }, { arith: ['*', { path: ['b'] }, { path: ['c'] }] }] }, { path: ['d'] }] });
	assert.deepEqual(cond('a - b - c = 0'), { cmp: ['=', { arith: ['-', { arith: ['-', { path: ['a'] }, { path: ['b'] }] }, { path: ['c'] }] }, { lit: '0' }] });
	assert.deepEqual(cond('x in a + 1..b'), { in: [{ path: ['x'] }, { range: [{ arith: ['+', { path: ['a'] }, { lit: '1' }] }, '..', { path: ['b'] }] }] });
	assert.deepEqual(cond('-a * b > 0'), { cmp: ['>', { arith: ['*', { neg: { path: ['a'] } }, { path: ['b'] }] }, { lit: '0' }] });
	assert.deepEqual(cond('when a then b else c or d'), { when: [{ path: ['a'] }, { path: ['b'] }, { or: [{ path: ['c'] }, { path: ['d'] }] }] });
});

test('and and or are n-ary: a chain and its parenthesised spelling are one question with one hash', async () => {
	const flat = parse('ask Host where a and b and c').tree!;
	const nested = parse('ask Host where a and (b and c)').tree!;
	assert.equal(toJson(nested), toJson(flat));
	const fixture = JSON.parse(readFileSync(new URL('fixture.schema.json', import.meta.url), 'utf8')) as Schema;
	const hash = (text: string) => questionHash(check(text, fixture), fixture);
	assert.equal(await hash('ask Host where a and (b and c)'), await hash('ask Host where a and b and c'));
	assert.equal(print(nested), 'ask Host where a and b and c');
	assert.equal(toJson(fromJson({ ask: 'Host', where: { and: [{ path: ['a'] }, { and: [{ path: ['b'] }, { path: ['c'] }] }] } })), toJson(flat));
});

test('parentheses are printed only where precedence needs them', () => {
	for (const [source, printed] of [
		['(a or b) and c', '(a or b) and c'],
		['a or (b and c)', 'a or b and c'],
		['(a + b) * c > 0', '(a + b) * c > 0'],
		['a + (b * c) > 0', 'a + b * c > 0'],
		['a - (b - c) > 0', 'a - (b - c) > 0'],
		['(a - b) - c > 0', 'a - b - c > 0'],
		['a / (b / c) > 0', 'a / (b / c) > 0'],
		['not (a and b)', 'not (a and b)'],
		['not (not a)', 'not not a'],
		['(a => b) => c', '(a => b) => c'],
		['a => (b => c)', 'a => b => c'],
		['(a = b) = c', '(a = b) = c'],
		['-(a + b) > 0', '-(a + b) > 0'],
		['(when a then b else c) and d', '(when a then b else c) and d'],
		['f((a), (b or c))', 'f(a, b or c)'],
		['((a))', 'a'],
		['x in (1..5)', 'x in 1..5'],
		['(a + 1)..(b * 2) = r', 'a + 1..b * 2 = r']
	])
		assert.equal(normal(source), printed, source);
});

test('a filter extends as far as it can, so it keeps its parentheses wherever something follows it', () => {
	assert.deepEqual(cond('x in Plan where a or b'), { in: [{ path: ['x'] }, { filter: [{ kind: 'Plan' }, { or: [{ path: ['a'] }, { path: ['b'] }] }] }] });
	assert.equal(normal('x in Plan where a or b'), 'x in Plan where a or b');
	assert.equal(normal('x in (Plan where a) or b'), 'x in (Plan where a) or b');
	assert.equal(normal('(Plan where memory >= 512 GiB).count() > 2'), '(Plan where memory >= 512 GiB).count() > 2');
	assert.equal(normal('(clusters where count > 1).any(spec.nodes > 3)'), '(clusters where count > 1).any(spec.nodes > 3)');
	assert.deepEqual(cond('(Plan where a).provider = cherry'), { cmp: ['=', { dot: [{ filter: [{ kind: 'Plan' }, { path: ['a'] }] }, 'provider'] }, { path: ['cherry'] }] });
});

test('tokens: an id with a hyphen is one token, a minus between names needs spaces', () => {
	assert.deepEqual(cond('a-b = c'), { cmp: ['=', { lit: 'a-b' }, { path: ['c'] }] });
	assert.deepEqual(cond('a - b = c'), { cmp: ['=', { arith: ['-', { path: ['a'] }, { path: ['b'] }] }, { path: ['c'] }] });
	assert.deepEqual(cond('scw-pro2-m.hourly_price > 0'), { cmp: ['>', { path: ['scw-pro2-m', 'hourly_price'] }, { lit: '0' }] });
});

test('a word followed by a hyphen and an id character is an id, whatever the word (review of #648)', () => {
	const keywords = 'pack use as private unit enum param kind extend derived rule check warn require fact decide assume theory view example ask suppose propose when then else unless where show not and or in is version valid known at by on because until requires sources world open closed inverse reckon norm exception applies replaces deprecated true false during order group limit unknown invalid'.split(' ');
	for (const word of keywords) {
		const id = { lit: `${word}-x` };
		assert.deepEqual(cond(`h.id = ${word}-x`), { cmp: ['=', { path: ['h', 'id'] }, id] }, word);
		assert.deepEqual(cond(`fits(${word}-x, plan)`), { call: ['fits', [id, { path: ['plan'] }]] }, word);
		assert.deepEqual(cond(`${word}-x`), id, word);
	}
	// With spaces it is the word: `not -x` negates, `true - x` subtracts.
	assert.deepEqual(cond('not -x'), { not: { neg: { path: ['x'] } } });
	assert.deepEqual(cond('true - x'), { arith: ['-', { lit: 'true' }, { path: ['x'] }] });
	assert.deepEqual(codes('ask Host where x in-use'), ['R000 -']);
});

test('an operand of a context or a time selection prints as an atom, so the text parses again', () => {
	for (const text of ['ask Host where x at (d.x)', 'ask Host at (d.x) where true', 'ask Host where x as known (a + b)', 'ask Host during (s.next) in (f(a).b) where true']) {
		const { tree } = parse(text);
		assert.equal(print(tree!), text);
		assert.equal(toJson(parse(print(tree!)).tree!), toJson(tree!), text);
		assert.equal(toJson(fromJson(JSON.parse(toJson(tree!)))), toJson(tree!), text);
	}
});

test('literals keep their text, with one space between their parts', () => {
	for (const [source, lit] of [
		['384   GiB', '384 GiB'],
		['0.1610', '0.1610'],
		['3/4', '3/4'],
		['21%', '21 %'],
		['€0.20/h', '€ 0.20/h'],
		['$ 5', '$ 5'],
		['2026-11-08', '2026-11-08'],
		['2026-11-08T14:02:00Z', '2026-11-08T14:02:00Z'],
		['"no monthly rate published yet"', '"no monthly rate published yet"'],
		['"a \\" in a text"', '"a \\" in a text"'],
		['unknown   no_rate', 'unknown no_rate'],
		['unknown "not yet assigned"', 'unknown "not yet assigned"'],
		['invalid bad_format', 'invalid bad_format'],
		['n/a', 'n/a'],
		['true', 'true'],
		['10.12.0.1', '10.12.0.1'],
		['Cidr"10.12.0.0/31"', 'Cidr"10.12.0.0/31"'],
		['Host:`host-b`', 'Host:`host-b`'],
		['1 month', '1 month']
	]) {
		assert.deepEqual(cond(`x = ${source}`), { cmp: ['=', { path: ['x'] }, { lit }] }, source);
		assert.equal(normal(`x = ${source}`), `x = ${lit}`, source);
	}
	// A keyword or a contextual word after a number is never its unit.
	assert.deepEqual(cond('x > 3 and y'), { and: [{ cmp: ['>', { path: ['x'] }, { lit: '3' }] }, { path: ['y'] }] });
	assert.deepEqual((parse('ask Host where x > 3 limit 5').tree as Ask).tail, [{ limit: '5' }]);
	// A range of numbers is two numbers, not a literal token with dots.
	assert.deepEqual(cond('asn in 65001..65099'), { in: [{ path: ['asn'] }, { range: [{ lit: '65001' }, '..', { lit: '65099' }] }] });
	assert.deepEqual(cond('d in 2026-01-01..<2027-01-01'), { in: [{ path: ['d'] }, { range: [{ lit: '2026-01-01' }, '..<', { lit: '2027-01-01' }] }] });
});

test('a contextual word stays a name where it is not expected as a word', () => {
	assert.deepEqual(cond('during = limit'), { cmp: ['=', { path: ['during'] }, { path: ['limit'] }] });
	assert.deepEqual(cond('placement.during > 1'), { cmp: ['>', { path: ['placement', 'during'] }, { lit: '1' }] });
	assert.deepEqual(codes('ask Host where where > 1'), ['R000 where']);
});

test('comments and line breaks are white space', () => {
	assert.equal(print(parse('ask Host -- every host\n  where memory_need > 384 GiB -- above the limit\n  show owner').tree!), 'ask Host where memory_need > 384 GiB show owner');
});

test('parse-level checks come first, and a plain syntax error has a place', () => {
	assert.deepEqual(codes('ask Host where'), ['R000 ']);
	assert.deepEqual(codes('ask Host memory_need > 1'), ['R000 memory_need']);
	assert.deepEqual(codes('ask Host where a < b < c order by a'), ['R016 a < b < c']);
	assert.deepEqual(codes('ask host at 2026-01-01 at 2026-02-01 where a'), ['R014 host', 'R018 at 2026-02-01']);
	assert.deepEqual(codes('ask Host where a at 2026-01-01 as known 2026-02-01 limit 5'), ['R015 at 2026-01-01', 'R015 as known 2026-02-01', 'R015 limit 5']);
	assert.deepEqual(codes('ask Host where a group by b, c'), ['R015 group by b, c']);
	assert.equal(parse('ask Host where a < b < c').tree, undefined);
});

test('spans are code-point offsets, also after a character outside the basic plane', () => {
	const { diagnostics } = parse('ask Host where x = "𝛑" order by x');
	assert.deepEqual(diagnostics.map((d) => d.span), [{ text: 'order by x', start: 23, end: 33 }]);
});

test('suppose lines', () => {
	assert.deepEqual(parse('+ scw-pro2-m.hourly_price = € 0.1740/h').tree, { set: [{ path: ['scw-pro2-m', 'hourly_price'] }, { lit: '€ 0.1740/h' }] });
	assert.deepEqual(parse('+ host-d.memory_need = invalid versions_overlap').tree, { set: [{ path: ['host-d', 'memory_need'] }, { lit: 'invalid versions_overlap' }] });
	assert.deepEqual(parse('+ host-a.owner = team-platform').tree, { set: [{ path: ['host-a', 'owner'] }, { lit: 'team-platform' }] });
	assert.deepEqual(parse('- x2.owner').tree, { retract: { path: ['x2', 'owner'] } });
	assert.deepEqual(parse('- Plan scw-pro2-l').tree, { retract_row: ['Plan', 'scw-pro2-l'] });
	assert.equal(print(parse('+ x2.count = -3').tree!), '+ x2.count = -3');
});

test('the JSON form: only the tree of its own text is one', () => {
	assert.equal(print(fromJson({ ask: 'Host', where: { path: ['a'] }, context: { as_known: { lit: '2026-02-01' }, at: { lit: '2026-01-01' } } })), 'ask Host at 2026-01-01 as known 2026-02-01 where a');
	assert.equal(print(fromJson({ ask: 'Plan', where: { cmp: ['=', { path: ['provider'] }, { lit: 'cherry' }] } })), 'ask Plan where provider = cherry');
	for (const bad of [
		null,
		[],
		{ ask: 'Host' },
		{ ask: 'host', where: { path: ['a'] } },
		{ ask: 'Host', where: { path: ['a'] }, order: 'a' },
		{ ask: 'Host', where: { path: ['a b'] } },
		{ ask: 'Host', where: { lit: '1 or true' } },
		{ ask: 'Host', where: { cmp: ['~', { path: ['a'] }, { path: ['b'] }] } },
		{ ask: 'Host', where: { path: ['a'], extra: '1' } },
		{ ask: 'Host', where: { is: [{ path: ['a'] }, 'missing'] } },
		{ ask: 'Host', where: { lit: 1 } },
		{ ask: 'Host', where: { lit: true } },
		{ ask: 'Host', where: { and: [{ path: ['a'] }, { and: [{ path: ['b'] }, { path: ['c'] }], extra: 'lost' }] } }
	])
		assert.throws(() => fromJson(bad), JsonFormError, JSON.stringify(bad));
});

// A small generator with a fixed seed (mulberry32): the same trees on every run.
function generator(seed: number) {
	let s = seed;
	const next = () => {
		s = (s + 0x6d2b79f5) | 0;
		let t = Math.imul(s ^ (s >>> 15), 1 | s);
		t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
		return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
	};
	const pick = <T>(xs: T[]): T => xs[Math.floor(next() * xs.length)];
	const leaf = (): Expr => pick<Expr>([{ path: ['a'] }, { path: ['h', 'memory_need'] }, { lit: '384 GiB' }, { lit: '€ 0.20/h' }, { lit: 'host-b' }, { lit: '3/4' }, { kind: 'Plan' }, { lit: 'true' }]);
	const expr = (depth: number): Expr => {
		if (depth === 0) return leaf();
		const e = () => expr(depth - 1);
		const flat = (op: 'and' | 'or', xs: Expr[]) => xs.flatMap((x) => (op in x ? (x as Record<string, Expr[]>)[op] : [x]));
		return pick<() => Expr>([
			leaf,
			() => ({ and: flat('and', [e(), e(), e()]) }),
			() => ({ or: flat('or', [e(), e()]) }),
			() => ({ not: e() }),
			() => ({ imply: [e(), e()] }),
			() => ({ cmp: [pick(['=', '!=', '<', '<=', '>', '>=']), e(), e()] }),
			() => ({ in: [e(), e()] }),
			() => ({ is: [e(), pick(['known', 'unknown', 'n/a', 'invalid'])] }),
			() => ({ range: [e(), pick(['..', '..<']), e()] }),
			() => ({ arith: [pick(['+', '-', '*', '/']), e(), e()] }),
			() => ({ neg: e() }),
			() => ({ when: [e(), e(), e()] }),
			() => ({ call: ['fits', [e(), e()]] }),
			() => ({ agg: [pick(['sum', 'min', 'any', 'all', 'none']), e(), e()] }),
			() => ({ agg: ['count', e()] }),
			() => ({ filter: [pick<Expr>([{ kind: 'Plan' }, { path: ['clusters'] }]), e()] }),
			() => ({ dot: [{ call: ['f', [e()]] }, 'slot'] })
		])();
	};
	return { expr };
}

test('generated trees: print, parse and print again is stable, and the JSON form reads back (seed 20261111)', () => {
	const { expr } = generator(20261111);
	for (let i = 0; i < 400; i++) {
		const tree: Ask = { ask: 'Host', where: expr(1 + (i % 4)), ...(i % 3 === 0 ? { binder: 'h', show: [expr(1), expr(2)] } : {}) };
		const text = print(tree);
		const { tree: again, diagnostics } = parse(text);
		assert.deepEqual(diagnostics, [], text);
		assert.equal(toJson(again!), toJson(tree), text);
		assert.equal(print(again!), text);
		assert.equal(toJson(fromJson(JSON.parse(toJson(tree)))), toJson(tree), text);
	}
});

test('every code the parser reports has a sentence in each language of the catalogue', () => {
	const read = (language: string) => JSON.parse(readFileSync(new URL(`../messages/${language}.json`, import.meta.url), 'utf8')) as Record<string, string>;
	const en = read('en');
	const nl = read('nl');
	assert.deepEqual(Object.keys(nl), Object.keys(en));
	for (const code of ['R000', 'R014', 'R015', 'R016', 'R018']) {
		assert.ok(en[code], code);
		assert.ok(nl[code], code);
	}
});

test('a text ends on its line in the whole language: the question reader refuses the input the module reader refuses', () => {
	// The same input and the same diagnostic as in module.test.ts (v0 §11): one rule, read by one function.
	const input = 'check late: x.label = "too late,\n    try again"\n';
	const expected = [{ code: 'R000', span: { text: '"too late,', start: 22, end: 32 }, args: ['a text that ends on its line'] }];
	assert.deepEqual(parse(input).diagnostics, expected);
	assert.equal(parse(input).tree, undefined);
	// In an `ask` as in a check, an id between backticks too, with CRLF line ends, and with the line end escaped.
	assert.deepEqual(codes('ask Host where owner = Team:`platform,\n  one`'), ['R000 `platform,']);
	assert.deepEqual(codes('ask Host where label = "too late,\r\n  again"'), ['R000 "too late,']);
	assert.deepEqual(codes('ask Host where label = "too late \\\n  again"'), ['R000 "too late \\']);
	// A question over lines whose texts end on their line still reads, whatever a comment between them holds.
	assert.deepEqual(codes('ask Host where label = "a -- `" -- it\'s "odd\n  or owner = Team:`b"c`'), []);
});
