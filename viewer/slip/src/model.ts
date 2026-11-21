import { fill, fillParts } from '../../messages/src/fill.ts';
import type { CalcStep } from '../../../contracts/typescript/generated/proof.ts';
import type {
	AnswerTable,
	AnswerTableRow,
	ExplainAnswer,
	FetchLike,
	GroundsNode,
	GroundsStep,
	HeadResponse,
	LineVerb,
	RoleBundleResponse,
	RowSelection,
	SentenceSegment,
	SignInfo,
	SlipLine,
	SlipView,
	StdPacks,
	ValueState,
} from './types.ts';

interface RuleTermLike {
	kind?: string;
	value?: string;
}

interface RuleLiteralLike {
	kind?: string;
	position?: number;
	polarity?: string;
	relation?: string;
	terms?: RuleTermLike[];
	result?: RuleTermLike;
}

interface RuleLike {
	id: string;
	message?: string;
	body?: RuleLiteralLike[];
}

interface AggregateWitnessLike {
	relation: string;
	position?: number;
	group_key: string;
	count: number;
	result: string;
}

function canonicalKey(parts: readonly string[]): string {
	return JSON.stringify(parts.map(String));
}

function parseKey(raw: string): string[] {
	try {
		const parsed: unknown = JSON.parse(raw);
		if (Array.isArray(parsed) && parsed.every((p) => typeof p === 'string')) {
			return parsed;
		}
	} catch {
		// fall through
	}
	return [raw];
}

function stripQuestionPrefix(name: string): string {
	return name.startsWith('?') ? name.slice(1) : name;
}

function rowId(relation: string, key: string): string {
	return `${relation}\u0000${key}`;
}

export function parseStateValue(raw: string): { state: ValueState; value: string; reason: string } {
	if (raw.startsWith('known:')) {
		return { state: 'known', value: raw.slice('known:'.length), reason: '' };
	}
	for (const state of ['unknown', 'not_applicable', 'invalid'] as const) {
		if (raw === state) {
			return { state, value: '', reason: '' };
		}
		if (raw.startsWith(`${state}:`)) {
			return { state, value: '', reason: raw.slice(state.length + 1) };
		}
	}
	return { state: 'known', value: raw, reason: '' };
}

function viewMessage(
	stdPacks: StdPacks,
	lang: string,
	id: string,
	args: Record<string, string | number | boolean> = {},
): string {
	return (
		fill(stdPacks.viewMessages, lang, id, args) ??
		fill(stdPacks.viewMessages, 'en', id, args) ??
		id
	);
}

function explainMessage(
	stdPacks: StdPacks,
	lang: string,
	id: string,
	args: Record<string, string | number | boolean> = {},
): string | undefined {
	return (
		fill(stdPacks.explainMessages, lang, id, args) ??
		fill(stdPacks.explainMessages, 'en', id, args)
	);
}

function buildSignCatalog(stdPacks: StdPacks, lang: string): SignInfo[] {
	const catalog: SignInfo[] = [];
	const seen = new Set<string>();
	for (const status of stdPacks.statuses) {
		if (seen.has(status.status)) continue;
		seen.add(status.status);
		catalog.push({
			name: status.status,
			glyph: status.glyph ?? '',
			label: viewMessage(stdPacks, lang, status.label_message),
		});
	}
	for (const sign of stdPacks.signs) {
		if (seen.has(sign.sign)) continue;
		seen.add(sign.sign);
		catalog.push({
			name: sign.sign,
			glyph: sign.glyph ?? '',
			label: viewMessage(stdPacks, lang, sign.label_message),
			form: sign.form,
		});
	}
	return catalog;
}

function signByName(catalog: readonly SignInfo[], name: string): SignInfo | undefined {
	return catalog.find((entry) => entry.name === name);
}

function stateSign(catalog: readonly SignInfo[], state: ValueState): SignInfo | undefined {
	if (state === 'known') return undefined;
	if (state === 'invalid') return signByName(catalog, 'violated');
	return signByName(catalog, state);
}

function formatNonKnownText(
	bundle: RoleBundleResponse,
	stdPacks: StdPacks,
	lang: string,
	state: ValueState,
	reason: string,
): string {
	const stateLabel = viewMessage(stdPacks, lang, `status.${state}`);
	if (!reason) {
		return stateLabel;
	}
	const packReason = fill(bundle.messages, lang, `reason.${reason}`, {});
	const reasonText = packReason ?? reason;
	return viewMessage(stdPacks, lang, 'value.reason', {
		value: stateLabel,
		reason: reasonText,
	});
}

