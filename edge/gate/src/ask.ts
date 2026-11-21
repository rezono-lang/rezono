// Walk the role's published proof witnesses in stable UTF-8 key order.
import type { CalcWitness, RowRef, Witness } from '../../../contracts/typescript/generated/proof.ts';
import type { Answer as ContractAnswer, Question as ContractQuestion, Source } from '../../../contracts/typescript/generated/explain.ts';
import { compareText as byText } from './pieces.ts';

export const ANSWER = 'rezono.answer/1';
/** An error with the HTTP status the gate answers with. */
export class AskError extends Error {
	status: number;
	constructor(status: number, message: string) {
		super(message);
		this.status = status;
	}
}

export type Direction = 'back' | 'forward';
/** Names that select nodes (contracts/explain.yaml, Filter). */
export interface Filter {
	kinds?: string[];
	relations?: string[];
	rules?: string[];
	layers?: string[];
}
export interface Trace {
	direction: Direction;
	depth: string;
	through?: string;
	keep?: Filter;
	stop?: Filter;
	fanout?: number;
}
/** One question as the schema bundle carries it (contracts/explain.yaml, Question). */
export interface Question extends ContractQuestion {
	term: string;
	start: string;
	applies_to?: { derivation?: string; kinds?: string[]; relations?: string[] };
	steps: { trace?: Trace; suppose?: { delta?: string; over?: string } }[];
	answer: string;
	limit: number;
}
/**
 * One row of `step`: the conclusion, the premise, how the premise counts and its place in the rule. `value`
 * is what a row contributes to a `sum`, `min` or `max`: the value text its witness's
 * `contributors_sha256` is taken over, on a `contributes` edge only; absent where the pieces state none.
 */
export interface Edge {
	c: RowRef;
	p: RowRef;
	how: string;
	position: number;
	value?: string;
}
/** The proof graph of one role in one manifest. */
export interface Graph {
	/**
	 * The edges at a node, in a direction (back from a conclusion to its premises, forward from a premise),
	 * whose far end comes after `after` (all without it): by far end, then `how`, then `position`. Read as
	 * they are taken, so a node with many edges costs only what the walk takes of them.
	 */
	edges(direction: Direction, node: RowRef, after?: RowRef): AsyncIterable<Edge>;
	/** The chosen witness of a conclusion, a rule's or a calculation's (W12); none for a row that is not one. */
	witness(conclusion: RowRef): Promise<Witness | CalcWitness | undefined>;
}
export interface Cursor {
	distance: number;
	ref: RowRef;
}
/**
 * The sources of a base row (contracts/source.yaml, Source), as the role's own source set gives them (S25): a
 * locator, not content and not proof that the row is true or of where it really came from (principle 10).
 */
export type Sources = Source[];
/**
 * The sources of a row the role reads, by its typed reference; undefined for any other row (decision O8). Read
 * per row (one lookup in the role's source trees beside the proof pieces), so a page reads only its own rows.
 */
export type SourcesOf = (row: RowRef) => Promise<Sources | undefined>;
export interface AnswerNode extends RowRef {
	distance: number;
	/** A base row's sources, from the role's source set: where a walk back ends (S25). */
	sources?: Sources;
}
export interface AnswerStep {
	conclusion: RowRef;
	premise: RowRef;
	how: string;
	position: number;
	value?: string;
}
/** One page of an answer (contracts/explain.yaml, Answer). */
export interface Answer extends Omit<ContractAnswer, 'nodes' | 'steps'> {
	format: string;
	question: string;
	manifest_id: string;
	start?: RowRef;
	nodes: AnswerNode[];
	steps: AnswerStep[];
	witnesses: Witness[];
	/** The calculation witnesses of the nodes shown (W12); absent when there are none. */
	calc_witnesses?: CalcWitness[];
	next?: string;
	more?: RowRef[];
}

/** True for a calculation's witness: it names its `rule`, a rule's witness its `rule_id`. */
export const isCalc = (w: Witness | CalcWitness): w is CalcWitness => !('rule_id' in w);

