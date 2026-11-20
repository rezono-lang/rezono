import type {
	Bundle,
	Kind,
	Label,
	MessageResource,
	Question,
	Rule,
	SemanticType
} from '../../../contracts/typescript/generated/bundle.ts';
import type { Snapshot } from '../../../contracts/typescript/generated/manifest.ts';

type RoleSnapshot = Pick<Snapshot, 'relation' | 'complete' | 'full'>;
type World = 'open' | 'closed';
type DeclaredKind = Pick<Kind, 'id' | 'class' | 'parent' | 'iri' | 'name_attribute' | 'name_arrows'> & { world?: World };
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
	currency?: string;
	semantic?: SemanticType;
	world?: World;
};
type RelationColumn = {
	name: string;
	currency?: string;
	semantic?: SemanticType;
};
type DeclaredRelation = {
	id: string;
	world?: World;
	calc?: string;
	outcome?: string;
	semantic?: SemanticType;
	columns: RelationColumn[];
};

export interface RoleCatalogue {
	pack: Pick<Bundle['pack'], 'id' | 'base'>;
	kinds: DeclaredKind[];
	attributes: Slot[];
	arrows: Slot[];
	relations: DeclaredRelation[];
	enums: { id: string; values: string[] }[];
}

export interface RoleBundle extends RoleCatalogue {
	rules: Rule[];
	labels: Label[];
	messages: MessageResource[];
	home: { claim: string[] };
	questions: Question[];
}

const MESSAGE_ENTRY = /^([A-Za-z0-9_.-]+)\s*=\s*/;
const STANDARD_MESSAGES = new Set([
	'arrow.total',
	'arrow.partial',
	'arrow.many.total',
	'arrow.many.partial',
	'attribute.total',
	'attribute.partial',
	'attribute.many.total',
	'attribute.many.partial',
	'is_a',
	'unique_key',
	'path_equation'
]);

function worldOf(value: unknown): World | undefined {
	return value === 'open' || value === 'closed' ? value : undefined;
}

function semanticOf(value: unknown, visibleKinds: ReadonlySet<string>): SemanticType | undefined {
	if (value === null || typeof value !== 'object' || Array.isArray(value)) return undefined;
	const raw = value as Record<string, unknown>;
	if (typeof raw.case !== 'string' || typeof raw.base !== 'string') return undefined;
	if (raw.case === 'ref' && typeof raw.target !== 'string') return undefined;
	if (raw.target !== undefined && (typeof raw.target !== 'string' || !visibleKinds.has(raw.target))) return undefined;
	const out: SemanticType = { case: raw.case, base: raw.base };
	if (typeof raw.range === 'string') out.range = raw.range;
	if (typeof raw.enum === 'string') out.enum = raw.enum;
	if (typeof raw.open === 'boolean') out.open = raw.open;
	if (typeof raw.target === 'string') out.target = raw.target;
	if (typeof raw.currency === 'string') out.currency = raw.currency;
	if (typeof raw.unit === 'string') out.unit = raw.unit;
	if (typeof raw.derived === 'string') out.derived = raw.derived;
	return out;
}

function ruleReadable(rule: Rule, scoped: ReadonlySet<string>): boolean {
	const headRelation = rule.head ? rule.head.relation : rule.relation;
	if (typeof headRelation !== 'string' || !scoped.has(headRelation)) return false;
	if (rule.relation !== undefined && (typeof rule.relation !== 'string' || !scoped.has(rule.relation))) return false;
	if (!Array.isArray(rule.body)) return false;
	for (const literal of rule.body) {
		if (literal.kind === 'atom' || literal.kind === 'aggregate') {
			if (typeof literal.relation !== 'string' || !scoped.has(literal.relation)) return false;
		} else if (literal.relation !== undefined && (typeof literal.relation !== 'string' || !scoped.has(literal.relation))) {
			return false;
		}
	}
	for (const agg of rule.aggregates ?? []) {
		if (typeof agg.relation !== 'string' || !scoped.has(agg.relation)) return false;
	}
	return true;
}

