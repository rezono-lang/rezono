import type { Answer, DifferenceEntry, RelationCount } from '../../../contracts/typescript/generated/explain.ts';
import type { Snapshot } from '../../../contracts/typescript/generated/manifest.ts';
import { canonicalJson } from '../../../viewer/src/lib/canon.ts';
import { ANSWER, AskError } from './ask.ts';
import { compareKey, compareText } from './pieces.ts';
import { StoreLimit } from './store.ts';
import type { PublishedVariant, SweepView } from './sweep.ts';

const EXPLAIN_INDEX_FORMAT = 'rezono.explain-index/1';
const PROOF_INDEX_FORMAT = 'rezono.proof-index/3';
const PROOF_PIECE_FORMAT = 'rezono.proof/1';
const SHA256 = /^[0-9a-f]{64}$/;
const SAFE = /^[A-Za-z0-9][A-Za-z0-9._-]*$/;
const S3_PREFIX = /^s3:\/\/[A-Za-z0-9._-]+\//;
const MAX_PIECE = 64 * 1024;
const MAX_FANOUT = 1024;
const MAX_LEVELS = 16;
const ROW_LIMIT = 25_000;
const INDEX_FIELDS = new Set(['format', 'pack', 'manifest', 'base_manifest', 'role', 'base', 'target', 'difference', 'proof']);
const DIFF_FIELDS = new Set(['format', 'piece', 'fanout', 'counts', 'trees']);

type Keyed = { key: string[] };
type RawDiffRow =
	| { key: string[]; change: 'added' | 'removed' }
	| { key: string[]; change: 'changed'; was: string[] };

export interface DifferenceCursor {
	distance: number;
	relation: string;
	key?: string[];
}

export interface DifferencePage {
	counts: RelationCount[];
	entries: DifferenceEntry[];
	next?: string;
}

