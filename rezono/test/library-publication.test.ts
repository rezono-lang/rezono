import test from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';

import { moduleForm } from '../src/module-json.ts';

const sources = new URL('../../examples/library/candidate/', import.meta.url);

test('each submitted library form is the tree of its own authored text', () => {
    let checked = 0;
    for (const name of ['library', 'valid', 'errors']) {
        const source = new URL(name + '.rezono', sources);
        const form = new URL(name + '.json', sources);
        if (!existsSync(source) && !existsSync(form)) continue;
        const parsed = moduleForm(readFileSync(source, 'utf8'));
        assert.ok(parsed.form, JSON.stringify(parsed.diagnostics));
        assert.deepEqual(parsed.form, JSON.parse(readFileSync(form, 'utf8')), name);
        checked++;
    }
    // The candidate holds all three modules, so the test never passes by finding none.
    assert.equal(checked, 3, 'complete-pack acceptance requires library, valid and errors');
});
