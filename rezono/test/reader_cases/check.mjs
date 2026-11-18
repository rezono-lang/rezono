import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { moduleForm, moduleFromJson, moduleToJson } from '../../src/module-json.ts';

/** Only the recorded refusal is an expected mismatch. Any other failure throws. */
export function mismatch(file) {
    const fixture = JSON.parse(readFileSync(file, 'utf8'));
    const source = 'rezono 0\npack sample\n' + fixture.source + '\n';
    const { form, diagnostics } = moduleForm(source);
    if (!form) {
        assert.deepEqual(diagnostics, fixture.knownDiagnostics, 'The reader returned a different diagnostic.');
        return JSON.stringify(diagnostics);
    }
    assert.equal(form.format, 'rezono.module/2');
    if (fixture.module) {
        assert.deepEqual(form.module, fixture.module);
        assert.deepEqual(moduleFromJson(JSON.parse(moduleToJson(form))), form);
    } else {
        assert.deepEqual(form.module.decls, fixture.declarations);
    }
    for (const [at, name] of Object.entries(fixture.spanNames ?? {})) {
        const place = form.spans.find(span => span.at === at);
        assert.ok(place, `Missing authored span at ${at}.`);
        assert.equal([...source].slice(Number(place.start), Number(place.end)).join(''), name);
    }
    for (const { from, to } of fixture.rejections ?? []) {
        assert.ok(source.includes(from), `No source to replace: ${from}`);
        assert.equal(moduleForm(source.replace(from, to)).form, undefined, `Accepted ${to}`);
    }
    return null;
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
    process.stdout.write(JSON.stringify(mismatch(process.argv[2])));
}