function record(value: unknown): value is Record<string, unknown> {
	return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function keyParts(value: unknown): value is string[] {
	return Array.isArray(value) && value.every((part) => typeof part === 'string');
}

function safe(name: string): boolean {
	return SAFE.test(name) && !name.includes('..');
}

function safePath(path: string): boolean {
	const parts = path.split('/');
	return parts.length > 0 && parts.every(safe);
}

function fault(): never {
	throw new AskError(500, 'invalid publication');
}

function verifySnapshotList(list: unknown, expected: ReadonlyMap<string, Snapshot>): void {
	if (!Array.isArray(list) || list.length !== expected.size) fault();
	let prev: string | undefined;
	for (const entry of list) {
		if (!record(entry) || Object.keys(entry).length !== 2) fault();
		if (typeof entry.relation !== 'string' || typeof entry.sha256 !== 'string' || !SHA256.test(entry.sha256)) fault();
		if (prev !== undefined && compareText(prev, entry.relation) >= 0) fault();
		const snap = expected.get(entry.relation);
		if (!snap || snap.sha256 !== entry.sha256) fault();
		prev = entry.relation;
	}
}

async function loadVariantSnapshotRows(view: SweepView, snap: Snapshot): Promise<Keyed[]> {
	if (typeof snap.uri !== 'string' || typeof snap.sha256 !== 'string' || !SHA256.test(snap.sha256)) fault();
	const raw = await view.object({ uri: snap.uri, sha256: snap.sha256 }, 'objects');
	if (!Array.isArray(raw)) fault();
	if (raw.length > ROW_LIMIT) throw new StoreLimit();
	if (raw.some((row) => !record(row) || !keyParts(row.key) || !row.key.length)) fault();
	const sorted = (raw as Keyed[]).slice().sort((a, b) => compareKey(a.key, b.key));
	if (sorted.some((row, i) => i > 0 && compareKey(sorted[i - 1].key, row.key) === 0)) fault();
	return sorted;
}

function expectedDifference(baseRows: readonly Keyed[], targetRows: readonly Keyed[]): RawDiffRow[] {
	const before = new Map<string, string[]>();
	const after = new Map<string, string[]>();
	const widthBefore = new Map<string, number>();
	const widthAfter = new Map<string, number>();
	for (const { key } of baseRows) {
		before.set(canonicalJson(key), key);
		if (key.length > 1) {
			const prefix = canonicalJson(key.slice(0, -1));
			widthBefore.set(prefix, (widthBefore.get(prefix) ?? 0) + 1);
		}
	}
	for (const { key } of targetRows) {
		after.set(canonicalJson(key), key);
		if (key.length > 1) {
			const prefix = canonicalJson(key.slice(0, -1));
			widthAfter.set(prefix, (widthAfter.get(prefix) ?? 0) + 1);
		}
	}
	const wasByPrefix = new Map<string, string[]>();
	for (const [id, key] of before) {
		if (after.has(id) || key.length <= 1) continue;
		const prefix = canonicalJson(key.slice(0, -1));
		if (widthBefore.get(prefix) === 1 && widthAfter.get(prefix) === 1) {
			wasByPrefix.set(prefix, key);
		}
	}
	const paired = new Set<string>();
	const out: RawDiffRow[] = [];
	for (const [id, key] of after) {
		if (before.has(id)) continue;
		if (key.length > 1) {
			const prefix = canonicalJson(key.slice(0, -1));
			const old = wasByPrefix.get(prefix);
			if (old) {
				paired.add(canonicalJson(old));
				out.push({ key, change: 'changed', was: old });
				continue;
			}
		}
		out.push({ key, change: 'added' });
	}
	for (const [id, key] of before) {
		if (after.has(id) || paired.has(id)) continue;
		out.push({ key, change: 'removed' });
	}
	out.sort((a, b) => compareKey(a.key, b.key));
	return out;
}

function parseDiffRow(raw: unknown): RawDiffRow {
	if (!record(raw) || !keyParts(raw.key) || !raw.key.length) fault();
	if (raw.change === 'added' || raw.change === 'removed') {
		if (Object.keys(raw).length !== 2) fault();
		return { key: raw.key, change: raw.change };
	}
	if (raw.change === 'changed') {
		if (Object.keys(raw).length !== 3 || !keyParts(raw.was) || raw.was.length !== raw.key.length || raw.key.length < 2) fault();
		const samePrefix = raw.key.slice(0, -1).every((part, i) => part === (raw.was as string[])[i]);
		if (!samePrefix || raw.key[raw.key.length - 1] === raw.was[raw.was.length - 1]) fault();
		return { key: raw.key, change: 'changed', was: raw.was };
	}
	fault();
}

function sameDiffRows(actual: readonly RawDiffRow[], expected: readonly RawDiffRow[]): boolean {
	if (actual.length !== expected.length) return false;
	for (let i = 0; i < actual.length; i++) {
		const a = actual[i], b = expected[i];
		if (a.change !== b.change || compareKey(a.key, b.key) !== 0) return false;
		if (a.change === 'changed' && b.change === 'changed' && compareKey(a.was, b.was) !== 0) return false;
	}
	return true;
}

async function readDifferenceTree(
	view: SweepView,
	at: string,
	relation: string,
	treeRef: unknown,
	fanout: number
): Promise<RawDiffRow[]> {
	if (!record(treeRef) || Object.keys(treeRef).length !== 3) fault();
	const { uri, sha256, levels } = treeRef;
	if (typeof uri !== 'string' || !S3_PREFIX.test(uri) || typeof sha256 !== 'string' || !SHA256.test(sha256)
		|| typeof levels !== 'number' || !Number.isSafeInteger(levels) || levels < 1 || levels > MAX_LEVELS) {
		fault();
	}
	const rootKey = uri.replace(S3_PREFIX, '');
	const relPrefix = at + '/difference/' + relation + '/';
	if (!rootKey.startsWith(relPrefix) || !rootKey.endsWith('.json') || !safePath(rootKey)) fault();

	const out: RawDiffRow[] = [];
	const childPrefix = 'difference/' + relation + '/';

	async function walk(key: string, expectedSha: string, level: number, boundFirst?: string[], boundLast?: string[]): Promise<void> {
		const piece = await view.read(key, expectedSha, false);
		if (!record(piece) || Object.keys(piece).length !== 5
			|| piece.format !== PROOF_PIECE_FORMAT || piece.tree !== 'difference'
			|| piece.relation !== relation || piece.level !== level) {
			fault();
		}
		if (level === 0) {
			if (!Array.isArray(piece.rows) || !piece.rows.length) fault();
			let prev: string[] | undefined;
			const first = parseDiffRow(piece.rows[0]);
			if (boundFirst && compareKey(first.key, boundFirst) !== 0) fault();
			for (const item of piece.rows) {
				const row = parseDiffRow(item);
				if (prev && compareKey(prev, row.key) >= 0) fault();
				prev = row.key;
				if (out.length >= ROW_LIMIT) throw new StoreLimit();
				out.push(row);
			}
			if (boundLast && (!prev || compareKey(prev, boundLast) !== 0)) fault();
			return;
		}
		if (!Array.isArray(piece.children) || !piece.children.length || piece.children.length > fanout) fault();
		let prevLast: string[] | undefined;
		for (let i = 0; i < piece.children.length; i++) {
			const child = piece.children[i];
			if (!record(child) || Object.keys(child).length !== 4
				|| !keyParts(child.first) || !child.first.length
				|| !keyParts(child.last) || !child.last.length
				|| compareKey(child.first, child.last) > 0
				|| typeof child.file !== 'string' || !child.file.startsWith(childPrefix)
				|| !child.file.endsWith('.json') || !safePath(child.file)
				|| typeof child.sha256 !== 'string' || !SHA256.test(child.sha256)) {
				fault();
			}
			if (i === 0 && boundFirst && compareKey(child.first, boundFirst) !== 0) fault();
			if (prevLast && compareKey(prevLast, child.first) >= 0) fault();
			prevLast = child.last;
			await walk(at + '/' + child.file, child.sha256, level - 1, child.first, child.last);
		}
		if (boundLast && (!prevLast || compareKey(prevLast, boundLast) !== 0)) fault();
	}

	await walk(rootKey, sha256, levels - 1);
	return out;
}

export async function readPublishedVariantDifference(
	view: SweepView,
	pack: string,
	role: string,
	variant: PublishedVariant,
	page: { limit: number; after?: DifferenceCursor }
): Promise<DifferencePage | undefined> {
	const at = pack + '/' + variant.id + '/' + role + '/explain';
	const index = await view.read(at + '/index.json', undefined, true);
	if (index === undefined) return undefined;
	if (!record(index) || !Object.keys(index).every((field) => INDEX_FIELDS.has(field))
		|| index.format !== EXPLAIN_INDEX_FORMAT || index.pack !== pack
		|| index.manifest !== variant.id || index.base_manifest !== view.manifest.id
		|| index.role !== role) {
		fault();
	}
	verifySnapshotList(index.base, view.snaps);
	verifySnapshotList(index.target, variant.snapshots);

	const diff = index.difference;
	if (!record(diff) || !Object.keys(diff).every((field) => DIFF_FIELDS.has(field))
		|| diff.format !== PROOF_INDEX_FORMAT
		|| typeof diff.piece !== 'number' || !Number.isSafeInteger(diff.piece) || diff.piece < 1 || diff.piece > MAX_PIECE
		|| typeof diff.fanout !== 'number' || !Number.isSafeInteger(diff.fanout) || diff.fanout < 2 || diff.fanout > MAX_FANOUT
		|| !record(diff.counts) || !record(diff.trees)) {
		fault();
	}

	const countRels = Object.keys(diff.counts).sort(compareText);
	const treeRels = Object.keys(diff.trees).sort(compareText);
	if (countRels.length !== treeRels.length || countRels.some((rel, i) => rel !== treeRels[i])) fault();

	const allRels = [...new Set([...view.snaps.keys(), ...variant.snapshots.keys()])].sort(compareText);
	const allRelSet = new Set(allRels);
	if (countRels.some((rel) => !allRelSet.has(rel))) fault();

	const counts: RelationCount[] = [];
	const allEntries: Array<{ relation: string; row: RawDiffRow }> = [];

	for (const rel of allRels) {
		const baseSnap = view.snaps.get(rel);
		const targetSnap = variant.snapshots.get(rel);
		const hasCount = Object.hasOwn(diff.counts, rel);
		if (baseSnap && targetSnap && baseSnap.sha256 === targetSnap.sha256) {
			if (hasCount) fault();
			continue;
		}
		const baseRows = baseSnap ? await view.rows(rel) : [];
		const targetRows = targetSnap ? await loadVariantSnapshotRows(view, targetSnap) : [];
		const expected = expectedDifference(baseRows, targetRows);
		if (!expected.length) {
			if (hasCount) fault();
			continue;
		}
		if (!hasCount) fault();
		const rawCount = diff.counts[rel];
		if (!record(rawCount) || Object.keys(rawCount).length !== 3) fault();
		const added = expected.filter((entry) => entry.change === 'added').length;
		const removed = expected.filter((entry) => entry.change === 'removed').length;
		const changed = expected.filter((entry) => entry.change === 'changed').length;
		if (rawCount.added !== added || rawCount.removed !== removed || rawCount.changed !== changed) fault();

		const actual = await readDifferenceTree(view, at, rel, diff.trees[rel], diff.fanout);
		if (!sameDiffRows(actual, expected)) fault();
		counts.push({ relation: rel, added, removed, changed });
		for (const row of actual) {
			if (allEntries.length >= ROW_LIMIT) throw new StoreLimit();
			allEntries.push({ relation: rel, row });
		}
	}

	const filtered = !page.after ? allEntries
		: page.after.distance > 0 ? []
		: allEntries.filter(({ relation, row }) => {
			const relCmp = compareText(relation, page.after!.relation);
			return relCmp > 0 || (relCmp === 0 && compareKey(row.key, page.after!.key!) > 0);
		});
	const slice = filtered.slice(0, page.limit);
	const entries: DifferenceEntry[] = slice.map(({ relation, row }) => ({
		relation,
		key: canonicalJson(row.key),
		change: row.change,
		...(row.change === 'changed' ? { was: canonicalJson(row.was) } : {})
	}));
	const next = filtered.length > slice.length
		? '0,' + entries[entries.length - 1].relation + ',' + entries[entries.length - 1].key
		: undefined;
	return { counts, entries, ...(next !== undefined ? { next } : {}) };
}

export function scenarioAnswer(term: string, manifest: string, variantId: string, page: DifferencePage): Answer {
	return {
		format: ANSWER,
		question: term,
		manifest_id: manifest,
		delta: { kind: 'variant', id: variantId, manifest: variantId },
		nodes: page.entries.map(({ relation, key }) => ({ relation, key, distance: 0 })),
		difference: {
			counts: page.counts,
			entries: page.entries
		},
		...(page.next !== undefined ? { next: page.next } : {})
	};
}
