import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { join } from 'node:path';
import { test } from 'node:test';
import { rolePublication } from '../../../examples/platform/proof_cases/role-publication-cases.ts';
import type { Bundle } from '../../../contracts/typescript/generated/bundle.ts';
import type { Manifest } from '../../../contracts/typescript/generated/manifest.ts';
import { catalogueKindsQuestion, catalogueSchemaQuestion } from '../../../edge/gate/src/catalogue-questions.ts';
import { rowQuestion } from '../../../edge/gate/src/row-query.ts';
import { local } from '../src/client.ts';
import { answerText } from '../src/explain.ts';
import { Recorder, replay } from '../src/record.ts';
import { Session } from '../src/session.ts';

const store = process.env.REZONO_REPL_TEST_STORE;
const retained = process.env.REZONO_REPL_RETAINED_STORE;
if (!store || !retained) throw new Error('REZONO_REPL_TEST_STORE and REZONO_REPL_RETAINED_STORE must name the published two-role platform stores');

const { pack, manifest, retainedManifest, hiddenKind, absentKind, groundRelation, roles,
	replQuestion: ask } = rolePublication;
const published = JSON.parse(await readFile(join(store, pack, 'manifests', `${manifest}.json`), 'utf8')) as Manifest;
const bundleRef = published.compiled?.find(({ file }) => file === 'bundle/schema-bundle.json');
assert.ok(bundleRef?.uri);
const bundle = JSON.parse(await readFile(join(store, new URL(bundleRef.uri).pathname.slice(1)), 'utf8')) as Bundle;
assert.ok(bundle.kinds.some(({ id }) => id === hiddenKind));
assert.ok(!bundle.kinds.some(({ id }) => id === absentKind));

for (const [role, peer] of roles) {
	test(`published ${role} session replays bytewise and sees only its own rows and grounds`, async () => {
		const connection = local(store);
		const session = new Session(connection, role, { pack, manifest }, { pageSize: 1 });
		const recorder = new Recorder(session);
		assert.deepEqual(await recorder.exec(`:use ${pack} latest`), [`using ${pack} ${manifest} as ${role}`]);

		const page = (await recorder.exec(ask)).join('\n');
		assert.match(page, new RegExp(`(?:^|\\n)${role}-request[ \\t]+`));
		assert.match(page, /next:/);
		assert.doesNotMatch(page, new RegExp(`${peer}-(?:second-)?request`));

		const next = (await recorder.exec(':more')).join('\n');
		assert.match(next, new RegExp(`${role}-second-request[ \t]+`));
		assert.doesNotMatch(next, new RegExp(`${peer}-(?:second-)?request`));
		assert.deepEqual(await session.search('request', `${role}-`), [`${role}-request`, `${role}-second-request`]);
		assert.deepEqual(await session.search('request', `${peer}-`), await session.search('request', 'absent-'));
		assert.deepEqual(await recorder.exec(`:complete :row request ${role}-`), [`${role}-request`, `${role}-second-request`]);

		const own = `:grounds ${groundRelation} ${role} ${role}-request ${role}-quota`;
		assert.match((await recorder.exec(own)).join('\n'), new RegExp(groundRelation));
		const hidden = await recorder.exec(`:grounds ${groundRelation} ${peer} ${peer}-request ${peer}-quota`);
		const absent = await recorder.exec(`:grounds ${groundRelation} absent absent-request absent-quota`);
		assert.deepEqual(hidden, ['error: not found (or outside your view)']);
		assert.deepEqual(hidden, absent);

		const direct = new Session(connection, role, { pack, manifest }, { pageSize: 1 });
		await direct.use(pack, manifest);
		const kinds = await direct.query(catalogueKindsQuestion, 'catalogue');
		assert.ok(kinds.next);
		assert.deepEqual(await recorder.exec(':kinds'), answerText(kinds));
		assert.deepEqual(await recorder.exec(':more'), answerText(await direct.more()));

		let schema = await direct.query(catalogueSchemaQuestion('Request'), 'catalogue');
		const schemaLines = await recorder.exec(':schema Request');
		assert.deepEqual(schemaLines, answerText(schema));
		while (schema.next) {
			schema = await direct.more();
			const lines = await recorder.exec(':more');
			assert.deepEqual(lines, answerText(schema));
			schemaLines.push(...lines);
		}
		assert.match(schemaLines.join('\n'), /kind\/request[^\n]+Request/);
		assert.match(schemaLines.join('\n'), /slot\/request\/cores[^\n]+Integer/);
		const hiddenSchema = await recorder.exec(`:schema ${hiddenKind}`);
		assert.ok(hiddenSchema.includes('rows: 0  undecided: 0  not applicable: 0'));
		assert.deepEqual(hiddenSchema, await recorder.exec(`:schema ${absentKind}`));

		const storedRow = `${role}-request`;
		const request = await connection.open(role);
		const askRow = async (after?: string) => {
			const response = await request(`/${pack}/${manifest}/ask`, { method: 'POST',
				body: JSON.stringify({ text: rowQuestion, scope: 'row', limit: 1, after,
					row: { kind: 'Request', key: [storedRow], source_limit: 50 } })
			});
			assert.equal(response.status, 200);
			return response.json();
		};
		const row = await askRow();
		const firstRow = await recorder.exec(`:row Request ${storedRow}`);
		assert.deepEqual(firstRow, answerText(row, true));
		assert.match(firstRow[0], /name +relation +subject_kind +subject_key.*integer_value.*state/);
		assert.match(firstRow[1], /cores +request__cores.*integer.*2.*known/);
		assert.ok(row.next);
		assert.deepEqual(await recorder.exec(':more'), answerText(await askRow(row.next), true));
		const isolated = await recorder.exec(`:row Request ${peer}-request`);
		assert.deepEqual(isolated, ['error: not found (or outside your view)']);
		assert.deepEqual(isolated, await recorder.exec(':row Request absent-request'));

		const result = await replay(recorder.text(), new Session(connection, role, { pack, manifest }, { pageSize: 1 }));
		assert.equal(result.same, true, JSON.stringify(result));
		const archived = local(retained);
		const latest = await new Session(archived, role).use(pack, 'latest');
		assert.equal(latest.manifest, retainedManifest);
		const historical = await replay(recorder.text(), new Session(archived, role, { pack, manifest }, { pageSize: 1 }));
		assert.equal(historical.same, true, JSON.stringify(historical));
	});
}
