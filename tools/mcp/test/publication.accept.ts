import assert from 'node:assert/strict';
import { test, type TestContext } from 'node:test';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { InMemoryTransport } from '@modelcontextprotocol/sdk/inMemory.js';
import { z } from 'zod';
import { catalogueKindsQuestion, catalogueSchemaQuestion } from '../../../edge/gate/src/catalogue-questions.ts';
import { openLocalGate } from '../../../edge/gate/src/local.ts';
import { rowQuestion, type RowSelection } from '../../../edge/gate/src/row-query.ts';
import { local } from '../../repl/src/client.ts';
import { answerText } from '../../repl/src/explain.ts';
import { Session, type Answer } from '../../repl/src/session.ts';
import { compare, run, type Call } from '../src/replay.ts';
import { mcpServer } from '../src/server.ts';

const store = process.env.REZONO_REPL_TEST_STORE;
const retained = process.env.REZONO_REPL_RETAINED_STORE;
if (!store || !retained) throw new Error('REZONO_REPL_TEST_STORE and REZONO_REPL_RETAINED_STORE must name the published two-role platform stores');

const pack = 'platform-core';
const manifest = 'm-1';
const pin = { pack, manifest };
const source = 'ask Request where request.cores > 0 show request.cores';
type Query = { after?: string; scope?: 'catalogue' | 'row'; row?: RowSelection };
const rowDataset = z.object({
	rows: z.array(z.object({
		c1: z.string(),
		c2: z.string(),
		c3: z.string(),
		c4: z.string(),
		c5: z.string(),
		c6: z.string(),
		c8: z.unknown(),
		c13: z.string(),
	})),
});

async function connect(t: TestContext, role: string, publication: string) {
	const server = mcpServer(new Session(local(publication), role, pin, { pageSize: 1 }), role, { lockedPin: pin });
	const client = new Client({ name: 'publication-acceptance', version: '0.1.0' });
	const [from, to] = InMemoryTransport.createLinkedPair();
	await server.connect(to);
	await client.connect(from);
	t.after(async () => {
		await client.close();
		await server.close();
	});
	return client;
}

