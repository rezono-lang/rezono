import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { readdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import test from 'node:test';

import { mismatch } from './reader_cases/check.mjs';

const root = new URL('../../', import.meta.url);
const cases = new URL('./reader_cases/', import.meta.url);
const board = JSON.parse(execFileSync('python', ['scripts/red_list.py', '--json'], {
    cwd: fileURLToPath(root), encoding: 'utf8'
}));
const expectedRed = new Set(board.map(task => task.file));

for (const file of readdirSync(cases).filter(file => file.endsWith('.json')).sort()) {
    const name = file.slice(0, -'.json'.length);
    test(name, t => {
        const difference = mismatch(new URL(file, cases));
        if (expectedRed.has(`rezono/test/test_${name}.py`)) {
            assert.notEqual(difference, null, 'The source matches the design. Remove its strict xfail.');
            t.todo(difference);
        } else {
            assert.equal(difference, null, difference ?? undefined);
        }
    });
}
