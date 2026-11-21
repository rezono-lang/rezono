import type {
	Bundle,
	ChannelBinding,
	EdgeSource,
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

function semanticOf(
	value: unknown,
	visibleKinds: ReadonlySet<string>,
	visibleEnums: ReadonlySet<string>,
	visibleDerived: ReadonlySet<string>
): SemanticType | undefined {
	if (value === null || typeof value !== 'object' || Array.isArray(value)) return undefined;
	const raw = value as Record<string, unknown>;
	if (typeof raw.case !== 'string' || typeof raw.base !== 'string') return undefined;
	if (raw.case === 'ref' && typeof raw.target !== 'string') return undefined;
	if (raw.target !== undefined && (typeof raw.target !== 'string' || !visibleKinds.has(raw.target))) return undefined;
	if (raw.case === 'enum' && typeof raw.enum !== 'string') return undefined;
	if (raw.enum !== undefined && (typeof raw.enum !== 'string' || !visibleEnums.has(raw.enum))) return undefined;
	if (raw.case === 'derived' && typeof raw.derived !== 'string') return undefined;
	if (raw.derived !== undefined && (typeof raw.derived !== 'string' || !visibleDerived.has(raw.derived))) return undefined;
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

function addCalcNames(calc: unknown, target: Set<string>): void {
	if (typeof calc !== 'string' || !calc.length) return;
	target.add(calc);
	const at = calc.indexOf('@');
	if (at > 0) target.add(calc.slice(0, at));
}

function ruleReadable(rule: Rule, readableRelations: ReadonlySet<string>): boolean {
	const headRelation = rule.head ? rule.head.relation : rule.relation;
	if (typeof headRelation !== 'string' || !readableRelations.has(headRelation)) return false;
	if (rule.relation !== undefined && (typeof rule.relation !== 'string' || !readableRelations.has(rule.relation))) return false;
	if (!Array.isArray(rule.body)) return false;
	for (const literal of rule.body) {
		if (literal.kind === 'atom' || literal.kind === 'aggregate') {
			if (typeof literal.relation !== 'string' || !readableRelations.has(literal.relation)) return false;
		} else if (literal.kind === 'comparison' || literal.kind === 'assignment') {
			if (literal.relation !== undefined) return false;
		} else {
			return false;
		}
	}
	for (const agg of rule.aggregates ?? []) {
		if (typeof agg.relation !== 'string' || !readableRelations.has(agg.relation)) return false;
	}
	return true;
}

function filterReadable(
	filter: { kinds?: string[]; relations?: string[]; rules?: string[] } | undefined,
	visibleKinds: ReadonlySet<string>,
	readableRelations: ReadonlySet<string>,
	visibleRules: ReadonlySet<string>
): boolean {
	if (!filter) return true;
	if (filter.kinds !== undefined && (!Array.isArray(filter.kinds)
		|| !filter.kinds.every((kind) => typeof kind === 'string' && visibleKinds.has(kind)))) return false;
	if (filter.relations !== undefined && (!Array.isArray(filter.relations)
		|| !filter.relations.every((relation) => typeof relation === 'string' && readableRelations.has(relation)))) return false;
	if (filter.rules !== undefined && (!Array.isArray(filter.rules)
		|| !filter.rules.every((rule) => typeof rule === 'string' && visibleRules.has(rule)))) return false;
	return true;
}

function questionReadable(
	question: Question,
	visibleKinds: ReadonlySet<string>,
	readableRelations: ReadonlySet<string>,
	visibleRules: ReadonlySet<string>
): boolean {
	if (!filterReadable(question.applies_to, visibleKinds, readableRelations, visibleRules)) return false;
	if (!Array.isArray(question.steps)) return false;
	for (const step of question.steps) {
		if (!step || typeof step !== 'object' || (!step.trace && !step.suppose)) return false;
		if (step.trace) {
			if (!filterReadable(step.trace.keep, visibleKinds, readableRelations, visibleRules)) return false;
			if (!filterReadable(step.trace.stop, visibleKinds, readableRelations, visibleRules)) return false;
		}
		if (step.suppose && step.suppose.over !== undefined) return false;
	}
	return true;
}

function addChannelBindingMessages(binding: ChannelBinding | undefined, target: Set<string>): void {
	if (!binding) return;
	if (typeof binding.meaning_message === 'string') target.add(binding.meaning_message);
	if (typeof binding.scale?.unit_message === 'string') target.add(binding.scale.unit_message);
}

function collectHiddenChannelMessages(
	bundle: Bundle,
	visibleKinds: ReadonlySet<string>,
	visibleSlotIds: ReadonlySet<string>,
	visibleSlotTables: ReadonlySet<string>,
	readableRelations: ReadonlySet<string>
): Set<string> {
	const hidden = new Set<string>();
	const channels = bundle.channels;
	if (!channels) return hidden;

	const slotVisible = (slot: string | undefined): boolean =>
		typeof slot === 'string' && (visibleSlotIds.has(slot) || visibleSlotTables.has(slot));
	const edgeVisible = (edge: EdgeSource | undefined): boolean => {
		if (!edge) return false;
		if (edge.arrow !== undefined) return slotVisible(edge.arrow);
		if (edge.via !== undefined) {
			return visibleKinds.has(edge.via) && slotVisible(edge.from) && slotVisible(edge.to)
				&& (edge.quantity === undefined || slotVisible(edge.quantity.slot));
		}
		if (edge.relation !== undefined) {
			return readableRelations.has(edge.relation)
				&& (edge.from_kinds ?? []).every((kind) => visibleKinds.has(kind))
				&& (edge.to_kinds ?? []).every((kind) => visibleKinds.has(kind));
		}
		return false;
	};

	const relief = channels.relief;
	if (relief) {
		const visible = visibleKinds.has(relief.region) && slotVisible(relief.member)
			&& (relief.label === undefined || slotVisible(relief.label))
			&& (relief.height === undefined || slotVisible(relief.height.slot));
		if (!visible) addChannelBindingMessages(relief.height, hidden);
	}

	for (const flow of channels.flows ?? []) {
		const nodesVisible = (flow.nodes ?? []).every((node) =>
			visibleKinds.has(node.kind)
			&& (node.label === undefined || slotVisible(node.label))
			&& (node.group === undefined || slotVisible(node.group))
			&& (node.lane === undefined || slotVisible(node.lane.slot)));
		const edgesVisible = (flow.edges ?? []).every((edge) => edgeVisible(edge));
		const routesVisible = flow.routes === undefined || edgeVisible(flow.routes);
		if (!(nodesVisible && edgesVisible && routesVisible)) {
			if (typeof flow.title_message === 'string') hidden.add(flow.title_message);
			for (const node of flow.nodes ?? []) addChannelBindingMessages(node.lane, hidden);
			for (const edge of flow.edges ?? []) addChannelBindingMessages(edge.quantity, hidden);
			addChannelBindingMessages(flow.routes?.quantity, hidden);
		}
	}

	const visibleMatrices = new Set<string>();
	for (const matrix of channels.matrices ?? []) {
		const visible = visibleKinds.has(matrix.rows?.kind)
			&& (matrix.rows?.lane === undefined || slotVisible(matrix.rows.lane.slot))
			&& visibleKinds.has(matrix.columns?.kind)
			&& (matrix.columns?.lane === undefined || slotVisible(matrix.columns.lane.slot))
			&& edgeVisible(matrix.cells);
		if (visible) {
			visibleMatrices.add(matrix.id);
		} else {
			if (typeof matrix.title_message === 'string') hidden.add(matrix.title_message);
			addChannelBindingMessages(matrix.rows?.lane, hidden);
			addChannelBindingMessages(matrix.columns?.lane, hidden);
			addChannelBindingMessages(matrix.cells?.quantity, hidden);
		}
	}

	for (const tl of channels.timelines ?? []) {
		const visible = visibleKinds.has(tl.rows)
			&& slotVisible(tl.start)
			&& slotVisible(tl.end)
			&& (tl.label === undefined || slotVisible(tl.label))
			&& (tl.extension === undefined || slotVisible(tl.extension))
			&& (tl.judgement === undefined || slotVisible(tl.judgement.slot))
			&& (tl.marks ?? []).every((mark) => slotVisible(mark.slot));
		if (!visible) {
			if (typeof tl.title_message === 'string') hidden.add(tl.title_message);
			if (typeof tl.main_message === 'string') hidden.add(tl.main_message);
			if (typeof tl.extension_message === 'string') hidden.add(tl.extension_message);
			addChannelBindingMessages(tl.judgement, hidden);
		}
	}

	for (const nest of channels.nests ?? []) {
		const baseVisible = (nest.levels ?? []).every((level) =>
			visibleKinds.has(level.kind)
			&& (level.part_of === undefined || slotVisible(level.part_of))
			&& (level.label === undefined || slotVisible(level.label)));
		if (!baseVisible) {
			if (typeof nest.title_message === 'string') hidden.add(nest.title_message);
			if (typeof nest.part_message === 'string') hidden.add(nest.part_message);
			for (const level of nest.levels ?? []) {
				if (typeof level.order_message === 'string') hidden.add(level.order_message);
			}
		}
		for (const perspective of nest.perspectives ?? []) {
			const visible = baseVisible && (perspective.relation === undefined || readableRelations.has(perspective.relation));
			if (!visible) {
				if (typeof perspective.label_message === 'string') hidden.add(perspective.label_message);
				addChannelBindingMessages(perspective.state, hidden);
			}
		}
	}

	for (const report of channels.reports ?? []) {
		const visible = (report.parts ?? []).every((part) => {
			if (part.cards) return visibleKinds.has(part.cards.kind) && (part.cards.fields ?? []).every(slotVisible);
			if (part.waterfall) return slotVisible(part.waterfall.slot);
			if (part.matrix) return visibleMatrices.has(part.matrix.sheet);
			if (part.comparison) return readableRelations.has(part.comparison.relation);
			return false;
		});
		if (!visible && typeof report.title_message === 'string') hidden.add(report.title_message);
	}

	return hidden;
}

function filterMessageResource(entry: MessageResource, allow: (id: string) => boolean): MessageResource {
	const normalized = entry.resource.replace(/\r\n/g, '\n');
	const sep = normalized.indexOf('\n---\n');
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
	return { lang: entry.lang, resource: `@locale ${entry.lang}\n---\n${kept.join('')}` };
}

export function roleCatalogue(bundle: Bundle, snapshots: RoleSnapshot[]): RoleCatalogue {
	const scoped = new Set(snapshots.map((snapshot) => snapshot.relation));
	const full = new Set(snapshots.filter((snapshot) => snapshot.complete || snapshot.full).map((s) => s.relation));
	const slotWorld = (table: string, declared: unknown): World => full.has(table) ? worldOf(declared) ?? 'closed' : 'open';
	const visible = new Set((bundle.kinds ?? []).filter((kind) => scoped.has(kind.id)).map((kind) => kind.id));

	const visibleAttributesRaw = (bundle.attributes ?? [])
		.filter((slot) => visible.has(slot.kind) && scoped.has(slot.table));
	const visibleArrowsRaw = (bundle.arrows ?? [])
		.filter((slot) => visible.has(slot.kind) && visible.has(slot.target) && scoped.has(slot.table));
	const visibleRelationsRaw = (bundle.relations ?? [])
		.filter((relation) => scoped.has(relation.id));

	const visibleDerived = new Set<string>();
	for (const relation of visibleRelationsRaw) {
		visibleDerived.add(relation.id);
		if (typeof relation.calc === 'string' && relation.calc.length > 0) {
			visibleDerived.add(relation.calc);
		}
	}

	const declaredEnums = new Set((bundle.enums ?? []).map((entry) => entry.id));
	const visibleEnums = new Set<string>();
	const collectSemanticEnum = (value: unknown): void => {
		if (value === null || typeof value !== 'object' || Array.isArray(value)) return;
		const raw = value as Record<string, unknown>;
		if (typeof raw.case !== 'string' || typeof raw.base !== 'string') return;
		if (raw.case === 'ref' && typeof raw.target !== 'string') return;
		if (raw.target !== undefined && (typeof raw.target !== 'string' || !visible.has(raw.target))) return;
		if (raw.case === 'derived' && typeof raw.derived !== 'string') return;
		if (raw.derived !== undefined && (typeof raw.derived !== 'string' || !visibleDerived.has(raw.derived))) return;
		if (typeof raw.enum === 'string' && declaredEnums.has(raw.enum)) {
			visibleEnums.add(raw.enum);
		}
	};
	for (const slot of visibleAttributesRaw) {
		if (typeof slot.enum === 'string' && declaredEnums.has(slot.enum)) {
			visibleEnums.add(slot.enum);
		}
		collectSemanticEnum(slot.semantic);
	}
	for (const slot of visibleArrowsRaw) {
		collectSemanticEnum(slot.semantic);
	}
	for (const relation of visibleRelationsRaw) {
		collectSemanticEnum(relation.semantic);
		for (const col of relation.columns ?? []) {
			collectSemanticEnum(col.semantic);
		}
	}

	const attributes: Slot[] = visibleAttributesRaw
		.map(({ id, kind, name, table, type, schema_type, enum: enumerated, minimum, maximum, patterns, required, multivalued, world, currency, semantic }) => {
			const scopedSemantic = semanticOf(semantic, visible, visibleEnums, visibleDerived);
			const scopedEnum = typeof enumerated === 'string' && visibleEnums.has(enumerated) ? enumerated : undefined;
			return {
				id, kind, name, table, type, schema_type, enum: scopedEnum, minimum, maximum, patterns, required, multivalued,
				...(typeof currency === 'string' && currency.length > 0 && { currency }),
				...(scopedSemantic && { semantic: scopedSemantic }),
				world: slotWorld(table, world)
			};
		});
	const arrows: Slot[] = visibleArrowsRaw
		.map(({ id, kind, name, table, target, required, multivalued, world, semantic }) => {
			const scopedSemantic = semanticOf(semantic, visible, visibleEnums, visibleDerived);
			return {
				id, kind, name, table, target, required, multivalued,
				...(scopedSemantic && { semantic: scopedSemantic }),
				world: slotWorld(table, world)
			};
		});
	const visibleAttributes = new Set(attributes.map((slot) => slot.id));
	const visibleArrows = new Set(arrows.map((slot) => slot.id));
	const kinds: DeclaredKind[] = (bundle.kinds ?? [])
		.filter((kind) => visible.has(kind.id))
		.map(({ id, class: name, parent, world, iri, name_attribute, name_arrows }) => {
			const visibleNameArrows = Array.isArray(name_arrows)
				? name_arrows.filter((arrowId): arrowId is string => typeof arrowId === 'string' && visibleArrows.has(arrowId))
				: [];
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

	const relations: DeclaredRelation[] = visibleRelationsRaw
		.map(({ id, world, calc, outcome, semantic, columns }) => {
			const scopedSemantic = semanticOf(semantic, visible, visibleEnums, visibleDerived);
			return {
				id,
				world: full.has(id) ? worldOf(world) : 'open' as const,
				...(typeof calc === 'string' && calc.length > 0 && { calc }),
				...(typeof outcome === 'string' && visible.has(outcome) && { outcome }),
				...(scopedSemantic && { semantic: scopedSemantic }),
				columns: (columns ?? []).map(({ name, currency, semantic: colSemantic }) => {
					const scopedColSemantic = semanticOf(colSemantic, visible, visibleEnums, visibleDerived);
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
		enums: (bundle.enums ?? []).filter((entry) => visibleEnums.has(entry.id)).map(({ id, values }) => ({ id, values }))
	};
}

export function roleBundle(bundle: Bundle, snapshots: RoleSnapshot[]): RoleBundle {
	const catalogue = roleCatalogue(bundle, snapshots);
	const scoped = new Set(snapshots.map((snapshot) => snapshot.relation));

	const allKinds = new Set((bundle.kinds ?? []).map((kind) => kind.id));
	const visibleKinds = new Set(catalogue.kinds.map((kind) => kind.id));
	const allSlots = [...(bundle.attributes ?? []), ...(bundle.arrows ?? [])];
	const visibleSlots = [...catalogue.attributes, ...catalogue.arrows];
	const allSlotIds = new Set(allSlots.map((slot) => slot.id));
	const visibleSlotIds = new Set(visibleSlots.map((slot) => slot.id));
	const allSlotTables = new Set(allSlots.map((slot) => slot.table));
	const visibleSlotTables = new Set(visibleSlots.map((slot) => slot.table));
	const allRelations = new Set((bundle.relations ?? []).map((relation) => relation.id));
	const visibleRelations = new Set(catalogue.relations.map((relation) => relation.id));
	const allEnums = new Set((bundle.enums ?? []).map((entry) => entry.id));
	const visibleEnums = new Set(catalogue.enums.map((entry) => entry.id));

	const hiddenKinds = new Set([...allKinds].filter((id) => !visibleKinds.has(id)));
	const hiddenSlotIds = new Set([...allSlotIds].filter((id) => !visibleSlotIds.has(id)));
	const hiddenSlotTables = new Set([...allSlotTables].filter((table) => !visibleSlotTables.has(table)));
	const hiddenRelations = new Set([...allRelations].filter((id) => !visibleRelations.has(id)));
	const hiddenEnums = new Set([...allEnums].filter((id) => !visibleEnums.has(id)));

	const readableRuleRelations = new Set(
		[...scoped].filter((relation) =>
			!hiddenKinds.has(relation)
			&& !hiddenSlotTables.has(relation)
			&& !hiddenRelations.has(relation)
			&& !hiddenEnums.has(relation))
	);
	const rules = (bundle.rules ?? []).filter((rule) => ruleReadable(rule, readableRuleRelations));

	const labeled = new Set<string>([
		...catalogue.kinds.map((kind) => kind.id),
		...catalogue.attributes.map((slot) => slot.id),
		...catalogue.arrows.map((slot) => slot.id),
		...catalogue.relations.map((relation) => relation.id),
		...catalogue.enums.map((entry) => entry.id),
		...catalogue.enums.flatMap((entry) => entry.values ?? []),
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

	const allCalcs = new Set<string>();
	for (const relation of bundle.relations ?? []) addCalcNames(relation.calc, allCalcs);
	const visibleCalcs = new Set<string>();
	for (const relation of catalogue.relations) addCalcNames(relation.calc, visibleCalcs);
	const hiddenCalcs = new Set([...allCalcs].filter((name) => !visibleCalcs.has(name)));

	const allRules = new Set((bundle.rules ?? []).map((rule) => rule.id));
	const visibleRuleIds = new Set(rules.map((rule) => rule.id));
	const hiddenRules = new Set([...allRules].filter((id) => !visibleRuleIds.has(id)));
	const allRuleMessages = new Set((bundle.rules ?? []).flatMap((rule) => rule.message ? [rule.message] : []));
	const visibleRuleMessages = new Set(rules.flatMap((rule) => rule.message ? [rule.message] : []));
	const hiddenRuleMessages = new Set([...allRuleMessages].filter((msg) => !visibleRuleMessages.has(msg)));

	const allEnumValues = new Set((bundle.enums ?? []).flatMap((entry) => entry.values ?? []));
	const visibleEnumValues = new Set(catalogue.enums.flatMap((entry) => entry.values ?? []));
	const hiddenEnumValues = new Set([...allEnumValues].filter((value) => !visibleEnumValues.has(value)));
	const bareValue = (value: string): string | undefined => {
		const dot = value.indexOf('.');
		return dot >= 0 && dot + 1 < value.length ? value.slice(dot + 1) : undefined;
	};
	const allEnumBareValues = new Set([...allEnumValues].flatMap((value) => {
		const bare = bareValue(value);
		return bare ? [bare] : [];
	}));
	const visibleEnumBareValues = new Set([...visibleEnumValues].flatMap((value) => {
		const bare = bareValue(value);
		return bare ? [bare] : [];
	}));
	const hiddenEnumBareValues = new Set([...allEnumBareValues].filter((bare) =>
		!visibleEnumBareValues.has(bare)
		&& !visibleKinds.has(bare)
		&& !visibleRelations.has(bare)
		&& !visibleRuleIds.has(bare)
		&& !visibleCalcs.has(bare)
		&& !visibleEnums.has(bare)));

	const allChecks = new Set<string>();
	for (const check of bundle.checks ?? []) {
		allChecks.add(check.view);
		if (check.relation) allChecks.add(check.relation);
	}
	for (const relation of bundle.relations ?? []) {
		for (const checkName of relation.checks ?? []) allChecks.add(checkName);
	}

	const questions: Question[] = [];
	const visibleQuestionTerms = new Set<string>();
	const hiddenQuestionTerms = new Set<string>();
	for (const question of bundle.questions ?? []) {
		if (questionReadable(question, visibleKinds, readableRuleRelations, visibleRuleIds)) {
			questions.push(question);
			visibleQuestionTerms.add(question.term);
		} else {
			hiddenQuestionTerms.add(question.term);
		}
	}

	const hiddenReaderMessages = new Set<string>();
	for (const rq of bundle.reader_questions ?? []) {
		const readable = readableRuleRelations.has(rq.relation)
			&& (rq.columns ?? []).every((col) => col.element === undefined || visibleKinds.has(col.element))
			&& (rq.context ?? []).every((ctx) =>
				visibleKinds.has(ctx.kind)
				&& (ctx.fields ?? []).every((entry) => {
					const fieldId = typeof entry === 'string' ? entry : entry?.field;
					return typeof fieldId === 'string' && visibleSlotIds.has(fieldId);
				}));
		if (!readable) {
			hiddenReaderMessages.add(rq.title_message);
			hiddenReaderMessages.add(rq.about_message);
			for (const col of rq.columns ?? []) hiddenReaderMessages.add(col.message);
		}
	}

	const hiddenChannelMessages = collectHiddenChannelMessages(
		bundle,
		visibleKinds,
		visibleSlotIds,
		visibleSlotTables,
		readableRuleRelations
	);

	const readableReasonColumn = new Map<string, number>();
	for (const relation of bundle.relations ?? []) {
		if (!readableRuleRelations.has(relation.id)) continue;
		const cols = relation.columns ?? [];
		const reasonIdx = cols.findIndex((col) => col.name === 'reason');
		if (reasonIdx >= 0) {
			readableReasonColumn.set(relation.id, reasonIdx);
		} else if (typeof relation.outcome === 'string' && relation.outcome.length > 0 && cols.length > 2) {
			readableReasonColumn.set(relation.id, 2);
		}
	}
	const visibleReasonCodes = new Set<string>();
	const addReasonTerm = (term: { kind?: string; value?: unknown } | undefined): void => {
		if (term && term.kind === 'constant' && typeof term.value === 'string' && term.value.length > 0) {
			visibleReasonCodes.add(term.value);
		}
	};
	for (const rule of bundle.rules ?? []) {
		const headRelation = rule.head ? rule.head.relation : rule.relation;
		if (typeof headRelation !== 'string') continue;
		const reasonIdx = readableReasonColumn.get(headRelation);
		if (reasonIdx === undefined) continue;
		addReasonTerm(rule.head?.terms?.[reasonIdx]);
	}
	for (const rule of rules) {
		for (const literal of rule.body ?? []) {
			if (literal.kind !== 'atom' || typeof literal.relation !== 'string') continue;
			const reasonIdx = readableReasonColumn.get(literal.relation);
			if (reasonIdx === undefined) continue;
			addReasonTerm(literal.terms?.[reasonIdx]);
		}
	}

	const allowMessage = (id: string): boolean => {
		const parts = id.split('.');
		if (id.startsWith('check.') || allChecks.has(id) || parts.some((part) => allChecks.has(part))) return false;
		if (hiddenRuleMessages.has(id) || hiddenReaderMessages.has(id) || hiddenChannelMessages.has(id)) return false;
		if (parts[0] === 'explain' && parts[1] && hiddenQuestionTerms.has(parts[1])) return false;

		if (parts[0] === 'reason') {
			if (parts.length < 2) return false;
			const code = id.slice('reason.'.length);
			return code.length > 0 && visibleReasonCodes.has(code);
		}

		if (parts[0] === 'rule' && parts.length >= 2) {
			const rest = id.slice('rule.'.length);
			const first = parts[1];
			if (hiddenRules.has(rest) || hiddenRules.has(first)) return false;
			if (hiddenRelations.has(rest) || hiddenRelations.has(first)) return false;
			if (hiddenCalcs.has(rest) || hiddenCalcs.has(first)) return false;
		}
		if (parts[0] === 'enum' && parts[1] && (hiddenEnums.has(parts[1]) || hiddenEnumBareValues.has(parts[1]))) return false;

		if (STANDARD_MESSAGES.has(id) && !hiddenSlotIds.has(id) && !hiddenEnumValues.has(id)) return true;

		const isVisibleQuestionMessage = parts[0] === 'explain' && parts[1] !== undefined
			&& visibleQuestionTerms.has(parts[1])
			&& (parts.length === 2 || (parts.length === 3 && parts[2] === 'question'));
		if (isVisibleQuestionMessage) return true;

		const start = parts[0] === 'rule' && visibleRuleMessages.has(id) ? 1 : 0;
		for (let i = start; i < parts.length; i++) {
			const seg = parts[i];
			if (hiddenKinds.has(seg) || hiddenSlotTables.has(seg) || hiddenRelations.has(seg)
				|| hiddenRules.has(seg) || hiddenCalcs.has(seg) || hiddenEnums.has(seg)
				|| hiddenEnumBareValues.has(seg)) {
				return false;
			}
			if (i + 1 < parts.length) {
				const pair = `${seg}.${parts[i + 1]}`;
				if (hiddenSlotIds.has(pair) || hiddenEnumValues.has(pair)) return false;
			}
		}

		return true;
	};

	const messages = (bundle.messages ?? []).map((entry) => filterMessageResource(entry, allowMessage));
	const claim = (bundle.channels?.home?.claim ?? []).filter((relation) => readableRuleRelations.has(relation));

	return {
		...catalogue,
		rules,
		labels,
		messages,
		home: { claim },
		questions
	};
}
