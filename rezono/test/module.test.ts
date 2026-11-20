// The reader of a module (src/module.ts) on what the examples do not show: blocks and continuation lines, where a
// line may stand, the header, and W108. Every module here is made up for the test.
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { parseModule, type DerivedDecl, type ExtendDecl, type KindDecl, type ParamDecl } from '../src/index.ts';

const codes = (text: string) => parseModule(text).diagnostics.map((d) => `${d.code} ${d.span.text}`);
const decls = (text: string) => {
	const r = parseModule(text);
	assert.deepEqual(r.diagnostics, []);
	return r.module!.decls;
};

test('the header: an optional language line, `pack`, then `use` lines', () => {
	const m = parseModule('rezono 0\npack p\nuse std.money\nuse a.b as c\n').module!;
	assert.deepEqual(m, { rezono: '0', pack: 'p', use: [{ use: 'std.money' }, { use: 'a.b', as: 'c' }], decls: [] });
	assert.deepEqual(codes('use a\npack p\n'), ['R000 use']);
	assert.deepEqual(codes('pack p\nenum E = a\nuse a\n'), ['R000 use']);
	assert.deepEqual(codes('enum E = a\n'), ['R000 enum']);
	assert.deepEqual(codes(''), ['R000 ']);
});

test('a deeper line goes on with the statement when either line shows it is not finished', () => {
	const [ext] = decls(
		[
			'pack p',
			'extend K',
			'  derived a: Bool =',
			'      when x then y',
			'      else z',
			'  derived b: Int = x',
			'      + y * (1 +',
			'        2)',
			'  derived c: Bool = x',
			'      and y   -- a comment ending in or',
			'      or z'
		].join('\n')
	) as ExtendDecl[];
	assert.deepEqual(
		ext.derived.map((d) => [d.derived, d.value]),
		[
			['a', { when: [{ path: ['x'] }, { path: ['y'] }, { path: ['z'] }] }],
			['b', { arith: ['+', { path: ['x'] }, { arith: ['*', { path: ['y'] }, { arith: ['+', { lit: '1' }, { lit: '2' }] }] }] }],
			['c', { or: [{ and: [{ path: ['x'] }, { path: ['y'] }] }, { path: ['z'] }] }]
		]
	);
});

test('a card at the end of a type does not continue the line; a block under it is a block', () => {
	const r = parseModule('pack p\nkind K world open\n  xs: T*\n  derived ys: T*\n    table collect\n      | a | -> ys |\n      | - | b |\n');
	assert.deepEqual(r.diagnostics, []);
	const [kind] = r.module!.decls as KindDecl[];
	assert.deepEqual(kind.slots, [{ slot: 'xs', type: 'T', card: '*' }]);
	assert.deepEqual(kind.derived[0].table, { table: 'collect', inputs: [{ path: ['a'] }], output: 'ys', rows: [{ tests: ['-'], value: { lit: 'b' } }] });
});

test('a decision table is read into the tree of tables.md §2: its policy, its inputs, its rows of tests', () => {
	const text = [
		'pack p',
		'extend Claim',
		'  total derived band: Band',
		'    table unique',
		'      | age    | income          | owner.team | -> band    |',
		'      | ..<18  | -               | a-b, Cd    | none       |',
		'      | 18..65 | ..<€ 30000.00   | -          | low        |',
		'      | 66..<  | € 30000.00..    | "x | y"    | standard   |',
		''
	].join('\n');
	const r = parseModule(text);
	assert.deepEqual(r.diagnostics, []);
	const [band] = (r.module!.decls[0] as ExtendDecl).derived;
	assert.deepEqual(band, {
		derived: 'band',
		totality: 'total',
		type: 'Band',
		table: {
			table: 'unique',
			inputs: [{ path: ['age'] }, { path: ['income'] }, { path: ['owner', 'team'] }],
			output: 'band',
			rows: [
				// A test is a value or a range with an end left open; a value is the literal, the id or the word written.
				{ tests: [[{ between: { op: '..<', to: { lit: '18' } } }], '-', [{ lit: 'a-b' }, { lit: 'Cd' }]], value: { lit: 'none' } },
				{ tests: [[{ between: { from: { lit: '18' }, op: '..', to: { lit: '65' } } }], [{ between: { op: '..<', to: { lit: '€ 30000.00' } } }], '-'], value: { lit: 'low' } },
				{ tests: [[{ between: { from: { lit: '66' }, op: '..<' } }], [{ between: { from: { lit: '€ 30000.00' }, op: '..' } }], [{ lit: '"x | y"' }]], value: { lit: 'standard' } }
			]
		}
	});
	// The table stands at `table <policy>`, a row at its whole line, a test and a value at their text.
	const at = (node: object) => r.spans.get(node)!.text;
	const table = band.table!;
	assert.deepEqual([at(table), at(table.rows[0]), at(table.rows[0].tests[0][0] as object), at(table.rows[1].tests[0] as object), at(table.rows[2].value)], ['table unique', '| ..<18  | -               | a-b, Cd    | none       |', '..<18', '18..65', 'standard']);
});