function labelOf(bundle: RoleBundleResponse, lang: string, element: string): string {
	const direct = bundle.labels.find((l) => l.element === element && l.lang === lang);
	if (direct) return direct.text;
	const slot =
		bundle.attributes.find((a) => a.table === element) ??
		bundle.arrows.find((a) => a.table === element);
	if (slot) {
		const slotLabel = bundle.labels.find((l) => l.element === slot.id && l.lang === lang);
		if (slotLabel) return slotLabel.text;
	}
	return element;
}

function calcLeafLabel(bundle: RoleBundleResponse, lang: string, step: CalcStep): string {
	if (step.ref) {
		const direct = bundle.labels.find((l) => l.element === step.ref && l.lang === lang);
		if (direct) return direct.text;
	}
	if (step.relation) {
		const relLabel = labelOf(bundle, lang, step.relation);
		if (relLabel !== step.relation) return relLabel;
	}
	return step.ref ?? step.relation ?? step.op;
}

function formatLineLabel(
	bundle: RoleBundleResponse,
	lang: string,
	stdPacks: StdPacks,
	relation: string,
	keyParts: readonly string[],
	polarity: 'positive' | 'negative',
): string {
	const relLabel = labelOf(bundle, lang, relation);
	const sep = viewMessage(stdPacks, lang, 'value.separator');
	if (polarity === 'negative') {
		return viewMessage(stdPacks, lang, 'lead.absent', {
			relation: relLabel,
			row: keyParts.join(sep),
		});
	}
	const isSlot =
		bundle.attributes.some((a) => a.table === relation) ||
		bundle.arrows.some((a) => a.table === relation);
	if (isSlot && keyParts.length >= 2) {
		return viewMessage(stdPacks, lang, 'lead.row', {
			relation: relLabel,
			row: keyParts[0],
		});
	}
	return relLabel;
}

function formatLineValue(
	bundle: RoleBundleResponse,
	lang: string,
	stdPacks: StdPacks,
	catalog: readonly SignInfo[],
	relation: string,
	keyParts: readonly string[],
	polarity: 'positive' | 'negative',
	stepValue: string | undefined,
): { state: ValueState; value: string; reason: string; valueSign?: SignInfo } {
	if (polarity === 'negative') {
		return {
			state: 'absent',
			value: formatNonKnownText(bundle, stdPacks, lang, 'absent', ''),
			reason: '',
			valueSign: stateSign(catalog, 'absent'),
		};
	}
	if (stepValue !== undefined) {
		const parsed = parseStateValue(stepValue);
		if (parsed.state !== 'known') {
			return {
				state: parsed.state,
				value: formatNonKnownText(bundle, stdPacks, lang, parsed.state, parsed.reason),
				reason: parsed.reason,
				valueSign: stateSign(catalog, parsed.state),
			};
		}
		return parsed;
	}
	const sep = viewMessage(stdPacks, lang, 'value.separator');
	const isSlot =
		bundle.attributes.some((a) => a.table === relation) ||
		bundle.arrows.some((a) => a.table === relation);
	if (isSlot && keyParts.length >= 2) {
		return { state: 'known', value: keyParts.slice(1).join(sep), reason: '' };
	}
	return { state: 'known', value: keyParts.join(sep), reason: '' };
}

function formatOrigin(
	bundle: RoleBundleResponse,
	lang: string,
	stdPacks: StdPacks,
	catalog: readonly SignInfo[],
	node: GroundsNode,
	answer: ExplainAnswer,
	polarity: 'positive' | 'negative',
): { origin: string; originSign?: SignInfo } {
	if (polarity === 'negative') {
		return { origin: viewMessage(stdPacks, lang, 'status.absent') };
	}
	if (node.sources && node.sources.length > 0) {
		const first = node.sources[0];
		return { origin: first.position ? `${first.name}:${first.position}` : first.name };
	}
	const witness = (answer.witnesses ?? []).find(
		(w) => w.conclusion.relation === node.relation && w.conclusion.key === node.key,
	);
	if (witness) {
		return {
			origin: labelOf(bundle, lang, witness.rule_id),
			originSign: signByName(catalog, 'derived'),
		};
	}
	const calcWitness = (answer.calc_witnesses ?? []).find(
		(cw) => cw.conclusion.relation === node.relation && cw.conclusion.key === node.key,
	);
	if (calcWitness) {
		return {
			origin: labelOf(bundle, lang, calcWitness.rule),
			originSign: signByName(catalog, 'derived'),
		};
	}
	return { origin: '' };
}

function buildSeal(
	head: HeadResponse,
	lang: string,
	stdPacks: StdPacks,
	catalog: readonly SignInfo[],
) {
	return {
		manifestSha256: head.manifest_sha256,
		witnessCheck: head.witness_check,
		manifestLabel: viewMessage(stdPacks, lang, 'cartouche.manifest'),
		readerHashesLabel: viewMessage(stdPacks, lang, 'sign.sealed'),
		sealSign: signByName(catalog, 'sealed'),
	};
}

