// The cases of an example written in Reckon (examples/<name>/cases.yaml beside its *.rezono files) run here as far
// as this implementation reaches. A case with `evidence: current` must give its outcome now; one with
// `evidence: future` is design input, listed as a todo with the current case that blocks it, never run. The
// kinds of current case this implementation runs are `compile`: the diagnostics of the example's files, read as
// modules (src/module.ts), in source order, each with its code and the text at its span (`at`); and `form`:
// which of those files have a JSON form (src/module-json.ts), the form the compiler reads. Whatever a case says,
// every file is written as its form twice here, and every module is printed and read back. Nothing here names
// one example: what an example expects is in its own folder.
import assert from 'node:assert/strict';
import { existsSync, readdirSync, readFileSync } from 'node:fs';
import { test } from 'node:test';
import { parse as yaml } from 'yaml';
import { isError, moduleForm, moduleFromJson, moduleToJson, parseModule, printModule } from '../src/index.ts';

interface Case {
	id: string;
	title: string;
	evidence: 'current' | 'future';
	blocked_by?: string[];
	compile?: boolean;
	form?: boolean;
	expect: { diagnostics?: { code: string; at: string }[]; forms?: { file: string; written: boolean }[] };
}

const root = new URL('../../examples/', import.meta.url);
const examples = readdirSync(root, { withFileTypes: true })
	.filter((e) => e.isDirectory() && existsSync(new URL(`${e.name}/cases.yaml`, root)))
	.map((e) => e.name)
	.filter((name) => readdirSync(new URL(`${name}/`, root)).some((f) => f.endsWith('.rezono')))
	.sort();

test('at least one example is written in Reckon', () => assert.ok(examples.length > 0));

for (const name of examples) {
	const dir = new URL(`${name}/`, root);
	const { pack, cases } = yaml(readFileSync(new URL('cases.yaml', dir), 'utf8')) as { pack: string; cases: Case[] };
	// The pack's own file first, then the others by name.
	const files = readdirSync(dir)
		.filter((f) => f.endsWith('.rezono'))
		.sort((a, b) => Number(b === `${pack}.rezono`) - Number(a === `${pack}.rezono`) || (a < b ? -1 : a > b ? 1 : 0));
	const texts = files.map((f) => readFileSync(new URL(f, dir), 'utf8'));
	const read = files.map((f, i) => ({ file: f, ...parseModule(texts[i]) }));
	const forms = files.map((f, i) => ({ file: f, ...moduleForm(texts[i]) }));

	test(`${name}: every file is a module of pack ${pack}`, () => {
		for (const r of read) {
			assert.ok(r.module, `${r.file}: ${r.diagnostics.map((d) => `${d.code} ${d.span.text} (${d.args.join(', ')})`).join('; ')}`);
			assert.equal(r.module.pack, pack, r.file);
		}
	});

	test(`${name}: every module prints in its normal form and reads back as the same module`, () => {
		for (const r of read) {
			const printed = printModule(r.module!);
			const again = parseModule(printed).module;
			assert.deepEqual(again, r.module, r.file);
			assert.equal(printModule(again!), printed, r.file);
		}
	});

	test(`${name}: every file writes its JSON form, the same bytes twice, or has an error and no form`, () => {
		for (const [i, f] of forms.entries()) {
			assert.deepEqual(f.diagnostics, read[i].diagnostics, f.file);
			assert.equal(f.form === undefined, read[i].diagnostics.some(isError), f.file);
			if (!f.form) continue;
			const json = moduleToJson(f.form);
			assert.equal(moduleToJson(moduleForm(texts[i]).form!), json, f.file);
			assert.equal(moduleToJson(moduleFromJson(JSON.parse(json))), json, f.file);
		}
	});

	const current = new Set(cases.filter((c) => c.evidence === 'current').map((c) => c.id));
	for (const c of cases) {
		if (c.evidence === 'future') {
			test(`${name} ${c.id}: ${c.title}`, { todo: `future evidence, blocked by ${(c.blocked_by ?? []).join(', ')}` }, () => {
				assert.ok(c.blocked_by?.length && c.blocked_by.every((id) => current.has(id)), 'a future case names the current cases that block it');
			});
			continue;
		}
		test(`${name} ${c.id}: ${c.title}`, () => {
			assert.ok(c.compile === true || c.form === true, 'the current cases this implementation runs are `compile` and `form`');
			if (c.compile) {
				const got = read.flatMap((r) => r.diagnostics.map((d) => ({ code: d.code, at: d.span.text })));
				assert.deepEqual(got, (c.expect.diagnostics ?? []).map(({ code, at }) => ({ code, at })));
			}
			if (c.form)
				assert.deepEqual(
					forms.map((f) => ({ file: f.file, written: f.form !== undefined })),
					(c.expect.forms ?? []).map(({ file, written }) => ({ file, written }))
				);
		});
	}
}