export const byRef = (a: RowRef, b: RowRef) => byText(a.relation, b.relation) || byText(a.key, b.key);
const idOf = (r: RowRef) => `${r.relation}\u0000${r.key}`;
const plain = (r: RowRef): RowRef => ({ relation: r.relation, key: r.key });

/** The cursor `after=<distance>,<relation>,<key>`; undefined without one. A malformed one is a 400. */
export function parseAfter(text: string | null): Cursor | undefined {
	if (text === null) return undefined;
	const m = /^(0|[1-9][0-9]{0,8}),([^,]+),(.*)$/s.exec(text);
	if (!m) throw new AskError(400, 'after is <distance>,<relation>,<key>');
	return { distance: Number(m[1]), ref: { relation: m[2], key: m[3] } };
}
const cursor = (n: AnswerNode) => `${n.distance},${n.relation},${n.key}`;

/** A filter as a test on a node. Only relations are served yet; a question with another filter is refused. */
function matcher(f: Filter | undefined, what: string): ((r: RowRef) => boolean) | undefined {
	if (!f) return undefined;
	const other = (['kinds', 'rules', 'layers'] as const).filter((k) => f[k]?.length);
	if (other.length) throw new AskError(501, `${what} on ${other.join(' and ')} is not served yet`);
	const relations = new Set(f.relations ?? []);
	return (r) => relations.has(r.relation);
}

/** The one trace step of a question from a row, if the gate can answer it now; otherwise a 501. */
function traceOf(q: Question): Trace {
	if (q.start === 'delta' || q.start === 'sweep') throw new AskError(400, `the question ${q.term} starts from a ${q.start}: ask it with proposal=, variant= or sweep=`);
	const [step, ...rest] = q.steps ?? [];
	if (q.start !== 'present' || rest.length || !step?.trace) throw new AskError(501, `the question ${q.term} is not served yet`);
	return checked(step.trace, q.term);
}

/** A trace step through the proof graph that the walker serves; otherwise a 501, or a 500 if malformed. */
export function checked(t: Trace, term: string): Trace {
	if ((t.through ?? 'proof') !== 'proof') throw new AskError(501, `the question ${term} is not served yet`);
	if ((t.direction !== 'back' && t.direction !== 'forward') || !/^(all|[1-9][0-9]*)$/.test(String(t.depth)))
		throw new AskError(500, `the question ${term} is not well-formed`);
	return t;
}

/** True if the question is offered for this start (applies_to); a start it does not apply to is a 404. */
function applies(q: Question, start: RowRef, conclusion: boolean): boolean {
	const a = q.applies_to;
	if (!a) return true;
	if (a.derivation === 'conclusion' && !conclusion) return false;
	if (a.derivation === 'fact' && conclusion) return false;
	if (a.relations?.length && !a.relations.includes(start.relation)) return false;
	// A kind's rows are in its kind relation and its slot relations (`<kind>__<slot>`).
	if (a.kinds?.length && !a.kinds.some((k) => start.relation === k || start.relation.startsWith(`${k}__`))) return false;
	return true;
}

/** The value of an edge as a field, or nothing: only text is a value, and an edge without one states none. */
const valued = (value: unknown) => (typeof value === 'string' ? { value } : {});
const far = (d: Direction, e: Edge) => (d === 'back' ? e.p : e.c);
const near = (d: Direction, e: Edge) => (d === 'back' ? e.c : e.p);
/** Edges in the order a walk this way reads them: by far end, `how`, `position`, then near end. */
const edgeOrder = (d: Direction) => (a: Edge, b: Edge) =>
	byRef(far(d, a), far(d, b)) || byText(a.how, b.how) || a.position - b.position || byRef(near(d, a), near(d, b));

/** Sorted sources as one sorted sequence: a k-way merge that reads each source only as far as it is taken. */
async function* merge<T>(sources: AsyncIterable<T>[], compare: (a: T, b: T) => number): AsyncGenerator<T> {
	const its = sources.map((s) => s[Symbol.asyncIterator]());
	const heads = await Promise.all(its.map((it) => it.next()));
	for (;;) {
		let best = -1;
		for (let i = 0; i < heads.length; i++) if (!heads[i].done && (best < 0 || compare(heads[i].value, heads[best].value) < 0)) best = i;
		if (best < 0) return;
		yield heads[best].value;
		heads[best] = await its[best].next();
	}
}