function buildHeaders(lang: string, stdPacks: StdPacks) {
	return {
		line: viewMessage(stdPacks, lang, 'waterfall.row'),
		value: viewMessage(stdPacks, lang, 'answer.value'),
		origin: viewMessage(stdPacks, lang, 'zone.rests'),
		verbs: viewMessage(stdPacks, lang, 'zone.verbs'),
	};
}

function buildLegendHeaders(lang: string, stdPacks: StdPacks) {
	return {
		title: viewMessage(stdPacks, lang, 'key.title'),
		sign: viewMessage(stdPacks, lang, 'specimen.column.sign'),
		meaning: viewMessage(stdPacks, lang, 'specimen.column.meaning'),
	};
}

function formatRowRefText(
	bundle: RoleBundleResponse,
	stdPacks: StdPacks,
	lang: string,
	relation: string,
	key: string,
): string {
	const sep = viewMessage(stdPacks, lang, 'value.separator');
	const parts = parseKey(key);
	return viewMessage(stdPacks, lang, 'lead.row', {
		relation: labelOf(bundle, lang, relation),
		row: parts.join(sep),
	});
}

export function buildAnswerTable(
	bundle: RoleBundleResponse,
	stdPacks: StdPacks,
	lang: string,
	questionTerm: string,
	shape: string,
	answer: ExplainAnswer,
	catalog: readonly SignInfo[],
): AnswerTable {
	const elementText = answer.start
		? formatRowRefText(bundle, stdPacks, lang, answer.start.relation, answer.start.key)
		: questionTerm;
	const heading =
		explainMessage(stdPacks, lang, `explain.${questionTerm}.question`, { element: elementText }) ??
		explainMessage(stdPacks, lang, `explain.${questionTerm}`) ??
		questionTerm;
	const moreLabel =
		answer.more && answer.more.length > 0
			? explainMessage(stdPacks, lang, 'explain.more')
			: undefined;

	if (shape === 'route') {
		const headers = [
			viewMessage(stdPacks, lang, 'answer.distance'),
			viewMessage(stdPacks, lang, 'waterfall.row'),
			viewMessage(stdPacks, lang, 'answer.value'),
			viewMessage(stdPacks, lang, 'zone.rests'),
		];
		const stepsByPremise = new Map<string, GroundsStep[]>();
		for (const step of answer.steps ?? []) {
			const id = rowId(step.premise.relation, step.premise.key);
			const list = stepsByPremise.get(id);
			if (list) list.push(step);
			else stepsByPremise.set(id, [step]);
		}
		const rows: AnswerTableRow[] = answer.nodes.map((node) => {
			if (node.outside) {
				const outsideText =
					explainMessage(stdPacks, lang, 'explain.outside') ??
					viewMessage(stdPacks, lang, 'sign.screened');
				return {
					depth: node.distance,
					cells: [
						{ text: String(node.distance) },
						{ text: outsideText, sign: signByName(catalog, 'screened') },
						{ text: '' },
						{ text: '' },
					],
				};
			}
			const steps = stepsByPremise.get(rowId(node.relation, node.key)) ?? [];
			const polarity: 'positive' | 'negative' = steps.some((s) => s.how === 'negative')
				? 'negative'
				: 'positive';
			const keyParts = parseKey(node.key);
			const formatted = formatLineValue(
				bundle,
				lang,
				stdPacks,
				catalog,
				node.relation,
				keyParts,
				polarity,
				steps[0]?.value,
			);
			const originInfo = formatOrigin(bundle, lang, stdPacks, catalog, node, answer, polarity);
			return {
				depth: node.distance,
				cells: [
					{ text: String(node.distance) },
					{ text: formatLineLabel(bundle, lang, stdPacks, node.relation, keyParts, polarity) },
					{ text: formatted.value, sign: formatted.valueSign },
					{ text: originInfo.origin, sign: originInfo.originSign },
				],
			};
		});
		return { question: questionTerm, shape, heading, headers, rows, moreLabel };
	}

	if (shape === 'rings') {
		const headers = [
			viewMessage(stdPacks, lang, 'effect.col.ring'),
			viewMessage(stdPacks, lang, 'effect.col.sector'),
			viewMessage(stdPacks, lang, 'effect.col.row'),
		];
		const sep = viewMessage(stdPacks, lang, 'value.separator');
		const rows: AnswerTableRow[] = answer.nodes.map((node) => {
			if (node.outside) {
				const outsideText =
					explainMessage(stdPacks, lang, 'explain.outside') ??
					viewMessage(stdPacks, lang, 'sign.screened');
				return {
					depth: node.distance,
					cells: [
						{ text: viewMessage(stdPacks, lang, 'answer.ring', { distance: node.distance }) },
						{ text: outsideText, sign: signByName(catalog, 'screened') },
						{ text: '' },
					],
				};
			}
			const keyParts = parseKey(node.key);
			return {
				depth: node.distance,
				cells: [
					{ text: viewMessage(stdPacks, lang, 'answer.ring', { distance: node.distance }) },
					{ text: labelOf(bundle, lang, node.relation) },
					{ text: keyParts.join(sep) },
				],
			};
		});
		return { question: questionTerm, shape, heading, headers, rows, moreLabel };
	}

	if (shape === 'gap') {
		const headers = [
			viewMessage(stdPacks, lang, 'answer.distance'),
			viewMessage(stdPacks, lang, 'answer.premises'),
			viewMessage(stdPacks, lang, 'answer.candidates'),
		];
		const sep = viewMessage(stdPacks, lang, 'value.separator');
		const gap = answer.gap;
		const premises = gap?.premises ?? [];
		const candidates = gap?.candidates ?? [];
		const rows: AnswerTableRow[] = premises.map((premise, idx) => {
			const nodeText = formatRowRefText(
				bundle,
				stdPacks,
				lang,
				premise.node.relation,
				premise.node.key,
			);
			const itemText = viewMessage(stdPacks, lang, `gap.item.${premise.kind}`);
			const premiseText = viewMessage(stdPacks, lang, 'gap.premise', {
				node: nodeText,
				relation: labelOf(bundle, lang, premise.relation ?? premise.rule),
				item: itemText,
			});
			const matched = candidates
				.filter((c) => c.premise === idx)
				.map((c) =>
					viewMessage(stdPacks, lang, 'gap.candidate', {
						relation: labelOf(bundle, lang, c.relation),
						key: parseKey(c.key).join(sep),
						change: viewMessage(stdPacks, lang, `gap.${c.change}`),
					}),
				)
				.join(sep);
			return {
				depth: premise.distance,
				cells: [{ text: String(premise.distance) }, { text: premiseText }, { text: matched }],
			};
		});
		if (rows.length === 0) {
			const emptyText =
				explainMessage(stdPacks, lang, 'explain.empty', { element: elementText }) ??
				viewMessage(stdPacks, lang, 'table.empty');
			rows.push({ cells: [{ text: '0' }, { text: emptyText }, { text: '' }] });
		}
		return {
			question: questionTerm,
			shape,
			heading,
			headers,
			rows,
			cutMessage: gap?.cut ? viewMessage(stdPacks, lang, 'answer.cut') : undefined,
			moreLabel,
		};
	}

	if (shape === 'overlay') {
		const headers = [
			viewMessage(stdPacks, lang, 'effect.col.sector'),
			viewMessage(stdPacks, lang, 'effect.col.row'),
			viewMessage(stdPacks, lang, 'effect.col.change'),
		];
		const sep = viewMessage(stdPacks, lang, 'value.separator');
		const entries = answer.difference?.entries ?? [];
		const rows: AnswerTableRow[] = entries.map((entry) => ({
			cells: [
				{ text: labelOf(bundle, lang, entry.relation) },
				{ text: parseKey(entry.key).join(sep) },
				{ text: viewMessage(stdPacks, lang, `impact.${entry.change}`) },
			],
		}));
		return { question: questionTerm, shape, heading, headers, rows, moreLabel };
	}

	// series (or fallback tabular form)
	const headers = [
		viewMessage(stdPacks, lang, 'scale.value'),
		viewMessage(stdPacks, lang, 'scale.status'),
		viewMessage(stdPacks, lang, 'scale.difference'),
	];
	const sep = viewMessage(stdPacks, lang, 'value.separator');
	const rows: AnswerTableRow[] = (answer.series ?? []).map((cell) => {
		const diffText = (cell.counts ?? [])
			.map((c) =>
				viewMessage(stdPacks, lang, 'scale.counts', {
					relation: labelOf(bundle, lang, c.relation),
					added: c.added,
					removed: c.removed,
					changed: c.changed,
				}),
			)
			.join(sep);
		return {
			cells: [
				{ text: cell.value },
				{ text: viewMessage(stdPacks, lang, `scale.${cell.status}`) },
				{ text: diffText || viewMessage(stdPacks, lang, 'scale.no_difference') },
			],
		};
	});
	return { question: questionTerm, shape, heading, headers, rows, moreLabel };
}

