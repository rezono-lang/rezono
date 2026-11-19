import type { Answer, AnswerNode, RelationCount, RowRef, SeriesCell } from '../../../contracts/typescript/generated/explain.ts';
import { table } from './text.ts';

type Node = AnswerNode;
type Count = RelationCount;

/** The direction a question walks: back from a conclusion to its premises, or forward. */
export type Direction = 'back' | 'forward';

export const OUTSIDE = 'outside your view';

/**
 * A table whose anonymous rows (`undefined` cells after the distance) print their distance and OUTSIDE:
 * they take no part in the widths of the other columns, so a hidden row changes no other line.
 */
function tableOutside(header: string[], rows: { dist: string; cells?: string[] }[]): string[] {
	const lines = table(header, rows.map((r) => (r.cells ? [r.dist, ...r.cells] : [r.dist])));
	const w0 = Math.max(...[header[0], ...rows.map((r) => r.dist)].map((x) => [...x].length));
	return lines.map((l, i) => (i > 0 && !rows[i - 1].cells ? `${rows[i - 1].dist}${' '.repeat(w0 - [...rows[i - 1].dist].length + 2)}${OUTSIDE}` : l));
}
const same = (a: RowRef, b: { relation?: string; key?: string }) => a.relation === b.relation && a.key === b.key;

/**
 * How a node is reached, `<how> <rule>`, from the first edge of the page that reaches it: walking back, the
 * edge whose premise it is, with its conclusion's rule; walking forward, the edge whose conclusion it is,
 * with its own rule. `-` for the start, and for a rule whose witness is on an earlier page.
 */
function via(a: Answer, n: Node, direction: Direction): string {
	if (n.distance === 0) return '-';
	const step = (a.steps ?? []).find((s) => same(direction === 'back' ? s.premise : s.conclusion, n));
	if (!step) return '-';
	const rule = (a.witnesses ?? []).find((w) => same(w.conclusion, step.conclusion))?.rule_id ?? '-';
	return `${step.how} ${rule}`;
}

/**
 * A page of nodes as table `dist  relation  key  via`. Grouped (reach) prints a distance only on the first
 * line of its group. An anonymous node prints its distance and `outside your view`, nothing else.
 */
function nodes(a: Answer, direction: Direction, grouped: boolean): string[] {
	let last = -1;
	const rows = a.nodes.map((n) => {
		const dist = grouped && n.distance === last ? '' : String(n.distance);
		last = n.distance;
		return { dist, cells: n.outside ? undefined : [n.relation ?? '', n.key ?? '', via(a, n, direction)] };
	});
	return tableOutside(['dist', 'relation', 'key', 'via'], rows);
}

const counts = (cs: Count[]) =>
	cs.length ? ['counts:', ...table(['relation', 'added', 'removed', 'changed'], cs.map((c) => [c.relation, String(c.added), String(c.removed), String(c.changed)]))] : ['counts: none'];

/** `more:` (the nodes to continue from, each with the same question) and `next:` (the cursor `:more` uses). */
function tail(a: Answer): string[] {
	const out: string[] = [];
	if (a.more?.length) out.push('more:', ...table(['relation', 'key'], a.more.map((r) => [r.relation, r.key])));
	if (a.next !== undefined) out.push(`next: ${a.next}`);
	return out;
}

