/**
 * Canonical conclusion & witness IRIs, epoch/hash pinning, and single-row resolution
 * (decisions/publication-conclusion-addresses.md §1–§4).
 */

import { createHash } from 'node:crypto';
import type { Bundle } from '../../../contracts/typescript/generated/bundle.ts';
import { canonicalJson } from '../../../viewer/src/lib/canon.ts';
import { AskError } from './ask.ts';

const SHA256_LOWER = /^[0-9a-f]{64}$/;
const EPOCH_PIN = /^m-(0|[1-9][0-9]*)$/;
const UNRESERVED_BYTE = /^[A-Za-z0-9._-]$/;
const HEX_PAIR = /^[0-9A-F]{2}$/;

export interface IriPin {
	readonly manifest?: string;
	readonly dataset: string;
}

export interface ParsedPinnedIri {
	readonly iri: string;
	readonly pin: IriPin | null;
}

/**
 * Bijective L0 §3.4 segment spelling:
 * ASCII letters, digits, `-`, `.`, `_` stay as written, except `.` -> `~2E` and `..` -> `~2E~2E`.
 * Every other UTF-8 byte (including `~`) is encoded as `~XX` (uppercase hex).
 */
export function spellSegment(raw: string): string {
	if (typeof raw !== 'string' || raw.length === 0) {
		throw new AskError(400, 'segment must be non-empty text');
	}
	if (raw === '.') return '~2E';
	if (raw === '..') return '~2E~2E';
	const bytes = new TextEncoder().encode(raw);
	let out = '';
	for (const b of bytes) {
		const ch = String.fromCharCode(b);
		if (b < 0x80 && UNRESERVED_BYTE.test(ch)) {
			out += ch;
		} else {
			out += '~' + b.toString(16).toUpperCase().padStart(2, '0');
		}
	}
	return out;
}

/**
 * Strict inverse of L0 §3.4 segment spelling. Refuses non-canonical encodings.
 */
export function unspellSegment(segment: string): string {
	if (typeof segment !== 'string' || segment.length === 0) {
		throw new AskError(400, 'invalid spelled segment');
	}
	const bytes: number[] = [];
	for (let i = 0; i < segment.length; i++) {
		const ch = segment[i]!;
		if (ch === '~') {
			const hex = segment.slice(i + 1, i + 3);
			if (!HEX_PAIR.test(hex)) {
				throw new AskError(400, 'malformed escape in spelled segment');
			}
			bytes.push(Number.parseInt(hex, 16));
			i += 2;
		} else if (UNRESERVED_BYTE.test(ch)) {
			bytes.push(ch.charCodeAt(0));
		} else {
			throw new AskError(400, 'illegal character in spelled segment');
		}
	}
	let decoded: string;
	try {
		decoded = new TextDecoder('utf-8', { fatal: true }).decode(new Uint8Array(bytes));
	} catch {
		throw new AskError(400, 'invalid UTF-8 in spelled segment');
	}
	if (spellSegment(decoded) !== segment) {
		throw new AskError(400, 'non-canonical spelled segment');
	}
	return decoded;
}

export function kindIriOf(base: string, kind: { class?: string; id: string; iri?: string }): string {
	if (typeof kind.iri === 'string' && kind.iri.length > 0) return kind.iri;
	const name = typeof kind.class === 'string' && kind.class.length > 0 ? kind.class : kind.id;
	return base + name;
}

export function conclusionIri(base: string, kind: { class?: string; id: string; iri?: string }, rowId: string, pin?: IriPin): string {
	const unpinned = `${kindIriOf(base, kind)}/${spellSegment(rowId)}`;
	return pin ? pinIri(unpinned, pin) : unpinned;
}

export function canonicalWitnessIri(base: string, witness: unknown, pin?: IriPin): string {
	if (typeof base !== 'string' || base.length === 0 || !base.endsWith('/') || base.includes('?') || base.includes('#')) {
		throw new AskError(400, 'base IRI must be a non-empty URI ending in "/" without query or fragment');
	}
	const digest = createHash('sha256').update(canonicalJson(witness)).digest('hex');
	const unpinned = `${base}witness/${digest}`;
	return pin ? pinIri(unpinned, pin) : unpinned;
}

export function pinIri(iri: string, pin: IriPin): string {
	if (iri.includes('?') || iri.includes('#')) {
		throw new AskError(400, 'unpinned IRI must not contain query or fragment');
	}
	if (!SHA256_LOWER.test(pin.dataset)) {
		throw new AskError(400, 'dataset pin must be 64 lower-case hex characters');
	}
	if (pin.manifest !== undefined) {
		if (!EPOCH_PIN.test(pin.manifest)) {
			throw new AskError(400, 'manifest pin must match m-<epoch>');
		}
		return `${iri}?pin=${pin.manifest}@d-${pin.dataset}`;
	}
	return `${iri}?pin=d-${pin.dataset}`;
}

