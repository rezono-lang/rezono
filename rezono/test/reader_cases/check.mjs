import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { moduleForm } from '../../src/module-json.ts';

/** Only the recorded refusal is an expected mismatch. Any other failure throws. */
export function mismatch(file) {
    const { source, declarations, knownDiagnostics } = JSON.parse(readFileSync(file, 'utf8'));
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