/** A page of a named question. Reach groups nodes by distance. */
function namedText(a: Answer, direction: Direction, grouped: boolean): string[] {
	if (a.gap) {
		const g = a.gap;
		const premises = g.premises.map((p) => {
			const dist = String(p.distance);
			if (p.outside) return { dist };
			const flags = [p.more && '(more)', p.overflow && '(overflow)'].filter(Boolean);
			const bindings = [...(p.bindings ?? []).map((b) => `${b.variable}=${b.value}`), ...flags].join(' ');
			return { dist, cells: [p.rule, String(p.item), p.kind, p.relation ?? '-', bindings] };
		});
		const candidates = (g.candidates ?? []).map((c) => [c.change, c.relation, c.key, c.status, String(c.premise)]);
		return [
			...(premises.length ? ['premises:', ...tableOutside(['dist', 'rule', 'item', 'kind', 'relation', 'bindings'], premises)] : ['premises: none']),
			...(candidates.length ? ['candidates:', ...table(['change', 'relation', 'key', 'status', 'premise'], candidates)] : ['candidates: none']),
			`cut: ${g.cut ? 'yes' : 'no'}`,
			...tail(a)
		];
	}
	if (a.difference && a.difference.entries !== undefined) {
		const entries = a.difference.entries.map((e) => [e.change, e.relation, e.key, e.was ?? '-']);
		return [
			...counts(a.difference.counts),
			...(entries.length ? ['changes:', ...table(['change', 'relation', 'key', 'was'], entries)] : ['changes: none']),
			...tail(a)
		];
	}
	if (a.series) return [...seriesTable(a.series), ...tail(a)];
	return [...(a.difference ? counts(a.difference.counts) : []), ...nodes(a, direction, grouped), ...tail(a)];
}


/** The changes of a series cell: the sum of its counts for the role, or `-` where none was published. */
const changes = (cs: Count[] | undefined) => (cs ? String(cs.reduce((n, c) => n + c.added + c.removed + c.changed, 0)) : '-');

const seriesTable = (cells: SeriesCell[]) =>
	table(['index', 'value', 'status', 'manifest', 'changes'], cells.map((c) => [String(c.index), c.value, c.status, c.manifest ?? '-', changes(c.counts)]));

function valueText(value: unknown): string {
	if (value === undefined) return '-';
	if (typeof value === 'object' && value !== null) {
		for (const [member, label] of [['$unknown', 'unknown'], ['$na', 'n/a'], ['$invalid', 'invalid']]) {
			const reason = (value as Record<string, unknown>)[member];
			if (typeof reason === 'string') return reason ? `${label} (${reason})` : label;
		}
	}
	return typeof value === 'string' ? value : JSON.stringify(value);
}

function languageText(answer: Answer, rowFields: boolean): string[] {
	const dataset = answer.dataset as {
		rows?: Record<string, unknown>[];
		schema?: { kinds?: { Answer?: { slots?: Record<string, { expr?: string }> } } };
	} | undefined;
	const rows = (dataset?.rows ?? []).filter((row) => row.$kind === 'Answer');
	const fields = new Set(rows.flatMap((row) => Object.keys(row).filter((key) => /^c[1-9][0-9]*$/.test(key))));
	const slots = [...fields].sort((a, b) => Number(a.slice(1)) - Number(b.slice(1)));
	const expressions = dataset?.schema?.kinds?.Answer?.slots;
	const labels = rowFields ? slots.map((slot) => expressions?.[slot]?.expr?.split('.').at(-1) ?? slot) : slots;
	const lines = table(['binder', ...labels], rows.map((row) => [valueText(row.$id), ...slots.map((slot) => valueText(row[slot]))]));
	if (answer.undecided?.length) {
		lines.push('undecided:', ...table(['binder', 'state', 'reason'], answer.undecided.map((row) => [row.binder, row.state, row.reason ?? '-'])));
	}
	if (answer.counts) {
		const { rows, undecided, not_applicable } = answer.counts;
		lines.push(`rows: ${rows}  undecided: ${undecided}  not applicable: ${not_applicable}`);
	}
	for (const diagnostic of answer.diagnostics ?? []) lines.push(`warning: ${diagnostic.code}`);
	return [...lines, ...tail(answer)];
}

export function answerText(answer: Answer, rowFields = false): string[] {
	if (answer.question === 'ask') return languageText(answer, rowFields);
	const forward = answer.question === 'reach' || answer.question === 'impact' || answer.question === 'consequence';
	return namedText(answer, forward ? 'forward' : 'back', forward);
}
