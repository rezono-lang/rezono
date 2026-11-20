// The JSON form of a module (src/module-json.ts, contracts/rezono-module.yaml), its printer (src/print.ts) and
// the command that writes it (src/write-form.ts). The module of `module.rezono` is made up for the test and
// holds every member the form carries; its form is a fixture of the contract, so the bytes this implementation
// writes are the bytes the contract's check validates.
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';
import { parse as parseYaml } from 'yaml';
import { canonicalJson } from '../../viewer/src/lib/canon.ts';
import { JsonFormError, MODULE_FORMAT, moduleForm, moduleFromJson, moduleToJson, parse, parseModule, printModule, type Expr } from '../src/index.ts';
import { lineOf } from '../src/module-json.ts';
import { writeForm } from '../src/write-form.ts';

const source = fileURLToPath(new URL('module.rezono', import.meta.url));
// The form counts offsets, so a checkout that turned the line ends into CRLF would be another text.
const text = readFileSync(source, 'utf8').replace(/\r\n/g, '\n');
const made = moduleForm(text);
const json = moduleToJson(made.form!);
const fixture = new URL('../../contracts/fixtures/rezono-module/ModuleForm/valid/every-member.yaml', import.meta.url);

/** The form of a small module, which must have one. */
const formOf = (lines: string[]) => {
	const r = moduleForm(lines.join('\n') + '\n');
	assert.ok(r.form, r.diagnostics.map((d) => `${d.code} ${d.span.text}`).join('; '));
	return r.form;
};
/** The diagnostics that leave a small module without a form: each with its code and its line. */
const refused = (lines: string[]) => {
	const body = lines.join('\n') + '\n';
	const r = moduleForm(body);
	assert.equal(r.form, undefined);
	const line = lineOf(body);
	return r.diagnostics.map((d) => `${d.code} line ${line(d.span.start)}`);
};
const at = (value: unknown, pointer: string): unknown =>
	pointer
		.split('/')
		.slice(1)
		.reduce((v, key) => (v as Record<string, unknown>)[key], value);

test('the same text gives the same bytes, and they are the bytes of the contract fixture', () => {
	assert.equal(moduleToJson(moduleForm(text).form!), json);
	assert.equal(readFileSync(fixture, 'utf8'), json, 'write it again: node src/write-form.ts test/module.rezono ../contracts/fixtures/rezono-module/ModuleForm/valid/every-member.yaml');
	// Canonical JSON and nothing after it: reading the bytes and writing them again changes nothing.
	assert.equal(canonicalJson(JSON.parse(json)), json);
	assert.deepEqual(Object.keys(JSON.parse(json)), ['format', 'module', 'spans']);
	// A warning stands beside the form; it does not stop it.
	assert.deepEqual(
		made.diagnostics.map((d) => `${d.code} ${d.span.text}`),
		['W108 rate']
	);
});

test('print and JSON round-trip', () => {
	const printed = printModule(made.form!.module);
	const again = parseModule(printed);
	assert.deepEqual(again.module, made.form!.module);
	assert.equal(printModule(again.module!), printed);
	const read = moduleFromJson(JSON.parse(json));
	assert.deepEqual(read, made.form);
	assert.equal(moduleToJson(read), json);
});

test('pack headers and use targets round-trip existing pack slugs', (t) => {
	const lines = ['rezono 0', 'pack std-access', 'use std-order as order_pack', 'use catalog.std-part',
		'kind Item', '  item_code: Text'];
	const sourceText = lines.join('\n') + '\n';
	const dir = mkdtempSync(join(tmpdir(), 'rezono-pack-form-'));
	t.after(() => rmSync(dir, { recursive: true, force: true }));
	const sourcePath = join(dir, 'access.rezono');
	const targetPath = join(dir, 'access.json');
	writeFileSync(sourcePath, sourceText);

	const diagnostics: string[] = [];
	assert.equal(writeForm(sourcePath, targetPath, (line) => diagnostics.push(line)), 0, diagnostics.join('\n'));
	const form = moduleFromJson(JSON.parse(readFileSync(targetPath, 'utf8')));
	assert.equal(form.module.pack, 'std-access');
	assert.deepEqual(form.module.use, [{ use: 'std-order', as: 'order_pack' }, { use: 'catalog.std-part' }]);
	assert.equal(printModule(form.module), sourceText);
	for (const [index, use] of form.module.use.entries()) {
		const span = form.spans.find((entry) => entry.at === `/use/${index}`);
		assert.ok(span);
		assert.equal(sourceText.slice(Number(span.start), Number(span.end)), use.use);
	}

	assert.equal(formOf(['pack legacy_pack', 'use legacy.module_name']).module.pack, 'legacy_pack');
	for (const name of ['-std', 'std-', 'std-Access', 'std-ac_cess', 'std-access.']) {
		assert.deepEqual(refused([`pack ${name}`]), ['R000 line 1']);
		assert.deepEqual(refused(['pack lab', `use ${name}`]), ['R000 line 2']);
	}
	assert.deepEqual(refused(['pack lab', 'use std-access as wrong-alias']), ['R000 line 2']);
	assert.deepEqual(refused(['pack lab', 'kind Item', '  item-code: Text']), ['R000 line 3']);
	assert.deepEqual(refused(['pack lab', 'kind Std-Access']), ['R000 line 2']);
});

