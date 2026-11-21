import type { StaircaseReading } from '../../../contracts/typescript/generated/bundle.ts';
import type { ArchivedFile, Manifest, Snapshot, WitnessSet } from '../../../contracts/typescript/generated/manifest.ts';
import type { CalcWitness, Witness } from '../../../contracts/typescript/generated/proof.ts';
import { canonicalJson, canonicalSha256 } from '../../../viewer/src/lib/canon.ts';
import { AskError } from './ask.ts';
import { visibleStaircases } from './catalogue.ts';
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
		kinds?: { id: string }[];
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

async function readableEpochSnapshots(view: StaircaseEpochView): Promise<Snapshot[]> {
	const readable: Snapshot[] = [];
	for (const snapshot of view.snaps.values()) {
		if (snapshot.complete || snapshot.full === true || (await view.rows(snapshot.relation)).length > 0) {
			readable.push(snapshot);
		}
	}
	return readable;
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

async function resolveAsOfSnapshotValidAt(
	epochView: StaircaseEpochView,
	withdrawals: readonly WithdrawalRecord[]
): Promise<string | undefined> {
	if (!epochView.snaps.has('calc__as_of')) return undefined;
	const asOfRows = await epochView.rows('calc__as_of');
	const allWithdrawn = rowsWithdrawal(withdrawals, epochView.manifest.id, 'calc__as_of', asOfRows);
	if (allWithdrawn) throw new WithdrawnError(allWithdrawn);
	const row = asOfRows.find((entry) => entry.key[0] === 'as_of' && entry.key.length >= 2 && entry.key[1].length > 0);
	if (!row) return undefined;
	const withdrawn = rowWithdrawal(withdrawals, epochView.manifest.id, 'calc__as_of', row.key);
	if (withdrawn) throw new WithdrawnError(withdrawn);
	return row.key[1];
}

async function resolveCalcIrValidAt(epochView: StaircaseEpochView): Promise<string | undefined> {
	const calcRef = epochView.compiled('ir/calc.json');
	if (!calcRef) return undefined;
	const calcDoc = await epochView.object(calcRef, 'bundles');
	if (record(calcDoc) && record(calcDoc.as_of) && typeof calcDoc.as_of.valid_at === 'string'
		&& calcDoc.as_of.valid_at.length > 0) {
		return calcDoc.as_of.valid_at;
	}
	return undefined;
}

export function witnessRefKey(relation: string, key: string): string {
	return relation + '\u0000' + key;
}

export async function checkProofClosureWithdrawals(
	epochView: StaircaseEpochView,
	withdrawals: readonly WithdrawalRecord[],
	rootWitness: Witness | CalcWitness,
	witnessByRef: ReadonlyMap<string, Witness | CalcWitness>
): Promise<void> {
	if (!withdrawals.some((entry) => entry.rows.length > 0)) return;
	const manifestId = epochView.manifest.id;
	let withdrawn: WithdrawalRecord | undefined;
	const visited = new Set<string>();
	const checkedRelations = new Set<string>();
	const queue: (Witness | CalcWitness)[] = [rootWitness];

	const checkRelationRows = async (relation: string) => {
		if (checkedRelations.has(relation) || !epochView.snaps.has(relation)) return;
		checkedRelations.add(relation);
		const rows = await epochView.rows(relation);
		withdrawn = earlierWithdrawal(withdrawn, rowsWithdrawal(withdrawals, manifestId, relation, rows));
		for (const row of rows) {
			const ref = witnessByRef.get(witnessRefKey(relation, canonicalJson(row.key)));
			if (ref && !visited.has(witnessRefKey(ref.conclusion.relation, ref.conclusion.key))) {
				queue.push(ref);
			}
		}
	};

	const checkRowRef = async (relation: string, rawKey: string, checkCollection = false) => {
		let parsed: unknown;
		try { parsed = JSON.parse(rawKey); } catch { parsed = undefined; }
		if (keyParts(parsed)) {
			withdrawn = earlierWithdrawal(withdrawn, rowWithdrawal(withdrawals, manifestId, relation, parsed));
		}
		if (checkCollection) {
			await checkRelationRows(relation);
		}
		const next = witnessByRef.get(witnessRefKey(relation, rawKey));
		if (next && !visited.has(witnessRefKey(next.conclusion.relation, next.conclusion.key))) {
			queue.push(next);
		}
	};

	while (queue.length > 0) {
		const w = queue.pop()!;
		const id = witnessRefKey(w.conclusion.relation, w.conclusion.key);
		if (visited.has(id)) continue;
		visited.add(id);

		await checkRowRef(w.conclusion.relation, w.conclusion.key);

		if ('rule_id' in w) {
			for (const premise of w.premises ?? []) {
				await checkRowRef(premise.row.relation, premise.row.key, premise.polarity === 'negative');
			}
			for (const agg of w.aggregates ?? []) {
				await checkRelationRows(agg.relation);
			}
		} else {
			for (const premise of w.premises ?? []) {
				await checkRowRef(premise.relation, premise.key);
			}
			for (const readRelation of w.reads ?? []) {
				await checkRelationRows(readRelation);
			}
			for (const step of w.steps ?? []) {
				if (typeof step.relation === 'string' && epochView.snaps.has(step.relation)) {
					if (typeof step.element === 'string') {
						const matching = rangeMatchingRows(await epochView.rows(step.relation), { prefix: [step.element] });
						withdrawn = earlierWithdrawal(withdrawn, rowsWithdrawal(withdrawals, manifestId, step.relation, matching));
					}
					await checkRelationRows(step.relation);
				}
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

	const targetVisible = visibleStaircases(targetView.bundle, await readableEpochSnapshots(targetView));
	const selected = selectReading(targetVisible, readingParam);
	if (!selected) return undefined;

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

		const epochVisible = epochView === targetView
			? targetVisible
			: visibleStaircases(epochView.bundle, await readableEpochSnapshots(epochView));
		const epochReading = selectReading(epochVisible, selected.id);
		if (!epochReading) continue;

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
			witnessByRef.set(witnessRefKey(w.conclusion.relation, w.conclusion.key), w);
		}

		const snapshotValidAt = epochReading.valid_time_source === 'as_of'
			? await resolveAsOfSnapshotValidAt(epochView, withdrawals)
			: undefined;
		let calcIrValidAt: string | undefined;
		let calcIrLoaded = false;
		const base = epochView.bundle.pack.base || `https://rezono.example/${epochView.bundle.pack.id}/`;

		for (const row of matchingRows) {
			const w = witnessByRef.get(witnessRefKey(epochReading.relation, canonicalJson(row.key)));
			if (!w) fault();
			await checkProofClosureWithdrawals(epochView, withdrawals, w, witnessByRef);
			let validAt: string;
			if (validTimeIdx >= 0) {
				validAt = row.key[validTimeIdx];
			} else {
				const fromWitness = !('rule_id' in w) && typeof w.valid_at === 'string' && w.valid_at.length > 0
					? w.valid_at
					: undefined;
				let resolved = snapshotValidAt ?? fromWitness;
				if (resolved === undefined) {
					if (!calcIrLoaded) {
						calcIrValidAt = await resolveCalcIrValidAt(epochView);
						calcIrLoaded = true;
					}
					resolved = calcIrValidAt;
				}
				if (resolved === undefined) fault();
				validAt = resolved;
			}
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
