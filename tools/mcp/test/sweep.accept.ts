import assert from 'node:assert/strict';
import { test } from 'node:test';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { InMemoryTransport } from '@modelcontextprotocol/sdk/inMemory.js';
import { openLocalGate } from '../../../edge/gate/src/local.ts';
import { local } from '../../repl/src/client.ts';
import { answerText } from '../../repl/src/explain.ts';
import { Session, type Answer } from '../../repl/src/session.ts';
import { run, type Call } from '../src/replay.ts';
import { mcpServer } from '../src/server.ts';

const store = process.env.REZONO_REPL_SWEEP_STORE;
if (!store) throw new Error('REZONO_REPL_SWEEP_STORE must name the neutral published sweep fixture');

const pack = 'minimal';
const manifest = 'm-3';
const name = 'size_scale';
const pin = { pack, manifest };
const cases = [
	['checker', ['green', 'green', 'red', 'red']],
	['partial', ['unavailable', 'unavailable', 'unavailable', 'unavailable']],
	['other', undefined],
] as const;

for (const [role, statuses] of cases) {
	test(`${role} sees the same scoped published sweep through the gate, REPL and MCP`, async (t) => {
		const gate = await openLocalGate(store, role);
		const named = `http://rezono.local/${pack}/${manifest}/ask/sweep?sweep=`;
		const response = await gate(new Request(named + name));
		const absent = await gate(new Request(named + 'unused_sweep'));
		assert.equal(absent.status, 404);
		const listing = await gate(new Request(`http://rezono.local/${pack}/sweeps?m=${manifest}`));
		assert.equal(listing.status, statuses ? 200 : 404);
		let expected: string[] | undefined;
		if (statuses) {
			assert.equal(response.status, 200);
			const answer: Answer = await response.json();
			assert.equal(answer.format, 'rezono.answer/1');
			assert.equal(answer.manifest_id, manifest);
			assert.deepEqual(answer.series?.map(cell => cell.status), statuses);
			assert.deepEqual(answer.series?.map(cell => cell.value), ['0', '3', '6', '9']);
			if (role === 'partial') {
				assert.ok(answer.series?.every(cell => !cell.manifest && !cell.diagnosis && !cell.counts));
			}
			expected = answerText(answer);
		} else {
			assert.equal(response.status, 404);
			assert.deepEqual(await response.json(), await absent.json());
		}

		const connection = local(store);
		const repl = new Session(connection, role, pin);
		assert.deepEqual(await repl.exec(`:use ${pack} ${manifest}`), [`using ${pack} ${manifest} as ${role}`]);
		const server = mcpServer(new Session(connection, role, pin), role, { lockedPin: pin });
		const client = new Client({ name: 'sweep-acceptance', version: '0.1.0' });
		const [from, to] = InMemoryTransport.createLinkedPair();
		await server.connect(to);
		await client.connect(from);
		t.after(async () => {
			await client.close();
			await server.close();
		});
		const calls: Call[] = [
			{ tool: 'sweep', args: { pack } },
			{ tool: 'sweep', args: { pack, name } },
			{ tool: 'sweep', args: { pack, name: 'unused_sweep' } },
		];
		const results = await run(client, calls);
		assert.deepEqual(results.map(result => result.error), [!statuses, !statuses, true]);
		assert.equal(results[0].text, (await repl.exec(':sweep')).join('\n'));
		assert.equal(results[1].text, (await repl.exec(`:sweep ${name}`)).join('\n'));
		assert.equal(results[2].text, (await repl.exec(':sweep unused_sweep')).join('\n'));
		if (expected) {
			assert.equal(results[0].text, expected.join('\n'));
			assert.equal(results[1].text, expected.join('\n'));
		} else {
			assert.equal(results[0].text, results[2].text);
			assert.equal(results[1].text, results[2].text);
		}
	});
}
