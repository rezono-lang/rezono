import type { StaircaseReading } from '../../../contracts/typescript/generated/bundle.ts';
import type { ArchivedFile, Manifest, Snapshot, WitnessSet } from '../../../contracts/typescript/generated/manifest.ts';
import type { CalcWitness, Witness } from '../../../contracts/typescript/generated/proof.ts';
import { canonicalJson, canonicalSha256 } from '../../../viewer/src/lib/canon.ts';
import { AskError } from './ask.ts';
import { compareKey, compareText } from './pieces.ts';
import {
	earlierWithdrawal, epochWithdrawal, hasSortedKey, rangeMatchingRows, rowWithdrawal, rowsWithdrawal,
	WithdrawnError, type WithdrawalRecord
} from './standing.ts';

type Keyed = { key: string[] };
type Witnesses = { witnesses: Witness[]; calc_witnesses?: CalcWitness[]; hidden: [] };

const VALID_STATES = new Set(['known', 'unknown', 'not_applicable', 'invalid', 'absent']);

export interface StaircaseEpochView {
	manifest: Manifest;
	snaps: Map<string, Snapshot>;
	bundle: {
		pack: { id: string; base?: string };
		relations?: { id: string; columns?: { name: string }[] }[];
		channels?: { staircases?: StaircaseReading[] };
	};
	compiled: (file: string) => ArchivedFile | undefined;
	rows: (relation: string) => Promise<Keyed[]>;
	object: (ref: ArchivedFile | WitnessSet, category: 'objects' | 'bundles') => Promise<unknown>;
}

export interface StaircaseCell {
	manifest: string;
	valid_at: string;
	known_at: string;
	relation: string;
	key: string[];
	state: string;
	value: string | null;
	reason: string;
	witness: {
		sha256: string;
		iri: string;
	};
}

export interface StaircaseResponse {
	format: 'rezono.staircase/1';
	pack: string;
	manifest: string;
	reading: string;
	subject: string;
	valid_times: string[];
	knowledge_times: { manifest: string; epoch: number; knowledge_time: string }[];
	cells: StaircaseCell[];
}

function record(x: unknown): x is Record<string, unknown> {
	return x !== null && typeof x === 'object' && !Array.isArray(x);
}

function keyParts(x: unknown): x is string[] {
	return Array.isArray(x) && x.every((part) => typeof part === 'string');
}

function fault(): never {
	throw new AskError(500, 'invalid publication');
}

function selectReading(readings: readonly StaircaseReading[], readingParam: string | null): StaircaseReading | undefined {
	if (readingParam !== null) {
		return readingParam.length ? readings.find((entry) => entry.id === readingParam) : undefined;
	}
	if (readings.length === 1) return readings[0];
	return readings.find((entry) => entry.id === 'bitemporal');
}

function resolveColumns(epochView: StaircaseEpochView, reading: StaircaseReading) {
	const rel = epochView.bundle.relations?.find((entry) => entry.id === reading.relation);
	if (!rel || !Array.isArray(rel.columns) || !rel.columns.length) fault();
	const colNames = rel.columns.map((col) => col.name);
	const subjectCol = reading.subject_column ?? colNames[0];
	const subjectIdx = colNames.indexOf(subjectCol);
	if (subjectIdx < 0) fault();
	const validTimeIdx = reading.valid_time_column ? colNames.indexOf(reading.valid_time_column) : -1;
	if (reading.valid_time_column && validTimeIdx < 0) fault();
	const stateCol = reading.state_column ?? 'state';
	const stateIdx = colNames.indexOf(stateCol);
	if (stateIdx < 0) fault();
	const valueCol = reading.value_column ?? (colNames.includes('value') ? 'value' : stateCol);
	const valueIdx = colNames.indexOf(valueCol);
	if (valueIdx < 0) fault();
	const reasonCol = reading.reason_column ?? 'reason';
	const reasonIdx = colNames.indexOf(reasonCol);
	if (reading.reason_column && reasonIdx < 0) fault();
	return { colNames, subjectIdx, validTimeIdx, stateIdx, valueIdx, reasonIdx };
}

