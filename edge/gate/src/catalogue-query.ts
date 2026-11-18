import type { Bundle } from '../../../contracts/typescript/generated/bundle.ts';
import type { Snapshot } from '../../../contracts/typescript/generated/manifest.ts';
import type { SlotDef, World } from '../../../rezono/src/index.ts';
import { roleCatalogue } from './catalogue.ts';
import { catalogueFields } from './catalogue-questions.ts';
import type { Read, View } from './expr.ts';
import { compareKey, pageByKey } from './pieces.ts';
import { StoreLimit } from './store.ts';

const RELATION = 'catalogue_entry';
const KIND = 'CatalogueEntry';
const slotRelation = (field: string) => RELATION + '__' + field;
interface Entry {
	id: string;
	kind_id: string;
	kind_name: string;
	entry_type: 'kind' | 'slot' | 'outcome';
	name: string;
	effective_world?: World;
	coverage?: 'full' | 'partial';
	row_presence?: 'present' | 'empty';
	value_type?: string;
	slot_card?: '?' | '*' | '+' | '1';
}
type ScopedBundle = ReturnType<typeof roleCatalogue>;
type Kind = ScopedBundle['kinds'][number];
type Slot = ScopedBundle['attributes'][number];
const typeNames = new Map([['text', 'Text'], ['integer', 'Integer'], ['boolean', 'Bool'], ['date', 'Date']]);

function lineage(kind: Kind, byId: Map<string, Kind>): Kind[] {
	const result: Kind[] = [];
	const seen = new Set<string>();
	let current: Kind | undefined = kind;
	while (current && !seen.has(current.id)) {
		seen.add(current.id);
		result.push(current);
		current = current.parent ? byId.get(current.parent) : undefined;
	}
	return result;
}

function slotsOf(kind: Kind, ancestors: Kind[], scoped: ScopedBundle, byId: Map<string, Kind>, world: World): Entry[] {
	const byName = new Map<string, Slot>();
	for (const ancestor of ancestors) {
		for (const slot of [...scoped.attributes, ...scoped.arrows])
			if (slot.kind === ancestor.id && !byName.has(slot.name)) byName.set(slot.name, slot);
	}
	return [...byName.values()].map((slot) => ({
		id: 'slot/' + kind.id + '/' + slot.name, kind_id: kind.id, kind_name: kind.class,
		entry_type: 'slot', name: slot.name, effective_world: slot.world ?? world,
		value_type: slot.target ? byId.get(slot.target)?.class : slot.enum ?? typeNames.get(slot.type ?? '') ?? slot.schema_type ?? slot.type,
		slot_card: slot.multivalued ? (slot.required ? '+' : '*') : slot.required ? '1' : '?'
	}));
}

function data(scope: Entry[]): {view: View; read: Read} {
	const byRelation = new Map([[RELATION, scope.map(({ id }) => ({ key: [id] }))]]);
	const definitions: Record<string, SlotDef> = {};
	for (const field of catalogueFields) {
		const required = ['kind_id', 'kind_name', 'entry_type', 'name'].includes(field);
		definitions[field] = { type: 'Text', card: required ? '1' : '?',
			states: required ? ['known'] : ['known', 'not_applicable'] };
		byRelation.set(slotRelation(field), scope.flatMap((entry) => {
			const value = entry[field];
			return value === undefined ? [] : [{ key: [entry.id, value] }];
		}));
	}
	const view: View = {
		schema: { rezono: '1.0', pack: 'catalogue', base: 'https://rezono.org/catalogue/',
			kinds: { [KIND]: { id: { type: 'Text' }, world: 'closed', slots: definitions } } },
		kinds: new Map([[KIND, { relation: RELATION }]]),
		slots: new Map([[KIND, new Map(catalogueFields.map((field) => [field, { relation: slotRelation(field), partial: false }]))]]),
		reads: new Set(byRelation.keys()),
		trees: new Set()
	};
	for (const rows of byRelation.values()) rows.sort((a, b) => compareKey(a.key, b.key));
	return {
		view,
		read: async (relation, range) => pageByKey(byRelation.get(relation) ?? [], range)
	};
}

/** Project metadata from the verified publication and its selected role. */
export async function catalogueQueryScope(bundle: Bundle, snapshots: Snapshot[], read: Read, rowLimit: number) {
	const manifest = new Map(snapshots.map((snapshot) => [snapshot.relation, snapshot]));
	const knownKinds = new Set(bundle.kinds.map(({ id }) => id));
	const offered = new Map<string, { full: boolean; nonempty: boolean }>();
	for (const { id } of bundle.kinds) {
		const snapshot = manifest.get(id);
		if (!snapshot) continue;
		const full = snapshot.complete || snapshot.full === true;
		const nonempty = (await read(id, { prefix: [], limit: 1 })).rows.length > 0;
		if (full || nonempty) offered.set(id, { full, nonempty });
	}
	const scoped = roleCatalogue(bundle, snapshots.filter(({ relation }) => !knownKinds.has(relation) || offered.has(relation)));
	const byId = new Map(scoped.kinds.map((kind) => [kind.id, kind]));
	const readableRelations = new Set(scoped.relations.map(({ id }) => id));
	const outcomes = (bundle.relations ?? []).flatMap(({ id, outcome }) =>
		outcome && offered.has(outcome) && readableRelations.has(id) ? [{ id, kind: outcome }] : []);
	const entries: Entry[] = [];
	for (const kind of scoped.kinds) {
		const { nonempty, full } = offered.get(kind.id)!;
		const ancestors = lineage(kind, byId);
		const world = ancestors.find((ancestor) => ancestor.world)?.world ?? 'closed';
		entries.push({ id: 'kind/' + kind.id, kind_id: kind.id, kind_name: kind.class,
			entry_type: 'kind', name: kind.class, effective_world: world, coverage: full ? 'full' : 'partial',
			row_presence: nonempty ? 'present' : 'empty' });
		entries.push(...slotsOf(kind, ancestors, scoped, byId, world));
		const inherited = new Set(ancestors.map(({ id }) => id));
		for (const relation of outcomes) {
			if (!inherited.has(relation.kind)) continue;
			entries.push({ id: 'outcome/' + kind.id + '/' + relation.id, kind_id: kind.id, kind_name: kind.class,
				entry_type: 'outcome', name: relation.id });
		}
		if (entries.length > rowLimit) throw new StoreLimit();
	}
	return data(entries);
}