test('what a table could only hold by dropping a part is refused, each at its line', () => {
	const under = (...lines: string[]) => codes(['pack p', 'extend K', ...lines, ''].join('\n'));
	const table = ['  derived a: T', '    table unique', '      | x | -> a |', '      | 1 | y |'];
	assert.deepEqual(under(...table), []);
	// A table has a header, and each row one cell for each input and then its value.
	assert.deepEqual(under('  derived a: T', '    table unique'), ['R000 table']);
	assert.deepEqual(under('  derived a: T', '    table unique', '      | 1 | y |'), ['R000 | 1 | y |']);
	assert.deepEqual(under('  derived a: T', '    table unique', '      | x + | -> a |'), ['R000 |']);
	assert.deepEqual(under(...table, '      | 1 | 2 | y |', '      | - | - | - | y |'), ['R000 | 1 | 2 | y |', 'R000 | - | - | - | y |']);
	// A row that ends before its value is refused where it ends.
	assert.deepEqual(under(...table, '      | y |'), ['R000 ']);
	// A value is no state, no `-` and no range: a row that gives no value is left out.
	assert.deepEqual(under(...table, '      | 1 | - |'), ['R000 ']);
	assert.deepEqual(under(...table, '      | 1 | 2..3 |'), ['R000 ']);
	assert.deepEqual(under(...table, '      | 1 | n/a |'), ['R000 /']);
	assert.deepEqual(under(...table, '      | unknown why | y |'), ['R000 why']);
	// A statement under a line of a table would be dropped unseen, and so would a second table, or a table
	// beside another definition.
	assert.deepEqual(under(...table, '        version 1 = 2'), ['R000 version']);
	assert.deepEqual(under(...table.slice(0, 3), '        | 1 | y |'), ['R000 |']);
	assert.deepEqual(under(...table, '    table first', '      | x | -> a |'), ['R000 table']);
	assert.deepEqual(under('  derived a: T = 1', ...table.slice(1)), ['R000 table']);
	assert.deepEqual(under(...table, '    version 1 = 2'), ['R000 table']);
	assert.deepEqual(under(...table, '    unless z then 3'), ['R000 table']);
	assert.deepEqual(under(...table, '    x: T'), ['R000 x:']);
	// The name after `->` is the derived value's own: the tree is kept, the name is reported.
	const other = parseModule('pack p\nextend K\n  derived a: T\n    table unique\n      | x | -> b |\n');
	assert.deepEqual(other.diagnostics.map((d) => [d.code, d.span.text, d.suggest]), [['R001', 'b', ['a']]]);
	assert.equal((other.module!.decls[0] as ExtendDecl).derived[0].table!.output, 'b');
	// `total` is read on a value with a table: only there is its promise checked (table.ts).
	assert.deepEqual(under('  total derived a: T = 1'), ['R000 total']);
	assert.deepEqual(under('  total derived a: T', ...table.slice(1)), []);
	assert.deepEqual(codes('pack p\nkind K\n  total: T\n'), []);
});

test('`unless`: one clause on its line, or a block of `when` lines, each with its source', () => {
	const [ext] = decls('pack p\nextend K\n  derived a: Int = 1\n    unless x then 0\n    unless\n      when y then 2  @ src#1\n      when z then 3\n') as ExtendDecl[];
	assert.deepEqual((ext.derived[0] as DerivedDecl).unless, [
		[{ when: { path: ['x'] }, then: { lit: '0' } }],
		[
			{ when: { path: ['y'] }, then: { lit: '2' }, source: 'src#1' },
			{ when: { path: ['z'] }, then: { lit: '3' } }
		]
	]);
});

test('a line where its block does not allow it is an R000 at its first word, and there is no module', () => {
	assert.deepEqual(codes('pack p\nkind K\n  version 1 = 2\n'), ['R000 version']);
	assert.deepEqual(codes('pack p\nparam a: Int\n  x: Int\n'), ['R000 x:']);
	assert.deepEqual(codes('pack p\nenum E = a\n  reason r = "t"\n'), ['R000 reason']);
	assert.equal(parseModule('pack p\nenum E = a\n  reason r = "t"\n').module, undefined);
	assert.deepEqual(codes('pack p\nkind K\n\tx: Int\n'), ['R000 \t']);
});

