import { createHash } from 'node:crypto';
import type { Bundle } from '../../../contracts/typescript/generated/bundle.ts';
import type { Answer, Source } from '../../../contracts/typescript/generated/explain.ts';
import type { ArchivedFile, Manifest, Snapshot, WitnessSet } from '../../../contracts/typescript/generated/manifest.ts';
import type { CalcWitness, RowRef, Witness } from '../../../contracts/typescript/generated/proof.ts';
import { canonicalJson } from '../../../viewer/src/lib/canon.ts';
import { ask as trace, AskError, calcSteps, memoryGraph, parseAfter, questionOf, stepsOf, type RuleDoc, type Sources, type SourcesOf } from './ask.ts';
import { catalogueQueryScope } from './catalogue-query.ts';
import { roleBundle } from './catalogue.ts';
import { readPublishedVariantDifference, scenarioAnswer, type DifferenceCursor } from './difference.ts';
import { ask as evaluate, roleSchema, type Asking } from './expr.ts';
import { compareKey, pageByKey, type KeyRange } from './pieces.ts';
import { rowQueryScope, type RowSelection } from './row-query.ts';
import {
	earlierWithdrawal, epochWithdrawal, hasSortedKey, loadWithdrawals, rangeMatchingRows, rowsWithdrawal, rowWithdrawal,
	standingHeaders, withdrawalBody, WithdrawnError, type WithdrawalRecord
} from './standing.ts';
import { fileStore, StoreLimit, type Store } from './store.ts';
import { completeScope, readPublishedSweep, readPublishedVariant, sweepAnswer, type SweepStart } from './sweep.ts';

const LIMIT = 1000;
const REQUEST_BYTES = 16 * 1024;
const PUBLICATION_BYTES = 24 * 1024 * 1024;
const ROW_LIMIT = 25_000;
const PAIR_LIMIT = 2048;
const EVALUATION_STEPS = 250_000;
const SHA256 = /^[0-9a-f]{64}$/;
const MAIN = /^m-[0-9]+$/;
const SAFE = /^[A-Za-z0-9][A-Za-z0-9._-]*$/;
const WITNESS_CHECK = 'rezono:proofs';
const CHECK_STATUSES = new Set(['green', 'warning', 'red'] as const);
const headers = { 'cache-control': 'private, no-store' };

type WitnessCheckStatus = 'green' | 'warning' | 'red';
type ObjectRef = Pick<ArchivedFile, 'uri' | 'sha256'>;
type Keyed = { key: string[] };
type Witnesses = { witnesses: Witness[]; calc_witnesses?: CalcWitness[]; hidden: [] };
type Head = { format: 'rezono.head/1'; manifest: string; epoch: number; sha256: string };
type Page = { rows: Keyed[]; next?: string[] };
type Handle = (request: Request) => Promise<Response>;