for (const [role, peer] of [['elm', 'reed'], ['reed', 'elm']]) {
	test(`${role} sees only its published rows and replays the shared answers`, async (t) => {
		const gate = await openLocalGate(store, role);
		function request(question: string, query: Query) {
			return gate(new Request(`http://rezono.local/${pack}/${manifest}/ask`, {
				method: 'POST',
				headers: { 'content-type': 'application/json' },
				body: JSON.stringify({ text: question, limit: 1, ...query }),
			}));
		}
		async function ask(question: string, query: Query = {}): Promise<Answer> {
			const response = await request(question, query);
			assert.equal(response.status, 200);
			const answer: Answer = await response.json();
			assert.equal(answer.format, 'rezono.answer/1');
			assert.equal(answer.manifest_id, manifest);
			return answer;
		}
		const first = await ask(source);
		assert.equal(first.counts?.rows, 2);
		assert.ok(first.next);
		const second = await ask(source, { after: first.next });
		assert.equal(second.next, undefined);
		assert.deepEqual(
			[first, second].flatMap(answer => answer.nodes.map(node => node.key)),
			[JSON.stringify([`${role}-request`]), JSON.stringify([`${role}-second-request`])],
		);

		const repl = new Session(local(store), role, pin, { pageSize: 1 });
		await repl.exec(`:use ${pack} ${manifest}`);
		const replFirst = await repl.exec(source);
		const replSecond = await repl.exec(':more');
		assert.deepEqual(replFirst, answerText(first));
		assert.deepEqual(replSecond, answerText(second));

		const calls: Call[] = [
			{ tool: 'ask', args: { pack, text: source } },
			{ tool: 'more', args: {} },
			{ tool: 'grounds', args: { pack, target: ['tenant_capacity_fits', role, `${role}-request`, `${role}-quota`] } },
			{ tool: 'grounds', args: { pack, target: ['tenant_capacity_fits', peer, `${peer}-request`, `${peer}-quota`] } },
			{ tool: 'grounds', args: { pack, target: ['tenant_capacity_fits', role, 'unused-request', `${role}-quota`] } },
			{ tool: 'search', args: { pack, kind: 'request', prefix: role } },
			{ tool: 'search', args: { pack, kind: 'request', prefix: peer } },
			{ tool: 'search', args: { pack, kind: 'request', prefix: 'unused' } },
		];
		const requestSchema = catalogueSchemaQuestion('Request');
		const kinds = await ask(catalogueKindsQuestion, { scope: 'catalogue' });
		const schema = await ask(requestSchema, { scope: 'catalogue' });
		assert.ok(kinds.next && schema.next);
		assert.deepEqual(schema.nodes.map(node => node.key), ['["kind/request"]']);
		const hiddenKind = 'backup_capture';
		const absentKind = 'unused_kind';
		const hidden = await ask(catalogueSchemaQuestion(hiddenKind), { scope: 'catalogue' });
		const absent = await ask(catalogueSchemaQuestion(absentKind), { scope: 'catalogue' });
		assert.equal(hidden.counts?.rows, 0);
		assert.deepEqual(hidden.nodes, absent.nodes);
		const catalogueCalls: Call[] = [
			{ tool: 'kinds', args: { pack } },
			{ tool: 'more', args: {} },
			{ tool: 'schema', args: { pack, kind: 'Request' } },
			{ tool: 'more', args: {} },
			{ tool: 'schema', args: { pack, kind: hiddenKind } },
			{ tool: 'schema', args: { pack, kind: absentKind } },
		];
		const expectedCatalogue = [
			[':kinds', kinds],
			[':more', await ask(catalogueKindsQuestion, { after: kinds.next, scope: 'catalogue' })],
			[':schema Request', schema],
			[':more', await ask(requestSchema, { after: schema.next, scope: 'catalogue' })],
			[`:schema ${hiddenKind}`, hidden],
			[`:schema ${absentKind}`, absent],
		] as const;
		const ownRequest = `${role}-request`;
		const foreignRequest = `${peer}-request`;
		const rowQuery = (id: string): Query => ({ scope: 'row', row: { kind: 'Request', key: [id], source_limit: 50 } });
		const firstRow = await ask(rowQuestion, rowQuery(ownRequest));
		assert.ok(firstRow.next);
		const nextRow = await ask(rowQuestion, { ...rowQuery(ownRequest), after: firstRow.next });
		assert.equal(nextRow.next, undefined);
		const cells = [firstRow, nextRow].flatMap(answer => rowDataset.parse(answer.dataset).rows);
		assert.equal(cells.length, 2);
		assert.ok(cells.every(cell => cell.c3 === 'request' && cell.c4 === JSON.stringify([ownRequest])));
		const cores = cells.find(cell => cell.c1 === 'cores');
		assert.ok(cores);
		assert.deepEqual([cores.c2, cores.c5, cores.c6, cores.c8, cores.c13],
			['request__cores', JSON.stringify([ownRequest, '2']), 'integer', '2', 'known']);
		const hiddenRow = await request(rowQuestion, rowQuery(foreignRequest));
		const absentRow = await request(rowQuestion, rowQuery('unused-request'));
		assert.equal(hiddenRow.status, 404);
		assert.equal(absentRow.status, 404);
		assert.deepEqual(await hiddenRow.json(), await absentRow.json());
		const rowCalls: Call[] = [
			{ tool: 'row', args: { pack, kind: 'Request', id: ownRequest } },
			{ tool: 'more', args: {} },
			{ tool: 'row', args: { pack, kind: 'Request', key: [foreignRequest] } },
			{ tool: 'row', args: { pack, kind: 'Request', key: ['unused-request'] } },
		];
		const allCalls = [...calls, ...catalogueCalls, ...rowCalls];
		const results = await run(await connect(t, role, store), allCalls);
		assert.equal(results[0].text, replFirst.join('\n'));
		assert.equal(results[1].text, replSecond.join('\n'));
		assert.equal(results[2].error, false);
		assert.match(results[2].text, /tenant_capacity_fits/);
		assert.equal(results[3].error, true);
		assert.equal(results[3].text, results[4].text);
		assert.equal(results[5].text, (await repl.exec(`:complete :row request ${role}`)).join('\n'));
		assert.equal(results[6].text, results[7].text);
		assert.equal(results[6].text, '');
		for (const [index, [line, answer]] of expectedCatalogue.entries()) {
			const expected = answerText(answer);
			assert.deepEqual(await repl.exec(line), expected);
			const got = results[calls.length + index];
			assert.equal(got.error, false);
			assert.equal(got.text, expected.join('\n'));
		}
		const catalogueEnd = calls.length + catalogueCalls.length;
		assert.equal(results[catalogueEnd - 2].text, results[catalogueEnd - 1].text);
		const rows = results.slice(catalogueEnd);
		assert.deepEqual(rows.map(result => result.error), [false, false, true, true]);
		const rowCommands = [`:row Request ${ownRequest}`, ':more', `:row Request ${foreignRequest}`, ':row Request unused-request'];
		for (const [index, line] of rowCommands.entries()) {
			assert.equal(rows[index].text, (await repl.exec(line)).join('\n'));
		}
		assert.match(rows[0].text, /cores/);
		assert.match(rows[1].text, /owner/);
		assert.equal(rows[2].text, rows[3].text);
		const newer = await openLocalGate(retained, role);
		const head = await newer(new Request(`http://rezono.local/${pack}/head`));
		assert.equal(head.status, 200);
		assert.equal((await head.json()).id, 'm-2');
		assert.deepEqual(compare(results, await run(await connect(t, role, retained), allCalls)), []);
	});
}
