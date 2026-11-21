/**
 * Canonical conclusion IRIs, epoch/hash pinning, and single-row resolution
 * (decisions/publication-conclusion-addresses.md §1, §3, §4).
 */

import type { Schema } from '../../../rezono/src/index.ts';
import { AskError } from './ask.ts';
import type { View } from './expr.ts';

const ABSOLUTE_IRI = /^[A-Za-z][A-Za-z0-9+.-]*:\S+$/;
const MANIFEST_ID = /^m-[0-9]+$/;
const DATASET_ID = /^d-[0-9a-f]{64}$/;
const PIN_VALUE = /^(?:(m-[0-9]+)@)?(d-[0-9a-f]{64})$/;
const WITNESS_HASH = /^[0-9a-f]{64}$/;
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

/**
 * Root kind of `kindName` in `schema` (L0 §2.1, publication-conclusion-addresses.md §1).
 * A subkind shares its root kind's IRI space.
 */
export function rootKind(schema: Schema, kindName: string): string {
	if (!Object.hasOwn(schema.kinds, kindName)) {
		throw new AskError(400, `unknown kind: ${kindName}`);
	}
	const seen = new Set<string>();
	let cur = kindName;
	while (schema.kinds[cur]?.parent) {
		if (seen.has(cur)) throw new AskError(500, 'cyclic kind parent chain');
		seen.add(cur);
		const parent = schema.kinds[cur]!.parent!;
		if (!Object.hasOwn(schema.kinds, parent)) break;
		cur = parent;
	}
	return cur;
}

/**
 * Where `kindName`'s elements and conclusions live: the root kind's declared `iri`, else `<base><Root>`.
 */
export function elementSpace(schema: Schema, kindName: string): string {
	const root = rootKind(schema, kindName);
	const spec = schema.kinds[root]!;
	return spec.iri || `${schema.base}${root}`;
}

export function conclusionIri(schema: Schema, kindName: string, rowId: string, pin?: IriPin): string {
	const unpinned = `${elementSpace(schema, kindName)}/${spellSegment(rowId)}`;
	return pin ? pinIri(unpinned, pin) : unpinned;
}

export function pinIri(iri: string, pin: IriPin): string {
	if (typeof iri !== 'string' || !ABSOLUTE_IRI.test(iri)) {
		throw new AskError(400, 'an IRI to pin must be an absolute IRI');
	}
	if (iri.includes('?') || iri.includes('#')) {
		throw new AskError(400, 'unpinned IRI must not contain query or fragment');
	}
	if (typeof pin.dataset !== 'string' || !DATASET_ID.test(pin.dataset)) {
		throw new AskError(400, 'dataset pin must match d-<64 lower-case hex>');
	}
	if (pin.manifest !== undefined) {
		if (typeof pin.manifest !== 'string' || !MANIFEST_ID.test(pin.manifest)) {
			throw new AskError(400, 'manifest pin must match m-<epoch>');
		}
		return `${iri}?pin=${pin.manifest}@${pin.dataset}`;
	}
	return `${iri}?pin=${pin.dataset}`;
}

/**
 * Splits a pinned or unpinned canonical IRI per decisions/publication-conclusion-addresses.md §3.
 * Refuses non-absolute IRIs, fragments, unknown query params, malformed pins, and `m-<epoch>` without `d-<64 hex>`.
 */
export function parsePinnedIri(rawIri: string): ParsedPinnedIri {
	if (typeof rawIri !== 'string' || !ABSOLUTE_IRI.test(rawIri)) {
		throw new AskError(400, 'expected an absolute IRI');
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
	if (!iri || !ABSOLUTE_IRI.test(iri) || query.includes('?')) {
		throw new AskError(400, 'malformed query in IRI');
	}
	if (query.includes('&') || !query.startsWith('pin=')) {
		throw new AskError(400, 'only the pin query parameter is allowed');
	}
	const rawPin = query.slice(4);
	if (MANIFEST_ID.test(rawPin)) {
		throw new AskError(400, 'epoch pin without dataset hash is refused');
	}
	const match = PIN_VALUE.exec(rawPin);
	if (!match) {
		throw new AskError(400, 'malformed pin: expected d-<64 hex> or m-<epoch>@d-<64 hex>');
	}
	const manifest = match[1];
	const dataset = match[2]!;
	return { iri, pin: manifest !== undefined ? { manifest, dataset } : { dataset } };
}

/**
 * True when `unpinnedIri` is a canonical witness IRI `<base>witness/<64 lower-case hex>` (§2, §4.4).
 */
export function isWitnessIri(base: string, unpinnedIri: string): boolean {
	const prefix = `${base}witness/`;
	if (!unpinnedIri.startsWith(prefix)) return false;
	return WITNESS_HASH.test(unpinnedIri.slice(prefix.length));
}

export interface MatchedKindSegment {
	readonly kind: string;
	readonly relation: string;
	readonly kindIri: string;
	readonly rowId: string;
	readonly tupleKey: boolean;
}

/**
 * Matches an unpinned conclusion IRI against the root kinds of a `roleSchema` view.
 * Subkinds share their root kind's IRI space and never match under their own name.
 */
export function matchKindConclusionIri(view: View, unpinnedIri: string): MatchedKindSegment | undefined {
	const { schema, kinds } = view;
	if (!schema.base || !schema.base.endsWith('/')) return undefined;

	let matched: MatchedKindSegment | undefined;
	for (const [kindName, spec] of Object.entries(schema.kinds)) {
		if (spec.parent) continue;
		const binding = kinds.get(kindName);
		if (!binding) continue;
		const space = elementSpace(schema, kindName);
		const prefix = `${space}/`;
		if (!unpinnedIri.startsWith(prefix)) continue;
		const segment = unpinnedIri.slice(prefix.length);
		if (!segment || segment.includes('/')) continue;
		const rowId = unspellSegment(segment);
		if (matched) throw new AskError(500, 'ambiguous kind IRI space');
		const tupleKey = Array.isArray(spec.tuple_key) && spec.tuple_key.length > 0;
		matched = { kind: kindName, relation: binding.relation, kindIri: space, rowId, tupleKey };
	}

	return matched;
}
