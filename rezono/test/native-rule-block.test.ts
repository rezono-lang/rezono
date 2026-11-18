import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { existsSync, mkdtempSync, readFileSync, rmSync, rmdirSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

import { moduleForm, moduleFromJson, moduleToJson, printModule } from '../src/index.ts';
import { writeForm } from '../src/write-form.ts';

const TASK = 'rezono/test/test_native_rule_block.py--test_native_rule_block';

// The five clauses and their expected trees come from decisions/language-native-rules.md.
const header = 'rezono 0\npack sample\n-- 🔎 Authored rule examples\n';
const source = header + [
    'rules inventory',
    '  listed(item: ?item, group: ?group) if Item.group(?item, ?group) and Group.state(?group, "active")',
    'rules ancestry',
    '  reachable(item: ?item, group: ?group) if Item.group(?item, ?group)',
    '  reachable(item: ?item, group: ?group) if reachable(item: ?item, group: ?parent) and Group.parent(?parent, ?group)',
    'rules eligibility',
    '  blocked(item: ?item) if Exclusion.item(?exclusion, ?item)',
    '  eligible(item: ?item) if Item(?item) and not blocked(item: ?item)',
    'rules membership',
    '  size(group: ?group, count: ?n) if Group(?group) and ?n = count { Item.group(?item, ?group) }',
    'rules capacity',
    '  heavy(item: ?item) if Item.weight(?item, ?weight) and ?weight > 2',
    '',
].join('\n');

const variable = (name: string) => ({ var: name });
const value = (name: string) => ({ value: variable(name) });
const field = (label: string, name = label) => ({ field: label, value: variable(name) });
const itemGroup = { relation: 'Item.group', arguments: [value('item'), value('group')] };
const reach = { relation: 'reachable', arguments: [field('item'), field('group')] };
const blocked = { relation: 'blocked', arguments: [field('item')] };
const group = { relation: 'Group', arguments: [value('group')] };

const expected = {
    rezono: '0',
    pack: 'sample',
    use: [],
    decls: [
        { rules: 'inventory', clauses: [{
            head: { relation: 'listed', arguments: [field('item'), field('group')] },
            body: [
                { atom: itemGroup },
                { atom: { relation: 'Group.state', arguments: [
                    value('group'), { value: { lit: { type: 'text', value: 'active' } } },
                ] } },
            ],
        }] },
        { rules: 'ancestry', clauses: [
            { head: reach, body: [{ atom: itemGroup }] },
            { head: reach, body: [
                { atom: { relation: 'reachable', arguments: [field('item'), field('group', 'parent')] } },
                { atom: { relation: 'Group.parent', arguments: [value('parent'), value('group')] } },
            ] },
        ] },
        { rules: 'eligibility', clauses: [
            { head: blocked, body: [
                { atom: { relation: 'Exclusion.item', arguments: [value('exclusion'), value('item')] } },
            ] },
            { head: { relation: 'eligible', arguments: [field('item')] }, body: [
                { atom: { relation: 'Item', arguments: [value('item')] } }, { not: blocked },
            ] },
        ] },
        { rules: 'membership', clauses: [{
            head: { relation: 'size', arguments: [field('group'), field('count', 'n')] },
            body: [{ atom: group }, { count: { result: 'n', atom: itemGroup } }],
        }] },
        { rules: 'capacity', clauses: [{
            head: { relation: 'heavy', arguments: [field('item')] },
            body: [
                { atom: { relation: 'Item.weight', arguments: [value('item'), value('weight')] } },
                { compare: {
                    left: variable('weight'), op: '>', right: { lit: { type: 'integer', value: '2' } },
                } },
            ],
        }] },
    ],
};

const position = (text: string, offset: number) => [...text.slice(0, offset)].length;

function assertPlace(
    form: NonNullable<ReturnType<typeof moduleForm>['form']>,
    at: string, lineStart: string, token: string, after = '',
) {
    const line = source.indexOf(lineStart);
    assert.ok(line >= 0);
    const anchor = after ? source.indexOf(after, line) + after.length : line;
    const offset = source.indexOf(token, anchor);
    assert.ok(offset >= line && offset < source.indexOf('\n', line), token);
    assert.deepEqual(form.spans.find(place => place.at === at), {
        at,
        line: String(source.slice(0, offset).split('\n').length),
        start: String(position(source, offset)),
        end: String(position(source, offset + token.length)),
    });
}

function assertRefused(text: string) {
    const start = position(text, text.lastIndexOf('\n', text.trimEnd().length - 1) + 1);
    const result = moduleForm(text);
    assert.equal(result.form, undefined);
    assert.ok(result.diagnostics.some(diagnostic => diagnostic.code === 'R000' && diagnostic.span.start >= start),
        JSON.stringify(result.diagnostics));
}

function assertInterim() {
    const lines = ['.decl retained(item: symbol)', 'retained(x) :- item(x).', '.output retained'];
    const text = header + 'rules legacy\n' + lines.map(line => '  | ' + line + '\n').join('');
    const result = moduleForm(text);
    if (result.form) {
        assert.deepEqual(result.form.module.decls, [{ rules: 'legacy', lines }]);
        assert.deepEqual(moduleForm(printModule(result.form.module)).form?.module, result.form.module);
    } else {
        // The independent interim reader task is still red until its syntax lands.
        const existing = JSON.parse(execFileSync('python', ['scripts/red_list.py', '--json'], {
            cwd: fileURLToPath(new URL('../../', import.meta.url)), encoding: 'utf8',
        }));
        assert.ok(existing.some(({ id }: { id: string }) =>
            id === 'rezono/test/test_relational_rule_block.py--test_relational_rule_block'));
        assert.ok(result.diagnostics.some(diagnostic => diagnostic.code === 'R000'));
    }
}

function mismatch() {
    const result = moduleForm(source);
    if (!result.form) {
        // Keep the expected failure narrow. A different refusal or a crash fails the runnable check.
        const first = result.diagnostics[0];
        const start = position(source, source.indexOf('inventory'));
        assert.equal(first.code, 'R000');
        assert.deepEqual(first.span, { text: 'inventory', start, end: start + 'inventory'.length });
        return 'R000 at inventory: the module reader does not yet admit native rules';
    }
    assert.deepEqual(result.diagnostics, []);
    assert.equal(result.form.format, 'rezono.module/2');
    assert.deepEqual(result.form.module, expected);
    assertPlace(result.form, '/decls/0/clauses/0/head/relation', '  listed(', 'listed');
    assertPlace(result.form, '/decls/0/clauses/0/head/arguments/1/field', '  listed(', 'group');
    assertPlace(result.form, '/decls/0/clauses/0/body/1/atom/relation', '  listed(', 'Group.state');
    assertPlace(result.form, '/decls/2/clauses/1/body/1/not/relation', '  eligible(', 'blocked', 'and not ');
    assertPlace(result.form, '/decls/3/clauses/0/body/1/count/atom/relation', '  size(', 'Item.group', 'count { ');
    assertPlace(result.form, '/decls/4/clauses/0/body/1/compare/op', '  heavy(', '>');

    const canonical = moduleToJson(result.form);
    assert.deepEqual(moduleFromJson(JSON.parse(canonical)), result.form);
    assert.deepEqual(moduleForm(printModule(result.form.module)).form?.module, expected);
    const mixed = JSON.parse(canonical);
    mixed.module.decls[0].lines = ['.output listed'];
    assert.throws(() => moduleFromJson(mixed));

    assertRefused(header + 'rules capacity\n  heavy(item: ?item) if\n');
    assertRefused(header + 'rules capacity\n  heavy(item: ?item) if Item(?item)\n  | .output heavy\n');
    assertInterim();

    const directory = mkdtempSync(join(tmpdir(), 'rezono-native-rules-'));
    const input = join(directory, 'sample.rezono');
    const output = join(directory, 'sample.json');
    try {
        writeFileSync(input, source);
        const diagnostics: string[] = [];
        assert.equal(writeForm(input, output, line => diagnostics.push(line)), 0, diagnostics.join('\n'));
        assert.equal(readFileSync(output, 'utf8'), canonical);
        writeFileSync(input, header + 'rules capacity\n  heavy(item: ?item) if\n');
        assert.equal(writeForm(input, output, line => diagnostics.push(line)), 1);
        assert.equal(existsSync(output), false, 'the previous form must be removed after a refusal');
    } finally {
        rmSync(input, { force: true });
        rmSync(output, { force: true });
        rmdirSync(directory);
    }
    return null;
}

if (process.argv[2] === '--probe') {
    process.stdout.write(JSON.stringify(mismatch()));
} else {
    test('reads native rules and preserves their authored places', t => {
        const remaining = mismatch();
        const board = JSON.parse(execFileSync('python', ['scripts/red_list.py', '--json'], {
            cwd: fileURLToPath(new URL('../../', import.meta.url)), encoding: 'utf8',
        }));
        if (board.some(({ id }: { id: string }) => id === TASK)) {
            assert.notEqual(remaining, null, 'Remove the strict xfail once native rule reading works.');
            t.todo(remaining ?? undefined);
        } else {
            assert.equal(remaining, null);
        }
    });
}