/** The far ends of the edges of `from` this way after `after`, each once and in reference order, with its edges. */
async function* level(g: Graph, d: Direction, from: RowRef[], after?: RowRef): AsyncGenerator<{ node: RowRef; edges: Edge[] }> {
	let group: { node: RowRef; edges: Edge[] } | undefined;
	for await (const e of merge(from.map((n) => g.edges(d, n, after)), edgeOrder(d))) {
		const n = plain(far(d, e));
		if (group && byRef(group.node, n) === 0) group.edges.push(e);
		else {
			if (group) yield group;
			group = { node: n, edges: [e] };
		}
	}
	if (group) yield group;
}

/**
 * One page of the answer to a question from a start row, over a role's proof graph. Undefined if the question
 * does not apply to the start, or the start is not in the graph (then the gate answers 404, as for a row that
 * is not there).
 *
 * With the role's sources (S25, `sourcesOf`), each node of the page that is a base row the role reads carries
 * its sources, so a walk back ends at them; and such a row is in the graph also without an edge, so a fact's
 * `grounds` are the fact with its sources. Without them (a manifest from before S25) the answer is as before.
 * Sources are read only for a question that applies, and only for the start and the nodes of the page.
 */
export async function ask(g: Graph, q: Question, manifestId: string, start: RowRef, page: { limit: number; after?: Cursor }, sourcesOf?: SourcesOf): Promise<Answer | undefined> {
	const t = traceOf(q);
	start = plain(start);
	const conclusion = (await g.witness(start)) !== undefined;
	if (!applies(q, start, conclusion)) return undefined; // before any source is read
	const a = await walk(g, t, [start], page, !conclusion && !(sourcesOf && (await sourcesOf(start))));
	if (!a) return undefined;
	const nodes = sourcesOf ? await Promise.all(a.nodes.map(async (n) => withSources(n, await sourcesOf(n)))) : a.nodes;
	return { format: ANSWER, question: q.term, manifest_id: manifestId, start, ...a, nodes };
}

const withSources = (n: AnswerNode, sources: Sources | undefined): AnswerNode => (sources ? { ...n, sources } : n);

/** What a walk gives: the page of an answer without what was asked. */
export type Walked = Pick<Answer, 'nodes' | 'steps' | 'witnesses' | 'calc_witnesses' | 'next' | 'more'>;

/**
 * One page of a walk from the starts, all at distance 0 and each always shown (`impact` starts from every row a
 * delta changed; ask.ts and suppose.ts). `strict`: a start without an edge this way is not in the graph, and
 * the walk is undefined (one start that is no conclusion: the gate answers 404). The starts of a delta are
 * given rows, also one removed in the target, so they are not strict.
 */
