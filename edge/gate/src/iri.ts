/**
 * The canonical IRIs of a publication, as the gate reads and writes them: segment spelling (docs/publication/l0.md
 * §3.4), pins (§6.4), and the conclusion and witness IRIs of decisions/publication-conclusion-addresses.md §1-§3.
 * The one module of the gate that spells, pins or parses them. It is a port of `rezono_publication.rdf`; both sides
 * run contracts/fixtures/iri/vectors.json, which `publication/tests/iri_vectors.py` writes from the Python side.
 *
 * The IRI space of a kind comes from the role's schema (`roleSchema` in expr.ts, `View.spaces`), never from here:
 * this module only joins a space and an id.
 */
import { createHash } from 'node:crypto';
import { canonicalJson } from '../../../viewer/src/lib/canon.ts';

/** An IRI, an id or a pin that is not in its canonical form; the caller decides what that means for a request. */
export class IriError extends Error {}

/** A pin (§6.4): the dataset hash `d-<64 hex>`, and the manifest id `m-<epoch>` only with it. */
export interface Pin {
	readonly manifest?: string;
	readonly dataset: string;
}

/** `m-<epoch>` with `<epoch>` a natural number in its decimal spelling: `m-01` names no epoch (l0.md §1). */
const MANIFEST = /^m-(?:0|[1-9][0-9]*)$/;
const DATASET = /^d-[0-9a-f]{64}$/;
const PIN = /^(?:(m-(?:0|[1-9][0-9]*))@)?(d-[0-9a-f]{64})$/;
const HEX64 = /^[0-9a-f]{64}$/;
/** Python's `\S` (`str.isspace`), which is not JavaScript's: it holds U+001C-U+001F and U+0085, and not U+FEFF. */
const S = '[^\\t\\n\\v\\f\\r\\x1c-\\x1f \\x85\\xa0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000]';
/** An absolute IRI, as `l0._IRI` reads one. */
const ABSOLUTE = new RegExp(`^[A-Za-z][A-Za-z0-9+.-]*:${S}+$`, 'u');
/** A schema `base` (l0.md §2.1, `l0.check_schema`): an absolute IRI ending in `/`. */
const BASE = new RegExp(`^[a-z][a-z0-9+.-]*://${S}+/$`, 'u');
const PLAIN = /^[A-Za-z0-9._-]$/;
const PAIR = /^[0-9A-F]{2}$/;

/** An id as one IRI segment (§3.4): letters, digits, `-`, `.` and `_` as they are, every other character as `~XX` per UTF-8 byte; `.` and `..` as `~2E`. */
export function spell(text: string): string {
	if (!text.isWellFormed()) throw new IriError('an id is text: a lone surrogate has no UTF-8 form');
	if (text === '.' || text === '..') return '~2E'.repeat(text.length);
	let out = '';
	for (const c of text) {
		if (PLAIN.test(c)) out += c;
		else for (const b of new TextEncoder().encode(c)) out += '~' + b.toString(16).toUpperCase().padStart(2, '0');
	}
	return out;
}

/** The id a segment spells; a segment that is not the spelling of its id is refused, so an id has one IRI. */
export function unspell(segment: string): string {
	const bytes: number[] = [];
	for (let i = 0; i < segment.length;) {
		const c = segment[i];
		if (c === '~') {
			const pair = segment.slice(i + 1, i + 3);
			if (!PAIR.test(pair)) throw new IriError('a `~` is followed by two upper-case hex digits (§3.4)');
			bytes.push(Number.parseInt(pair, 16));
			i += 3;
		} else if (PLAIN.test(c)) {
			bytes.push(c.charCodeAt(0));
			i += 1;
		} else throw new IriError('a character that is not written as itself in an IRI segment (§3.4)');
	}
	let text: string;
	try {
		text = new TextDecoder('utf-8', { fatal: true }).decode(new Uint8Array(bytes));
	} catch {
		throw new IriError('not the UTF-8 form of a text (§3.4)');
	}
	if (spell(text) !== segment) throw new IriError('not the spelling of its id (§3.4)');
	return text;
}

/** Hold a schema `base` to l0.md §2.1; a base that is not one is refused, never repaired. */
export function checkBase(base: string): string {
	if (typeof base !== 'string' || !BASE.test(base)) throw new IriError('`base` is an absolute IRI ending in `/`');
	return base;
}

