import { NOT_FOUND, ReplError } from './text.ts';

export type Fetch = (path: string, init?: RequestInit) => Promise<Response>;

export interface Connection {
	open(role: string): Promise<Fetch>;
}

export function local(root: string): Connection {
	return {
		async open(role) {
			const { openLocalGate } = await import('../../../edge/gate/src/local.ts');
			const handle = await openLocalGate(root, role);
			return (path, init) => handle(new Request(`http://rezono.local${path}`, init));
		}
	};
}

/** Use the role asserted by a configured Gate. The role never travels in the query or its body. */
export function remote(base: string, token?: string, fetcher: typeof fetch = fetch): Connection {
	const url = new URL(base);
	const localHttp = url.protocol === 'http:' && ['localhost', '127.0.0.1', '[::1]'].includes(url.hostname);
	if ((!localHttp && url.protocol !== 'https:') || url.username || url.password || url.search || url.hash)
		throw new ReplError('use an HTTPS Gate URL');
	const root = base.replace(/\/+$/, '');
	const request: Fetch = (path, init) => {
		const headers = new Headers(init?.headers);
		if (token) headers.set('authorization', `Bearer ${token}`);
		return fetcher(`${root}${path}`, { ...init, headers, redirect: 'error' });
	};
	return {
		async open(role) {
			const who = await response<{ role?: unknown }>(request, '/whoami');
			if (who.role !== role) throw new ReplError('role not served here');
			return request;
		}
	};
}

export async function response<T>(request: Fetch, path: string, init?: RequestInit): Promise<T> {
	const res = await request(path, init);
	if (res.ok) return (await res.json()) as T;
	if (res.status === 404) throw new ReplError(NOT_FOUND);
	if (res.status === 401 || res.status === 403) throw new ReplError('role not served here');
	if (res.status === 501) throw new ReplError('not served for this manifest');
	if (res.status === 422) {
		const body = await res.json().catch(() => null) as { cut?: { budget?: unknown }; error?: unknown } | null;
		if (body?.error === 'read budget exhausted' || body?.cut?.budget === 'rows' || body?.cut?.budget === 'steps')
			throw new ReplError('question exceeded the read budget');
	}
	if (res.status === 400) {
		const body = await res.json().catch(() => null) as { diagnostics?: { code?: unknown }[] } | null;
		const codes = Array.isArray(body?.diagnostics)
			? body.diagnostics.map((item) => item?.code).filter((code): code is string => typeof code === 'string' && /^R[0-9]{3}$/.test(code))
			: [];
		throw new ReplError(codes.length ? `question refused (${codes.join(', ')})` : 'bad request');
	}
	// A failed service response may contain implementation details. Use only the status.
	throw new ReplError(`gate ${res.status}`);
}
