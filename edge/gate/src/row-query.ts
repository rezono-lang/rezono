import { createHash } from 'node:crypto';
import type { Bundle } from '../../../contracts/typescript/generated/bundle.ts';
import type { Snapshot } from '../../../contracts/typescript/generated/manifest.ts';
import type { SlotDef } from '../../../rezono/src/index.ts';
import { canonicalJson } from '../../../viewer/src/lib/canon.ts';
import { AskError } from './ask.ts';
import type { Read, View } from './expr.ts';
import { compareKey, compareText, pageByKey, type KeyRange } from './pieces.ts';
import { StoreLimit } from './store.ts';

export interface RowSelection {
	kind: string;
	key: string[];
	source_limit: number;
	continuation?: string;
}

type BundleAttribute = NonNullable<Bundle['attributes']>[number];
type BundleArrow = NonNullable<Bundle['arrows']>[number];
type BundleRelation = NonNullable<Bundle['relations']>[number];
type RowSlot = Pick<BundleAttribute, 'kind' | 'name' | 'table' | 'required' | 'multivalued' | 'world'>;
interface RowBundle {
	pack: Pick<Bundle['pack'], 'id'>;
	kinds: Pick<Bundle['kinds'][number], 'id' | 'class' | 'parent' | 'world'>[];
	attributes?: (RowSlot & Pick<BundleAttribute, 'type' | 'enum' | 'currency'>)[];
	arrows?: (RowSlot & Pick<BundleArrow, 'target'>)[];
	relations?: (Pick<BundleRelation, 'id' | 'outcome' | 'world'> & { columns: Pick<BundleRelation['columns'][number], 'name'>[] })[];
}
type RowSnapshot = Pick<Snapshot, 'relation' | 'complete' | 'full'>;
type RowReader = (relation: string, range: KeyRange) => Promise<{ rows: { key: string[] }[]; next?: string[] }>;

const relation = 'row_cell';
const kindName = 'RowCell';
const slotRelation = (field: string) => `${relation}__${field}`;
const fields = {
	name: 'Text', relation: 'Text', subject_kind: 'Text', subject_key: 'Text', source_key: 'Text',
	value_type: 'Text', text_value: 'Text', integer_value: 'ExactInteger', currency: 'Text', target_kind: 'Text',
	cardinality: 'Text', coverage: 'Text', state: 'Text', reason: 'Text', continuation: 'Text'
} as const;
type Field = keyof typeof fields;
type State = 'known' | 'unknown' | 'not_applicable' | 'invalid';
type Cardinality = '1' | '?' | '+' | '*';
type Cell = Partial<Record<Field, string>> & { id: string; state: State; coverage: 'full' | 'partial' };
const fieldNames = Object.keys(fields) as Field[];
export const rowQuestion = 'ask cell: RowCell where true show ' + fieldNames.map((field) => `cell.${field}`).join(', ');

interface Source {
	relation: string;
	name: string;
	valueType: string;
	currency?: string;
	target?: string;
	cardinality?: Cardinality;
	open: boolean;
	full: boolean;
	outcome?: { state: number; reason: number; length: number };
}

function outcomeState(value: string | number): value is State {
	return value === 'known' || value === 'unknown' || value === 'not_applicable' || value === 'invalid';
}

function projection(cells: Cell[]) {
	const rows = new Map([[relation, cells.map(({ id }) => ({ key: [id] }))]]);
	const slots: Record<string, SlotDef> = {};
	for (const field of fieldNames) {
		slots[field] = { type: fields[field], card: '?', states: ['known', 'not_applicable'] };
		rows.set(slotRelation(field), cells.flatMap(({ id, [field]: value }) =>
			value === undefined ? [] : [{ key: [id, value] }]));
	}
	const view: View = {
		schema: { rezono: '1.0', pack: 'row-cells', base: 'https://rezono.org/row-cells/',
			types: { ExactInteger: { of: 'Integer' } },
			kinds: { [kindName]: { id: { type: 'Text' }, world: 'closed', slots } } },
		kinds: new Map([[kindName, { relation }]]), reads: new Set(rows.keys()), trees: new Set(),
		slots: new Map([[kindName, new Map(fieldNames.map((field) => [field, { relation: slotRelation(field), partial: false }]))]])
	};
	for (const entries of rows.values()) entries.sort((a, b) => compareKey(a.key, b.key));
	const read: Read = async (name, range) => pageByKey(rows.get(name) ?? [], range);
	return { view, read };
}

function cursorOf(token: string, scope: string, subject: string[]) {
	const invalid = () => new AskError(400, 'invalid row continuation');
	const [bound, encoded, extra] = token.split('.');
	if (bound !== scope || !encoded || extra !== undefined || !/^[A-Za-z0-9_-]+$/.test(encoded)) throw invalid();
	let candidate: unknown;
	try { candidate = JSON.parse(Buffer.from(encoded, 'base64url').toString('utf8')); }
	catch { throw invalid(); }
	if (!Array.isArray(candidate) || candidate.length !== 2 || typeof candidate[0] !== 'string'
		|| !Array.isArray(candidate[1]) || candidate[1].length <= subject.length
		|| !candidate[1].every((part) => typeof part === 'string')
		|| !subject.every((part, index) => candidate[1][index] === part)) throw invalid();
	return { relation: candidate[0], after: candidate[1] as string[] };
}