function safe(name: string): boolean {
	return SAFE.test(name) && !name.includes('..');
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

function missing(): never {
	throw new AskError(404, 'not found');
}

function json(value: unknown, status = 200, extra?: Record<string, string>): Response {
	return Response.json(value, { status, headers: extra ? { ...headers, ...extra } : headers });
}

function gone(entry: WithdrawalRecord): Response {
	return json(withdrawalBody(entry), 410, { 'x-rezono-standing': 'withdrawn' });
}

function textList(raw: string | null): string[] | undefined {
	if (raw === null) return undefined;
	let parsed: unknown;
	try { parsed = JSON.parse(raw); } catch { throw new AskError(400, 'expected a JSON key array'); }
	if (!keyParts(parsed)) throw new AskError(400, 'expected a JSON key array');
	return parsed;
}

function limitOf(raw: unknown): number {
	if (raw === undefined || raw === null) return LIMIT;
	const n = typeof raw === 'string' && /^[1-9][0-9]*$/.test(raw) ? Number(raw) : raw;
	if (typeof n !== 'number' || !Number.isInteger(n) || n < 1 || n > LIMIT)
		throw new AskError(400, 'invalid page limit');
	return n;
}

function headKey(pack: string, epoch: number): string {
	return pack + '/heads/' + (10n ** 19n - 1n - BigInt(epoch)).toString().padStart(19, '0') + '.json';
}

function witnessCheck(checks: unknown): WitnessCheckStatus | undefined {
	if (checks === undefined) return undefined;
	if (!Array.isArray(checks)) fault();
	let status: WitnessCheckStatus | undefined;
	for (const entry of checks) {
		if (!record(entry) || typeof entry.name !== 'string') fault();
		if (entry.name !== WITNESS_CHECK) continue;
		if (status !== undefined || typeof entry.status !== 'string'
			|| !CHECK_STATUSES.has(entry.status as WitnessCheckStatus)) fault();
		status = entry.status as WitnessCheckStatus;
	}
	return status;
}

type QuestionBody = { text: string; limit: number; after?: string } &
	({ scope?: 'data' | 'catalogue' } | { scope: 'row'; row: RowSelection });

function rowSelection(value: unknown): RowSelection {
	if (!record(value) || typeof value.kind !== 'string' || value.kind.length === 0
		|| !keyParts(value.key) || !value.key.length
		|| (value.source_limit !== undefined && typeof value.source_limit !== 'number')
		|| (value.continuation !== undefined && typeof value.continuation !== 'string')
		|| Object.keys(value).some((key) => !['kind', 'key', 'source_limit', 'continuation'].includes(key)))
		throw new AskError(400, 'invalid row selection');
	return { kind: value.kind, key: value.key, source_limit: limitOf(value.source_limit), continuation: value.continuation };
}

async function bodyOf(req: Request): Promise<QuestionBody> {
	const stream = req.body?.getReader();
	if (!stream) throw new AskError(400, 'expected a question body');
	const decoder = new TextDecoder('utf-8', { fatal: true });
	let text = '', bytes = 0;
	try {
		for (;;) {
			const { done, value } = await stream.read();
			if (done) break;
			if ((bytes += value.byteLength) > REQUEST_BYTES) {
				await stream.cancel();
				throw new AskError(413, 'question body is too large');
			}
			text += decoder.decode(value, { stream: true });
		}
		const body: unknown = JSON.parse(text + decoder.decode());
		if (!record(body) || typeof body.text !== 'string' || (body.after !== undefined && typeof body.after !== 'string')
			|| (body.limit !== undefined && typeof body.limit !== 'number')
			|| (body.scope !== undefined && body.scope !== 'data' && body.scope !== 'catalogue' && body.scope !== 'row')
			|| (body.scope !== 'row' && body.row !== undefined)
			|| Object.keys(body).some((key) => !['text', 'limit', 'after', 'scope', 'row'].includes(key)))
			throw new AskError(400, 'invalid question body');
		const question = { text: body.text, limit: limitOf(body.limit), after: body.after };
		if (body.scope === 'row') return { ...question, scope: body.scope, row: rowSelection(body.row) };
		return { ...question, scope: body.scope };
	} catch (error) {
		if (error instanceof AskError) throw error;
		throw new AskError(400, 'invalid question body');
	}
}

function publication(store: Store, pack: string, role: string) {
	let remaining = PUBLICATION_BYTES;
	async function read(key: string, sha?: string, optional = false, decode: (text: string) => unknown = JSON.parse): Promise<unknown> {
		if (sha !== undefined && !SHA256.test(sha)) fault();
		const bytes = await store.get(key, remaining);
		if (!bytes) return optional ? undefined : fault();
		remaining -= bytes.byteLength;
		if (sha && createHash('sha256').update(bytes).digest('hex') !== sha) fault();
		try { return decode(new TextDecoder('utf-8', { fatal: true }).decode(bytes)); }
		catch { return fault(); }
	}
	async function object(ref: ObjectRef, category: 'objects' | 'bundles', decode?: (text: string) => unknown) {
		if (typeof ref.uri !== 'string' || !/^s3:\/\/[A-Za-z0-9._-]+\//.test(ref.uri)) fault();
		const key = ref.uri.replace(/^s3:\/\/[^/]+\//, '');
		if (!key.startsWith(pack + '/' + category + '/') || typeof ref.sha256 !== 'string') fault();
		if (category === 'objects' && key !== pack + '/objects/' + ref.sha256 + '.json') fault();
		return await read(key, ref.sha256, false, decode);
	}
	const latest = async () => (await store.list(pack + '/heads/', { limit: 1 }))[0];
	return {
		latest,
		read,
		async current(id?: string) {
			const epoch = id && MAIN.test(id) ? Number(id.slice(2)) : undefined;
			if (id !== undefined && (epoch === undefined || !Number.isSafeInteger(epoch) || id !== 'm-' + epoch))
				return undefined;
			const key = epoch === undefined ? await latest() : headKey(pack, epoch);
			if (!key) return undefined;
			const head = await read(key, undefined, epoch !== undefined) as Head | undefined;
			if (head === undefined) return undefined;
			if (!record(head) || head.format !== 'rezono.head/1' || !MAIN.test(head.manifest)
				|| !Number.isSafeInteger(head.epoch) || head.epoch < 0 || key !== headKey(pack, head.epoch)
				|| head.manifest !== 'm-' + head.epoch || typeof head.sha256 !== 'string') fault();
			const manifest = await read(pack + '/manifests/' + head.manifest + '.json', head.sha256) as Manifest;
			if (!record(manifest) || manifest.id !== head.manifest || manifest.epoch !== head.epoch
				|| manifest.variant || manifest.proposal || !Array.isArray(manifest.snapshots) || !Array.isArray(manifest.compiled))
				fault();
			if (manifest.access_semantics !== 2) return undefined;
			const witness = witnessCheck(manifest.checks);
			const snaps = new Map<string, Snapshot>();
			for (const entry of manifest.snapshots) {
				if (!record(entry) || typeof entry.role !== 'string') fault();
				if (entry.role !== role) continue;
				if (typeof entry.relation !== 'string' || !safe(entry.relation) || entry.format !== 'json'
					|| typeof entry.complete !== 'boolean' || (entry.full !== undefined && typeof entry.full !== 'boolean')
					|| snaps.has(entry.relation)) fault();
				snaps.set(entry.relation, entry);
			}
			if (!snaps.size) return undefined;

			const compiled = (file: string) => manifest.compiled!.find((ref) => ref.file === file);
			const schema = compiled('bundle/schema-bundle.json');
			if (!schema) return undefined;
			const bundle = await object(schema, 'bundles');
			if (!record(bundle) || !record(bundle.pack) || bundle.pack.id !== pack || !Array.isArray(bundle.kinds)) fault();
			const snapshots = new Map<string, Promise<Keyed[]>>();
			const rows = (relation: string) => {
				const ref = snaps.get(relation);
				if (!ref) return missing();
				if (!snapshots.has(relation)) snapshots.set(relation, object(ref, 'objects').then((value) => {
					if (!Array.isArray(value) || value.some((row) => !record(row) || !keyParts(row.key) || !row.key.length)) fault();
					if (value.length > ROW_LIMIT) throw new StoreLimit();
					const sorted = (value as Keyed[]).sort((a, b) => compareKey(a.key, b.key));
					if (sorted.some((row, i) => i > 0 && compareKey(sorted[i - 1].key, row.key) === 0)) fault();
					return sorted;
				}));
				return snapshots.get(relation)!;
			};
			const range = async (relation: string, at: KeyRange): Promise<Page> =>
				pageByKey(await rows(relation), at);
			return {
				manifest, manifestSha256: head.sha256, witnessCheck: witness,
				compiled, snaps, bundle: bundle as unknown as Bundle, schema, rows, range, object, read
			};
		}
	};
}

type Current = NonNullable<Awaited<ReturnType<ReturnType<typeof publication>['current']>>>;

/**
 * The historical view must still be readable as a whole: complete snapshots
 * require a current complete snapshot, full snapshots require current complete
 * or full coverage, and a current full snapshot bypasses row-by-row key checks
 * only when definition_sha256 is present and unchanged.
 */
async function stillReadable(then: Current, now: Current): Promise<boolean> {
	const sameDefinition = typeof then.manifest.definition_sha256 === 'string'
		&& then.manifest.definition_sha256.length > 0
		&& then.manifest.definition_sha256 === now.manifest.definition_sha256;
	for (const [relation, past] of then.snaps) {
		const present = now.snaps.get(relation);
		if (!present) return false;
		if (past.complete && !present.complete) return false;
		if (past.full && !present.complete && !present.full) return false;
		if (present.complete || (present.full && sameDefinition)) continue;
		if (past.sha256 && past.sha256 === present.sha256) continue;
		const visible = new Set((await now.rows(relation)).map(({ key }) => canonicalJson(key)));
		if (!(await then.rows(relation)).every(({ key }) => visible.has(canonicalJson(key)))) return false;
	}
	return true;
}

async function readableSnapshots(view: Current): Promise<Snapshot[]> {
	const readable: Snapshot[] = [];
	for (const snapshot of view.snaps.values()) {
		if (snapshot.complete || snapshot.full === true || (await view.rows(snapshot.relation)).length > 0) {
			readable.push(snapshot);
		}
	}
	return readable;
}

function listed(view: Current) {
	const { manifest, manifestSha256, witnessCheck: witness, schema, snaps } = view;
	return {
		id: manifest.id, epoch: manifest.epoch, knowledge_time: manifest.knowledge_time,
		access_semantics: 2, definition_sha256: manifest.definition_sha256,
		manifest_sha256: manifestSha256,
		...(witness !== undefined && { witness_check: witness }),
		compiled: [{ file: schema.file, sha256: schema.sha256 }],
		snapshots: [...snaps.values()].map(({ relation, role, complete, full, format }) => ({ relation, role, complete, full, format }))
	};
}

const SOURCE_FIELDS = new Set(['kind', 'name', 'position', 'revision', 'url', 'retrieved_at',
	'fragment_sha256', 'ownership', 'licence', 'attribution']);

function sourceRecord(x: unknown): x is Source {
	return record(x) && typeof x.kind === 'string' && typeof x.name === 'string' && typeof x.position === 'string'
		&& Object.entries(x).every(([field, value]) => SOURCE_FIELDS.has(field) && typeof value === 'string');
}

function sourcesOf(view: Current, role: string): SourcesOf | undefined {
	const ref = view.manifest.fact_sources?.find((set) => set.role === role);
	if (!ref) return undefined;
	const id = (row: RowRef) => row.relation + '\\u0000' + row.key;
	let index: Promise<Map<string, Sources>> | undefined;
	const load = async () => {
		const rows = await view.object(ref, 'objects');
		if (!Array.isArray(rows)) fault();
		const by = new Map<string, Sources>();
		for (const entry of rows) {
			if (!record(entry) || !record(entry.row) || typeof entry.row.relation !== 'string'
				|| typeof entry.row.key !== 'string' || !Array.isArray(entry.sources)
				|| !entry.sources.length || !entry.sources.every(sourceRecord) || !view.snaps.has(entry.row.relation)) fault();
			const address = id({ relation: entry.row.relation, key: entry.row.key });
			if (by.has(address)) fault();
			by.set(address, entry.sources);
		}
		return by;
	};
	return async (row) => (await (index ??= load())).get(id(row));
}

async function rangeChecked(view: Current, withdrawals: readonly WithdrawalRecord[], relation: string, at: KeyRange): Promise<Page> {
	const all = await view.rows(relation);
	const withdrawn = rowsWithdrawal(withdrawals, view.manifest.id, relation, rangeMatchingRows(all, at));
	if (withdrawn) throw new WithdrawnError(withdrawn);
	return pageByKey(all, at);
}

async function readSweepChecked(
	current: Current,
	withdrawals: readonly WithdrawalRecord[],
	pack: string,
	role: string,
	name?: string,
	start?: SweepStart
) {
	let withdrawn: WithdrawalRecord | undefined;
	const checkedView = {
		...current,
		range: async (relation: string, at: KeyRange): Promise<Page> => {
			const all = await current.rows(relation);
			withdrawn = earlierWithdrawal(
				withdrawn,
				rowsWithdrawal(withdrawals, current.manifest.id, relation, rangeMatchingRows(all, at))
			);
			return pageByKey(all, at);
		}
	};
	const published = await readPublishedSweep(checkedView, pack, role, name, start);
	if (!published) return undefined;
	if (start) {
		withdrawn = earlierWithdrawal(withdrawn, rowWithdrawal(withdrawals, current.manifest.id, start.relation, start.key));
	}
	if (withdrawals.some((entry) => entry.rows.length > 0) && completeScope(current)) {
		for (const relation of current.snaps.keys()) {
			const rows = await current.rows(relation);
			withdrawn = earlierWithdrawal(withdrawn, rowsWithdrawal(withdrawals, current.manifest.id, relation, rows));
		}
	}
	if (withdrawn) throw new WithdrawnError(withdrawn);
	return published;
}

async function readVariantDifferenceChecked(
	current: Current,
	withdrawals: readonly WithdrawalRecord[],
	pack: string,
	role: string,
	variantId: string,
	page: { limit: number; after?: DifferenceCursor }
) {
	let withdrawn: WithdrawalRecord | undefined;
	const checkedView = {
		...current,
		range: async (relation: string, at: KeyRange): Promise<Page> => {
			const all = await current.rows(relation);
			withdrawn = earlierWithdrawal(
				withdrawn,
				rowsWithdrawal(withdrawals, current.manifest.id, relation, rangeMatchingRows(all, at))
			);
			return pageByKey(all, at);
		}
	};
	const variant = await readPublishedVariant(checkedView, pack, role, variantId);
	if (!variant) return undefined;
	const published = await readPublishedVariantDifference(checkedView, pack, role, variant, page);
	if (!published) return undefined;
	if (withdrawals.some((entry) => entry.rows.length > 0)) {
		for (const relation of current.snaps.keys()) {
			const rows = await current.rows(relation);
			withdrawn = earlierWithdrawal(withdrawn, rowsWithdrawal(withdrawals, current.manifest.id, relation, rows));
		}
	}
	if (withdrawn) throw new WithdrawnError(withdrawn);
	return published;
}

function isManifestRoute(method: string, parts: readonly string[], search: URLSearchParams, manifestId: string): boolean {
	const [, id, route] = parts;
	if (parts.length === 2 && (id === 'head' || id === 'bundle')) {
		const selected = search.get('m');
		return selected === null || selected === manifestId;
	}
	if (parts.length === 3 && id === 'manifests' && route === manifestId) return true;
	if (id !== manifestId) return false;
	if (parts.length === 4 && (route === 'snapshots' || route === 'rows' || route === 'ask')) return true;
	if (parts.length === 3 && route === 'rows') return true;
	if (method === 'POST' && parts.length === 3 && route === 'ask') return true;
	return false;
}

async function named(view: Current, withdrawals: readonly WithdrawalRecord[], role: string, term: string, search: URLSearchParams): Promise<Answer> {
	const question = questionOf(view.bundle, term);
	if (!question) return missing();
	if (question.start !== 'present' || question.steps.some((step) => !step.trace))
		throw new AskError(501, 'this named question needs a publication index');
	const relation = search.get('relation');
	const key = textList(search.get('key'));
	if (!relation || !key) throw new AskError(400, 'a named question needs a relation and key');
	if (!view.snaps.has(relation) || !(await view.rows(relation)).some((row) => compareKey(row.key, key) === 0)) return missing();
	const direct = rowWithdrawal(withdrawals, view.manifest.id, relation, key);
	if (direct) throw new WithdrawnError(direct);
	const ref = view.manifest.witnesses?.find((set) => set.role === role);
	if (!ref) return missing();
	const published = await view.object(ref as WitnessSet, 'objects') as Witnesses;
	if (!record(published) || !Array.isArray(published.witnesses) || !Array.isArray(published.hidden) || published.hidden.length
		|| (published.calc_witnesses !== undefined && !Array.isArray(published.calc_witnesses))) fault();
	const compiled = view.compiled('ir/rules.json');
	const rules = compiled ? await view.object(compiled, 'bundles') as RuleDoc : undefined;
	const steps = await stepsOf(rules, published.witnesses, async (name) => (await view.rows(name)).map((row) => row.key));
	const calc = published.calc_witnesses ?? [];
	const answer = await trace(memoryGraph([...published.witnesses, ...calc], [...steps, ...calcSteps(calc)]), question,
		view.manifest.id, { relation, key: canonicalJson(key) }, { limit: Math.min(limitOf(search.get('limit')), question.limit), after: parseAfter(search.get('after')) }, sourcesOf(view, role));
	if (!answer) return missing();
	if (withdrawals.some((entry) => entry.rows.length > 0)) {
		let withdrawn: WithdrawalRecord | undefined;
		for (const node of answer.nodes) {
			if (!view.snaps.has(node.relation)) continue;
			let parsed: unknown;
			try { parsed = JSON.parse(node.key); } catch { continue; }
			if (!keyParts(parsed)) continue;
			if (!hasSortedKey(await view.rows(node.relation), parsed)) continue;
			withdrawn = earlierWithdrawal(withdrawn, rowWithdrawal(withdrawals, view.manifest.id, node.relation, parsed));
		}
		if (withdrawn) throw new WithdrawnError(withdrawn);
	}
	return answer;
}

async function batch(view: Current, withdrawals: readonly WithdrawalRecord[], search: URLSearchParams) {
	const relations = [...new Set(textList(search.get('relations')) ?? [])];
	const keys = [...new Set(textList(search.get('ids')) ?? [])];
	const limit = limitOf(search.get('limit'));
	if (!relations.length || !keys.length || relations.length * keys.length > PAIR_LIMIT)
		throw new AskError(400, 'invalid row lookup');
	if (search.get('order') && search.get('order') !== 'key') throw new AskError(501, 'inverse index is unavailable');
	const rows: Record<string, Keyed[]> = Object.create(null);
	const more: {relation: string; id: string; after: string[]}[] = [];
	let withdrawn: WithdrawalRecord | undefined;
	for (const relation of relations.filter((name) => view.snaps.has(name))) {
		const all = await view.rows(relation);
		rows[relation] = [];
		for (const id of keys) {
			const matching = rangeMatchingRows(all, { prefix: [id] });
			withdrawn = earlierWithdrawal(withdrawn, rowsWithdrawal(withdrawals, view.manifest.id, relation, matching));
			if (withdrawn) continue;
			const { rows: selected, next } = pageByKey(all, { prefix: [id], limit });
			rows[relation].push(...selected);
			if (next) more.push({ relation, id, after: next });
		}
	}
	if (withdrawn) throw new WithdrawnError(withdrawn);
	return { rows, ...(more.length && { more }) };
}

/** The caller that opens the local store chooses a role for this handler's lifetime. */
export async function openLocalGate(root: string, role: string): Promise<Handle> {
	if (!safe(role)) throw new TypeError('invalid local publication role');
	const store = await fileStore(root);
	return async (req) => {
		try {
			const url = new URL(req.url);
			let parts: string[];
			try { parts = url.pathname.split('/').filter(Boolean).map(decodeURIComponent); }
			catch { return json({ error: 'invalid route' }, 400); }
			if (!parts.length || !parts.every(safe)) return missing();
			const [pack, id, route, item] = parts;
			if (req.method !== 'GET' && !(req.method === 'POST' && parts.length === 3 && route === 'ask'))
				return json({ error: 'method not allowed' }, 405);
			if (parts.length === 1 && pack === 'packs') {
				const visible = [];
				for (const entry of await store.list('', { delimiter: '/' })) {
					const name = entry.slice(0, -1);
					if (entry.endsWith('/') && safe(name) && await publication(store, name, role).current()) visible.push(name);
				}
				return json(visible);
			}
			const source = publication(store, pack, role);
			const current = await source.current();
			if (!current) return missing();
			const withdrawals = await loadWithdrawals(store, pack, (key) => source.read(key));
			if (parts.length === 2 && id === 'sweeps') {
				if (url.searchParams.get('m') !== current.manifest.id) return missing();
				const withdrawn = epochWithdrawal(withdrawals, current.manifest.id);
				if (withdrawn) return gone(withdrawn);
				const published = await readSweepChecked(current, withdrawals, pack, role);
				if (!published || await source.latest() !== headKey(pack, current.manifest.epoch)) return missing();
				return json(published.listing, 200, standingHeaders(pack, current.manifest.epoch, current.manifest.id, current.manifest.epoch));
			}
			const pin = id === 'head' || id === 'bundle' ? url.searchParams.get('m') ?? undefined
				: id === 'manifests' ? route : id;
			let view = current;
			if (pin !== undefined && pin !== current.manifest.id) {
				const earlier = await source.current(pin);
				if (!earlier || earlier.manifest.epoch >= current.manifest.epoch) return missing();
				const withdrawn = epochWithdrawal(withdrawals, earlier.manifest.id);
				if (withdrawn) {
					if (!isManifestRoute(req.method, parts, url.searchParams, earlier.manifest.id)) return missing();
					return gone(withdrawn);
				}
				if (!await stillReadable(earlier, current)) return missing();
				view = earlier;
			} else {
				const withdrawn = epochWithdrawal(withdrawals, current.manifest.id);
				if (withdrawn) {
					if (!isManifestRoute(req.method, parts, url.searchParams, current.manifest.id)) return missing();
					return gone(withdrawn);
				}
			}
			const standing = standingHeaders(pack, view.manifest.epoch, current.manifest.id, current.manifest.epoch);
			const response = await (async () => {
				if (parts.length === 2 && id === 'head') return json(listed(view), 200, standing);
				if (parts.length === 2 && id === 'bundle') {
					const selected = url.searchParams.get('m');
					return selected === null || selected === view.manifest.id
						? json(roleBundle(view.bundle, await readableSnapshots(view)), 200, standing) : missing();
				}
				if (parts.length === 3 && id === 'manifests' && route === view.manifest.id) return json(listed(view), 200, standing);
				if (id !== view.manifest.id) return missing();
				if (parts.length === 4 && route === 'snapshots') {
					const rows = await view.rows(item);
					const withdrawn = rowsWithdrawal(withdrawals, view.manifest.id, item, rows);
					if (withdrawn) throw new WithdrawnError(withdrawn);
					return json(rows, 200, standing);
				}
				if (parts.length === 4 && route === 'rows') {
					if (url.searchParams.get('order') && url.searchParams.get('order') !== 'key')
						throw new AskError(501, 'inverse index is unavailable');
					return json(await rangeChecked(view, withdrawals, item, { prefix: textList(url.searchParams.get('prefix')) ?? [],
						after: textList(url.searchParams.get('after')), limit: limitOf(url.searchParams.get('limit')),
						starts: url.searchParams.get('starts') ?? undefined }), 200, standing);
				}
				if (parts.length === 3 && route === 'rows') return json(await batch(view, withdrawals, url.searchParams), 200, standing);
				if (parts.length === 4 && route === 'ask') {
					const q = questionOf(view.bundle, item);
					if (q?.start === 'sweep' && q.answer === 'series') {
						const name = url.searchParams.get('sweep');
						if (!name || view !== current) return missing();
						const relation = url.searchParams.get('relation');
						const rawKey = url.searchParams.get('key');
						let start: SweepStart | undefined;
						if (relation !== null || rawKey !== null) {
							if (!relation || rawKey === null) throw new AskError(400, 'a start row needs a relation and key');
							const key = textList(rawKey);
							if (!key || !key.length) throw new AskError(400, 'expected a JSON key array');
							start = { relation, key };
						}
						const published = await readSweepChecked(current, withdrawals, pack, role, name, start);
						if (!published || await source.latest() !== headKey(pack, current.manifest.epoch)) return missing();
						return json(sweepAnswer(item, name, id, published.series, published.start), 200, standing);
					}
					if (q?.start === 'delta' && q.answer === 'overlay'
						&& q.steps.length === 1 && q.steps[0]?.suppose?.delta === 'given') {
						const variant = url.searchParams.get('variant');
						const proposal = url.searchParams.get('proposal');
						if (proposal !== null) {
							if (variant !== null) throw new AskError(400, 'give one of proposal or variant');
							throw new AskError(501, 'this named question needs a publication index');
						}
						if (variant === null) throw new AskError(400, 'a delta question needs a variant');
						const limit = Math.min(limitOf(url.searchParams.get('limit')), q.limit);
						const rawAfter = parseAfter(url.searchParams.get('after'));
						let after: DifferenceCursor | undefined;
						if (rawAfter) {
							if (rawAfter.distance === 0) {
								const key = textList(rawAfter.ref.key);
								if (!key || !key.length) throw new AskError(400, 'expected a JSON key array');
								after = { distance: 0, relation: rawAfter.ref.relation, key };
							} else {
								after = { distance: rawAfter.distance, relation: rawAfter.ref.relation };
							}
						}
						if (!variant || view !== current) return missing();
						const published = await readVariantDifferenceChecked(current, withdrawals, pack, role, variant, { limit, after });
						if (!published || await source.latest() !== headKey(pack, current.manifest.epoch)) return missing();
						return json(scenarioAnswer(item, id, variant, published), 200, standing);
					}
					return json(await named(view, withdrawals, role, item, url.searchParams), 200, standing);
				}
				if (req.method === 'POST' && route === 'ask') {
					const body = await bodyOf(req);
					const read = body.scope === 'row'
						? (relation: string, at: KeyRange) => rangeChecked(view, withdrawals, relation, at)
						: async (relation: string, at: KeyRange) => {
							const rows = await view.rows(relation);
							const withdrawn = rowsWithdrawal(withdrawals, view.manifest.id, relation, rows);
							if (withdrawn) throw new WithdrawnError(withdrawn);
							return pageByKey(rows, at);
						};
					const snapshots = [...view.snaps.values()];
					const subject = body.scope === 'row'
						? await rowQueryScope(view.bundle, snapshots, read, ROW_LIMIT, body.row, { manifest: id, role })
						: body.scope === 'catalogue'
						? await catalogueQueryScope(view.bundle, snapshots, read, ROW_LIMIT)
						: { view: roleSchema(view.bundle, snapshots), read };
					const asking: Asking = { text: body.text, limit: body.limit, after: body.after, ...subject, manifest: id,
						budget: { rows: ROW_LIMIT, steps: EVALUATION_STEPS } };
					const answered = await evaluate(asking);
					if ('refused' in answered) return json({ error: 'the text does not check', diagnostics: answered.refused }, 400);
					if ('cut' in answered) return json({ cut: answered.cut }, 422);
					return json(answered.answer, 200, standing);
				}
				return missing();
			})();
			if (view !== current && await source.latest() !== headKey(pack, current.manifest.epoch)) return missing();
			return response;
		} catch (error) {
			if (error instanceof WithdrawnError) return gone(error.withdrawal);
			if (error instanceof StoreLimit) return json({ error: 'read budget exhausted' }, 422);
			if (error instanceof AskError && error.status < 500) return json({ error: error.message }, error.status);
			if (error instanceof AskError && error.status === 501) return json({ error: 'question unavailable for this publication' }, 501);
			return json({ error: 'publication unavailable' }, 500);
		}
	};
}
