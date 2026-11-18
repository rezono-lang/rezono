import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { readdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import test, { type TestContext } from 'node:test';

import { mismatch } from './reader_cases/check.mjs';

const root = new URL('../../', import.meta.url);
const cases = new URL('./reader_cases/', import.meta.url);
const board = JSON.parse(execFileSync('python', ['scripts/red_list.py', '--json'], {
    cwd: fileURLToPath(root), encoding: 'utf8'
}));
const expectedRed = new Set(board.map(task => task.id));

function assertCase(name: string, difference: string | null, t: TestContext) {
    const task = `rezono/test/test_${name}.py--test_${name}`;
    if (expectedRed.has(task)) {
        assert.notEqual(difference, null, 'The source matches the design. Remove its strict xfail.');
        t.todo(difference);
    } else {
        assert.equal(difference, null, difference ?? undefined);
    }
}

for (const file of readdirSync(cases).filter(file => file.endsWith('.json')).sort()) {
    const name = file.slice(0, -'.json'.length);
    test(name, t => assertCase(name, mismatch(new URL(file, cases)), t));
}

for (const [name, file] of [
    ['native_rule_safe_body', 'native-rule-safe-body.mts'],
    ['expression_ts_negated_call', 'expression-negated-call.mts'],
]) {
    test(name, t => {
        const probe = fileURLToPath(new URL(file, import.meta.url));
        const report: unknown = JSON.parse(execFileSync(process.execPath, [probe], { encoding: 'utf8' }));
        assert.ok(Array.isArray(report), 'The native rule probe must report a list of differences.');
        assertCase(name, report.length ? JSON.stringify(report, null, 2) : null, t);
    });
}

test('expression_ts_filtered_count', t => {
    const probe = fileURLToPath(new URL('./expression-filtered-count.mts', import.meta.url));
    const report: unknown = JSON.parse(execFileSync(process.execPath, [probe], { encoding: 'utf8' }));
    assert.ok(report === null || typeof report === 'string', 'The filtered group probe must report a difference or null.');
    assertCase('expression_ts_filtered_count', report, t);
});
