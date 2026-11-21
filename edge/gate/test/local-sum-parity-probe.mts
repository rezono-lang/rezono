import { createHash } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import { join } from 'node:path';
import type { Witness } from '../../../contracts/typescript/generated/proof.ts';
import { ask, memoryGraph, questionOf, type Edge } from '../src/ask.ts';
import { openLocalGate } from '../src/local.ts';

type TreeRoot = { uri: string; sha256: string; levels: number };
type ViewIndex = {
	proof: {
		trees: {
			witness: Record<string, TreeRoot>;
			back: Record<string, TreeRoot>;
		};
	};
};

function keyFromUri(uri: string): string {
	return uri.replace(/^s3:\/\/[^/]+\//, '');
}

async function readCheckedJson<T>(root: string, key: string, expectedSha256?: string): Promise<T> {
	const bytes = await readFile(join(root, key));
	if (expectedSha256 !== undefined) {
		const actual = createHash('sha256').update(bytes).digest('hex');
		if (actual !== expectedSha256) {
			throw new Error(`sha256 mismatch for ${key}: expected ${expectedSha256}, got ${actual}`);
		}
	}
	return JSON.parse(bytes.toString('utf-8')) as T;
}

async function readTreeRows<T>(root: string, basePrefix: string, ref: TreeRoot): Promise<T[]> {
	const visit = async (key: string, sha256: string): Promise<T[]> => {
		const piece = await readCheckedJson<{
			level: number;
			rows?: T[];
			children?: { file: string; sha256: string }[];
		}>(root, key, sha256);
		if (piece.level === 0) {
			return piece.rows ?? [];
		}
		const out: T[] = [];
		for (const child of piece.children ?? []) {
			out.push(...await visit(`${basePrefix}/${child.file}`, child.sha256));
		}
		return out;
	};
	return visit(keyFromUri(ref.uri), ref.sha256);
}

async function main() {
	const [storeRoot, pack, manifestId, role, questionTerm, relation, keyJson] = process.argv.slice(2);
	if (!storeRoot || !pack || !manifestId || !role || !questionTerm || !relation || !keyJson) {
		throw new Error('usage: <storeRoot> <pack> <manifestId> <role> <questionTerm> <relation> <keyJson>');
	}

	// 1. Walk the role's published proof steps directly from its verified view index & proof trees.
	const manifest = await readCheckedJson<{
		compiled: { file: string; uri: string; sha256: string }[];
	}>(storeRoot, `${pack}/manifests/${manifestId}.json`);
	const schemaRef = manifest.compiled.find((c) => c.file === 'bundle/schema-bundle.json');
	if (!schemaRef) throw new Error('missing schema-bundle.json in manifest');
	const bundle = await readCheckedJson<{ questions?: unknown[] }>(storeRoot, keyFromUri(schemaRef.uri), schemaRef.sha256);
	const question = questionOf(bundle as Parameters<typeof questionOf>[0], questionTerm);
	if (!question) throw new Error(`question ${questionTerm} not found in schema bundle`);

	const viewBase = `${pack}/${manifestId}/${role}/views`;
	const index = await readCheckedJson<ViewIndex>(storeRoot, `${viewBase}/index.json`);
	const witnesses: Witness[] = [];
	for (const ref of Object.values(index.proof.trees.witness)) {
		witnesses.push(...await readTreeRows<Witness>(storeRoot, viewBase, ref));
	}
	const edges: Edge[] = [];
	for (const [cRel, ref] of Object.entries(index.proof.trees.back)) {
		const rows = await readTreeRows<[string, string, number, string, string, string?]>(storeRoot, viewBase, ref);
		for (const [cKey, how, position, pRel, pKey, value] of rows) {
			edges.push({
				c: { relation: cRel, key: cKey },
				p: { relation: pRel, key: pKey },
				how,
				position,
				...(value !== undefined ? { value } : {})
			});
		}
	}
	const published = await ask(
		memoryGraph(witnesses, edges),
		question,
		manifestId,
		{ relation, key: keyJson },
		{ limit: question.limit }
	);

	// 2. Ask the exact same publication and role via the local gate.
	const localGate = await openLocalGate(storeRoot, role);
	const params = new URLSearchParams({ relation, key: keyJson });
	const response = await localGate(new Request(`http://rezono.local/${pack}/${manifestId}/ask/${questionTerm}?${params}`));
	const local = {
		status: response.status,
		body: await response.json()
	};

	process.stdout.write(JSON.stringify({ published, local }) + '\n');
}

await main();
