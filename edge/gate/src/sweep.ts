import type { BoundSweep, BoundSweepList, BoundSweepCell, Answer, SeriesCell } from '../../../contracts/typescript/generated/explain.ts';
import type { ArchivedFile, Manifest, Snapshot } from '../../../contracts/typescript/generated/manifest.ts';
import type { Bundle } from '../../../contracts/typescript/generated/bundle.ts';
import { ANSWER } from './ask.ts';
import { roleCatalogue } from './catalogue.ts';
import type { Read } from './expr.ts';
import { StoreLimit } from './store.ts';

const NAME = /^[a-z][a-z0-9]*(_[a-z0-9]+)*$/;
const SHA256 = /^[0-9a-f]{64}$/;
const DECIMAL = /^(0|-?[1-9][0-9]*)$/;
const SAFE = /^[A-Za-z0-9][A-Za-z0-9._-]*$/;

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

interface View {
	manifest: Manifest;
	bundle: Bundle;
	snaps: ReadonlyMap<string, Snapshot>;
	compiled(file: string): ArchivedFile | undefined;
	object(ref: ArchivedFile, category: 'bundles', decode?: (text: string) => unknown): Promise<unknown>;
	read(key: string, sha?: string, optional?: boolean): Promise<unknown>;
	range: Read;
}

interface Point {
	cell: BoundSweepCell;
	diagnosis?: string;
}

function record(value: unknown): value is Record<string, unknown> {
	return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function publishedGrid(text: string): Grid | undefined {
	const document: unknown = JSON.parse(text, (_key, value: unknown, context?: {source?: string}) => {
		if (typeof value !== 'number') return value;
		const decimal = context?.source;
		if (decimal !== undefined && DECIMAL.test(decimal)) return BigInt(decimal);
		if (decimal === undefined && Number.isSafeInteger(value)) return BigInt(value);
		throw new TypeError('sweep grid needs exact whole numbers');
	});
	if (!record(document) || document.format !== 'rezono.sweeps/1' || !Array.isArray(document.sweeps)
		|| document.sweeps.length !== 1) return undefined;
	const grid: unknown = document.sweeps[0];
	if (!record(grid)) return undefined;
	const { name, kind, key, slot, min, max, step, count } = grid;
	if (typeof name !== 'string' || !NAME.test(name)
		|| typeof kind !== 'string' || typeof key !== 'string' || typeof slot !== 'string'
		|| typeof min !== 'bigint' || typeof max !== 'bigint' || typeof step !== 'bigint' || typeof count !== 'bigint'
		|| step <= 0n || max < min || count > 64n || (max - min) / step + 1n !== count) return undefined;
	return { name, kind, key, slot, min, max, step, count: Number(count) };
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

async function readableCell(view: View, grid: Grid): Promise<boolean> {
	const scoped = roleCatalogue(view.bundle, [...view.snaps.values()]);
	const byId = new Map(scoped.kinds.map((kind) => [kind.id, kind]));
	const seen = new Set<string>();
	let kind = byId.get(grid.kind);
	while (kind && !seen.has(kind.id)) {
		seen.add(kind.id);
		const slot = scoped.attributes.find((entry) => entry.kind === kind!.id && entry.name === grid.slot);
		if (slot) {
			if (slot.multivalued || slot.type !== 'integer') return false;
			const member = await view.range(grid.kind, { prefix: [grid.key], limit: 2 });
			if (member.rows.length !== 1 || !record(member.rows[0]) || !Array.isArray(member.rows[0].key)
				|| member.rows[0].key.length !== 1) return false;
			const value = await view.range(slot.table, { prefix: [grid.key], limit: 2 });
			return value.rows.length === 1 && record(value.rows[0]) && Array.isArray(value.rows[0].key)
				&& value.rows[0].key.length === 2;
		}
		kind = kind.parent ? byId.get(kind.parent) : undefined;
	}
	return false;
}

function completeScope(view: View): boolean {
	return [...view.snaps.values()].every((entry) => entry.complete || entry.full)
		&& (view.manifest.snapshots ?? []).every((entry) => view.snaps.has(entry.relation));
}

async function publishedPoint(view: View, pack: string, role: string, grid: Grid, index: number, value: string): Promise<Point> {
	const epoch = view.manifest.epoch + 1;
	const id = 'v-' + grid.name + '-' + String(index).padStart(2, '0') + '-' + epoch;
	const fallback: Point = { cell: { index, value, status: 'not_computed' } };
	if (!Number.isSafeInteger(epoch)) return fallback;

	async function entry(category: 'manifests' | 'diagnoses'): Promise<{checks: Check[]; status: Check['status']} | undefined> {
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
			return { checks, status: red ? 'red' : checks.some((check) => check.status === 'warning') ? 'warning' : 'green' };
		} catch (error) {
			if (error instanceof StoreLimit) throw error;
			return undefined;
		}
	}

	const green = await entry('manifests');
	const red = await entry('diagnoses');
	if (green && red) return fallback;
	if (green) return { cell: { index, value, status: green.status, checks: green.checks, manifest: id } };
	if (red) return { cell: { index, value, status: 'red', checks: red.checks }, diagnosis: id };
	return fallback;
}

export async function readPublishedSweep(view: View, pack: string, role: string, named?: string):
	Promise<{listing: BoundSweepList; series: SeriesCell[]} | undefined> {
	const ref = view.compiled('ir/sweeps.json');
	if (!ref) return undefined;
	let grid: Grid | undefined;
	try { grid = await view.object(ref, 'bundles', publishedGrid) as Grid | undefined; }
	catch (error) {
		if (error instanceof StoreLimit) throw error;
		return undefined;
	}
	if (!grid || (named !== undefined && grid.name !== named) || !await readableCell(view, grid)) return undefined;
	const full = completeScope(view);
	const points: Point[] = [];
	for (let index = 0; index < grid.count; index++) {
		const value = (grid.min + BigInt(index) * grid.step).toString();
		points.push(full ? await publishedPoint(view, pack, role, grid, index, value)
			: { cell: { index, value, status: 'unavailable' } });
	}
	const listing: BoundSweep = { name: grid.name, cell: { kind: grid.kind, id: grid.key, slot: grid.slot },
		min: String(grid.min), max: String(grid.max), step: String(grid.step), cells: points.map(({ cell }) => cell) };
	const series = points.map(({ cell, diagnosis }) => ({ index: cell.index, value: cell.value, status: cell.status,
		...(cell.manifest && { manifest: cell.manifest }), ...(diagnosis && { diagnosis }) }));
	return { listing: { manifest_id: view.manifest.id, sweeps: [listing] }, series };
}

export function sweepAnswer(term: string, name: string, manifest: string, series: SeriesCell[]): Answer {
	return { format: ANSWER, question: term, manifest_id: manifest, delta: { kind: 'sweep', id: name }, nodes: [], series };
}