export function buildRuleSlipView(
	pack: string,
	lang: string,
	head: HeadResponse,
	bundle: RoleBundleResponse,
	row: RowSelection,
	answer: ExplainAnswer,
	stdPacks: StdPacks,
): SlipView {
	const catalog = buildSignCatalog(stdPacks, lang);
	const startKey = canonicalKey(row.key);
	const start = answer.start ?? { relation: row.relation, key: startKey };
	const witnesses = answer.witnesses ?? [];
	const calcWitnesses = answer.calc_witnesses ?? [];
	const steps = answer.steps ?? [];

	const witness = witnesses.find(
		(w) => w.conclusion.relation === start.relation && w.conclusion.key === start.key,
	);
	const calcWitness = !witness
		? calcWitnesses.find(
				(cw) => cw.conclusion.relation === start.relation && cw.conclusion.key === start.key,
			)
		: undefined;
	const rule = witness
		? (bundle.rules as unknown as RuleLike[]).find((r) => r.id === witness.rule_id)
		: undefined;

	const lines: SlipLine[] = [];
	const atomPosToLine = new Map<number, number>();
	const aggPosToLine = new Map<number, number>();

	if (calcWitness) {
		const subject = parseKey(start.key)[0] ?? '';
		const ruleLabel = labelOf(bundle, lang, calcWitness.rule);
		const premises = calcWitness.premises ?? [];
		for (const step of calcWitness.steps ?? []) {
			const depth = Math.max(0, step.path.split('/').length - 2);
			const state = step.state as ValueState;
			const reason = state === 'known' ? '' : (step.reason ?? '');
			const value =
				state === 'known'
					? (step.value ?? '')
					: formatNonKnownText(bundle, stdPacks, lang, state, reason);
			const valueSign = stateSign(catalog, state);

			let stepRelation = start.relation;
			let stepKey = start.key;
			let matchedNode: GroundsNode | undefined;
			if (step.relation) {
				const targetSubject = step.element ?? subject;
				const matchedPremise = premises.find(
					(p) =>
						p.relation === step.relation &&
						(!targetSubject || parseKey(p.key)[0] === targetSubject),
				);
				if (matchedPremise) {
					stepRelation = matchedPremise.relation;
					stepKey = matchedPremise.key;
				} else {
					const nodeMatch = answer.nodes.find(
						(n) =>
							!n.outside &&
							n.relation === step.relation &&
							(!targetSubject || parseKey(n.key)[0] === targetSubject),
					);
					if (nodeMatch) {
						stepRelation = nodeMatch.relation;
						stepKey = nodeMatch.key;
						matchedNode = nodeMatch;
					} else {
						stepRelation = step.relation;
						stepKey = canonicalKey(targetSubject ? [targetSubject] : []);
					}
				}
				matchedNode ??= answer.nodes.find(
					(n) => !n.outside && n.relation === stepRelation && n.key === stepKey,
				);
			}

			let label: string;
			if (step.op === 'fact') {
				label = viewMessage(stdPacks, lang, 'route.calc.fact', {
					fact: calcLeafLabel(bundle, lang, step),
				});
			} else if (step.op === 'parameter') {
				label = viewMessage(stdPacks, lang, 'route.calc.parameter', {
					parameter: calcLeafLabel(bundle, lang, step),
				});
			} else if (step.op === 'rule') {
				label = viewMessage(stdPacks, lang, 'route.calc.rule', {
					rule: calcLeafLabel(bundle, lang, step),
				});
			} else {
				label = viewMessage(stdPacks, lang, 'route.calc.op', { op: step.op });
			}

			let origin: string;
			let originSign: SignInfo | undefined;
			if (!step.relation) {
				origin = ruleLabel;
				originSign = signByName(catalog, 'derived');
			} else if (matchedNode) {
				const originInfo = formatOrigin(
					bundle,
					lang,
					stdPacks,
					catalog,
					matchedNode,
					answer,
					'positive',
				);
				origin = originInfo.origin;
				originSign = originInfo.originSign;
			} else {
				origin = labelOf(bundle, lang, step.relation);
			}

			lines.push({
				index: lines.length,
				relation: stepRelation,
				key: stepKey,
				depth,
				polarity: 'positive',
				path: step.path,
				label,
				value,
				state,
				reason,
				valueSign,
				origin,
				originSign,
				verbs: [],
			});
		}
	} else {
		const directSteps = steps.filter(
			(s) => s.conclusion.relation === start.relation && s.conclusion.key === start.key,
		);
		const stepsByPremise = new Map<string, GroundsStep[]>();
		for (const step of directSteps) {
			const id = rowId(step.premise.relation, step.premise.key);
			const list = stepsByPremise.get(id);
			if (list) list.push(step);
			else stepsByPremise.set(id, [step]);
		}

		const rawAggregates = ((witness?.aggregates ?? []) as unknown as AggregateWitnessLike[]).map(
			(agg, idx) => ({ agg, pos: typeof agg.position === 'number' ? agg.position : idx }),
		);
		const aggByPos = new Map<number, AggregateWitnessLike>();
		for (const { agg, pos } of rawAggregates) {
			aggByPos.set(pos, agg);
		}

		const emittedAggs = new Set<number>();

		const emitTotal = (aggPos: number, fallbackRelation: string): number => {
			const agg = aggByPos.get(aggPos);
			const relation = agg?.relation ?? fallbackRelation;
			const parsed = parseStateValue(agg?.result ?? '');
			const sep = viewMessage(stdPacks, lang, 'name.separator');
			const totalLabel =
				viewMessage(stdPacks, lang, 'waterfall.total') + sep + labelOf(bundle, lang, relation);
			const value =
				parsed.state === 'known'
					? parsed.value
					: formatNonKnownText(bundle, stdPacks, lang, parsed.state, parsed.reason);
			const index = lines.length;
			lines.push({
				index,
				relation,
				key: agg?.group_key ?? '[]',
				depth: 0,
				polarity: 'positive',
				part: 'total',
				label: totalLabel,
				value,
				state: parsed.state,
				reason: parsed.reason,
				valueSign: stateSign(catalog, parsed.state),
				origin: witness ? labelOf(bundle, lang, witness.rule_id) : '',
				originSign: signByName(catalog, 'derived'),
				verbs: [],
			});
			aggPosToLine.set(aggPos, index);
			emittedAggs.add(aggPos);
			return index;
		};

		// Keep distance-1 nodes from the route answer in exact answer order: none added, none dropped.
		const distanceOne = answer.nodes.filter((n) => n.distance === 1 && !n.outside);
		for (const node of distanceOne) {
			const nodeSteps = stepsByPremise.get(rowId(node.relation, node.key)) ?? [];
			const premiseSteps = nodeSteps.filter((s) => s.how === 'positive' || s.how === 'negative');
			const contribStep = nodeSteps.find((s) => s.how === 'contributes');
			const keyParts = parseKey(node.key);

			if (contribStep && premiseSteps.length === 0) {
				if (!emittedAggs.has(contribStep.position)) {
					emitTotal(contribStep.position, node.relation);
				}
				const index = lines.length;
				const polarity: 'positive' | 'negative' = 'positive';
				const formatted = formatLineValue(
					bundle,
					lang,
					stdPacks,
					catalog,
					node.relation,
					keyParts,
					polarity,
					contribStep.value,
				);
				const originInfo = formatOrigin(bundle, lang, stdPacks, catalog, node, answer, polarity);
				lines.push({
					index,
					relation: node.relation,
					key: node.key,
					depth: 1,
					polarity,
					label: formatLineLabel(bundle, lang, stdPacks, node.relation, keyParts, polarity),
					value: formatted.value,
					state: formatted.state,
					reason: formatted.reason,
					valueSign: formatted.valueSign,
					origin: originInfo.origin,
					originSign: originInfo.originSign,
					verbs: [],
				});
				continue;
			}

			const primary = premiseSteps[0];
			const polarity: 'positive' | 'negative' =
				primary?.how === 'negative' ? 'negative' : 'positive';
			const index = lines.length;
			for (const step of premiseSteps) {
				if (!atomPosToLine.has(step.position)) {
					atomPosToLine.set(step.position, index);
				}
			}
			const formatted = formatLineValue(
				bundle,
				lang,
				stdPacks,
				catalog,
				node.relation,
				keyParts,
				polarity,
				primary?.value,
			);
			const originInfo = formatOrigin(bundle, lang, stdPacks, catalog, node, answer, polarity);
			lines.push({
				index,
				relation: node.relation,
				key: node.key,
				depth: 0,
				polarity,
				label: formatLineLabel(bundle, lang, stdPacks, node.relation, keyParts, polarity),
				value: formatted.value,
				state: formatted.state,
				reason: formatted.reason,
				valueSign: formatted.valueSign,
				origin: originInfo.origin,
				originSign: originInfo.originSign,
				verbs: [],
			});
		}

		// Emit totals for any aggregates with zero contributing rows in the answer.
		for (const { agg, pos } of rawAggregates) {
			if (!emittedAggs.has(pos)) {
				emitTotal(pos, agg.relation);
			}
		}
	}

	// Map each variable bound by a rule body atom or aggregate to its slip line index.
	const varToLine = new Map<string, number>();
	let atomIndex = 0;
	let aggIndex = 0;
	for (const literal of rule?.body ?? []) {
		if (literal.kind === 'atom') {
			const pos = atomIndex++;
			if (literal.polarity === 'positive') {
				const lineIndex = atomPosToLine.get(pos);
				if (lineIndex !== undefined) {
					for (const term of literal.terms ?? []) {
						if (term.kind === 'variable' && typeof term.value === 'string') {
							const name = stripQuestionPrefix(term.value);
							if (!varToLine.has(name)) {
								varToLine.set(name, lineIndex);
							}
						}
					}
				}
			}
		} else if (literal.kind === 'aggregate') {
			const pos = aggIndex++;
			const lineIndex = aggPosToLine.get(pos);
			if (
				lineIndex !== undefined &&
				literal.result?.kind === 'variable' &&
				typeof literal.result.value === 'string'
			) {
				const name = stripQuestionPrefix(literal.result.value);
				if (!varToLine.has(name)) {
					varToLine.set(name, lineIndex);
				}
			}
		}
	}

	let sentence: SentenceSegment[];
	if (witness) {
		const args: Record<string, string> = {};
		for (const binding of witness.bindings ?? []) {
			args[stripQuestionPrefix(binding.variable)] = binding.value;
		}
		const messageId = rule?.message ?? `rule.${witness.rule_id}`;
		const parts = fillParts(bundle.messages, lang, messageId, args);
		if (parts !== undefined) {
			sentence = parts.map((part) => {
				if (part.kind === 'var') {
					const target = varToLine.get(part.name);
					if (target !== undefined) {
						return { text: part.text, line: target };
					}
				}
				return { text: part.text };
			});
		} else {
			sentence = [{ text: witness.rule_id }];
		}
	} else if (calcWitness) {
		const ruleLabel = labelOf(bundle, lang, calcWitness.rule);
		const resultText =
			calcWitness.state === 'known'
				? (calcWitness.value ?? '')
				: formatNonKnownText(
						bundle,
						stdPacks,
						lang,
						calcWitness.state as ValueState,
						calcWitness.reason ?? '',
					);
		sentence = [
			{
				text: viewMessage(stdPacks, lang, 'route.calc.none', {
					rule: ruleLabel,
					value: resultText,
				}),
			},
		];
	} else {
		const relLabel = labelOf(bundle, lang, row.relation);
		const sep = viewMessage(stdPacks, lang, 'value.separator');
		sentence = [
			{
				text: viewMessage(stdPacks, lang, 'lead.row', {
					relation: relLabel,
					row: row.key.join(sep),
				}),
			},
		];
	}

	return {
		kind: 'slip',
		lang,
		pack,
		manifestId: head.id,
		row,
		sentence,
		lines,
		relations: bundle.relations.map((rel) => ({
			id: rel.id,
			label: labelOf(bundle, lang, rel.id),
		})),
		seal: buildSeal(head, lang, stdPacks, catalog),
		headers: buildHeaders(lang, stdPacks),
		legendHeaders: buildLegendHeaders(lang, stdPacks),
		signCatalog: catalog,
		labels: {
			relationsHeading: viewMessage(stdPacks, lang, 'row.relations'),
			closeAnswer: viewMessage(stdPacks, lang, 'answer.close'),
		},
		answersByKey: {},
	};
}

