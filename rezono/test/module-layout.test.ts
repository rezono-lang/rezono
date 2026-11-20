// Counterexample tests for module layout splitting, line continuations, backtick handling,
// exact span preservation, and linear-time scaling (src/module-layout.ts).
import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
	moduleForm,
	parseModule,
	type CheckDecl,
	type ExtendDecl,
	type FactRow,
	type KindDecl,
	type ParamDecl
} from '../src/index.ts';
import * as moduleLayout from '../src/module-layout.ts';

const decls = (text: string) => {
	const r = parseModule(text);
	assert.deepEqual(r.diagnostics, []);
	return r.module!.decls;
};

test('lines ending in `=>` continue onto the next indented line (v0 §11)', () => {
	const text = [
		'rezono 0',
		'pack p',
		'check impl_check: a =>',
		'  b',
		'check impl_comment: a =>  -- implication continues',
		'  b',
		'extend K',
		'  derived ok: Bool = x =>',
		'    y',
		'param price: Money<EUR>',
		'  version 1 = € 10.00',
		''
	].join('\n');
	const parsed = decls(text);
	const [c1, c2, ext, param] = parsed as [CheckDecl, CheckDecl, ExtendDecl, ParamDecl];
	assert.deepEqual(c1.cond, { imply: [{ path: ['a'] }, { path: ['b'] }] });
	assert.deepEqual(c2.cond, { imply: [{ path: ['a'] }, { path: ['b'] }] });
	assert.deepEqual(ext.derived[0].value, { imply: [{ path: ['x'] }, { path: ['y'] }] });
	// `>` at the end of a parameterized type is not `=>`, so `version 1` stays a child block.
	assert.equal(param.versions?.length, 1);
	assert.deepEqual(param.versions![0].value, { lit: '€ 10.00' });
});

test('a deeper line starting with `.` continues a multiline method chain', () => {
	const text = [
		'rezono 0',
		'pack p',
		'extend K',
		'  derived one_step: Item = items.where(active)',
		'    .one()',
		'  derived multi_step: Item = items',
		'    .where(active)',
		'    .one()',
		'    unless missing then fallback',
		'check chained: items.where(active)',
		'  .one()',
		'  .score > 0',
		''
	].join('\n');
	const [ext, chk] = decls(text) as [ExtendDecl, CheckDecl];
	const expectedOne = { agg: ['one', { filter: [{ path: ['items'] }, { path: ['active'] }] }] };
	assert.deepEqual(ext.derived[0].value, expectedOne);
	assert.deepEqual(ext.derived[1].value, expectedOne);
	// A sibling `unless` clause after a `.one()` continuation remains a child block, not a continuation.
	assert.deepEqual(ext.derived[1].unless, [[{ when: { path: ['missing'] }, then: { path: ['fallback'] } }]]);
	assert.deepEqual(chk.cond, { cmp: ['>', { dot: [expectedOne, 'score'] }, { lit: '0' }] });
});

test('`codeOf` and bracket depth ignore comment markers, brackets, and quotes inside backticks', () => {
	assert.equal(moduleLayout.codeOf('  a = K:`a--b` -- trailing comment'), '  a = K:`a--b`');
	assert.equal(moduleLayout.codeOf('  a = K:`a"b` -- trailing comment'), '  a = K:`a"b`');
	assert.equal(moduleLayout.codeOf('  a = "x`y" -- trailing comment'), '  a = "x`y"');
	assert.equal(moduleLayout.codeOf('  a = K:`a\\` -- trailing comment'), '  a = K:`a\\`');

	const errors: { code: string; span: { text: string; start: number; end: number }; args: string[] }[] = [];
	const lines = moduleLayout.layout(
		['K:`x(1)`', 'K:`x(1`', 'K:`x[1`', 'K:`x{1`', 'near(K:`a"b`) -- comment'].join('\n'),
		errors,
		(at) => at,
		() => false
	);
	assert.deepEqual(errors, []);
	assert.deepEqual(
		lines.map((l) => l.depth),
		[0, 0, 0, 0, 0]
	);

	const mod = [
		'rezono 0',
		'pack p',
		'fact k k-a',
		'  a = K:`a--b` -- comment after backtick id with double dash',
		'extend K',
		'  derived b: Ref = K:`x(1`',
		'    unless missing then K:`y`',
		'  derived c: Ref = near(K:`a"b`) -- comment after quote inside backticks',
		'    unless missing then K:`z`',
		'  derived d: Ref = near(K:`x)1`,',
		'      K:`y[1{2`)',
		'    unless missing then K:`w`',
		''
	].join('\n');
	const [fact, ext] = decls(mod) as [FactRow, ExtendDecl];
	assert.deepEqual(fact.set, [{ slot: 'a', value: { lit: 'K:`a--b`' } }]);
	assert.deepEqual(ext.derived[0].value, { lit: 'K:`x(1`' });
	assert.deepEqual(ext.derived[0].unless, [[{ when: { path: ['missing'] }, then: { lit: 'K:`y`' } }]]);
	assert.deepEqual(ext.derived[1].value, { call: ['near', [{ lit: 'K:`a"b`' }]] });
	assert.deepEqual(ext.derived[1].unless, [[{ when: { path: ['missing'] }, then: { lit: 'K:`z`' } }]]);
	assert.deepEqual(ext.derived[2].value, { call: ['near', [{ lit: 'K:`x)1`' }, { lit: 'K:`y[1{2`' }]] });
	assert.deepEqual(ext.derived[2].unless, [[{ when: { path: ['missing'] }, then: { lit: 'K:`w`' } }]]);
});

