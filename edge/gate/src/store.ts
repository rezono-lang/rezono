export interface ListOptions {
	limit?: number;
	after?: string;
	delimiter?: string;
}

export interface Store {
	get(key: string, maxBytes?: number): Promise<Uint8Array | undefined>;
	list(prefix: string, options?: ListOptions): Promise<string[]>;
}

export class StoreLimit extends Error {}

/** A directory as a bucket (tests, one VM without object storage). Node only. */
export async function fileStore(root: string): Promise<Store> {
	const { open, readdir, realpath } = await import('node:fs/promises');
	const { join } = await import('node:path');
	root = await realpath(root);
	return {
		async get(key, maxBytes = 8 * 1024 * 1024) {
			if (!key.split('/').every((part) => /^[A-Za-z0-9][A-Za-z0-9._-]*$/.test(part) && !part.includes('..'))) return undefined;
			const path = join(root, key);
			try {
				if (await realpath(path) !== path) return undefined;
				const file = await open(path, 'r');
				try {
					const stat = await file.stat();
					if (!stat.isFile()) return undefined;
					if (stat.size > maxBytes) throw new StoreLimit();
					const bytes = new Uint8Array(stat.size + 1);
					const { bytesRead } = await file.read(bytes, 0, bytes.length, 0);
					if (bytesRead !== stat.size) throw new Error('publication object changed while reading');
					return bytes.subarray(0, bytesRead);
				} finally {
					await file.close();
				}
			} catch (error) {
				if (error && typeof error === 'object' && 'code' in error && error.code === 'ENOENT') return undefined;
				throw error;
			}
		},
		/**
		 * A sorted walk that enters only the directories that can hold a key under the prefix and after `after`,
		 * and stops at `limit`: a list of one key reads one directory per level, not the whole tree. With the
		 * delimiter "/", a directory below the prefix is listed as its common prefix.
		 */
		async list(prefix, { limit, after, delimiter } = {}) {
			if (delimiter !== undefined && delimiter !== '/') throw new Error('rezono: the directory store lists by "/" only');
			const out: string[] = [];
			const full = () => limit !== undefined && out.length >= limit;
			async function walk(dir: string, rel: string): Promise<void> {
				let entries;
				try {
					entries = await readdir(join(root, dir), { withFileTypes: true });
				} catch {
					return;
				}
				// In key order: a directory sorts as its name and a slash ("a-b" before "a/").
				const named = entries
					.filter((d) => !d.name.startsWith('.') && (d.isFile() || d.isDirectory()))
					.map((d) => ({ key: `${rel}${d.name}${d.isDirectory() ? '/' : ''}`, dir: d.isDirectory(), name: d.name }))
					.sort((a, b) => (a.key < b.key ? -1 : a.key > b.key ? 1 : 0));
				for (const e of named) {
					if (full()) return;
					if (e.dir) {
						// Only a directory whose keys can begin with the prefix and come after `after`.
						if (!(e.key.startsWith(prefix) || prefix.startsWith(e.key))) continue;
						if (after && e.key < after && !after.startsWith(e.key)) continue;
						// With a delimiter, a directory below the prefix is one common prefix, never entered.
						if (delimiter && e.key.startsWith(prefix)) {
							if (!after || e.key > after) out.push(e.key);
							continue;
						}
						await walk(join(dir, e.name), e.key);
					} else if (e.key.startsWith(prefix) && (!after || e.key > after)) out.push(e.key);
				}
			}
			await walk('', '');
			return out;
		}
	};
}
