import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { moduleForm } from '../../src/module-json.ts';
import { parse } from '../../src/parse.ts';
import { parseModule } from '../../src/module.ts';
import { printModule } from '../../src/print.ts';

const diagnosticPlaces = diagnostics => diagnostics.map(({ code, span }) => ({ code, span }));

function nativeRuleMismatch({ source, form: expected, knownDiagnostics, extended, refusals }) {
    const { form, diagnostics } = moduleForm(source);
    if (!form) {
        const places = diagnosticPlaces(diagnostics);
        assert.deepEqual(places, knownDiagnostics, 'The native reader returned a different diagnostic.');
        return JSON.stringify(places);
    }
    assert.deepEqual(diagnostics, []);
    assert.deepEqual(form, expected);
    assert.equal(printModule(form.module), source);

    const crlfSpans = expected.spans.map(({ at, line, start, end }) => ({
        at, line, start: String(Number(start) + Number(line) - 1), end: String(Number(end) + Number(line) - 1)
    }));
    assert.deepEqual(moduleForm(source.replaceAll('\n', '\r\n')), {
        form: { ...expected, spans: crlfSpans }, diagnostics: []
    });

    const rich = moduleForm(extended.source);
    assert.deepEqual(rich.diagnostics, []);
    assert.equal(rich.form?.format, expected.format);
    assert.deepEqual(rich.form.module, extended.module);
    const pointers = new Set(extended.spans.map(({ at }) => at));
    assert.deepEqual(rich.form.spans.filter(({ at }) => pointers.has(at)), extended.spans);
    const printed = printModule(rich.form.module);
    const readBack = parseModule(printed);
    assert.deepEqual(readBack.diagnostics, []);
    assert.deepEqual(readBack.module, extended.module);
    assert.equal(printModule(readBack.module), printed);
    const question = parse(extended.ask);
    assert.deepEqual(question.diagnostics, []);
    assert.deepEqual(question.tree.where, extended.module.decls[2].when);

    for (const { source, diagnostics } of refusals) {
        const refused = moduleForm(source);
        assert.equal(refused.form, undefined, source);
        assert.deepEqual(diagnosticPlaces(refused.diagnostics), diagnostics, source);
    }
    return null;
}

/** Only the recorded refusal is an expected mismatch. Any other failure throws. */
export function mismatch(file) {
    const fixture = JSON.parse(readFileSync(file, 'utf8'));
    if (fixture.form) return nativeRuleMismatch(fixture);
    const { source, declarations, knownDiagnostics } = fixture;
    const { form, diagnostics } = moduleForm('rezono 0\npack sample\n' + source + '\n');
    if (!form) {
        assert.deepEqual(diagnostics, knownDiagnostics, 'The reader returned a different diagnostic.');
        return JSON.stringify(diagnostics);
    }
    assert.equal(form.format, 'rezono.module/2');
    assert.deepEqual(form.module.decls, declarations);
    return null;
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
    process.stdout.write(JSON.stringify(mismatch(process.argv[2])));
}
