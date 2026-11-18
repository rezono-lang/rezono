import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { moduleForm } from '../../src/module-json.ts';

/** A refusal or a different tree is a case mismatch. A broken reader or fixture throws. */
export function mismatch(file) {
    const { source, declarations } = JSON.parse(readFileSync(file, 'utf8'));
    const { form, diagnostics } = moduleForm('rezono 0\npack sample\n' + source + '\n');
    if (!form) return JSON.stringify(diagnostics);
    try {
        assert.equal(form.format, 'rezono.module/2');
        assert.deepEqual(form.module.decls, declarations);
    } catch (error) {
        if (error instanceof assert.AssertionError) return error.message;
        throw error;
    }
    return null;
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
    process.stdout.write(JSON.stringify(mismatch(process.argv[2])));
}
