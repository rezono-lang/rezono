import { createHash } from 'node:crypto';
import { mkdir, mkdtemp, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { openLocalGate } from '../src/local.ts';

type SnapSpec = { complete: boolean; full: boolean; keys: string[][] };
type ManifestSpec = { epoch: number; definition: string; snap: SnapSpec };

const pack = 'sample';
const schema = {
	pack: { id: pack, base: 'https://example.org/sample/' },
	kinds: [{ id: 'item', class: 'Item', world: 'closed' }],
	attributes: [],
	enums: [],
	questions: []
};

async function runCase(earlier: ManifestSpec, current: ManifestSpec): Promise<number> {
	const root = await mkdtemp(join(tmpdir(), 'gate-still-readable-'));
	try {
		const write = async (key: string, value: unknown) => {
			const path = join(root, key);
			await mkdir(dirname(path), { recursive: true });
			const bytes = JSON.stringify(value);
			await writeFile(path, bytes);
			return createHash('sha256').update(bytes).digest('hex');
		};
		const object = async (data: unknown) => {
			const sha256 = createHash('sha256').update(JSON.stringify(data)).digest('hex');
			const key = pack + '/objects/' + sha256 + '.json';
			await write(key, data);
			return { uri: 's3://test-store/' + key, sha256 };
		};
		const bundleKey = pack + '/bundles/definition.json';
		const bundleSha = await write(bundleKey, schema);
		for (const spec of [earlier, current]) {
			const id = 'm-' + spec.epoch;
			const data = await object(spec.snap.keys.map((key) => ({ key })));
			const manifest = {
				id,
				epoch: spec.epoch,
				access_semantics: 2,
				definition_sha256: spec.definition,
				knowledge_time: '2026-01-01T00:00:00Z',
				snapshots: [{
					relation: 'item',
					role: 'reader',
					complete: spec.snap.complete,
					full: spec.snap.full,
					format: 'json',
					...data
				}],
				compiled: [{
					file: 'bundle/schema-bundle.json',
					uri: 's3://test-store/' + bundleKey,
					sha256: bundleSha
				}]
			};
			const sha256 = await write(pack + '/manifests/' + id + '.json', manifest);
			const head = pack + '/heads/' + (10n ** 19n - 1n - BigInt(spec.epoch)).toString().padStart(19, '0') + '.json';
			await write(head, { format: 'rezono.head/1', manifest: id, epoch: spec.epoch, sha256 });
		}
		const gate = await openLocalGate(root, 'reader');
		const response = await gate(new Request('http://rezono.local/sample/m-' + earlier.epoch + '/snapshots/item'));
		return response.status;
	} finally {
		await rm(root, { recursive: true, force: true });
	}
}

const defA = 'a'.repeat(64);
const defB = 'b'.repeat(64);

const results = {
	downgraded_complete: await runCase(
		{ epoch: 1, definition: defA, snap: { complete: true, full: false, keys: [['secret']] } },
		{ epoch: 2, definition: defA, snap: { complete: false, full: true, keys: [['public']] } }
	),
	redefined_full: await runCase(
		{ epoch: 1, definition: defA, snap: { complete: false, full: false, keys: [['old-only']] } },
		{ epoch: 2, definition: defB, snap: { complete: false, full: true, keys: [['new-only']] } }
	),
	retained_full: await runCase(
		{ epoch: 1, definition: defA, snap: { complete: false, full: false, keys: [['a']] } },
		{ epoch: 2, definition: defA, snap: { complete: false, full: true, keys: [['b']] } }
	),
	lost_full: await runCase(
		{ epoch: 1, definition: defA, snap: { complete: false, full: true, keys: [['a']] } },
		{ epoch: 2, definition: defA, snap: { complete: false, full: false, keys: [['a']] } }
	)
};

process.stdout.write(JSON.stringify(results) + '\n');