test('a line under a line that has no block of its own is an R000 where it stands, so no line is left out of the tree', () => {
	const under = (...lines: string[]) => {
		const r = parseModule(['pack p', ...lines, ''].join('\n'));
		assert.equal(r.module, undefined, lines.join(' / '));
		return r.diagnostics.map((d) => `${d.code} ${d.span.text}: ${d.args.join()}`);
	};
	const none = 'no line under this one';
	// A `when` line of an `unless` block: a clause one step too deep is not a clause of the block.
	assert.deepEqual(under('extend K', '  derived a: Int = 1', '    unless', '      when b then 2', '        when c then 3'), [`R000 when: ${none}`]);
	assert.deepEqual(under('extend K', '  derived a: Int = 1', '    unless', '      when b then 2', '          version 1 = 3', '      when c then 4', '        unless d then 5'), [`R000 version: ${none}`, `R000 unless: ${none}`]);
	// The same under every other line that takes no block.
	for (const [lines, word] of [
		[['extend K', '  derived a: Int = 1', '    unless b then 2', '      when c then 3'], 'when'],
		[['extend K', '  derived a: Int', '    version 1 = 2', '      unless b then 3'], 'unless'],
		[['param a: Int', '  version 1 = 2', '    version 2 = 3'], 'version'],
		[['kind K', '  a: Int', '    b: Int'], 'b:'],
		[['kind K', '  applies at: a', '    b: Int'], 'b:'],
		[['kind K', '  sealed at: a', '    b: Int'], 'b:'],
		[['check a: b', '  when c then d'], 'when'],
		[['fact k k-a', '  a = 1', '    b = 2'], 'b'],
		[['fact K', '  | id |', '    | k-a |'], '|'],
		[['extend K', '  derived a: T', '    table first', '      | b | -> a |', '        | c | d |'], '|'],
		[['unit U = integer', '  unit V = integer'], 'unit']
	] as [string[], string][])
		assert.deepEqual(under(...lines), [`R000 ${word}: ${none}`], lines.join(' / '));
	assert.deepEqual(codes('pack p\n  use a\n'), ['R000 use']);
});

test('a decision table is read whole or refused: a second table, and a header that does not end in its output', () => {
	const table = (...lines: string[]) => codes(['pack p', 'extend K', '  derived a: T', ...lines, ''].join('\n'));
	// A table is read (docs/rezono/tables.md): it is no longer R015.
	assert.deepEqual(table('    table first', '      | b | -> a |', '      | - | c |'), []);
	// A second table would replace the first one unseen.
	assert.deepEqual(table('    table first', '      | b | -> a |', '      | - | c |', '    table collect', '      | d | -> a |'), ['R000 table']);
	// The last cell of the header names the output: any other cell there would be in no tree.
	assert.deepEqual(table('    table first', '      | b | c |', '      | - | d |'), ['R000 | b | c |']);
	assert.deepEqual(table('    table first', '      | b | -> 3 |'), ['R000 | b | -> 3 |']);
});

test('a comment ends the code of its line, except inside a text', () => {
	assert.deepEqual(decls('pack p\nreason r = "a -- b"  -- the label\n'), [{ reason: 'r', text: '"a -- b"' }]);
});

test('a text and an id between backticks end on the line they start on: a line end inside one is an R000', () => {
	const at = (text: string) => parseModule(text).diagnostics.map((d) => [d.code, d.span.text, d.args.join()]);
	assert.deepEqual(at('pack p\nreason late = "too late,\n    try again"\n'), [['R000', '"too late,', 'a text that ends on its line']]);
	assert.equal(parseModule('pack p\nreason late = "too late,\n    try again"\n').module, undefined);
	// The same with the line ends of another checkout, and with the line end escaped.
	assert.deepEqual(at('pack p\r\nreason late = "too late,\r\n    try again"\r\n'), [['R000', '"too late,', 'a text that ends on its line']]);
	assert.deepEqual(at('pack p\nfact k k-a\n  a = near("x \\\n      y")\n'), [['R000', '"x \\', 'a text that ends on its line']]);
	// In an expression: a text, a typed text, the label of a state, an id between backticks.
	assert.deepEqual(at('pack p\nfact k k-a\n  a = "x" + "y,\n      z"\n'), [['R000', '"y,', 'a text that ends on its line']]);
	assert.deepEqual(at('pack p\nfact k k-a\n  a = Iban"NL91,\n      ABNA"\n'), [['R000', '"NL91,', 'a text that ends on its line']]);
	assert.deepEqual(at('pack p\nfact k k-a\n  a = unknown "not yet,\n      later"\n'), [['R000', '"not yet,', 'a text that ends on its line']]);
	assert.deepEqual(at('pack p\nfact k k-a\n  a = K:`x,\n      y`\n'), [['R000', '`x,', 'an id that ends on its line']]);
	// One R000 for each.
	assert.deepEqual(at('pack p\nreason a = "x,\n    y"\nreason b = "z,\n    y"\n').map(([code, text]) => `${code} ${text}`), ['R000 "x,', 'R000 "z,']);
	// A statement that goes on over lines keeps the texts that end on their line, whatever stands in them or in
	// a comment between them.
	assert.deepEqual(
		decls(['pack p', 'fact k k-a', '  a = near("x, -- `", -- it\'s "odd', '      K:`a"b`,', '      "y")', ''].join('\n')),
		[{ fact: 'k', id: 'k-a', set: [{ slot: 'a', value: { call: ['near', [{ lit: '"x, -- `"' }, { lit: 'K:`a"b`' }, { lit: '"y"' }]] } }] }]
	);
});

