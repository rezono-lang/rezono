import type { Bundle, Kind } from '../../../contracts/typescript/generated/bundle.ts';
import type { Snapshot } from '../../../contracts/typescript/generated/manifest.ts';

type RoleSnapshot = Pick<Snapshot, 'relation' | 'complete' | 'full'>;
type World = 'open' | 'closed';
type DeclaredKind = Pick<Kind, 'id' | 'class' | 'parent' | 'iri'> & {world?: World};
type Slot = {
	id: string;
	kind: string;
	name: string;
	table: string;
	target?: string;
	type?: string;
	schema_type?: string;
	enum?: string;
	minimum?: string;
	maximum?: string;
	patterns?: string[];
	multivalued?: boolean;
	required?: boolean;
	world?: 'open' | 'closed';
};

export interface RoleCatalogue {
	pack: Pick<Bundle['pack'], 'id' | 'base'>;
	kinds: DeclaredKind[];
	attributes: Slot[];
	arrows: Slot[];
	relations: {id: string; world?: 'open' | 'closed'; columns: {name: string}[]}[];
	enums: {id: string; values: string[]}[];
}

function worldOf(value: unknown): World | undefined {
	return value === 'open' || value === 'closed' ? value : undefined;
}

export function roleCatalogue(bundle: Bundle, snapshots: RoleSnapshot[]): RoleCatalogue {
	const scoped = new Set(snapshots.map((snapshot) => snapshot.relation));
	const full = new Set(snapshots.filter((snapshot) => snapshot.complete || snapshot.full).map((s) => s.relation));
	const slotWorld = (table: string, declared: unknown): World => full.has(table) ? worldOf(declared) ?? 'closed' : 'open';
	const visible = new Set(bundle.kinds.filter((kind) => scoped.has(kind.id)).map((kind) => kind.id));
	const kinds = bundle.kinds.filter((kind) => visible.has(kind.id)).map(({ id, class: name, parent, world, iri }) =>
		({ id, class: name, world: full.has(id) ? worldOf(world) : 'open' as const,
			...(parent && visible.has(parent) && { parent }), ...(iri && { iri }) }));

	const attributes = (bundle.attributes ?? []).filter((slot) => visible.has(slot.kind) && scoped.has(slot.table))
		.map(({ id, kind, name, table, type, schema_type, enum: enumerated, minimum, maximum, patterns, required, multivalued, world }) =>
			({ id, kind, name, table, type, schema_type, enum: enumerated, minimum, maximum, patterns, required, multivalued,
				world: slotWorld(table, world) }));
	const arrows = (bundle.arrows ?? []).filter((slot) => visible.has(slot.kind) && visible.has(slot.target) && scoped.has(slot.table))
		.map(({ id, kind, name, table, target, required, multivalued, world }) =>
			({ id, kind, name, table, target, required, multivalued, world: slotWorld(table, world) }));
	const enums = new Set(attributes.flatMap((slot) => slot.enum ? [slot.enum] : []));
	return {
		pack: { id: bundle.pack.id, base: bundle.pack.base },
		kinds, attributes, arrows,
		relations: (bundle.relations ?? []).filter((relation) => scoped.has(relation.id))
			.map(({ id, world, columns }) => ({ id, world: full.has(id) ? worldOf(world) : 'open' as const,
				columns: columns.map(({ name }) => ({ name })) })),
		enums: (bundle.enums ?? []).filter((entry) => enums.has(entry.id)).map(({ id, values }) => ({ id, values }))
	};
}