test('slice parsing with base offset preserves exact code-point spans, lines, and diagnostic positions', () => {
	// The quadratic `only()` helper is replaced by slice-based parsing with a base offset.
	assert.equal('only' in moduleLayout, false);
	assert.equal(typeof (moduleLayout as Record<string, unknown>).sliceOf, 'function');

	const lfText = [
		'rezono 0',
		'pack p',
		'-- 😀 astral comment before declarations',
		'reason note = "🎉"',
		'extend K',
		'  derived ok: Bool = a =>',
		'    b',
		'  derived pick: Item = items.where(active)',
		'    .one()',
		'  derived band: Band',
		'    table unique',
		'      | age | -> band |',
		'      | 18.. | standard |',
		''
	].join('\n');

	const expectedLine = (src: string, cpOffset: number) => {
		let line = 1;
		let i = 0;
		for (const ch of src) {
			if (i === cpOffset) break;
			if (ch === '\n') line++;
			i++;
		}
		return line;
	};

	for (const text of [lfText, lfText.replaceAll('\n', '\r\n')]) {
		const parsed = parseModule(text);
		assert.deepEqual(parsed.diagnostics, []);
		const formRes = moduleForm(text);
		assert.deepEqual(formRes.diagnostics, []);
		const points = [...text];
		assert.ok(formRes.form!.spans.length > 0);
		for (const place of formRes.form!.spans) {
			const start = Number(place.start);
			const end = Number(place.end);
			assert.ok(start >= 0 && end >= start && end <= points.length, `span out of bounds: ${JSON.stringify(place)}`);
			assert.equal(Number(place.line), expectedLine(text, start), `line mismatch at ${place.at}`);
		}
		// Spot-check exact spans for declarations and multiline expressions.
		const ext = parsed.module!.decls[1] as ExtendDecl;
		const okSpan = parsed.spans.get(ext.derived[0].value!)!;
		assert.equal(points.slice(okSpan.start, okSpan.end).join(''), 'a =>' + (text.includes('\r\n') ? '\r\n' : '\n') + '    b');
		const pickSpan = parsed.spans.get(ext.derived[1].value!)!;
		assert.equal(points.slice(pickSpan.start, pickSpan.end).join(''), 'items.where(active)' + (text.includes('\r\n') ? '\r\n' : '\n') + '    .one()');
	}

	// Reserved R015 span and end-of-line incomplete R000 diagnostic span remain exact with astral prefix.
	const r015Text = 'rezono 0\npack p\n-- 😀\nextend K\n  derived a: Int = x at y\n';
	const [r015] = parseModule(r015Text).diagnostics;
	assert.equal(r015.code, 'R015');
	assert.equal([...r015Text].slice(r015.span.start, r015.span.end).join(''), 'at y');

	const eolErrText = 'rezono 0\npack p\n-- 😀\nextend K\n  derived a: T\n    table unique\n      | x | -> a |\n      | y |\n';
	const [eolErr] = parseModule(eolErrText).diagnostics;
	assert.equal(eolErr.code, 'R000');
	assert.equal(eolErr.span.text, '');
	const rowEndCp = [...eolErrText.slice(0, eolErrText.lastIndexOf('\n'))].length;
	assert.equal(eolErr.span.start, rowEndCp);
	assert.equal(eolErr.span.end, rowEndCp);
});

test('large modules parse in linear time instead of quadratic full-file copies', () => {
	const count = 600;
	const lines = ['rezono 0', 'pack p', 'kind K world closed'];
	for (let i = 0; i < count; i++) lines.push(`  slot_${i}: Int`);
	lines.push('extend K');
	lines.push('  derived last_val: Int = slot_0 + 1');
	const src = lines.join('\n') + '\n';

	const t0 = performance.now();
	const parsed = parseModule(src);
	const elapsedMs = performance.now() - t0;

	assert.deepEqual(parsed.diagnostics, []);
	const [kind, ext] = parsed.module!.decls as [KindDecl, ExtendDecl];
	assert.equal(kind.slots.length, count);
	const lastSpan = parsed.spans.get(ext.derived[0])!;
	assert.equal(src.slice(lastSpan.start, lastSpan.end), 'last_val');
	assert.ok(elapsedMs < 2000, `expected linear-time parse (< 2000 ms) for ${count} slots, took ${elapsedMs.toFixed(1)} ms`);
});