/** Build a query view of one exact row using only the pinned role's published source rows. */
export async function rowQueryScope(bundle: RowBundle, snapshots: RowSnapshot[], reader: RowReader, budget: number,
	selection: RowSelection, authority: { manifest: string; role: string }) {
	const snapshotsByRelation = new Map(snapshots.map((entry) => [entry.relation, entry]));
	const full = (name: string) => Boolean(snapshotsByRelation.get(name)?.complete || snapshotsByRelation.get(name)?.full);
	const read = async (name: string, range: KeyRange) => {
		if (budget <= 0) throw new StoreLimit();
		const page = await reader(name, { ...range, limit: Math.min(range.limit, budget) });
		budget -= page.rows.length + 1;
		if (budget < 0 || (page.next && page.rows.length < range.limit)) throw new StoreLimit();
		return page;
	};
	const exact = async (name: string, key: string[]) =>
		(await read(name, { prefix: key, limit: 1 })).rows.some((row) => compareKey(row.key, key) === 0);
	const { key, kind: identifier, source_limit, continuation } = selection;
	const kind = bundle.kinds.find(({ id }) => id === identifier) ?? bundle.kinds.find((k) => k.class === identifier);
	if (!kind || !snapshotsByRelation.has(kind.id) || !await exact(kind.id, key))
		throw new AskError(404, 'not found');

	const ancestry = new Set<string>();
	const byId = new Map(bundle.kinds.map((entry) => [entry.id, entry]));
	for (let parent: string | null | undefined = kind.id; parent && !ancestry.has(parent); parent = byId.get(parent)?.parent)
		ancestry.add(parent);
	const scope = createHash('sha256').update(canonicalJson([bundle.pack.id, authority.manifest, authority.role, kind.id, key])).digest('hex');
	const continued = continuation === undefined ? undefined : cursorOf(continuation, scope, key);
	const sources: Source[] = [];
	for (const slot of [...(bundle.attributes ?? []), ...(bundle.arrows ?? [])]) {
		if (!ancestry.has(slot.kind) || !snapshotsByRelation.has(slot.table)) continue;
		const target = 'target' in slot ? slot.target : undefined;
		if (target && (!snapshotsByRelation.has(target)
			|| (!full(target) && !(await read(target, { prefix: [], limit: 1 })).rows.length))) continue;
		const currency = 'currency' in slot ? slot.currency : undefined;
		const valueType = target ? 'reference' : currency ? 'amount' : 'enum' in slot && slot.enum ? slot.enum : 'type' in slot ? slot.type : 'text';
		sources.push({ name: slot.name, relation: slot.table, valueType, currency, target,
			cardinality: slot.multivalued ? (slot.required ? '+' : '*') : (slot.required ? '1' : '?'),
			open: (slot.world ?? byId.get(slot.kind)?.world) === 'open', full: full(slot.table) });
	}
	sources.sort((a, b) => compareText(a.name, b.name) || compareText(a.relation, b.relation));
	for (const entry of [...(bundle.relations ?? [])].sort((a, b) => compareText(a.id, b.id))) {
		if (!entry.outcome || !ancestry.has(entry.outcome) || !snapshotsByRelation.has(entry.id)) continue;
		const state = entry.columns.findIndex((column) => column.name === 'state');
		const reason = entry.columns.findIndex((column) => column.name === 'reason');
		if (state < key.length || reason < key.length) throw new AskError(500, 'invalid outcome columns');
		sources.push({ name: entry.id, relation: entry.id, valueType: 'outcome', open: entry.world === 'open',
			full: full(entry.id), outcome: { state, reason, length: entry.columns.length } });
	}
	if (continued && (!sources.some((source) => source.relation === continued.relation)
		|| !await exact(continued.relation, continued.after)))
		throw new AskError(400, 'invalid row continuation');

	const cells: Cell[] = [];
	const subject_key = canonicalJson(key);
	for (const source of sources) {
		if (continued && source.relation !== continued.relation) continue;
		const page = await read(source.relation, { prefix: key, limit: source_limit, after: continued?.after });
		const prefix = { name: source.name, relation: source.relation, subject_kind: kind.id, subject_key, value_type: source.valueType,
			cardinality: source.cardinality, currency: source.currency, target_kind: source.target,
			coverage: source.full ? 'full' as const : 'partial' as const };
		const id = (sourceKey?: readonly (string | number)[]) => canonicalJson([
			String(cells.length).padStart(6, '0'), kind.id, key, source.relation, ...(sourceKey ? [sourceKey] : [])
		]);
		if (!page.rows.length && !source.outcome && !continued) {
			cells.push({ ...prefix, id: id(), state: !source.full || source.open ? 'unknown' : 'not_applicable',
				reason: source.full ? undefined : 'not_read_in_full' });
		}
		for (const { key: sourceKey } of page.rows) {
			const cell = { ...prefix, id: id(sourceKey), source_key: canonicalJson(sourceKey) };
			if (source.outcome) {
				const { state, reason, length } = source.outcome;
				const value = sourceKey[state];
				if (sourceKey.length !== length || !outcomeState(value))
					throw new AskError(500, 'invalid outcome row');
				cells.push({ ...cell, state: value, reason: value === 'known' ? undefined : String(sourceKey[reason]) || undefined });
			} else {
				if (sourceKey.length !== key.length + 1) throw new AskError(500, 'invalid slot row');
				const raw = String(sourceKey[key.length]);
				const value = source.valueType === 'integer' || source.valueType === 'amount' ? { integer_value: raw } : { text_value: raw };
				cells.push({ ...cell, ...value, state: 'known' });
			}
		}
		if (page.next && cells.length) cells.at(-1)!.continuation = scope + '.' +
			Buffer.from(canonicalJson([source.relation, page.next])).toString('base64url');
	}
	return projection(cells);
}