async function resolveEpochValidAt(
	epochView: StaircaseEpochView,
	withdrawals: readonly WithdrawalRecord[]
): Promise<string | undefined> {
	if (epochView.snaps.has('calc__as_of')) {
		const asOfRows = await epochView.rows('calc__as_of');
		const row = asOfRows.find((entry) => entry.key[0] === 'as_of' && entry.key.length >= 2);
		if (row) {
			const withdrawn = rowWithdrawal(withdrawals, epochView.manifest.id, 'calc__as_of', row.key);
			if (withdrawn) throw new WithdrawnError(withdrawn);
			return row.key[1];
		}
	}
	const calcRef = epochView.compiled('ir/calc.json');
	if (calcRef) {
		const calcDoc = await epochView.object(calcRef, 'bundles');
		if (record(calcDoc) && record(calcDoc.as_of) && typeof calcDoc.as_of.valid_at === 'string'
			&& calcDoc.as_of.valid_at.length > 0) {
			return calcDoc.as_of.valid_at;
		}
	}
	return undefined;
}

async function checkPremiseWithdrawals(
	epochView: StaircaseEpochView,
	withdrawals: readonly WithdrawalRecord[],
	witness: Witness | CalcWitness
): Promise<void> {
	if (!withdrawals.some((entry) => entry.rows.length > 0)) return;
	let withdrawn: WithdrawalRecord | undefined;
	const checkRef = async (relation: string, rawKey: string) => {
		if (!epochView.snaps.has(relation)) return;
		let parsed: unknown;
		try { parsed = JSON.parse(rawKey); } catch { return; }
		if (!keyParts(parsed)) return;
		if (!hasSortedKey(await epochView.rows(relation), parsed)) return;
		withdrawn = earlierWithdrawal(withdrawn, rowWithdrawal(withdrawals, epochView.manifest.id, relation, parsed));
	};
	if ('rule_id' in witness) {
		for (const premise of witness.premises ?? []) {
			await checkRef(premise.row.relation, premise.row.key);
		}
	} else {
		for (const premise of witness.premises ?? []) {
			await checkRef(premise.relation, premise.key);
		}
		for (const step of witness.steps ?? []) {
			if (typeof step.relation === 'string' && typeof step.element === 'string'
				&& epochView.snaps.has(step.relation)) {
				const matching = rangeMatchingRows(await epochView.rows(step.relation), { prefix: [step.element] });
				withdrawn = earlierWithdrawal(
					withdrawn,
					rowsWithdrawal(withdrawals, epochView.manifest.id, step.relation, matching)
				);
			}
		}
	}
	if (withdrawn) throw new WithdrawnError(withdrawn);
}

function interpretOutcome(key: string[], stateIdx: number, valueIdx: number, reasonIdx: number) {
	if (stateIdx !== valueIdx) {
		const rawState = key[stateIdx];
		if (!VALID_STATES.has(rawState)) fault();
		return {
			state: rawState,
			value: rawState === 'known' ? key[valueIdx] : null,
			reason: reasonIdx >= 0 ? key[reasonIdx] : ''
		};
	}
	const rawOutcome = key[stateIdx];
	if (rawOutcome === 'unknown' || rawOutcome === 'not_applicable' || rawOutcome === 'invalid' || rawOutcome === 'absent') {
		return { state: rawOutcome, value: null, reason: reasonIdx >= 0 ? key[reasonIdx] : '' };
	}
	return { state: 'known', value: rawOutcome, reason: reasonIdx >= 0 ? key[reasonIdx] : '' };
}

