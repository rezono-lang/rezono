import assert from 'node:assert/strict';
import { test } from 'node:test';
import { local } from '../src/client.ts';
import { answerText } from '../src/explain.ts';
import { Recorder, replay } from '../src/record.ts';
import { Session } from '../src/session.ts';

const fixture = process.env.REZONO_REPL_SWEEP_STORE;
if (!fixture) throw new Error('REZONO_REPL_SWEEP_STORE must name the published sweep test store');

const connection = local(fixture);
const pin = { pack: 'minimal', manifest: 'm-3' };
const sweep = 'size_scale';
const tableRows = (lines: string[]) => lines.slice(1).map((line) => line.trim().split(/ +/));

test('the published sweep uses the same named question and replays the exact series for each role', async () => {
	for (const role of ['checker', 'partial']) {
		const session = new Session(connection, role, pin);
		const recorder = new Recorder(session);
		assert.deepEqual(await recorder.exec(':use minimal latest'), [`using minimal m-3 as ${role}`]);
		const expected = answerText(await session.named('sweep', { sweep }));
		const implicit = await recorder.exec(':sweep');
		assert.deepEqual(implicit, expected);
		assert.deepEqual(await recorder.exec(`:sweep ${sweep}`), expected);
		const rows = [
			['0', '0', 'green', 'v-size_scale-00-4', '-'],
			['1', '3', 'green', 'v-size_scale-01-4', '-'],
			['2', '6', 'red', '-', '-'],
			['3', '9', 'red', '-', '-']
		];
		assert.deepEqual(tableRows(implicit), role === 'checker' ? rows
			: rows.map(([index, value]) => [index, value, 'unavailable', '-', '-']));
		assert.equal((await replay(recorder.text(), new Session(connection, role, pin))).same, true);
	}
});

test('a sweep the role cannot see is indistinguishable from an absent sweep', async () => {
	const session = new Session(connection, 'other', pin);
	await session.use(pin.pack, pin.manifest);
	const hidden = await session.exec(`:sweep ${sweep}`);
	assert.deepEqual(hidden, ['error: not found (or outside your view)']);
	assert.deepEqual(await session.exec(':sweep'), hidden);
	assert.deepEqual(await session.exec(':sweep unused'), hidden);
});