export async function walk(g: Graph, t: Trace, starts: RowRef[], page: { limit: number; after?: Cursor }, strict = false): Promise<Walked | undefined> {
	const keep = matcher(t.keep, 'keep');
	const stop = matcher(t.stop, 'stop');
	const seeds = [...new Map(starts.map((s) => [idOf(s), plain(s)])).values()].sort(byRef);
	const depth = t.depth === 'all' ? Infinity : Number(t.depth);
	const { limit, after } = page;
	const dir = t.direction;
	// A start is always gone past; a node in `stop` is reached, not gone past.
	const past = (ns: RowRef[], d: number) => ns.filter((n) => d === 0 || !stop?.(n));

	// Breadth first, a level at a time, each node once, at its first distance. A level is read while the levels
	// before it are within the limit, and only as far as the limit needs: a level read only in part is `open`,
	// and a page reads the rest of it again from its cursor (the levels before it are within the limit).
	const distance = new Map(seeds.map((s) => [idOf(s), 0]));
	const levels: RowRef[][] = [seeds];
	const read: Edge[] = []; // the edges of the levels read whole
	let total = seeds.length;
	let cut = -1;
	let open = false;
	for (let d = 0; d < depth && levels[d].length; d++) {
		if (total > limit) {
			cut = d;
			break;
		}
		const want = limit - total + 1;
		const found: RowRef[] = [];
		const edges: Edge[] = [];
		for await (const { node, edges: es } of level(g, dir, past(levels[d], d))) {
			if (!distance.has(idOf(node))) {
				if (found.length === want) {
					open = true;
					break;
				}
				distance.set(idOf(node), d + 1);
				found.push(node);
			}
			edges.push(...es);
		}
		// A start that is no conclusion and has no edge this way is not in the role's graph: whether it is a row
		// the role may not read or none at all, the answer is the same (404).
		if (d === 0 && strict && !edges.length) return undefined;
		if (!open) read.push(...edges);
		levels.push(found);
		total += found.length;
	}

	// The page: the next `limit` places after the cursor, shown or not, and one more to know there is a next.
	const last = levels.length - 1;
	const places: AnswerNode[] = [];
	const late: Edge[] = []; // the edges of the open level, read again for this page
	for (let d = 0; d <= last && places.length <= limit; d++) {
		if (after && after.distance > d) continue;
		if (!(open && d === last)) {
			for (const n of levels[d])
				if (!after || d > after.distance || byRef(n, after.ref) > 0) {
					places.push({ ...n, distance: d });
					if (places.length > limit) break;
				}
			continue;
		}
		// The open level from the cursor. An edge to a node of an earlier level comes with the page whose range
		// of this level it falls in, so each edge comes once over the pages.
		let pending: Edge[] = [];
		let whole = true;
		for await (const { node, edges } of level(g, dir, past(levels[d - 1], d - 1), after?.distance === d ? after.ref : undefined)) {
			if ((distance.get(idOf(node)) ?? d) < d) {
				pending.push(...edges);
				continue;
			}
			places.push({ ...node, distance: d });
			if (places.length > limit) {
				whole = false;
				break;
			}
			late.push(...pending, ...edges);
			pending = [];
		}
		if (whole) late.push(...pending);
	}
	const covered = places.slice(0, limit);
	const on = new Set(covered.map(idOf));
	// The nodes the answer shows: `keep`, and the starts always.
	const shown = (n: RowRef) => distance.get(idOf(n)) === 0 || !keep || keep(n);
	const nodes = covered.filter(shown);
	// Every place of the cut level continues, also one `keep` hides: the walk goes on past it.
	const more = cut < 0 ? [] : covered.filter((n) => n.distance === cut && !stop?.(n)).map(plain);
	// The edges that reach a node of the page, from a node the answer shows.
	const steps = [...read.filter((e) => on.has(idOf(far(dir, e)))), ...late]
		.filter((e) => shown(far(dir, e)) && shown(near(dir, e)))
		.sort((a, b) => byRef(a.c, b.c) || byText(a.how, b.how) || a.position - b.position || byRef(a.p, b.p))
		.map((e) => ({ conclusion: plain(e.c), premise: plain(e.p), how: e.how, position: e.position, ...valued(e.value) }));
	const found = (await Promise.all(nodes.map((n) => g.witness(n)))).filter((w) => w !== undefined);
	const witnesses = found.filter((w): w is Witness => !isCalc(w));
	const calc = found.filter(isCalc);
	return {
		nodes,
		steps,
		witnesses,
		...(calc.length ? { calc_witnesses: calc } : {}),
		...(places.length > limit ? { next: cursor(covered.at(-1)!) } : {}),
		...(more.length ? { more } : {})
	};
}

