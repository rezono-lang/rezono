import type { BoundSweep, BoundSweepList, BoundSweepCell, Answer, SeriesCell } from '../../../contracts/typescript/generated/explain.ts';
import type { ArchivedFile, Manifest, Snapshot } from '../../../contracts/typescript/generated/manifest.ts';
import type { Bundle } from '../../../contracts/typescript/generated/bundle.ts';
import type { RowRef } from '../../../contracts/typescript/generated/proof.ts';
import { canonicalJson } from '../../../viewer/src/lib/canon.ts';
import { ANSWER, AskError } from './ask.ts';
import { roleCatalogue } from './catalogue.ts';
import type { Read } from './expr.ts';
import { compareKey } from './pieces.ts';
import { StoreLimit } from './store.ts';

const NAME = /^[a-z][a-z0-9]*(_[a-z0-9]+)*$/;
const SHA256 = /^[0-9a-f]{64}$/;
const DECIMAL = /^(0|-?[1-9][0-9]*)$/;
const SAFE = /^[A-Za-z0-9][A-Za-z0-9._-]*$/;
const ROW_LIMIT = 25_000;
const TURNS_FORMAT = 'rezono.turns/1';

export type TurnStatus = 'turns' | 'same' | 'unknown';
export type TurnCause = 'rule' | 'version' | 'definition' | 'path' | 'count'
	| 'contributors' | 'state' | 'presence' | 'value' | 'cap';
export type SweepSeriesCell = SeriesCell & { row?: RowRef; turn?: TurnStatus; causes?: TurnCause[] };
export interface SweepStart {
	relation: string;
	key: string[];
}
export interface SweepCellLocation {
	kind: string;
	table: string;
	key: string;
}

const TURN_CAUSES = new Set<TurnCause>([
	'rule', 'version', 'definition', 'path', 'count',
	'contributors', 'state', 'presence', 'value', 'cap'
]);

type ObjectRef = Pick<ArchivedFile, 'uri' | 'sha256'>;
type Keyed = { key: string[] };

interface Grid {
	name: string;
	kind: string;
	key: string;
	slot: string;
	min: bigint;
	max: bigint;
	step: bigint;
	count: number;
}

export interface SweepView {
	manifest: Manifest;
	bundle: Bundle;
	snaps: ReadonlyMap<string, Snapshot>;
	compiled(file: string): ArchivedFile | undefined;
	object(ref: ObjectRef, category: 'objects' | 'bundles', decode?: (text: string) => unknown): Promise<unknown>;
	read(key: string, sha?: string, optional?: boolean): Promise<unknown>;
	rows(relation: string): Promise<Keyed[]>;
	range: Read;
}

export interface PublishedVariant {
	id: string;
	sweep: string;
	index: number;
	value: string;
	sha256: string;
	snapshots: Map<string, Snapshot>;
}

type View = SweepView;

interface Point {
	cell: BoundSweepCell;
	diagnosis?: string;
	manifestSha?: string;
	manifestBody?: Record<string, unknown>;
}