function filterMessageResource(entry: MessageResource, allow: (id: string) => boolean): MessageResource {
	const normalized = entry.resource.replace(/\r\n/g, '\n');
	const sep = normalized.indexOf('\n---\n');
	const head = sep >= 0 ? normalized.slice(0, sep) : `@locale ${entry.lang}`;
	const body = sep >= 0 ? normalized.slice(sep + '\n---\n'.length) : normalized;
	const lines = body.match(/[^\n]*\n|[^\n]+/g) ?? [];
	const kept: string[] = [];
	let currentId: string | undefined;
	let currentBlock = '';
	const flush = () => {
		if (currentId !== undefined && allow(currentId)) {
			kept.push(currentBlock.endsWith('\n') ? currentBlock : currentBlock + '\n');
		}
		currentId = undefined;
		currentBlock = '';
	};
	for (const line of lines) {
		const match = MESSAGE_ENTRY.exec(line);
		if (match) {
			flush();
			currentId = match[1];
			currentBlock = line;
		} else if (currentId !== undefined && (line.startsWith(' ') || line.startsWith('\t') || line === '\n')) {
			currentBlock += line;
		} else {
			flush();
		}
	}
	flush();
	return { lang: entry.lang, resource: `${head}\n---\n${kept.join('')}` };
}

export function roleCatalogue(bundle: Bundle, snapshots: RoleSnapshot[]): RoleCatalogue {
	const scoped = new Set(snapshots.map((snapshot) => snapshot.relation));
	const full = new Set(snapshots.filter((snapshot) => snapshot.complete || snapshot.full).map((s) => s.relation));
	const slotWorld = (table: string, declared: unknown): World => full.has(table) ? worldOf(declared) ?? 'closed' : 'open';
	const visible = new Set(bundle.kinds.filter((kind) => scoped.has(kind.id)).map((kind) => kind.id));

	const attributes: Slot[] = (bundle.attributes ?? [])
		.filter((slot) => visible.has(slot.kind) && scoped.has(slot.table))
		.map(({ id, kind, name, table, type, schema_type, enum: enumerated, minimum, maximum, patterns, required, multivalued, world, currency, semantic }) => {
			const scopedSemantic = semanticOf(semantic, visible);
			return {
				id, kind, name, table, type, schema_type, enum: enumerated, minimum, maximum, patterns, required, multivalued,
				...(typeof currency === 'string' && currency.length > 0 && { currency }),
				...(scopedSemantic && { semantic: scopedSemantic }),
				world: slotWorld(table, world)
			};
		});
	const arrows: Slot[] = (bundle.arrows ?? [])
		.filter((slot) => visible.has(slot.kind) && visible.has(slot.target) && scoped.has(slot.table))
		.map(({ id, kind, name, table, target, required, multivalued, world, semantic }) => {
			const scopedSemantic = semanticOf(semantic, visible);
			return {
				id, kind, name, table, target, required, multivalued,
				...(scopedSemantic && { semantic: scopedSemantic }),
				world: slotWorld(table, world)
			};
		});
	const visibleAttributes = new Set(attributes.map((slot) => slot.id));
	const visibleArrows = new Set(arrows.map((slot) => slot.id));
	const kinds: DeclaredKind[] = bundle.kinds
		.filter((kind) => visible.has(kind.id))
		.map(({ id, class: name, parent, world, iri, name_attribute, name_arrows }) => {
			const visibleNameArrows = (name_arrows ?? []).filter((arrowId) => visibleArrows.has(arrowId));
			return {
				id,
				class: name,
				world: full.has(id) ? worldOf(world) : 'open' as const,
				...(parent && visible.has(parent) && { parent }),
				...(iri && { iri }),
				...(typeof name_attribute === 'string' && visibleAttributes.has(name_attribute) && { name_attribute }),
				...(visibleNameArrows.length > 0 && { name_arrows: visibleNameArrows })
			};
		});

	const enums = new Set(attributes.flatMap((slot) => slot.enum ? [slot.enum] : []));
	const relations: DeclaredRelation[] = (bundle.relations ?? [])
		.filter((relation) => scoped.has(relation.id))
		.map(({ id, world, calc, outcome, semantic, columns }) => {
			const scopedSemantic = semanticOf(semantic, visible);
			return {
				id,
				world: full.has(id) ? worldOf(world) : 'open' as const,
				...(typeof calc === 'string' && calc.length > 0 && { calc }),
				...(typeof outcome === 'string' && visible.has(outcome) && { outcome }),
				...(scopedSemantic && { semantic: scopedSemantic }),
				columns: columns.map(({ name, currency, semantic: colSemantic }) => {
					const scopedColSemantic = semanticOf(colSemantic, visible);
					return {
						name,
						...(typeof currency === 'string' && currency.length > 0 && { currency }),
						...(scopedColSemantic && { semantic: scopedColSemantic })
					};
				})
			};
		});

	return {
		pack: { id: bundle.pack.id, base: bundle.pack.base },
		kinds,
		attributes,
		arrows,
		relations,
		enums: (bundle.enums ?? []).filter((entry) => enums.has(entry.id)).map(({ id, values }) => ({ id, values }))
	};
}