/** The question named `term` in a schema bundle, or undefined. */
export function questionOf(bundle: unknown, term: string): Question | undefined {
	const qs = (bundle as { questions?: unknown } | undefined)?.questions;
	if (!Array.isArray(qs)) return undefined;
	const q = (qs as Question[]).find((x) => x && x.term === term);
	if (q && !(Number.isSafeInteger(q.limit) && q.limit >= 1 && Array.isArray(q.steps))) throw new AskError(500, `the question ${term} is not well-formed`);
	return q;
}
/** The proof graph from a set of witnesses, a rule's or a calculation's, and their `step` rows, in memory. */
export function memoryGraph(witnesses: (Witness | CalcWitness)[], steps: Edge[]): Graph {
	const by = new Map(witnesses.map((w) => [idOf(w.conclusion), w]));
	const at = { back: new Map<string, Edge[]>(), forward: new Map<string, Edge[]>() };
	for (const e of steps)
		for (const d of ['back', 'forward'] as const) {
			const m = at[d];
			const n = idOf(near(d, e));
			if (!m.has(n)) m.set(n, []);
			m.get(n)!.push(e);
		}
	for (const d of ['back', 'forward'] as const) for (const es of at[d].values()) es.sort(edgeOrder(d));
	return {
		async *edges(direction, n, after) {
			for (const e of at[direction].get(idOf(n)) ?? []) if (!after || byRef(far(direction, e), after) > 0) yield e;
		},
		witness: async (c) => by.get(idOf(c))
	};
}

/**
 * The `step` rows of calculation witnesses (W12), as rezono_publisher.proof.calc_steps makes them: each premise,
 * `positive`, at its index in `premises`. `reads` names relations, not rows: no step.
 */
export const calcSteps = (witnesses: CalcWitness[]): Edge[] =>
	witnesses.flatMap((w) => (w.premises ?? []).map((p, position) => ({ c: plain(w.conclusion), p: plain(p), how: 'positive', position })));

/** One cell value in a snapshot record (contracts/value.yaml). */
export interface SnapshotValue {
	state?: unknown;
	value?: unknown;
	minor_units?: unknown;
}

/** One snapshot record as `rows` returns it, with key parts and optional value columns. */
export interface SnapshotRow {
	key: string[];
	values?: Record<string, unknown>;
}

/** The rule IR as far as `step` needs it (contracts/rules.yaml). */
export interface RuleDoc {
	relations?: { name: string; key?: { name?: string }[]; values?: { name?: string }[] }[];
	rules?: {
		id: string;
		body?: { relation: string; terms: string[]; polarity: string }[];
		aggregates?: { relation: string; terms: string[]; function?: string; over?: string }[];
	}[];
}

function contributionValue(row: SnapshotRow, over: string, keyIndex: number, ruleId: string, relation: string): string {
	if (keyIndex >= 0) {
		const cell = row.key[keyIndex];
		if (typeof cell !== 'string') throw new AskError(500, `${ruleId}: missing key column ${over} in ${relation}`);
		return `known:${cell}`;
	}
	const values = row.values;
	if (!values || typeof values !== 'object' || Array.isArray(values) || !Object.hasOwn(values, over)) {
		throw new AskError(500, `${ruleId}: ${relation}.${over} is missing`);
	}
	const cell = values[over];
	if (!cell || typeof cell !== 'object' || Array.isArray(cell) || (cell as SnapshotValue).state !== 'known') {
		throw new AskError(500, `${ruleId}: ${relation}.${over} is not known`);
	}
	const { value, minor_units } = cell as SnapshotValue;
	const text = typeof value === 'string' ? value : typeof minor_units === 'string' ? minor_units : undefined;
	if (text === undefined) throw new AskError(500, `${ruleId}: ${relation}.${over} has no known payload`);
	return `known:${text}`;
}

/**
 * The `step` rows of a set of chosen witnesses, as rezono_compiler.trace.steps makes them: the premises from the
 * rule body under the bindings (`position` is the literal's place in the rule), and per aggregate the rows of
 * its group in `rows` (the role's rows of that relation, key columns and optional `values`). Keys are canonical
 * key text. A `contributes` edge of a `sum`, `min` or `max` carries what its row gives the aggregate, as the
 * published pieces do (trace.steps, `valued`): `known:` and the row's cell in the key or value column the
 * aggregate ranges over.
 */
