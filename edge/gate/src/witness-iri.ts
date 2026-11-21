// Canonical witness hashing and IRI construction (decisions/publication-conclusion-addresses.md §2 & §5).
import { createHash } from 'node:crypto';
import type { CalcWitness, Witness } from '../../../contracts/typescript/generated/proof.ts';
import { canonicalJson } from '../../../viewer/src/lib/canon.ts';

/**
 * Canonical SHA-256 hex digest (64 lower-case hex digits) of a witness, matching `rezono_canon.canonical_sha256`.
 * Omits only a top-level gate-added `iri` property if present; any `undefined` or `null` value is left intact so
 * `canon.ts` refuses it rather than silently repairing malformed input.
 */
export function canonicalWitnessHash(w: Witness | CalcWitness): string {
	let target: unknown = w;
	if (Object.prototype.hasOwnProperty.call(w, 'iri')) {
		const copy = { ...(w as unknown as Record<string, unknown>) };
		delete copy.iri;
		target = copy;
	}
	return createHash('sha256').update(canonicalJson(target), 'utf8').digest('hex');
}

/**
 * Canonical witness IRI per decisions/publication-conclusion-addresses.md §2 & §5:
 * - `<base>witness/<64 hex>` when a schema `baseIri` is supplied (must be an absolute IRI ending in `/`, no `?` or `#`).
 * - `rezono:w/<64 hex>` only when `baseIri` is omitted (standalone use without a schema).
 * Refuses malformed `baseIri` (including a missing trailing `/`) rather than silently repairing it.
 */
export function canonicalWitnessIri(w: Witness | CalcWitness, baseIri?: string): string {
	const hash = canonicalWitnessHash(w);
	if (baseIri === undefined) return `rezono:w/${hash}`;
	if (!baseIri || !baseIri.includes(':') || !baseIri.endsWith('/') || /[?#]/.test(baseIri)) {
		throw new Error(`invalid schema base IRI for witness (must be an absolute IRI ending in '/'): ${baseIri}`);
	}
	return `${baseIri}witness/${hash}`;
}
