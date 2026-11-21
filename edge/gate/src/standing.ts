import { AskError } from './ask.ts';
import { compareKey, compareText, type KeyRange } from './pieces.ts';
import type { Store } from './store.ts';

const MAIN = /^m-[0-9]+$/;
const SAFE = /^[A-Za-z0-9][A-Za-z0-9._-]*$/;
const ISO_DATE = /^(\d{4})-(\d{2})-(\d{2})$/;
const WITHDRAWAL_FIELDS = new Set(['format', 'id', 'state', 'decider', 'decided_on', 'reason', 'epochs', 'rows']);
const ROW_TARGET_FIELDS = new Set(['relation', 'key', 'manifest']);

export interface RowWithdrawalTarget {
	relation: string;
	key: string[];
	manifest?: string;
}

export interface WithdrawalRecord {
	format: 'rezono.withdrawal/1';
	id: string;
	state: 'withdrawn';
	decider: string[];
	decided_on: string;
	reason: string;
	epochs: string[];
	rows: RowWithdrawalTarget[];
}

export class WithdrawnError extends Error {
	readonly withdrawal: WithdrawalRecord;
	constructor(withdrawal: WithdrawalRecord) {
		super('withdrawn');
		this.withdrawal = withdrawal;
	}
}

function safe(name: string): boolean {
	return SAFE.test(name) && !name.includes('..');
}

function record(x: unknown): x is Record<string, unknown> {
	return x !== null && typeof x === 'object' && !Array.isArray(x);
}

function keyParts(x: unknown): x is string[] {
	return Array.isArray(x) && x.every((part) => typeof part === 'string');
}

function isMainManifestId(value: unknown): value is string {
	if (typeof value !== 'string' || !MAIN.test(value)) return false;
	const epoch = Number(value.slice(2));
	return Number.isSafeInteger(epoch) && value === 'm-' + epoch;
}

function isIsoDate(value: unknown): value is string {
	if (typeof value !== 'string') return false;
	const match = ISO_DATE.exec(value);
	if (!match) return false;
	const year = Number(match[1]);
	const month = Number(match[2]);
	const day = Number(match[3]);
	if (month < 1 || month > 12 || day < 1 || day > 31) return false;
	const date = new Date(0);
	date.setUTCFullYear(year, month - 1, day);
	return date.getUTCFullYear() === year && date.getUTCMonth() === month - 1 && date.getUTCDate() === day;
}

function fault(): never {
	throw new AskError(500, 'invalid publication');
}

/** Validate one immutable withdrawal decision document against decisions/publication-supersession-and-withdrawal.md. */
export function parseWithdrawal(raw: unknown, expectedId: string): WithdrawalRecord {
	if (!safe(expectedId) || !record(raw)) fault();
	if (!Object.keys(raw).every((field) => WITHDRAWAL_FIELDS.has(field))) fault();
	if (raw.format !== 'rezono.withdrawal/1' || raw.state !== 'withdrawn') fault();
	if (raw.id !== expectedId) fault();
	if (!Array.isArray(raw.decider) || !raw.decider.length
		|| !raw.decider.every((party) => typeof party === 'string' && party.trim().length > 0)) fault();
	if (!isIsoDate(raw.decided_on)) fault();
	if (typeof raw.reason !== 'string' || !raw.reason.length || raw.reason.trim() !== raw.reason) fault();

	const epochs: string[] = [];
	if (Object.hasOwn(raw, 'epochs')) {
		if (!Array.isArray(raw.epochs) || !raw.epochs.every(isMainManifestId)) fault();
		epochs.push(...raw.epochs);
	}

	const rows: RowWithdrawalTarget[] = [];
	if (Object.hasOwn(raw, 'rows')) {
		if (!Array.isArray(raw.rows)) fault();
		for (const entry of raw.rows) {
			if (!record(entry) || !Object.keys(entry).every((field) => ROW_TARGET_FIELDS.has(field))) fault();
			if (typeof entry.relation !== 'string' || !safe(entry.relation)) fault();
			if (!keyParts(entry.key) || !entry.key.length) fault();
			if (Object.hasOwn(entry, 'manifest') && !isMainManifestId(entry.manifest)) fault();
			rows.push({
				relation: entry.relation,
				key: entry.key,
				...(Object.hasOwn(entry, 'manifest') ? { manifest: entry.manifest as string } : {})
			});
		}
	}

	if (!epochs.length && !rows.length) fault();
	return {
		format: 'rezono.withdrawal/1',
		id: expectedId,
		state: 'withdrawn',
		decider: raw.decider as string[],
		decided_on: raw.decided_on,
		reason: raw.reason,
		epochs,
		rows
	};
}