test('the normal form of a module: one statement on a line, two spaces for each block', () => {
	const lines = [
		'pack lab',
		'kind Host world closed',
		'  applies at: since',
		'  sealed at: closed_on',
		'  owner: Team? inverse hosts world open',
		'  derived label: Text = "taken"',
		'    unless memory is unknown then "?" @ lab#1',
		'    unless',
		'      when not roomy then "small" @ lab#2',
		'      when owner in Team then "ours"',
		'    version 1, valid 2025-01-01..<2026-01-01, known 2024-12-01 = "old" @ lab#3',
		'    version 2, valid 2026-01-01..',
		'fact Host',
		'  | id | owner |',
		'  | host-a | n/a |',
		'fact host host-a, valid 2026-01-01.., known 2025-12-01',
		'  owner = unknown not_measured @ lab#4',
		''
	];
	assert.equal(printModule(parseModule(lines.join('\n')).module!), lines.join('\n'));
	// What the tree does not order is written in one order, and a block of one clause on the `unless` line.
	const loose = ['pack lab', 'kind Host', '  derived a: Int = 1', '    version 1, known 2026-01-02, valid 2026-01-01.. = 2', '    unless', '      when b then 3', '  sealed at: c', '  d: Int', ''];
	const normal = ['pack lab', 'kind Host', '  sealed at: c', '  d: Int', '  derived a: Int = 1', '    unless b then 3', '    version 1, valid 2026-01-01.., known 2026-01-02 = 2', ''];
	assert.equal(printModule(parseModule(loose.join('\n')).module!), normal.join('\n'));
});