export async function readStaircase<T extends StaircaseEpochView>(opts: {
	pack: string;
	role: string;
	targetView: T;
	currentView: T;
	withdrawals: readonly WithdrawalRecord[];
	subject: string | null;
	reading: string | null;
	loadEpoch: (manifestId: string) => Promise<T | undefined>;
	stillReadable: (earlier: T, current: T) => Promise<boolean>;
}): Promise<StaircaseResponse | undefined> {
	const { pack, role, targetView, currentView, withdrawals, subject, reading: readingParam, loadEpoch, stillReadable } = opts;
	if (!subject) throw new AskError(400, 'a staircase reading needs a subject');

	const selected = selectReading(targetView.bundle.channels?.staircases ?? [], readingParam);
	if (!selected) return undefined;
	if (!targetView.snaps.has(selected.relation)) return undefined;

	const knowledgeTimes: { manifest: string; epoch: number; knowledge_time: string }[] = [];
	const collected: (StaircaseCell & { epoch: number })[] = [];

	for (let epoch = 1; epoch <= targetView.manifest.epoch; epoch++) {
		const mid = 'm-' + epoch;
		const withdrawnEpoch = epochWithdrawal(withdrawals, mid);
		if (withdrawnEpoch) throw new WithdrawnError(withdrawnEpoch);

		const epochView = epoch === targetView.manifest.epoch ? targetView : await loadEpoch(mid);
		if (!epochView) continue;
		if (epochView !== targetView) {
			if (!await stillReadable(epochView, currentView) || !await stillReadable(epochView, targetView)) continue;
		}

		const epochReading = selectReading(epochView.bundle.channels?.staircases ?? [], selected.id);
		if (!epochReading || !epochView.snaps.has(epochReading.relation)) continue;

		if (epochView.snaps.has(epochReading.subject)) {
			const subjRows = await epochView.rows(epochReading.subject);
			if (hasSortedKey(subjRows, [subject])) {
				const subjWithdrawn = rowWithdrawal(withdrawals, epochView.manifest.id, epochReading.subject, [subject]);
				if (subjWithdrawn) throw new WithdrawnError(subjWithdrawn);
			}
		}

		const { colNames, subjectIdx, validTimeIdx, stateIdx, valueIdx, reasonIdx } = resolveColumns(epochView, epochReading);
		const allRows = await epochView.rows(epochReading.relation);
		const matchingRows = allRows.filter((row) => {
			if (row.key.length !== colNames.length) fault();
			return row.key[subjectIdx] === subject;
		});

		const rowWithdrawn = rowsWithdrawal(withdrawals, epochView.manifest.id, epochReading.relation, matchingRows);
		if (rowWithdrawn) throw new WithdrawnError(rowWithdrawn);

		knowledgeTimes.push({
			manifest: epochView.manifest.id,
			epoch: epochView.manifest.epoch,
			knowledge_time: epochView.manifest.knowledge_time
		});

		if (!matchingRows.length) continue;

		const witnessRef = epochView.manifest.witnesses?.find((set) => set.role === role);
		if (!witnessRef) return undefined;
		const published = await epochView.object(witnessRef, 'objects') as Witnesses;
		if (!record(published) || !Array.isArray(published.witnesses) || !Array.isArray(published.hidden)
			|| published.hidden.length || (published.calc_witnesses !== undefined && !Array.isArray(published.calc_witnesses))) {
			fault();
		}
		const witnessByRef = new Map<string, Witness | CalcWitness>();
		for (const w of [...published.witnesses, ...(published.calc_witnesses ?? [])]) {
			witnessByRef.set(w.conclusion.relation + '\u0000' + w.conclusion.key, w);
		}

		const epochValidAt = epochReading.valid_time_source === 'as_of'
			? await resolveEpochValidAt(epochView, withdrawals)
			: undefined;
		const base = epochView.bundle.pack.base || `https://rezono.example/${epochView.bundle.pack.id}/`;

		for (const row of matchingRows) {
			const w = witnessByRef.get(epochReading.relation + '\u0000' + canonicalJson(row.key));
			if (!w) fault();
			await checkPremiseWithdrawals(epochView, withdrawals, w);
			const validAt = validTimeIdx >= 0
				? row.key[validTimeIdx]
				: (epochValidAt
					?? (!('rule_id' in w) && typeof w.valid_at === 'string' && w.valid_at.length ? w.valid_at : undefined)
					?? epochView.manifest.knowledge_time.slice(0, 10));
			const { state, value, reason } = interpretOutcome(row.key, stateIdx, valueIdx, reasonIdx);
			const sha256 = await canonicalSha256(w);
			collected.push({
				epoch: epochView.manifest.epoch,
				manifest: epochView.manifest.id,
				valid_at: validAt,
				known_at: epochView.manifest.knowledge_time,
				relation: epochReading.relation,
				key: row.key,
				state,
				value,
				reason,
				witness: {
					sha256,
					iri: `${base}witness/${sha256}`
				}
			});
		}
	}

	if (!collected.length) return undefined;

	collected.sort((a, b) =>
		(a.epoch - b.epoch) || compareText(a.valid_at, b.valid_at) || compareKey(a.key, b.key));

	const validTimes = [...new Set(collected.map((cell) => cell.valid_at))].sort(compareText);
	const cells: StaircaseCell[] = collected.map(({ epoch: _epoch, ...cell }) => cell);

	return {
		format: 'rezono.staircase/1',
		pack,
		manifest: targetView.manifest.id,
		reading: selected.id,
		subject,
		valid_times: validTimes,
		knowledge_times: knowledgeTimes,
		cells
	};
}