test('W108: versions that all start at a `valid` date leave the time before the earliest one without a value', () => {
	const text = [
		'pack p',
		'param a: Int per K',
		'  version 2, valid 2026-01-01.. = 2',
		'  version 1, valid 2025-01-01..<2026-01-01 = 1',
		'param b: Int',
		'  version 1 = 1',
		'  version 2, valid 2026-01-01.. = 2',
		'param c: Int = 3',
		'extend K',
		'  derived d: Int',
		'    version 1, valid 2024-06-01.., known 2024-05-01 = 4'
	].join('\n');
	const r = parseModule(text);
	assert.deepEqual(
		r.diagnostics.map((d) => [d.code, d.span.text, ...d.args]),
		[
			['W108', 'a', 'a', '2025-01-01'],
			['W108', 'd', 'd', '2024-06-01']
		]
	);
	assert.deepEqual((r.module!.decls[0] as ParamDecl).versions![1], { version: '1', valid: ['2025-01-01', '2026-01-01'], value: { lit: '1' } });
});

test('offsets are those of the file, in code points', () => {
	const text = 'pack p\n-- 😀\nextend K\n  derived a: Int = x at y\n';
	const [d] = parseModule(text).diagnostics;
	assert.equal(d.code, 'R015');
	assert.equal([...text].slice(d.span.start, d.span.end).join(''), 'at y');
});

test('a text ends on its line in the whole language: the module reader refuses the input the question reader refuses', () => {
	// The same input and the same diagnostic as in parse.test.ts: a check statement is a line of a module and a
	// question alike. Without `pack` the module has an R000 for that too, but only once its lines are read.
	const input = 'check late: x.label = "too late,\n    try again"\n';
	const expected = [{ code: 'R000', span: { text: '"too late,', start: 22, end: 32 }, args: ['a text that ends on its line'] }];
	assert.deepEqual(parseModule(input).diagnostics, expected);
	assert.equal(parseModule(input).module, undefined);
});

test('R029: an undeclared reason label leaves parseModule without a module, consistent with R021', () => {
	const input = [
		'pack p',
		'reason no_rate = "no monthly rate published yet"',
		'param rate: Int',
		'  version 1, valid 2026-01-01.. = 1',
		'fact host host-a',
		'  rate = unknown "no rate yet"',
		''
	].join('\n');
	const parsed = parseModule(input);
	assert.equal(parsed.module, undefined);
	assert.deepEqual(
		parsed.diagnostics.map((d) => [d.code, d.span.text, ...d.args]),
		[['R029', '"no rate yet"', '"no rate yet"']]
	);
});

test('R021: duplicate version numbers forming a self-replacement or cycle are still detected', () => {
	const selfDup = [
		'pack p',
		'param quota: Int',
		'  version 1, valid 2025-01-01.. = 1',
		'  version 1 replaces 1, valid 2026-01-01.. = 2',
		''
	].join('\n');
	const selfParsed = parseModule(selfDup);
	assert.equal(selfParsed.module, undefined);
	assert.deepEqual(
		selfParsed.diagnostics.map((d) => [d.code, d.span.text, ...d.args]),
		[['R021', '1', '1', '1', 'quota']]
	);

	const cycleDup = [
		'pack p',
		'param quota: Int',
		'  version 1 = 1',
		'  version 2 replaces 1 = 2',
		'  version 1 replaces 2 = 3',
		''
	].join('\n');
	const cycleParsed = parseModule(cycleDup);
	assert.equal(cycleParsed.module, undefined);
	assert.deepEqual(
		cycleParsed.diagnostics.map((d) => [d.code, d.span.text, ...d.args]),
		[['R021', '1', '2', '1', 'quota']]
	);
});