export async function stepsOf(doc: RuleDoc | undefined, witnesses: Witness[], rows: (relation: string) => Promise<readonly (string[] | SnapshotRow)[]>): Promise<Edge[]> {
	if (!witnesses.length) return [];
	if (!doc) throw new AskError(500, 'witnesses without a rule IR');
	const rules = new Map((doc.rules ?? []).map((r) => [r.id, r]));
	const width = new Map((doc.relations ?? []).map((r) => [r.name, (r.key ?? []).length]));
	const keyColumns = new Map((doc.relations ?? []).map((r) => [r.name, (r.key ?? []).map((c) => c.name)]));
	const valueColumns = new Map((doc.relations ?? []).map((r) => [r.name, (r.values ?? []).map((c) => c.name)]));
	const text = (parts: string[]) => JSON.stringify(parts.map(String));
	const out = new Map<string, Edge>();
	const add = (e: Edge) => out.set(JSON.stringify([e.c.relation, e.c.key, e.p.relation, e.p.key, e.how, e.position]), e);
	// The rows of a relation by the values of the columns an aggregate fixes: each relation and set of columns
	// is grouped once, so a witness reads its own group, never the whole relation again (as trace.steps caches).
	const groups = new Map<string, Promise<Map<string, SnapshotRow[]>>>();
	const groupOf = (relation: string, fixed: (readonly [number, string])[]) => {
		const k = `${relation}\u0000${fixed.map(([j]) => j).join(',')}`;
		if (!groups.has(k))
			groups.set(
				k,
				rows(relation).then((all) => {
					const by = new Map<string, SnapshotRow[]>();
					for (const item of all) {
						const r = Array.isArray(item) ? { key: item } : item;
						if (fixed.some(([j]) => j >= r.key.length)) continue;
						const at = JSON.stringify(fixed.map(([j]) => r.key[j]));
						if (!by.has(at)) by.set(at, []);
						by.get(at)!.push(r);
					}
					return by;
				})
			);
		return groups.get(k)!.then((by) => by.get(JSON.stringify(fixed.map(([, v]) => v))) ?? []);
	};
	for (const w of witnesses) {
		const rule = rules.get(w.rule_id);
		if (!rule) throw new AskError(500, `the rule ${w.rule_id} is not in the rule IR`);
		const theta = new Map((w.bindings ?? []).map((b) => [b.variable, b.value]));
		const value = (t: string) => {
			if (!t.startsWith('?')) return t;
			const v = theta.get(t);
			if (v === undefined) throw new AskError(500, `${w.rule_id}: ${t} is not bound`);
			return v;
		};
		const c = plain(w.conclusion);
		(rule.body ?? []).forEach((b, i) => add({ c, p: { relation: b.relation, key: text(b.terms.map(value)) }, how: b.polarity, position: i }));
		for (const [i, a] of ((w.aggregates ?? []) as unknown as { position?: number }[]).entries()) {
			const position = typeof a.position === 'number' ? a.position : i;
			const atom = rule.aggregates?.[position];
			if (!atom) throw new AskError(500, `${w.rule_id}: no aggregate at ${position}`);
			const fixed = atom.terms.flatMap((t, j) => (t === '_' ? [] : [[j, value(t)] as const]));
			const n = width.get(atom.relation) ?? 0;
			const needsValue = Boolean(atom.function && atom.function !== 'count');
			let keyIndex = -1;
			if (needsValue) {
				if (atom.over === undefined) {
					throw new AskError(500, `${w.rule_id}: the aggregate at ${position} is missing an over column`);
				}
				keyIndex = (keyColumns.get(atom.relation) ?? []).indexOf(atom.over);
				const hasValueCol = (valueColumns.get(atom.relation) ?? []).includes(atom.over);
				if (keyIndex < 0 && !hasValueCol) {
					throw new AskError(500, `${w.rule_id}: the aggregate at ${position} ranges over ${atom.over}, not a column of ${atom.relation}`);
				}
			}
			for (const r of await groupOf(atom.relation, fixed)) {
				if (r.key.length < n) throw new AskError(500, `${w.rule_id}: malformed row key in ${atom.relation}`);
				const cellValue = needsValue ? contributionValue(r, atom.over!, keyIndex, w.rule_id, atom.relation) : undefined;
				add({ c, p: { relation: atom.relation, key: text(r.key.slice(0, n)) }, how: 'contributes', position, ...(cellValue !== undefined && { value: cellValue }) });
			}
		}
	}
	return [...out.values()];
}