test('every span is the place of its node in the text', () => {
	const points = [...text];
	const line = lineOf(text);
	const { module, spans } = made.form!;
	assert.ok(spans.length > 100);
	for (const place of spans) {
		const node = at(module, place.at) as Record<string, unknown>;
		assert.equal(typeof node, 'object', place.at);
		const [start, end] = [Number(place.start), Number(place.end)];
		const there = points.slice(start, end).join('');
		assert.equal(place.line, String(line(start)), place.at);
		assert.equal(place.line, String(points.slice(0, start).filter((c) => c === '\n').length + 1), place.at);
		// A declaration stands at its name, a check statement and an expression at their whole text.
		const name = ['kind', 'enum', 'unit', 'reason', 'param', 'derived', 'extend', 'fact', 'use', 'rounding', 'version'].find((k) => typeof node[k] === 'string');
		if (name) assert.equal(there, node[name], place.at);
		// A decision table stands at `table <policy>`, a row at its whole line, a test and a value at their text.
		else if (typeof node.table === 'string') assert.equal(there, `table ${node.table}`, place.at);
		else if ('tests' in node) assert.ok(there.startsWith('| ') && there.endsWith(`| ${(node.value as { lit: string }).lit} |`), place.at);
		else if ('between' in node) {
			const { from, op, to } = node.between as { from?: { lit: string }; op: string; to?: { lit: string } };
			assert.equal(there, `${from?.lit ?? ''}${op}${to?.lit ?? ''}`, place.at);
		} else if (/\/table\/rows\//.test(place.at)) assert.equal(there, node.lit, place.at);
		else if ('slot' in node) assert.equal(there, node.slot, place.at);
		else if ('check' in node) assert.deepEqual(parse(there).tree, node, place.at);
		else assert.deepEqual((parse(`warn ${there}`).tree as { cond: Expr }).cond, node, place.at);
	}
	// Each node once, in the order of the canonical JSON of `module`: members by name, arrays by index.
	const nodes: string[] = [];
	const walk = (v: unknown, pointer: string) => {
		if (Array.isArray(v)) v.forEach((x, i) => walk(x, `${pointer}/${i}`));
		else if (typeof v === 'object' && v !== null) {
			nodes.push(pointer);
			for (const k of Object.keys(v).sort()) walk((v as Record<string, unknown>)[k], `${pointer}/${k}`);
		}
	};
	walk(module, '');
	const placed = new Set(spans.map((p) => p.at));
	assert.deepEqual(
		spans.map((p) => p.at),
		nodes.filter((pointer) => placed.has(pointer))
	);
	// Every node has a place but the module itself, the clauses of an `unless`, whose two expressions have, and
	// the ends of a range in a table, whose test has.
	assert.deepEqual(
		nodes.filter((pointer) => !placed.has(pointer) && !/\/unless\/\d+\/\d+$/.test(pointer) && !/\/between$/.test(pointer)),
		['']
	);
	assert.ok(spans.some((p) => /\/table\/rows\/0\/tests\/0\/1\/between\/to$/.test(p.at)));
	assert.equal(spans[0].at, '/decls/0');
	assert.equal(spans.at(-1)!.at, '/use/1');
});

test('the four states of a value are four different literals, and none of them is an absent member', () => {
	const form = formOf(['pack lab', 'fact Host', '  | id | a | b | c | d |', '  | host-a | 3 GiB | n/a | unknown not_measured | invalid out_of_range |']);
	const [table] = form.module.decls as { rows: unknown[][] }[];
	assert.deepEqual(table.rows, [[{ lit: 'host-a' }, { lit: '3 GiB' }, { lit: 'n/a' }, { lit: 'unknown not_measured' }, { lit: 'invalid out_of_range' }]]);
	assert.equal(new Set(table.rows[0].map((cell) => canonicalJson(cell))).size, 5);
	assert.deepEqual(moduleFromJson(JSON.parse(moduleToJson(form))), form);
	// The same in a fact row, with a reason given as its label.
	const [, row] = formOf(['pack lab', 'reason not_measured = "not measured yet"', 'fact host host-a', '  a = n/a', '  b = unknown "not measured yet"', '  c = invalid out_of_range']).module.decls as [unknown, { set: unknown[] }];
	assert.deepEqual(row.set, [
		{ slot: 'a', value: { lit: 'n/a' } },
		{ slot: 'b', value: { lit: 'unknown "not measured yet"' } },
		{ slot: 'c', value: { lit: 'invalid out_of_range' } }
	]);
	// A value that is not written is never read as a state: an empty cell, a short row and an assignment
	// without a value leave no form.
	assert.deepEqual(refused(['pack lab', 'fact Host', '  | id | a |', '  | host-a |  |']), ['R000 line 4']);
	assert.deepEqual(refused(['pack lab', 'fact Host', '  | id | a |', '  | host-a |']), ['R000 line 4']);
	assert.deepEqual(refused(['pack lab', 'fact host host-a', '  a =']), ['R000 line 3']);
	// And the form has no `null` to write one with.
	const holed = JSON.parse(moduleToJson(form));
	holed.module.decls[0].rows[0][2] = null;
	assert.throws(() => moduleFromJson(holed), JsonFormError);
	holed.module.decls[0].rows[0].splice(2, 1);
	assert.throws(() => moduleFromJson(holed), JsonFormError);
});

test('every declaration the reader reads is in the form, or its text is refused by name', () => {
	const kinds = made.form!.module.decls.map((d) => ['unit', 'enum', 'reason', 'rounding', 'param', 'kind', 'extend', 'check'].find((k) => k in d) ?? ('columns' in d ? 'fact table' : 'fact row'));
	assert.deepEqual([...new Set(kinds)].sort(), ['check', 'enum', 'extend', 'fact row', 'fact table', 'kind', 'param', 'reason', 'rounding', 'unit']);
	assert.deepEqual([made.form!.module.rezono, made.form!.module.pack, made.form!.module.use], ['0', 'lab', [{ use: 'std.units' }, { use: 'std.money', as: 'm' }]]);
	// A decision table has its form (tables.md §2): a cell is `-` or its tests, a test a value or a range with
	// an end left open, a value the literal, the id or the word that was written.
	const table = formOf(['pack lab', 'extend Host', '  total derived band: Tier', '    table first', '      | roomy | memory | -> band |', '      | true | ..<64 GiB, 128 GiB | high |', '      | - | 64 GiB.. | low |']);
	assert.deepEqual((table.module.decls[0] as { derived: unknown[] }).derived[0], {
		derived: 'band',
		totality: 'total',
		type: 'Tier',
		table: {
			table: 'first',
			inputs: [{ path: ['roomy'] }, { path: ['memory'] }],
			output: 'band',
			rows: [
				{ tests: [[{ lit: 'true' }], [{ between: { op: '..<', to: { lit: '64 GiB' } } }, { lit: '128 GiB' }]], value: { lit: 'high' } },
				{ tests: ['-', [{ between: { from: { lit: '64 GiB' }, op: '..' } }]], value: { lit: 'low' } }
			]
		}
	});
	assert.deepEqual(moduleFromJson(JSON.parse(moduleToJson(table))), table);
	// A table the reader refuses has no form: without a header, with a row that is short, beside another
	// definition, with a line under one of its lines, with another name after `->`.
	assert.deepEqual(refused(['pack lab', 'extend Host', '  derived band: Tier', '    table first']), ['R000 line 4']);
	assert.deepEqual(refused(['pack lab', 'extend Host', '  derived band: Tier', '    table first', '      | roomy | memory | -> band |', '      | true | high |']), ['R000 line 6']);
	assert.deepEqual(refused(['pack lab', 'extend Host', '  derived band: Tier = low', '    table first', '      | roomy | -> band |']), ['R000 line 4']);
	assert.deepEqual(refused(['pack lab', 'extend Host', '  derived band: Tier', '    table first', '      | roomy | -> band |', '      | true | high |', '        unless roomy then low']), ['R000 line 7']);
	assert.deepEqual(refused(['rezono 0', 'pack lab', 'extend Host', '  derived band: Tier', '    table first', '      | roomy | -> tier |']), ['R001 line 6']);
	// What v0 reserves is read and reported (R015), and has no form.
	assert.deepEqual(refused(['rezono 0', 'pack lab', 'extend Host', '  derived before: GiB = memory at since']), ['R015 line 4']);
	assert.deepEqual(refused(['rezono 0', 'pack lab', 'norm patched: host.memory > 1 GiB']), ['R015 line 3']);
	// What the reader does not read yet is no Rezono to it (R000), and has no form.
	for (const line of ['rule near(a: Host, b: Host): a.owner = b.owner', 'decide owner of host-a = platform by lab on 2026-01-01', 'assume host-a.memory = 1 GiB', 'theory order', 'view small = Host where roomy', 'example e', 'exception e of label', 'private unit GiB = 1024 MiB'])
		assert.deepEqual(refused(['pack lab', 'unit GiB = 1024 MiB', line]), ['R000 line 3'], line);
});

test('the reader refuses what its tree could only hold by dropping a part', () => {
	assert.deepEqual(refused(['pack lab', 'kind Host', '  applies at: a', '  applies in: b', '  sealed at: c', '  sealed at: d']), ['R000 line 4', 'R000 line 6']);
	assert.deepEqual(refused(['pack lab', 'param rate: Ratio', '  version 1, valid 2025-01-01.., valid 2026-01-01.. = 1']), ['R018 line 3']);
	assert.deepEqual(refused(['pack lab', 'fact host host-a, known 2026-01-01, known 2026-01-02', '  a = 1']), ['R018 line 2']);
	assert.deepEqual(refused(['pack lab', 'fact Host', '  | id | 3 |', '  | host-a | 1 |']), ['R000 line 3']);
	assert.deepEqual(refused(['pack lab', 'fact Host', '  | id | a |', '  | host-a | 1 | 2 |', '  | - | 1 |', '  | host-c | -> a |']), ['R000 line 4', 'R000 line 5', 'R000 line 6']);
	const [d] = parseModule('pack lab\nfact Host\n  | id | a |\n  | host-a |\n').diagnostics;
	assert.deepEqual([d.code, d.span.text, d.args], ['R000', '| host-a |', ['2 values']]);
	// A line under a `when` line of an `unless` block is a clause of no block: it is refused where it stands, and
	// no form is written without it. The same under the one clause of an `unless` line, and under a version.
	const deep = ['pack lab', 'extend Host', '  derived a: Int = 1', '    unless', '      when b then 2', '        when c then 3'];
	assert.deepEqual(refused(deep), ['R000 line 6']);
	assert.deepEqual(refused(['pack lab', 'extend Host', '  derived a: Int = 1', '    unless b then 2', '      when c then 3']), ['R000 line 5']);
	assert.deepEqual(refused(['pack lab', 'extend Host', '  derived a: Int', '    version 1 = 2', '      unless b then 3']), ['R000 line 5']);
	const dir = mkdtempSync(join(tmpdir(), 'rezono-form-'));
	writeFileSync(join(dir, 'deep.rezono'), deep.join('\n') + '\n');
	const said: string[] = [];
	assert.equal(writeForm(join(dir, 'deep.rezono'), join(dir, 'deep.json'), (line) => said.push(line)), 1);
	assert.equal(existsSync(join(dir, 'deep.json')), false);
	assert.equal(said.length, 1);
	assert.match(said[0], /deep\.rezono:6: R000 at `when`: this is not Rezono here; expected no line under this one$/);
});

test('a text in a form holds no line end: the reader refuses one, as the contract does', () => {
	const late = ['pack lab', 'reason late = "too late,', '    try again"'];
	assert.deepEqual(refused(late), ['R000 line 2']);
	assert.deepEqual(refused(['pack lab', 'fact host host-a', '  memory = unknown "not measured,', '      yet"']), ['R000 line 3']);
	assert.deepEqual(refused(['pack lab', 'fact host host-a', '  owner = Team:`platform,', '      one`']), ['R000 line 3']);
	// The contract's pattern for the label of a reason refuses that text, and holds for every label written.
	const contract = parseYaml(readFileSync(new URL('../../contracts/rezono-module.yaml', import.meta.url), 'utf8'));
	const label = new RegExp(contract.classes.ReasonDecl.attributes.text.pattern);
	assert.equal(label.test('"too late,\n    try again"'), false);
	const labels = made.form!.module.decls.flatMap((d) => ('reason' in d ? [d.text] : []));
	assert.deepEqual(labels, ['"not measured yet"']);
	assert.ok(labels.every((text) => label.test(text)));
	// Handed in as a tree it is refused too: its printed text is the text the reader refuses.
	const form = JSON.parse(moduleToJson(formOf(['pack lab', 'reason late = "too late"'])));
	assert.deepEqual(moduleFromJson(form).module.decls, [{ reason: 'late', text: '"too late"' }]);
	form.module.decls[0].text = '"too late,\n    try again"';
	assert.throws(() => moduleFromJson(form), /R000/);
	// And the command writes no file for it.
	const dir = mkdtempSync(join(tmpdir(), 'rezono-form-'));
	writeFileSync(join(dir, 'late.rezono'), late.join('\n') + '\n');
	const said: string[] = [];
	assert.equal(writeForm(join(dir, 'late.rezono'), join(dir, 'late.json'), (line) => said.push(line)), 1);
	assert.equal(existsSync(join(dir, 'late.json')), false);
	assert.equal(said.length, 1);
	assert.match(said[0], /late\.rezono:2: R000 at `"too late,`: this is not Rezono here; expected a text that ends on its line$/);
});

test('reading a form refuses what is not the tree of its own text', () => {
	const form = formOf(['pack lab', 'unit GiB = 1024 MiB', 'extend Host', '  derived roomy: Bool = memory > 384 GiB']);
	const changed = (change: (f: any) => void) => {
		const f = JSON.parse(moduleToJson(form));
		change(f);
		return () => moduleFromJson(f);
	};
	assert.deepEqual(changed(() => {})(), form);
	assert.throws(changed((f) => (f.format = 'rezono.module/2')), JsonFormError);
	assert.throws(changed((f) => (f.note = 'later')), JsonFormError);
	assert.throws(changed((f) => (f.module.decls[0].note = 'later')), /not the tree of its own text/);
	assert.throws(changed((f) => (f.module.decls[1].derived[0].value = null)), JsonFormError);
	assert.throws(changed((f) => delete f.module.decls[1].derived[0].type), JsonFormError);
	assert.throws(changed((f) => delete f.module.use), JsonFormError);
	// A reserved construct has no form, also when it is handed in as a tree.
	assert.throws(changed((f) => (f.module.decls[1].derived[0].value = { timesel: [{ path: ['memory'] }, { at: { path: ['since'] } }] })), /R015/);
	assert.throws(changed((f) => f.module.decls.push({ check: 'norm', cond: { path: ['a'] } })), /R015/);
	// A table handed in as a tree is read by the same test: beside a value it is refused, and so is a tree of
	// another shape, a row without a cell, and a value that is a state or a name.
	const tabled = formOf(['pack lab', 'extend Host', '  derived band: Tier', '    table first', '      | roomy | -> band |', '      | true | high |']);
	const retabled = (change: (table: any) => void) => {
		const f = JSON.parse(moduleToJson(tabled));
		change(f.module.decls[0].derived[0].table);
		return () => moduleFromJson(f);
	};
	assert.deepEqual(retabled(() => {})(), tabled);
	assert.throws(changed((f) => (f.module.decls[1].derived[0].table = JSON.parse(moduleToJson(tabled)).module.decls[0].derived[0].table)), /R000/);
	assert.throws(retabled((t) => (t.rows = [{ cells: [{ lit: 'true' }], value: { path: ['high'] } }])), JsonFormError);
	assert.throws(retabled((t) => (t.rows[0].tests = [])), JsonFormError);
	assert.throws(retabled((t) => (t.rows[0].tests = ['-', '-'])), /R000/);
	assert.throws(retabled((t) => (t.rows[0].value = { lit: 'n/a' })), /R000/);
	assert.throws(retabled((t) => (t.rows[0].value = { path: ['high'] })), JsonFormError);
	assert.throws(retabled((t) => (t.rows[0].tests[0] = [{ between: { op: '..' } }])), /R000/);
	assert.throws(retabled((t) => (t.rows[0].tests[0] = null)), JsonFormError);
	assert.throws(retabled((t) => (t.output = 'tier')), /R001/);
	assert.throws(retabled((t) => (t.table = 'any')), /R000/);
	// The spans place the nodes of the tree, each once and in their order, as decimal text.
	assert.throws(changed((f) => f.spans.pop()), /spans/);
	assert.throws(changed((f) => f.spans.reverse()), /spans/);
	assert.throws(changed((f) => (f.spans[0].line = 2)), /spans/);
	assert.throws(changed((f) => (f.spans[0].line = '0')), /spans/);
	assert.throws(changed((f) => (f.spans[0].end = '1')), /spans/);
	assert.throws(changed((f) => (f.spans[0].text = 'GiB')), /spans/);
	assert.equal(form.format, MODULE_FORMAT);
});

test('the command writes the bytes of the form, and leaves no file for a module it refuses', () => {
	const dir = mkdtempSync(join(tmpdir(), 'rezono-form-'));
	const target = join(dir, 'module.json');
	const said: string[] = [];
	assert.equal(writeForm(source, target, (line) => said.push(line)), 0);
	// The file is read as it is checked out, so only a text with LF line ends gives the fixture's bytes.
	if (!readFileSync(source, 'utf8').includes('\r')) assert.equal(readFileSync(target, 'utf8'), json);
	assert.equal(said.length, 1);
	assert.match(said[0], /module\.rezono:36: W108 at `rate`: /);

	const refusedText = join(dir, 'refused.rezono');
	writeFileSync(refusedText, 'rezono 0\npack lab\nextend Host\n  derived before: GiB = memory at since\n');
	writeFileSync(join(dir, 'refused.json'), 'the form of an earlier text');
	said.length = 0;
	assert.equal(writeForm(refusedText, join(dir, 'refused.json'), (line) => said.push(line)), 1);
	assert.equal(existsSync(join(dir, 'refused.json')), false);
	assert.equal(said.length, 1);
	assert.match(said[0], /refused\.rezono:4: R015 at `at since`: at on a value is reserved/);

	// A text that cannot be read leaves no earlier form either, and a form is never written over its text.
	writeFileSync(join(dir, 'gone.json'), 'the form of a text that is gone');
	assert.throws(() => writeForm(join(dir, 'gone.rezono'), join(dir, 'gone.json')), /ENOENT/);
	assert.equal(existsSync(join(dir, 'gone.json')), false);
	assert.throws(() => writeForm(refusedText, refusedText), /over its own text/);
	assert.equal(existsSync(refusedText), true);

	// As a command: the exit code says which of the three it was.
	const command = fileURLToPath(new URL('../src/write-form.ts', import.meta.url));
	const run = (...args: string[]) => spawnSync(process.execPath, [command, ...args], { encoding: 'utf8' });
	const refusedRun = run(refusedText, join(dir, 'refused.json'));
	assert.equal(refusedRun.status, 1, refusedRun.stderr);
	assert.match(refusedRun.stderr, /refused\.rezono:4: R015/);
	assert.equal(existsSync(join(dir, 'refused.json')), false);
	assert.equal(run(refusedText).status, 2);
	const small = join(dir, 'small.rezono');
	writeFileSync(small, 'pack lab\nunit GiB = 1024 MiB\n');
	const written = run(small, join(dir, 'small.json'));
	assert.equal(written.status, 0, written.stderr);
	assert.equal(readFileSync(join(dir, 'small.json'), 'utf8'), '{"format":"rezono.module/1","module":{"decls":[{"is":"1024 MiB","unit":"GiB"}],"pack":"lab","use":[]},"spans":[{"at":"/decls/0","end":"17","line":"2","start":"14"}]}');
});

test('the body of a unit is read as an expression: what v0 reserves in it is an R015, and it has no form', () => {
	assert.deepEqual(refused(['rezono 0', 'pack lab', 'unit Old = memory at since']), ['R015 line 3']);
	const [d] = parseModule('rezono 0\npack lab\nunit Old = memory at since\n').diagnostics;
	assert.deepEqual([d.code, d.span.text], ['R015', 'at since']);
	assert.deepEqual(refused(['pack lab', 'unit Odd = 1 < 2 < 3']), ['R016 line 2']);
	// The other bodies are as before.
	assert.deepEqual(formOf(['pack lab', 'unit Eur = money minor EUR per day', 'unit Count = integer']).module.decls, [
		{ unit: 'Eur', is: 'money minor EUR per day' },
		{ unit: 'Count', is: 'integer' }
	]);
});

test('a comment inside a type or a unit body over two lines is no part of the form, and gives no exception', () => {
	const form = formOf(['pack lab', 'param x: Map<A, -- the key', '    B>', 'unit Mem = 1024 * -- a factor', '    MiB']);
	assert.deepEqual(form.module.decls, [
		{ param: 'x', type: 'Map<A,B>' },
		{ unit: 'Mem', is: '1024 * MiB' }
	]);
	// A `--` inside a text of a unit body is no comment.
	assert.deepEqual(formOf(['pack lab', 'unit Odd = near("a -- b", -- c', '    1)']).module.decls, [{ unit: 'Odd', is: 'near("a -- b", 1)' }]);
});

test('an `unless` has its clause or a block of `when` lines: a bare `unless` with neither is an R000', () => {
	assert.deepEqual(refused(['pack lab', 'extend Host', '  derived a: Int = 1', '    unless']), ['R000 line 4']);
	const [d] = parseModule('pack lab\nextend Host\n  derived a: Int = 1\n    unless\n').diagnostics;
	assert.deepEqual([d.code, d.span.text, d.args], ['R000', 'unless', ['`when` under it']]);
});

test('the contract reads a label as the reader does, in either dialect: a line end is out, U+2028 and U+2029 are in', () => {
	const form = formOf(['pack lab', 'reason r = "a b c"']);
	assert.deepEqual(form.module.decls, [{ reason: 'r', text: '"a b c"' }]);
	const contract = parseYaml(readFileSync(new URL('../../contracts/rezono-module.yaml', import.meta.url), 'utf8'));
	const label = new RegExp(contract.classes.ReasonDecl.attributes.text.pattern);
	// ECMA-262's `.` and Python's differ on U+2028, U+2029 and a bare CR: the pattern names what it refuses.
	assert.equal(label.test('"a b c"'), true);
	for (const end of ['\n', '\r', '\r\n']) assert.equal(label.test(`"a${end}b"`), false, JSON.stringify(end));
});
