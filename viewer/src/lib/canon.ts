// The one canonical JSON form and hash of Rede (docs/contracts.md#canonical-hash), the twin of
// canon/rezono_canon in Python. Both must give the bytes in contracts/fixtures/canon/vectors.json.
// RFC 8785 (JCS) over a JSON value without numbers: an integer becomes decimal text, a Date ISO text.

// No parameter properties: the publisher runs this module with plain Node, which only strips types.
export class CanonError extends Error {
	readonly code: string;
	constructor(code: string, detail: string) {
		super(`${code}: ${detail}`);
		this.code = code;
	}
}

function string(s: string): string {
	if (!s.isWellFormed()) throw new CanonError('lone_surrogate', JSON.stringify(s));
	// JSON.stringify escapes exactly what RFC 8785 escapes (RFC 8785 §3.2.2.2 is defined by it).
	return JSON.stringify(s);
}

// UTF-16 code unit order (RFC 8785 §3.2.3): plain string comparison in JavaScript.
const byUnits = (a: string, b: string) => (a < b ? -1 : a > b ? 1 : 0);

function datetime(d: Date): string {
	if (Number.isNaN(d.getTime())) throw new CanonError('invalid_datetime', String(d));
	const year = d.getUTCFullYear();
	if (year < 1 || year > 9999) throw new CanonError('invalid_datetime', String(year));
	// toISOString gives YYYY-MM-DDTHH:MM:SS.sssZ; drop trailing zeros of the fraction, and the dot.
	return d.toISOString().replace(/\.?0*Z$/, 'Z');
}

function encode(v: unknown, out: string[]): void {
	if (typeof v === 'string') out.push(string(v));
	else if (typeof v === 'boolean') out.push(v ? 'true' : 'false');
	else if (typeof v === 'bigint') out.push(`"${v}"`);
	else if (typeof v === 'number') {
		if (Number.isSafeInteger(v)) out.push(`"${Object.is(v, -0) ? 0 : v}"`);
		else if (Number.isInteger(v)) throw new CanonError('unsafe_integer', `${v}: use a bigint or decimal text`);
		else throw new CanonError('float', String(v));
	} else if (v === null || v === undefined) {
		throw new CanonError('null', 'absent is a missing key; unknown is a state (docs/compiler.md)');
	} else if (v instanceof Date) out.push(`"${datetime(v)}"`);
	else if (Array.isArray(v)) {
		out.push('[');
		// Every index, not forEach: a hole would vanish ([,'x'] → ["x"]) and look like a shorter array.
		for (let i = 0; i < v.length; i++) {
			if (!(i in v)) throw new CanonError('sparse_array', `hole at index ${i}`);
			if (i) out.push(',');
			encode(v[i], out);
		}
		out.push(']');
	} else if (typeof v === 'object' && Object.getPrototypeOf(v) === Object.prototype) {
		const o = v as Record<string, unknown>;
		// Object.keys skips symbol and non-enumerable keys; content there would vanish silently.
		if (Object.getOwnPropertySymbols(o).length) throw new CanonError('symbol_key', 'a key is a string');
		const keys = Object.getOwnPropertyNames(o);
		if (keys.some((k) => !Object.prototype.propertyIsEnumerable.call(o, k)))
			throw new CanonError('unsupported', 'a non-enumerable key');
		keys.sort(byUnits);
		keys.forEach(string); // refuses a lone surrogate in a key before writing anything
		out.push('{');
		keys.forEach((k, i) => {
			if (i) out.push(',');
			out.push(string(k), ':');
			encode(o[k], out);
		});
		out.push('}');
	} else throw new CanonError('unsupported', Object.prototype.toString.call(v));
}

/** The canonical JSON text of `value`. */
export function canonicalJson(value: unknown): string {
	const out: string[] = [];
	encode(value, out);
	return out.join('');
}

/** SHA-256 of bytes as stored (a file, a snapshot), or of the UTF-8 of a text, as lowercase hex. */
export async function sha256Hex(data: Uint8Array | string): Promise<string> {
	const bytes = typeof data === 'string' ? new TextEncoder().encode(data) : data;
	const digest = await crypto.subtle.digest('SHA-256', bytes as Uint8Array<ArrayBuffer>);
	return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, '0')).join('');
}

/** SHA-256 of the canonical JSON of `value`: the hash of a value everywhere in Rede. */
export function canonicalSha256(value: unknown): Promise<string> {
	return sha256Hex(canonicalJson(value));
}