export function roleBundle(bundle: Bundle, snapshots: RoleSnapshot[]): RoleBundle {
	const catalogue = roleCatalogue(bundle, snapshots);
	const scoped = new Set(snapshots.map((snapshot) => snapshot.relation));
	const rules = (bundle.rules ?? []).filter((rule) => ruleReadable(rule, scoped));

	const labeled = new Set<string>([
		...catalogue.kinds.map((kind) => kind.id),
		...catalogue.attributes.map((slot) => slot.id),
		...catalogue.arrows.map((slot) => slot.id),
		...catalogue.relations.map((relation) => relation.id),
		...rules.map((rule) => rule.id)
	]);
	const labels: Label[] = (bundle.labels ?? [])
		.filter((label) => labeled.has(label.element))
		.map(({ element, lang, text, gender }) => ({
			element,
			lang,
			text,
			...(gender !== undefined ? { gender } : {})
		}));

	const allKinds = new Set(bundle.kinds.map((kind) => kind.id));
	const visibleKinds = new Set(catalogue.kinds.map((kind) => kind.id));
	const allSlots = [...(bundle.attributes ?? []), ...(bundle.arrows ?? [])];
	const visibleSlots = [...catalogue.attributes, ...catalogue.arrows];
	const allSlotIds = new Set(allSlots.map((slot) => slot.id));
	const visibleSlotIds = new Set(visibleSlots.map((slot) => slot.id));
	const allSlotTables = new Set(allSlots.map((slot) => slot.table));
	const visibleSlotTables = new Set(visibleSlots.map((slot) => slot.table));
	const allRelations = new Set((bundle.relations ?? []).map((relation) => relation.id));
	const visibleRelations = new Set(catalogue.relations.map((relation) => relation.id));
	const allCalcs = new Set((bundle.relations ?? []).flatMap((relation) => relation.calc ? [relation.calc] : []));
	const visibleCalcs = new Set(catalogue.relations.flatMap((relation) => relation.calc ? [relation.calc] : []));
	const allRules = new Set((bundle.rules ?? []).map((rule) => rule.id));
	const visibleRuleIds = new Set(rules.map((rule) => rule.id));
	const allRuleMessages = new Set((bundle.rules ?? []).flatMap((rule) => rule.message ? [rule.message] : []));
	const visibleRuleMessages = new Set(rules.flatMap((rule) => rule.message ? [rule.message] : []));
	const allChecks = new Set((bundle.checks ?? []).flatMap((check) =>
		check.relation ? [check.view, check.relation] : [check.view]));
	const hiddenReaderMessages = new Set<string>();
	for (const rq of bundle.reader_questions ?? []) {
		const readable = scoped.has(rq.relation)
			&& (rq.columns ?? []).every((col) => col.element === undefined || visibleKinds.has(col.element))
			&& (rq.context ?? []).every((ctx) => visibleKinds.has(ctx.kind));
		if (!readable) {
			hiddenReaderMessages.add(rq.title_message);
			hiddenReaderMessages.add(rq.about_message);
			for (const col of rq.columns ?? []) hiddenReaderMessages.add(col.message);
		}
	}

	const allowMessage = (id: string): boolean => {
		const parts = id.split('.');
		if (id.startsWith('check.') || allChecks.has(id) || parts.some((part) => allChecks.has(part))) return false;
		if (hiddenReaderMessages.has(id)) return false;

		if (allRuleMessages.has(id)) return visibleRuleMessages.has(id);
		if (id.startsWith('rule.')) {
			const rest = id.slice('rule.'.length);
			const first = rest.split('.')[0];
			if (allRules.has(rest)) return visibleRuleIds.has(rest);
			if (allRules.has(first)) return visibleRuleIds.has(first);
			if (allRelations.has(rest)) return visibleRelations.has(rest);
			if (allRelations.has(first)) return visibleRelations.has(first);
			if (allCalcs.has(rest)) return visibleCalcs.has(rest);
			if (allCalcs.has(first)) return visibleCalcs.has(first);
		}

		if (id.startsWith('kind.')) {
			const first = parts[1];
			if (first && allKinds.has(first)) return visibleKinds.has(first);
		}
		if (id.startsWith('slot.') || id.startsWith('arrow.') || id.startsWith('attr.') || id.startsWith('attribute.')) {
			const first = parts[1];
			const pair = parts.length >= 3 ? `${parts[1]}.${parts[2]}` : undefined;
			if (pair && allSlotIds.has(pair)) return visibleSlotIds.has(pair);
			if (first && allSlotTables.has(first)) return visibleSlotTables.has(first);
			if (first && allSlotIds.has(first)) return visibleSlotIds.has(first);
		}
		if (id.startsWith('relation.')) {
			const first = parts[1];
			if (first && allRelations.has(first)) return visibleRelations.has(first);
		}
		if (id.startsWith('calc.')) {
			const first = parts[1];
			if (first && allCalcs.has(first)) return visibleCalcs.has(first);
			if (first && allRelations.has(first)) return visibleRelations.has(first);
		}
		if (id.startsWith('unique_key.') || id.startsWith('path_equation.')) {
			const first = parts[1];
			if (first && allKinds.has(first)) return visibleKinds.has(first);
		}

		if (STANDARD_MESSAGES.has(id) && !allSlotIds.has(id)) return true;

		for (let i = 0; i < parts.length; i++) {
			if (allSlotTables.has(parts[i]) && !visibleSlotTables.has(parts[i])) return false;
			if (i + 1 < parts.length) {
				const pair = `${parts[i]}.${parts[i + 1]}`;
				if (allSlotIds.has(pair) && !visibleSlotIds.has(pair)) return false;
			}
		}

		const head = parts[0];
		const headPair = parts.length >= 2 ? `${parts[0]}.${parts[1]}` : undefined;
		if (headPair && allSlotIds.has(headPair)) return visibleSlotIds.has(headPair);
		if (allSlotTables.has(head)) return visibleSlotTables.has(head);
		if (allRules.has(head)) return visibleRuleIds.has(head);
		if (allRelations.has(head)) return visibleRelations.has(head);
		if (allKinds.has(head)) return visibleKinds.has(head);
		if (allCalcs.has(head)) return visibleCalcs.has(head);

		return true;
	};

	const messages = (bundle.messages ?? []).map((entry) => filterMessageResource(entry, allowMessage));
	const claim = (bundle.channels?.home?.claim ?? []).filter((relation) => scoped.has(relation));
	const questions = [...(bundle.questions ?? [])];

	return {
		...catalogue,
		rules,
		labels,
		messages,
		home: { claim },
		questions
	};
}