async function fetchJson<T>(fetchFn: FetchLike, url: string): Promise<{ status: number; body?: T }> {
	const response = await fetchFn(url);
	if (!response.ok) {
		return { status: response.status };
	}
	const body = (await response.json()) as T;
	return { status: response.status, body };
}

async function resolveHomeRow(
	fetchFn: FetchLike,
	pack: string,
	manifestId: string,
	bundle: RoleBundleResponse,
): Promise<RowSelection | undefined> {
	for (const relation of bundle.home?.claim ?? []) {
		const path = `/${encodeURIComponent(pack)}/${encodeURIComponent(manifestId)}/rows/${encodeURIComponent(relation)}?limit=2`;
		const res = await fetchJson<{ rows: Array<{ key: string[] }>; next?: string[] }>(fetchFn, path);
		if (res.status === 200 && res.body && res.body.rows.length === 1 && !res.body.next) {
			return { relation, key: res.body.rows[0].key };
		}
	}
	return undefined;
}

async function populateLineVerbs(
	fetchFn: FetchLike,
	bundle: RoleBundleResponse,
	stdPacks: StdPacks,
	view: SlipView,
): Promise<void> {
	const startRelation = view.row?.relation;
	const startKey = view.row ? canonicalKey(view.row.key) : undefined;
	const questionsByTerm = new Map(bundle.questions.map((q) => [q.term, q]));

	await Promise.all(
		view.lines.map(async (line) => {
			if (line.part === 'total') return;
			// An operator step of a calculation refers to the slip's own row, not a separate premise row.
			if (line.path !== undefined && line.relation === startRelation && line.key === startKey) {
				return;
			}
			const candidates = stdPacks.verbs
				.map((verb) => {
					if (!verb.question) return undefined;
					const question = questionsByTerm.get(verb.question);
					if (!question) return undefined;
					if (question.start === 'present' && line.polarity !== 'positive') return undefined;
					if (question.start === 'absent' && line.polarity !== 'negative') return undefined;
					if (question.start !== 'present' && question.start !== 'absent') return undefined;
					return { verb, question };
				})
				.filter((entry): entry is NonNullable<typeof entry> => entry !== undefined);

			const results = await Promise.all(
				candidates.map(async ({ verb, question }) => {
					const path =
						`/${encodeURIComponent(view.pack)}/${encodeURIComponent(view.manifestId)}` +
						`/ask/${encodeURIComponent(question.term)}` +
						`?relation=${encodeURIComponent(line.relation)}&key=${encodeURIComponent(line.key)}`;
					const res = await fetchJson<ExplainAnswer>(fetchFn, path);
					if (res.status !== 200 || !res.body) {
						return undefined;
					}
					const lineVerb: LineVerb = {
						verb: verb.verb,
						label: viewMessage(stdPacks, view.lang, verb.label_message),
						key: verb.key,
						question: question.term,
						answerShape: question.answer,
						primary: verb.primary,
					};
					const table = buildAnswerTable(
						bundle,
						stdPacks,
						view.lang,
						question.term,
						question.answer,
						res.body,
						view.signCatalog,
					);
					return { lineVerb, table };
				}),
			);

			const verbs: LineVerb[] = [];
			for (const result of results) {
				if (!result) continue;
				verbs.push(result.lineVerb);
				view.answersByKey[`${line.index}:${result.lineVerb.verb}`] = result.table;
			}
			line.verbs = verbs;
		}),
	);
}