function record(value: unknown): value is Record<string, unknown> {
	return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function keyParts(value: unknown): value is string[] {
	return Array.isArray(value) && value.every((part) => typeof part === 'string');
}

function compareCodePoints(a: string, b: string): number {
	let i = 0, j = 0;
	while (i < a.length && j < b.length) {
		const ca = a.codePointAt(i)!;
		const cb = b.codePointAt(j)!;
		if (ca !== cb) return ca < cb ? -1 : 1;
		i += ca > 0xffff ? 2 : 1;
		j += cb > 0xffff ? 2 : 1;
	}
	return i < a.length ? 1 : j < b.length ? -1 : 0;
}

function sameTuple(a: readonly string[], b: readonly string[]): boolean {
	return a.length === b.length && a.every((part, i) => part === b[i]);
}

const MAX_SWEEPS = 4;

function parseGrid(grid: unknown): Grid | undefined {
	if (!record(grid)) return undefined;
	const { name, kind, key, slot, min, max, step, count } = grid;
	if (typeof name !== 'string' || !NAME.test(name)
		|| typeof kind !== 'string' || typeof key !== 'string' || typeof slot !== 'string'
		|| typeof min !== 'bigint' || typeof max !== 'bigint' || typeof step !== 'bigint' || typeof count !== 'bigint'
		|| step <= 0n || max < min || count > 64n || (max - min) / step + 1n !== count) return undefined;
	return { name, kind, key, slot, min, max, step, count: Number(count) };
}

function publishedGrids(text: string): Grid[] | undefined {
	const document: unknown = JSON.parse(text, (_key, value: unknown, context?: {source?: string}) => {
		if (typeof value !== 'number') return value;
		const decimal = context?.source;
		if (decimal !== undefined && DECIMAL.test(decimal)) return BigInt(decimal);
		if (decimal === undefined && Number.isSafeInteger(value)) return BigInt(value);
		throw new TypeError('sweep grid needs exact whole numbers');
	});
	if (!record(document) || document.format !== 'rezono.sweeps/1' || !Array.isArray(document.sweeps)
		|| document.sweeps.length < 1 || document.sweeps.length > MAX_SWEEPS) return undefined;
	const grids: Grid[] = [];
	const seen = new Set<string>();
	for (const raw of document.sweeps) {
		const grid = parseGrid(raw);
		if (!grid || seen.has(grid.name)) return undefined;
		seen.add(grid.name);
		grids.push(grid);
	}
	return grids;
}

function roleList(value: unknown): value is string[] {
	return Array.isArray(value) && value.every((entry) => typeof entry === 'string'
		&& SAFE.test(entry) && !entry.includes('..')) && new Set(value).size === value.length;
}

type Check = { name: string; status: 'green' | 'warning' | 'red' };

function checkedStatuses(checks: unknown): checks is Check[] {
	return Array.isArray(checks) && checks.every((check: unknown) => record(check)
		&& typeof check.name === 'string' && typeof check.status === 'string' && ['green', 'warning', 'red'].includes(check.status));
}

async function readableCell(view: View, grid: Grid): Promise<string | undefined> {
	const scoped = roleCatalogue(view.bundle, [...view.snaps.values()]);
	const byId = new Map(scoped.kinds.map((kind) => [kind.id, kind]));
	const seen = new Set<string>();
	let kind = byId.get(grid.kind);
	while (kind && !seen.has(kind.id)) {
		seen.add(kind.id);
		const slot = scoped.attributes.find((entry) => entry.kind === kind!.id && entry.name === grid.slot);
		if (slot) {
			if (slot.multivalued || slot.type !== 'integer' || !view.snaps.has(grid.kind) || !view.snaps.has(slot.table)) return undefined;
			const member = await view.range(grid.kind, { prefix: [grid.key], limit: 2 });
			if (member.rows.length !== 1 || !record(member.rows[0]) || !Array.isArray(member.rows[0].key)
				|| member.rows[0].key.length !== 1) return undefined;
			const value = await view.range(slot.table, { prefix: [grid.key], limit: 2 });
			return value.rows.length === 1 && record(value.rows[0]) && Array.isArray(value.rows[0].key)
				&& value.rows[0].key.length === 2 ? slot.table : undefined;
		}
		kind = kind.parent ? byId.get(kind.parent) : undefined;
	}
	return undefined;
}

export function completeScope(view: View): boolean {
	return [...view.snaps.values()].every((entry) => entry.complete || entry.full)
		&& (view.manifest.snapshots ?? []).every((entry) => view.snaps.has(entry.relation));
}

async function publishedPoint(view: View, pack: string, role: string, grid: Grid, index: number, value: string): Promise<Point> {
	const epoch = view.manifest.epoch + 1;
	const id = 'v-' + grid.name + '-' + String(index).padStart(2, '0') + '-' + epoch;
	const fallback: Point = { cell: { index, value, status: 'not_computed' } };
	if (!Number.isSafeInteger(epoch)) return fallback;

	async function entry(category: 'manifests' | 'diagnoses'):
		Promise<{checks: Check[]; status: Check['status']; sha256: string; body: Record<string, unknown>} | undefined> {
		try {
			const pointer = await view.read(pack + '/epochs/' + epoch + '/' + category + '/' + id + '.json', undefined, true);
			if (!record(pointer) || pointer.format !== 'rezono.pointer/1' || pointer.id !== id
				|| typeof pointer.sha256 !== 'string' || !SHA256.test(pointer.sha256)) return undefined;
			const body = await view.read(pack + '/' + category + '/' + id + '.json', pointer.sha256);
			if (!record(body) || body.id !== id || body.epoch !== epoch || !record(body.variant)) return undefined;
			const { readers, status_readers } = body.variant;
			if (body.variant.sweep !== grid.name || body.variant.index !== index || body.variant.value !== value
				|| !roleList(readers) || !roleList(status_readers) || !status_readers.every((entry) => readers.includes(entry))
				|| !readers.includes(role) || !status_readers.includes(role) || !checkedStatuses(body.checks)) return undefined;
			const base = category === 'manifests' ? body.base_manifest : body.last_good_manifest;
			const red = body.checks.some((check) => check.status === 'red');
			if (base !== view.manifest.id || (category === 'manifests' && (red || body.proposal || body.access_semantics !== 2))
				|| (category === 'diagnoses' && !red)) return undefined;
			if (category === 'manifests' && (!Array.isArray(body.snapshots)
				|| !body.snapshots.some((entry: unknown) => record(entry) && entry.role === role && entry.relation === grid.kind)))
				return undefined;
			const checks = body.checks.map(({ name, status }) => ({ name, status }));
			return {
				checks,
				status: red ? 'red' : checks.some((check) => check.status === 'warning') ? 'warning' : 'green',
				sha256: pointer.sha256,
				body
			};
		} catch (error) {
			if (error instanceof StoreLimit) throw error;
			return undefined;
		}
	}

	const green = await entry('manifests');
	const red = await entry('diagnoses');
	if (green && red) return fallback;
	if (green) return {
		cell: { index, value, status: green.status, checks: green.checks, manifest: id },
		manifestSha: green.sha256,
		manifestBody: green.body
	};
	if (red) return { cell: { index, value, status: 'red', checks: red.checks }, diagnosis: id };
	return fallback;
}

async function variantRows(view: View, body: Record<string, unknown>, role: string, relation: string): Promise<Keyed[] | undefined> {
	if (!Array.isArray(body.snapshots)) return undefined;
	const matching = body.snapshots.filter((entry: unknown) =>
		record(entry) && entry.role === role && entry.relation === relation);
	if (matching.length !== 1) return undefined;
	const snap = matching[0];
	if (!record(snap) || snap.format !== 'json' || typeof snap.uri !== 'string'
		|| typeof snap.sha256 !== 'string' || !SHA256.test(snap.sha256)
		|| typeof snap.complete !== 'boolean'
		|| (snap.full !== undefined && typeof snap.full !== 'boolean')
		|| (!snap.complete && !snap.full)) return undefined;
	try {
		const raw = await view.object({ uri: snap.uri, sha256: snap.sha256 }, 'objects');
		if (!Array.isArray(raw)) return undefined;
		if (raw.length > ROW_LIMIT) throw new StoreLimit();
		if (raw.some((row) => !record(row) || !keyParts(row.key) || !row.key.length)) return undefined;
		const sorted = (raw as Keyed[]).slice().sort((a, b) => compareKey(a.key, b.key));
		if (sorted.some((row, i) => i > 0 && compareKey(sorted[i - 1].key, row.key) === 0)) return undefined;
		return sorted;
	} catch (error) {
		if (error instanceof StoreLimit) throw error;
		return undefined;
	}
}

type PairMode =
	| { kind: 'calc' }
	| { kind: 'functional'; keyArity: number }
	| { kind: 'default' };

type PairResult =
	| { kind: 'paired'; key: string[] }
	| { kind: 'absent' }
	| { kind: 'ambiguous' };

function functionalKeyArity(rulesDoc: unknown, relation: string): number | 'invalid' | undefined {
	if (!record(rulesDoc) || !Array.isArray(rulesDoc.relations)) return 'invalid';
	if (rulesDoc.format !== 'rezono.rules/1' && rulesDoc.format !== 'rezono.rules/2') return 'invalid';
	if (rulesDoc.format !== 'rezono.rules/2') return undefined;
	let matched: number | undefined;
	let seen = false;
	for (const rel of rulesDoc.relations) {
		if (!record(rel) || typeof rel.name !== 'string') return 'invalid';
		if (rel.name !== relation) continue;
		if (seen) return 'invalid';
		seen = true;
		if (rel.role === 'functional') {
			if (!Array.isArray(rel.key) || rel.key.length < 1
				|| !rel.key.every((col) => record(col) && typeof col.name === 'string')) return 'invalid';
			matched = rel.key.length;
		}
	}
	return matched;
}

function pairRow(
	mainRows: readonly Keyed[],
	stopRows: readonly Keyed[],
	startKey: readonly string[],
	mode: PairMode
): PairResult {
	if (mode.kind === 'calc' || mode.kind === 'functional') {
		const prefixLength = mode.kind === 'calc' ? 1 : mode.keyArity;
		const expectedLength = mode.kind === 'calc' ? 4 : mode.keyArity + 3;
		if (prefixLength < 1 || startKey.length !== expectedLength) return { kind: 'ambiguous' };
		const samePrefix = (key: readonly string[]) =>
			key.length === expectedLength && key.slice(0, prefixLength).every((part, i) => part === startKey[i]);
		const mainCount = mainRows.filter((row) => samePrefix(row.key)).length;
		if (mainCount !== 1) return { kind: 'ambiguous' };
		const stopMatches = stopRows.filter((row) => samePrefix(row.key));
		if (stopMatches.length === 0) return { kind: 'absent' };
		if (stopMatches.length > 1) return { kind: 'ambiguous' };
		return { kind: 'paired', key: stopMatches[0].key };
	}
	if (startKey.length < 1) return { kind: 'ambiguous' };
	const exact = stopRows.find((row) => sameTuple(row.key, startKey));
	if (exact) return { kind: 'paired', key: exact.key };
	if (startKey.length === 1) return { kind: 'absent' };
	const prefix = startKey.slice(0, -1);
	const samePrefix = (key: readonly string[]) =>
		key.length === startKey.length && prefix.every((part, i) => key[i] === part);
	const stopMatches = stopRows.filter((row) => samePrefix(row.key));
	if (stopMatches.length === 0) return { kind: 'absent' };
	if (stopMatches.length > 1) return { kind: 'ambiguous' };
	const mainCount = mainRows.filter((row) => samePrefix(row.key)).length;
	if (mainCount !== 1) return { kind: 'ambiguous' };
	return { kind: 'paired', key: stopMatches[0].key };
}

async function readTurns(
	view: View,
	pack: string,
	role: string,
	grid: Grid,
	before: { index: number; manifest: string; sha256: string },
	after: { index: number; manifest: string; sha256: string }
): Promise<Map<string, TurnCause[]> | undefined> {
	const path = pack + '/' + after.manifest + '/' + role + '/turns.json';
	let doc: unknown;
	try {
		doc = await view.read(path, undefined, true);
	} catch (error) {
		if (error instanceof StoreLimit) throw error;
		return undefined;
	}
	if (!record(doc) || Object.keys(doc).length !== 8) return undefined;
	if (doc.format !== TURNS_FORMAT || doc.pack !== pack || doc.role !== role
		|| doc.sweep !== grid.name || doc.base_manifest !== view.manifest.id) return undefined;
	if (!record(doc.before) || Object.keys(doc.before).length !== 3
		|| doc.before.index !== before.index || doc.before.manifest !== before.manifest
		|| doc.before.sha256 !== before.sha256) return undefined;
	if (!record(doc.after) || Object.keys(doc.after).length !== 3
		|| doc.after.index !== after.index || doc.after.manifest !== after.manifest
		|| doc.after.sha256 !== after.sha256) return undefined;
	if (!Array.isArray(doc.turns)) return undefined;
	const map = new Map<string, TurnCause[]>();
	let prevRel = '';
	let prevKey = '';
	let hasPrev = false;
	for (const entry of doc.turns) {
		if (!record(entry) || Object.keys(entry).length !== 3) return undefined;
		if (typeof entry.relation !== 'string' || !entry.relation.length || !view.snaps.has(entry.relation)
			|| typeof entry.key !== 'string' || !Array.isArray(entry.causes) || !entry.causes.length) return undefined;
		let parsedKey: unknown;
		try { parsedKey = JSON.parse(entry.key); } catch { return undefined; }
		if (!keyParts(parsedKey) || !parsedKey.length || canonicalJson(parsedKey) !== entry.key) return undefined;
		if (hasPrev) {
			const relCmp = compareCodePoints(prevRel, entry.relation);
			if (relCmp > 0 || (relCmp === 0 && compareCodePoints(prevKey, entry.key) >= 0)) return undefined;
		}
		const causes: TurnCause[] = [];
		for (let i = 0; i < entry.causes.length; i++) {
			const cause = entry.causes[i];
			if (typeof cause !== 'string' || !TURN_CAUSES.has(cause as TurnCause)) return undefined;
			if (i > 0 && cause <= causes[i - 1]) return undefined;
			causes.push(cause as TurnCause);
		}
		map.set(entry.relation + '\u0000' + entry.key, causes);
		prevRel = entry.relation;
		prevKey = entry.key;
		hasPrev = true;
	}
	return map;
}

async function loadGrids(view: View): Promise<Grid[] | undefined> {
	const ref = view.compiled('ir/sweeps.json');
	if (!ref) return undefined;
	try { return await view.object(ref, 'bundles', publishedGrids) as Grid[] | undefined; }
	catch (error) {
		if (error instanceof StoreLimit) throw error;
		return undefined;
	}
}

async function boundPoints(view: View, pack: string, role: string, grid: Grid, full: boolean): Promise<Point[]> {
	const points: Point[] = [];
	for (let index = 0; index < grid.count; index++) {
		const value = (grid.min + BigInt(index) * grid.step).toString();
		points.push(full ? await publishedPoint(view, pack, role, grid, index, value)
			: { cell: { index, value, status: 'unavailable' } });
	}
	return points;
}

export async function readPublishedSweeps(view: View, pack: string, role: string):
	Promise<{ listing: BoundSweepList; cells: SweepCellLocation[] } | undefined> {
	const grids = await loadGrids(view);
	if (!grids) return undefined;
	const full = completeScope(view);
	const sweeps: BoundSweep[] = [];
	const cells: SweepCellLocation[] = [];
	for (const grid of grids) {
		const table = await readableCell(view, grid);
		if (!table) continue;
		const points = await boundPoints(view, pack, role, grid, full);
		sweeps.push({
			name: grid.name,
			cell: { kind: grid.kind, id: grid.key, slot: grid.slot },
			min: String(grid.min),
			max: String(grid.max),
			step: String(grid.step),
			cells: points.map(({ cell }) => cell)
		});
		cells.push({ kind: grid.kind, table, key: grid.key });
	}
	if (!sweeps.length) return undefined;
	return { listing: { manifest_id: view.manifest.id, sweeps }, cells };
}

export async function readPublishedSweep(view: View, pack: string, role: string, named: string, start?: SweepStart):
	Promise<{ series: SweepSeriesCell[]; start?: RowRef; cell: SweepCellLocation } | undefined> {
	if (!NAME.test(named)) return undefined;
	const grids = await loadGrids(view);
	if (!grids) return undefined;
	const grid = grids.find((entry) => entry.name === named);
	if (!grid) return undefined;
	const table = await readableCell(view, grid);
	if (!table) return undefined;
	const cell: SweepCellLocation = { kind: grid.kind, table, key: grid.key };
	let startRef: RowRef | undefined;
	let mainRows: Keyed[] | undefined;
	let mode: PairMode = { kind: 'default' };
	if (start) {
		if (!view.snaps.has(start.relation)) return undefined;
		mainRows = await view.rows(start.relation);
		if (!mainRows.some((row) => compareKey(row.key, start.key) === 0)) return undefined;
		startRef = { relation: start.relation, key: canonicalJson(start.key) };
		const relMeta = view.bundle.relations?.find((rel) => rel.id === start.relation);
		if (typeof relMeta?.calc === 'string' && relMeta.calc.length > 0) {
			mode = { kind: 'calc' };
		} else {
			const rulesRef = view.compiled('ir/rules.json');
			if (rulesRef) {
				let rulesDoc: unknown;
				try { rulesDoc = await view.object(rulesRef, 'bundles'); }
				catch (error) {
					if (error instanceof StoreLimit) throw error;
					return undefined;
				}
				const keyArity = functionalKeyArity(rulesDoc, start.relation);
				if (keyArity === 'invalid') return undefined;
				if (keyArity !== undefined) mode = { kind: 'functional', keyArity };
			}
		}
	}
	const full = completeScope(view);
	const points = await boundPoints(view, pack, role, grid, full);
	if (!start || !mainRows || !startRef) {
		const series = points.map(({ cell: pointCell, diagnosis }) => ({ index: pointCell.index, value: pointCell.value, status: pointCell.status,
			...(pointCell.manifest && { manifest: pointCell.manifest }), ...(diagnosis && { diagnosis }) }));
		return { series, cell };
	}

	const pairedKeys: Array<string | undefined> = [];
	const rowValid: boolean[] = [];
	for (let i = 0; i < points.length; i++) {
		const point = points[i];
		if (full && point.manifestBody) {
			const stopRows = await variantRows(view, point.manifestBody, role, start.relation);
			if (stopRows !== undefined) {
				const paired = pairRow(mainRows, stopRows, start.key, mode);
				if (paired.kind === 'paired') {
					pairedKeys.push(canonicalJson(paired.key));
					rowValid.push(true);
					continue;
				}
				if (paired.kind === 'absent') {
					pairedKeys.push(undefined);
					rowValid.push(true);
					continue;
				}
			}
		}
		pairedKeys.push(undefined);
		rowValid.push(false);
	}

	const series: SweepSeriesCell[] = [];
	for (let i = 0; i < points.length; i++) {
		const { cell: pointCell, diagnosis } = points[i];
		const entry: SweepSeriesCell = {
			index: pointCell.index,
			value: pointCell.value,
			status: pointCell.status,
			...(pointCell.manifest && { manifest: pointCell.manifest }),
			...(diagnosis && { diagnosis })
		};
		if (pairedKeys[i] !== undefined) {
			entry.row = { relation: start.relation, key: pairedKeys[i]! };
		}
		if (i > 0) {
			const prev = points[i - 1];
			const curr = points[i];
			if (full && rowValid[i - 1] && rowValid[i]
				&& prev.cell.manifest && prev.manifestSha
				&& curr.cell.manifest && curr.manifestSha) {
				const turnsMap = await readTurns(
					view, pack, role, grid,
					{ index: i - 1, manifest: prev.cell.manifest, sha256: prev.manifestSha },
					{ index: i, manifest: curr.cell.manifest, sha256: curr.manifestSha }
				);
				if (!turnsMap) {
					entry.turn = 'unknown';
				} else {
					const lookupKey = pairedKeys[i] ?? pairedKeys[i - 1];
					const found = lookupKey !== undefined
						? turnsMap.get(start.relation + '\u0000' + lookupKey)
						: undefined;
					if (found) {
						entry.turn = 'turns';
						entry.causes = found;
					} else {
						entry.turn = 'same';
					}
				}
			} else {
				entry.turn = 'unknown';
			}
		}
		series.push(entry);
	}
	return { series, start: startRef, cell };
}

export async function readPublishedVariant(
	view: SweepView,
	pack: string,
	role: string,
	variantId: string
): Promise<PublishedVariant | undefined> {
	if (!SAFE.test(variantId) || variantId.includes('..')) return undefined;
	if (!completeScope(view)) return undefined;
	const ref = view.compiled('ir/sweeps.json');
	if (!ref) return undefined;
	const grids = await view.object(ref, 'bundles', publishedGrids) as Grid[] | undefined;
	if (!grids) return undefined;
	const epoch = view.manifest.epoch + 1;
	if (!Number.isSafeInteger(epoch)) return undefined;
	let matched: { grid: Grid; index: number; value: string } | undefined;
	for (const grid of grids) {
		const prefix = 'v-' + grid.name + '-';
		const suffix = '-' + epoch;
		if (!variantId.startsWith(prefix) || !variantId.endsWith(suffix)) continue;
		const rawIndex = variantId.slice(prefix.length, variantId.length - suffix.length);
		if (!/^[0-9]{2}$/.test(rawIndex)) continue;
		const index = Number(rawIndex);
		if (index < 0 || index >= grid.count) continue;
		matched = { grid, index, value: (grid.min + BigInt(index) * grid.step).toString() };
		break;
	}
	if (!matched || !await readableCell(view, matched.grid)) return undefined;

	const pointer = await view.read(pack + '/epochs/' + epoch + '/manifests/' + variantId + '.json', undefined, true);
	if (pointer === undefined) return undefined;
	if (!record(pointer) || pointer.format !== 'rezono.pointer/1' || pointer.id !== variantId
		|| typeof pointer.sha256 !== 'string' || !SHA256.test(pointer.sha256)) {
		throw new AskError(500, 'invalid publication');
	}
	const diagPointer = await view.read(pack + '/epochs/' + epoch + '/diagnoses/' + variantId + '.json', undefined, true);
	if (diagPointer !== undefined) return undefined;

	const body = await view.read(pack + '/manifests/' + variantId + '.json', pointer.sha256, false);
	if (!record(body) || body.id !== variantId || body.epoch !== epoch || !record(body.variant)
		|| body.proposal || body.access_semantics !== 2 || !checkedStatuses(body.checks)) {
		throw new AskError(500, 'invalid publication');
	}
	if (body.base_manifest !== view.manifest.id || body.checks.some((check) => check.status === 'red')) {
		return undefined;
	}
	const { readers, status_readers } = body.variant;
	if (body.variant.sweep !== matched.grid.name || body.variant.index !== matched.index
		|| body.variant.value !== matched.value
		|| !roleList(readers) || !roleList(status_readers)
		|| !status_readers.every((entry) => readers.includes(entry))) {
		throw new AskError(500, 'invalid publication');
	}
	if (!readers.includes(role) || !status_readers.includes(role)) return undefined;

	if (!Array.isArray(body.snapshots)) throw new AskError(500, 'invalid publication');
	const snapshots = new Map<string, Snapshot>();
	for (const entry of body.snapshots) {
		if (!record(entry) || typeof entry.role !== 'string' || typeof entry.relation !== 'string'
			|| !SAFE.test(entry.relation) || entry.relation.includes('..')) {
			throw new AskError(500, 'invalid publication');
		}
		if (entry.role !== role) continue;
		if (entry.format !== 'json' || typeof entry.uri !== 'string'
			|| typeof entry.sha256 !== 'string' || !SHA256.test(entry.sha256)
			|| typeof entry.complete !== 'boolean'
			|| (entry.full !== undefined && typeof entry.full !== 'boolean')
			|| snapshots.has(entry.relation)) {
			throw new AskError(500, 'invalid publication');
		}
		snapshots.set(entry.relation, entry as unknown as Snapshot);
	}
	if (!snapshots.size || !snapshots.has(matched.grid.kind)) return undefined;
	const variantComplete = [...snapshots.values()].every((entry) => entry.complete || entry.full === true)
		&& body.snapshots.every((entry: unknown) => record(entry) && typeof entry.relation === 'string' && snapshots.has(entry.relation));
	if (!variantComplete) return undefined;

	return {
		id: variantId,
		sweep: matched.grid.name,
		index: matched.index,
		value: matched.value,
		sha256: pointer.sha256,
		snapshots
	};
}

export function sweepAnswer(term: string, name: string, manifest: string, series: SweepSeriesCell[], start?: RowRef): Answer {
	return {
		format: ANSWER,
		question: term,
		manifest_id: manifest,
		...(start && { start }),
		delta: { kind: 'sweep', id: name },
		nodes: [],
		series
	};
}
