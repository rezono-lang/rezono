import { fill, fillParts } from '../../messages/src/fill.ts';
import type {
	FetchLike,
	GroundsAnswer,
	GroundsNode,
	GroundsStep,
	HeadResponse,
	RoleBundleResponse,
	RowSelection,
	SentenceSegment,
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
	relation: string,
	keyParts: readonly string[],
	polarity: 'positive' | 'negative',
	stepValue: string | undefined,
): { state: ValueState; value: string; reason: string } {
	if (polarity === 'negative') {
		return { state: 'absent', value: viewMessage(stdPacks, lang, 'status.absent'), reason: '' };
	}
	if (stepValue !== undefined) {
		return parseStateValue(stepValue);
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
	node: GroundsNode,
	answer: GroundsAnswer,
	polarity: 'positive' | 'negative',
): string {
	if (polarity === 'negative') {
		return viewMessage(stdPacks, lang, 'status.absent');
	}
	if (node.sources && node.sources.length > 0) {
		const first = node.sources[0];
		return first.position ? `${first.name}:${first.position}` : first.name;
	}
	const witness = answer.witnesses.find(
		(w) => w.conclusion.relation === node.relation && w.conclusion.key === node.key,
	);
	if (witness) {
		return labelOf(bundle, lang, witness.rule_id);
	}
	const calcWitness = (answer.calc_witnesses ?? []).find(
		(cw) => cw.conclusion.relation === node.relation && cw.conclusion.key === node.key,
	);
	if (calcWitness) {
		return labelOf(bundle, lang, calcWitness.rule);
	}
	return '';
}

function buildSeal(head: HeadResponse, lang: string, stdPacks: StdPacks) {
	return {
		manifestSha256: head.manifest_sha256,
		witnessCheck: head.witness_check,
		manifestLabel: viewMessage(stdPacks, lang, 'cartouche.manifest'),
		readerHashesLabel: viewMessage(stdPacks, lang, 'sign.sealed'),
	};
}

function buildHeaders(lang: string, stdPacks: StdPacks) {
	return {
		line: viewMessage(stdPacks, lang, 'waterfall.row'),
		value: viewMessage(stdPacks, lang, 'answer.value'),
		origin: viewMessage(stdPacks, lang, 'zone.rests'),
	};
}

export function buildRuleSlipView(
	pack: string,
	lang: string,
	head: HeadResponse,
	bundle: RoleBundleResponse,
	row: RowSelection,
	answer: GroundsAnswer,
	stdPacks: StdPacks,
): SlipView {
	const startKey = canonicalKey(row.key);
	const start = answer.start ?? { relation: row.relation, key: startKey };
	const witness = answer.witnesses.find(
		(w) => w.conclusion.relation === start.relation && w.conclusion.key === start.key,
	);
	const rule = witness
		? (bundle.rules as unknown as RuleLike[]).find((r) => r.id === witness.rule_id)
		: undefined;

	const directSteps = answer.steps.filter(
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

	const lines: SlipLine[] = [];
	const atomPosToLine = new Map<number, number>();
	const aggPosToLine = new Map<number, number>();
	const emittedAggs = new Set<number>();

	const emitTotal = (aggPos: number, fallbackRelation: string): number => {
		const agg = aggByPos.get(aggPos);
		const relation = agg?.relation ?? fallbackRelation;
		const parsed = parseStateValue(agg?.result ?? '');
		const sep = viewMessage(stdPacks, lang, 'name.separator');
		const totalLabel =
			viewMessage(stdPacks, lang, 'waterfall.total') + sep + labelOf(bundle, lang, relation);
		const index = lines.length;
		lines.push({
			index,
			relation,
			key: agg?.group_key ?? '[]',
			depth: 0,
			polarity: 'positive',
			part: 'total',
			label: totalLabel,
			value: parsed.value,
			state: parsed.state,
			reason: parsed.reason,
			origin: witness ? labelOf(bundle, lang, witness.rule_id) : '',
		});
		aggPosToLine.set(aggPos, index);
		emittedAggs.add(aggPos);
		return index;
	};

	// Keep distance-1 nodes from `grounds` in exact answer order: none added, none dropped.
	// Calculated rows carry their own CalcWitness steps rather than rule premises.
	const isCalculated =
		!witness &&
		(answer.calc_witnesses ?? []).some(
			(cw) => cw.conclusion.relation === start.relation && cw.conclusion.key === start.key,
		);
	const distanceOne = isCalculated ? [] : answer.nodes.filter((n) => n.distance === 1);
	for (const node of distanceOne) {
		const steps = stepsByPremise.get(rowId(node.relation, node.key)) ?? [];
		const premiseSteps = steps.filter((s) => s.how === 'positive' || s.how === 'negative');
		const contribStep = steps.find((s) => s.how === 'contributes');
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
				node.relation,
				keyParts,
				polarity,
				contribStep.value,
			);
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
				origin: formatOrigin(bundle, lang, stdPacks, node, answer, polarity),
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
			node.relation,
			keyParts,
			polarity,
			primary?.value,
		);
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
			origin: formatOrigin(bundle, lang, stdPacks, node, answer, polarity),
		});
	}

	// Emit totals for any aggregates with zero contributing rows in the answer.
	for (const { agg, pos } of rawAggregates) {
		if (!emittedAggs.has(pos)) {
			emitTotal(pos, agg.relation);
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
		row,
		sentence,
		lines,
		relations: bundle.relations.map((rel) => ({
			id: rel.id,
			label: labelOf(bundle, lang, rel.id),
		})),
		seal: buildSeal(head, lang, stdPacks),
		headers: buildHeaders(lang, stdPacks),
		labels: {
			relationsHeading: viewMessage(stdPacks, lang, 'row.relations'),
		},
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

export async function loadSlip(
	fetchFn: FetchLike,
	options: { pack: string; lang: string; row?: RowSelection },
	stdPacks: StdPacks,
): Promise<SlipView> {
	const { pack, lang } = options;
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
			sentence: [],
			lines: [],
			relations: bundle.relations.map((rel) => ({
				id: rel.id,
				label: labelOf(bundle, lang, rel.id),
			})),
			seal: buildSeal(head, lang, stdPacks),
			headers: buildHeaders(lang, stdPacks),
			labels: {
				relationsHeading: viewMessage(stdPacks, lang, 'row.relations'),
			},
		};
	}

	const keyText = canonicalKey(selectedRow.key);
	const groundsPath =
		`/${encodeURIComponent(pack)}/${encodeURIComponent(head.id)}/ask/grounds` +
		`?relation=${encodeURIComponent(selectedRow.relation)}&key=${encodeURIComponent(keyText)}`;
	const groundsRes = await fetchJson<GroundsAnswer>(fetchFn, groundsPath);
	if (groundsRes.status !== 200 || !groundsRes.body) {
		throw new Error(`Unable to read grounds for ${selectedRow.relation} (${groundsRes.status})`);
	}

	return buildRuleSlipView(pack, lang, head, bundle, selectedRow, groundsRes.body, stdPacks);
}