/** Load and validate every withdrawal record under <pack>/withdrawals/, failing closed on any malformed entry. */
export async function loadWithdrawals(
	store: Store,
	pack: string,
	read: (key: string) => Promise<unknown>
): Promise<WithdrawalRecord[]> {
	const prefix = pack + '/withdrawals/';
	const keys = await store.list(prefix);
	const records: WithdrawalRecord[] = [];
	const seen = new Set<string>();
	for (const key of keys) {
		if (!key.startsWith(prefix) || !key.endsWith('.json')) fault();
		const id = key.slice(prefix.length, -'.json'.length);
		if (!id || id.includes('/') || !safe(id) || seen.has(id)) fault();
		seen.add(id);
		records.push(parseWithdrawal(await read(key), id));
	}
	records.sort((a, b) => compareText(a.id, b.id));
	return records;
}

export function standingHeaders(pack: string, viewEpoch: number, currentManifestId: string, currentEpoch: number): Record<string, string> {
	if (viewEpoch < currentEpoch) {
		return {
			'x-rezono-standing': 'superseded',
			'x-rezono-superseded-by': currentManifestId,
			link: `</${pack}/manifests/${currentManifestId}>; rel="successor-version"`
		};
	}
	return { 'x-rezono-standing': 'current' };
}

export function withdrawalBody(entry: WithdrawalRecord) {
	return {
		error: 'withdrawn',
		reason: entry.reason,
		withdrawal: {
			id: entry.id,
			decider: [...entry.decider],
			decided_on: entry.decided_on,
			reason: entry.reason
		}
	};
}

export function earlierWithdrawal(a: WithdrawalRecord | undefined, b: WithdrawalRecord | undefined): WithdrawalRecord | undefined {
	if (!a) return b;
	if (!b) return a;
	return compareText(a.id, b.id) <= 0 ? a : b;
}

export function epochWithdrawal(withdrawals: readonly WithdrawalRecord[], manifestId: string): WithdrawalRecord | undefined {
	return withdrawals.find((entry) => entry.epochs.includes(manifestId));
}

export function rowWithdrawal(
	withdrawals: readonly WithdrawalRecord[],
	manifestId: string,
	relation: string,
	key: readonly string[]
): WithdrawalRecord | undefined {
	return withdrawals.find((entry) =>
		entry.rows.some((target) =>
			target.relation === relation
			&& (target.manifest === undefined || target.manifest === manifestId)
			&& compareKey(target.key, key as string[]) === 0
		)
	);
}

function hasSortedKey(sorted: readonly { key: string[] }[], target: readonly string[]): boolean {
	let lo = 0, hi = sorted.length - 1;
	while (lo <= hi) {
		const mid = (lo + hi) >>> 1;
		const cmp = compareKey(sorted[mid].key, target as string[]);
		if (cmp === 0) return true;
		if (cmp < 0) lo = mid + 1;
		else hi = mid - 1;
	}
	return false;
}

export function rowsWithdrawal(
	withdrawals: readonly WithdrawalRecord[],
	manifestId: string,
	relation: string,
	sortedRows: readonly { key: string[] }[]
): WithdrawalRecord | undefined {
	if (!withdrawals.length || !sortedRows.length) return undefined;
	return withdrawals.find((entry) =>
		entry.rows.some((target) =>
			target.relation === relation
			&& (target.manifest === undefined || target.manifest === manifestId)
			&& hasSortedKey(sortedRows, target.key)
		)
	);
}

export function rangeMatchingRows<T extends { key: string[] }>(rows: readonly T[], { prefix, starts }: Pick<KeyRange, 'prefix' | 'starts'>): T[] {
	return rows.filter(({ key }) =>
		prefix.every((part, i) => key[i] === part)
		&& (starts === undefined || key[0].startsWith(starts))
	);
}