export async function loadSlip(
	fetchFn: FetchLike,
	options: { pack: string; lang: string; row?: RowSelection },
	stdPacks: StdPacks,
): Promise<SlipView> {
	const { pack, lang } = options;
	const catalog = buildSignCatalog(stdPacks, lang);
	const headRes = await fetchJson<HeadResponse>(fetchFn, `/${encodeURIComponent(pack)}/head`);
	if (headRes.status !== 200 || !headRes.body) {
		throw new Error(`Unable to read head for ${pack} (${headRes.status})`);
	}
	const head = headRes.body;
	const bundleRes = await fetchJson<RoleBundleResponse>(
		fetchFn,
		`/${encodeURIComponent(pack)}/bundle?m=${encodeURIComponent(head.id)}`,
	);
	if (bundleRes.status !== 200 || !bundleRes.body) {
		throw new Error(`Unable to read bundle for ${pack} (${bundleRes.status})`);
	}
	const bundle = bundleRes.body;

	const selectedRow = options.row ?? (await resolveHomeRow(fetchFn, pack, head.id, bundle));
	if (!selectedRow) {
		return {
			kind: 'relations',
			lang,
			pack,
			manifestId: head.id,
			sentence: [],
			lines: [],
			relations: bundle.relations.map((rel) => ({
				id: rel.id,
				label: labelOf(bundle, lang, rel.id),
			})),
			seal: buildSeal(head, lang, stdPacks, catalog),
			headers: buildHeaders(lang, stdPacks),
			legendHeaders: buildLegendHeaders(lang, stdPacks),
			signCatalog: catalog,
			labels: {
				relationsHeading: viewMessage(stdPacks, lang, 'row.relations'),
				closeAnswer: viewMessage(stdPacks, lang, 'answer.close'),
			},
			answersByKey: {},
		};
	}

	const routeQuestion = bundle.questions.find(
		(q) => q.start === 'present' && q.answer === 'route',
	);
	if (!routeQuestion) {
		throw new Error(`No route question available for ${pack}`);
	}

	const keyText = canonicalKey(selectedRow.key);
	const routePath =
		`/${encodeURIComponent(pack)}/${encodeURIComponent(head.id)}` +
		`/ask/${encodeURIComponent(routeQuestion.term)}` +
		`?relation=${encodeURIComponent(selectedRow.relation)}&key=${encodeURIComponent(keyText)}`;
	const routeRes = await fetchJson<ExplainAnswer>(fetchFn, routePath);
	if (routeRes.status !== 200 || !routeRes.body) {
		throw new Error(`Unable to read proof for ${selectedRow.relation} (${routeRes.status})`);
	}

	const view = buildRuleSlipView(pack, lang, head, bundle, selectedRow, routeRes.body, stdPacks);
	await populateLineVerbs(fetchFn, bundle, stdPacks, view);
	return view;
}