/** `<iri>?pin=d-<64 hex>` or `<iri>?pin=m-<epoch>@d-<64 hex>` (decision §3). */
export function pinIri(iri: string, pin: Pin): string {
	if (typeof iri !== 'string' || !ABSOLUTE.test(iri)) throw new IriError('an IRI to pin must be an absolute IRI');
	if (iri.includes('?') || iri.includes('#')) throw new IriError('cannot pin an IRI that already carries `?` or `#`');
	if (typeof pin.dataset !== 'string' || !DATASET.test(pin.dataset)) throw new IriError('hash pin must be `d-<64 hex>` (§6.4)');
	if (pin.manifest === undefined) return `${iri}?pin=${pin.dataset}`;
	if (typeof pin.manifest !== 'string' || !MANIFEST.test(pin.manifest)) throw new IriError('epoch pin must be `m-<epoch>` (§6.4)');
	return `${iri}?pin=${pin.manifest}@${pin.dataset}`;
}

/** The unpinned IRI and its pin (decision §3); fragments, other query parameters and an epoch pin alone are refused. */
export function parsePin(iri: string): { iri: string; pin?: Pin } {
	if (typeof iri !== 'string' || !ABSOLUTE.test(iri)) throw new IriError('must be an absolute IRI');
	if (iri.includes('#')) throw new IriError('fragments are not allowed in a canonical or pinned IRI');
	const at = iri.indexOf('?');
	if (at < 0) return { iri };
	const unpinned = iri.slice(0, at), query = iri.slice(at + 1);
	if (query.includes('?') || !unpinned || !ABSOLUTE.test(unpinned)) throw new IriError('malformed query in IRI');
	if (query.includes('&') || !query.startsWith('pin=')) throw new IriError('only the `pin` query parameter is allowed');
	const raw = query.slice(4);
	if (MANIFEST.test(raw)) throw new IriError('epoch pin without hash pin: `m-<epoch>` requires `@d-<64 hex>` (§6.4)');
	const match = PIN.exec(raw);
	if (!match) throw new IriError('malformed pin: expected `d-<64 hex>` or `m-<epoch>@d-<64 hex>` (§6.4)');
	return { iri: unpinned, pin: match[1] === undefined ? { dataset: match[2] } : { manifest: match[1], dataset: match[2] } };
}

/** `<space>/<spelled id>` (decision §1), pinned when a pin is given. */
export function conclusionIri(space: string, id: string, pin?: Pin): string {
	if (typeof id !== 'string' || !id) throw new IriError('row id must be non-empty text');
	const iri = `${space}/${spell(id)}`;
	return pin ? pinIri(iri, pin) : iri;
}

/** The space and the id of an unpinned conclusion IRI: the id is the last segment, strictly unspelled. */
export function splitConclusion(iri: string): { space: string; id: string } {
	const at = iri.lastIndexOf('/');
	if (at < 0 || at === iri.length - 1) throw new IriError('not a canonical conclusion or witness IRI');
	return { space: iri.slice(0, at), id: unspell(iri.slice(at + 1)) };
}

/** `canonical_sha256(witness)` (docs/contracts.md#canonical-hash) as 64 lower-case hex digits. */
export function witnessHash(witness: unknown): string {
	return createHash('sha256').update(canonicalJson(witness), 'utf8').digest('hex');
}

/** `<base>witness/<H(witness)>` (decision §2), pinned when a pin is given; a bad base is refused. */
export function witnessIri(base: string, witness: unknown, pin?: Pin): string {
	const iri = `${checkBase(base)}witness/${witnessHash(witness)}`;
	return pin ? pinIri(iri, pin) : iri;
}

/** The digest of a witness IRI under `base`, or undefined when the IRI is not in the base's witness space. */
export function witnessDigest(base: string, iri: string): string | undefined {
	const prefix = `${checkBase(base)}witness/`;
	if (!iri.startsWith(prefix)) return undefined;
	const digest = iri.slice(prefix.length);
	if (!HEX64.test(digest)) throw new IriError('a witness IRI ends with a 64-character lower-case hex digest');
	return digest;
}