/**
 * Splits a pinned or unpinned canonical IRI per decisions/publication-conclusion-addresses.md §3.
 * Refuses fragments, unknown query params, malformed pins, and `m-<epoch>` without `d-<64 hex>`.
 */
export function parsePinnedIri(rawIri: string): ParsedPinnedIri {
	if (typeof rawIri !== 'string' || rawIri.length === 0) {
		throw new AskError(400, 'expected a non-empty IRI');
	}
	if (rawIri.includes('#')) {
		throw new AskError(400, 'IRI fragments are not allowed');
	}
	const qIndex = rawIri.indexOf('?');
	if (qIndex < 0) {
		return { iri: rawIri, pin: null };
	}
	const iri = rawIri.slice(0, qIndex);
	const query = rawIri.slice(qIndex + 1);
	if (!iri || query.includes('?') || query.includes('&')) {
		throw new AskError(400, 'only a single pin query parameter is allowed');
	}
	if (!query.startsWith('pin=')) {
		throw new AskError(400, 'unknown query parameter on IRI');
	}
	const rawPin = query.slice(4);
	if (rawPin.includes('@')) {
		const [manifestPart, datasetPart, ...extra] = rawPin.split('@');
		if (extra.length > 0 || !manifestPart || !datasetPart || !EPOCH_PIN.test(manifestPart) || !datasetPart.startsWith('d-')) {
			throw new AskError(400, 'malformed epoch@dataset pin');
		}
		const hex = datasetPart.slice(2);
		if (!SHA256_LOWER.test(hex)) {
			throw new AskError(400, 'malformed dataset hash in pin');
		}
		return { iri, pin: { manifest: manifestPart, dataset: hex } };
	}
	if (rawPin.startsWith('d-')) {
		const hex = rawPin.slice(2);
		if (!SHA256_LOWER.test(hex)) {
			throw new AskError(400, 'malformed dataset hash in pin');
		}
		return { iri, pin: { dataset: hex } };
	}
	throw new AskError(400, 'epoch pin without dataset hash is refused');
}

export interface MatchedKindSegment {
	readonly relation: string;
	readonly kindIri: string;
	readonly rowId: string;
	readonly tupleKey: boolean;
}

const pascal = (name: string): string =>
	name
		.split('_')
		.filter((p) => p)
		.map((p) => p[0]!.toUpperCase() + p.slice(1))
		.join('');

/**
 * Matches an unpinned conclusion IRI against the role's readable kinds (`bundle.kinds`)
 * and derived relations (`bundle.relations`, L0 kind name `pascal(r.id)` with `tuple_key`).
 */
export function matchKindConclusionIri(
	bundle: Bundle,
	readableRelations: ReadonlySet<string>,
	unpinnedIri: string
): MatchedKindSegment | undefined {
	const packMeta = bundle.pack as { id?: string; base?: string } | undefined;
	const base =
		typeof packMeta?.base === 'string' && packMeta.base.length > 0
			? packMeta.base
			: typeof packMeta?.id === 'string' && packMeta.id.length > 0
				? `https://rezono.example/${packMeta.id}/`
				: undefined;
	if (!base || !base.endsWith('/')) return undefined;

	const kinds = (bundle.kinds ?? []) as readonly { id: string; class?: string; iri?: string; tuple_key?: unknown }[];
	const seenKindIds = new Set<string>();
	let matched: MatchedKindSegment | undefined;

	const tryMatch = (relation: string, space: string, tupleKey: boolean): void => {
		const prefix = space + '/';
		if (!unpinnedIri.startsWith(prefix)) return;
		const segment = unpinnedIri.slice(prefix.length);
		if (!segment || segment.includes('/')) return;
		const rowId = unspellSegment(segment);
		if (matched) throw new AskError(500, 'ambiguous kind IRI space');
		matched = { relation, kindIri: space, rowId, tupleKey };
	};

	for (const kind of kinds) {
		seenKindIds.add(kind.id);
		if (!readableRelations.has(kind.id)) continue;
		const tupleKey = Array.isArray(kind.tuple_key) && kind.tuple_key.length > 0;
		tryMatch(kind.id, kindIriOf(base, kind), tupleKey);
	}

	const relations = (bundle.relations ?? []) as readonly { id: string; iri?: string }[];
	for (const rel of relations) {
		if (seenKindIds.has(rel.id) || !readableRelations.has(rel.id)) continue;
		const space = typeof rel.iri === 'string' && rel.iri.length > 0 ? rel.iri : base + pascal(rel.id);
		tryMatch(rel.id, space, true);
	}

	return matched;
}
