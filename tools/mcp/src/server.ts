import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { z } from 'zod';
import type { Fetch } from '../../repl/src/client.ts';
import type { Session } from '../../repl/src/session.ts';

export type Pin = { pack: string; manifest: string };
export type SessionInput = Pick<Session, 'exec' | 'search'> & { readonly pin?: Pin };
const verifiedProposal = Symbol('verified proposal capability');
type ProposalAccess = {
	[verifiedProposal]: true;
	submit(pack: string, body: unknown): Promise<{ status: number; text: string }>;
};
type Access = { mode: 'store' } | { mode: 'gate'; proposal?: ProposalAccess };
type Options = { access?: Access; lockedPin?: Pin };

const identity = z.object({ role: z.string(), rights: z.array(z.string()) }).strict();
const pack = z.string().regex(/^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$/);
const nonempty = z.string().min(1);
const reads = { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false };
const target = z.array(z.string()).min(2).describe('A relation and its key parts, or a kind, id and slot.');
const args = (...parts: string[]) => parts.map(part => JSON.stringify(part)).join(' ');

function text(lines: string[]) {
	const error = lines.length === 1 && lines[0].startsWith('error: ');
	return { content: [{ type: 'text' as const, text: lines.join('\n') }], ...(error ? { isError: true } : {}) };
}

/** The authenticated Gate's /whoami grants the proposal right for the served role. */
export async function proposalAccess(request: Fetch, role: string, hasCredential: boolean): Promise<ProposalAccess | undefined> {
	async function allowed(): Promise<boolean> {
		try {
			const response = await request('/whoami', { cache: 'no-store' });
			if (!response.ok) return false;
			const who = identity.safeParse(await response.json());
			return who.success && who.data.role === role && who.data.rights.includes('propose');
		} catch {
			return false;
		}
	}

	if (!hasCredential || !await allowed()) return;
	return {
		[verifiedProposal]: true,
		async submit(pack, body) {
			if (!await allowed()) return { status: 403, text: '' };
			const response = await request(`/${encodeURIComponent(pack)}/proposals`, {
				method: 'POST',
				headers: { 'content-type': 'application/json' },
				body: JSON.stringify(body),
			});
			return { status: response.status, text: await response.text() };
		},
	};
}

/** A tool runs one turn of the same role-scoped session as the REPL. */
export function mcpServer(session: SessionInput, role: string, options: Options = {}): McpServer {
	const server = new McpServer({ name: 'rezono', version: '0.1.0' });
	let pending: Promise<unknown> = Promise.resolve();

	function turn<T>(work: () => Promise<T>): Promise<T> {
		const result = pending.then(work);
		pending = result.then(() => undefined, () => undefined);
		return result;
	}

	async function select(on: string) {
		const locked = options.lockedPin;
		if (locked && locked.pack !== on) return text(['error: pack is outside this recording']);
		const selector = locked?.manifest ?? 'latest';
		const picked = session.pin;
		if (picked?.pack === on && (!locked || picked.manifest === locked.manifest)) return;
		const used = text(await session.exec(`:use ${args(on, selector)} as ${args(role)}`));
		if (used.isError) return used;
	}

	function run(on: string | undefined, line: string | (() => Promise<string[]>)) {
		return turn(async () => {
			const refused = on === undefined ? undefined : await select(on);
			return refused ?? text(await (typeof line === 'string' ? session.exec(line) : line()));
		});
	}

	server.registerTool('kinds', {
		description: 'The kinds in this role’s pinned publication, via the catalogue question.',
		inputSchema: { pack },
		annotations: reads,
	}, async (a) => run(a.pack, ':kinds'));
	server.registerTool('schema', {
		description: 'The available slots, types, and coverage for one kind in this role’s pinned catalogue.',
		inputSchema: { pack, kind: nonempty },
		annotations: reads,
	}, async (a) => run(a.pack, `:schema ${args(a.kind)}`));
	server.registerTool('row', {
		description: 'The typed cells and outcomes of one row this role can read.',
		inputSchema: { pack, kind: nonempty, id: nonempty.optional(), key: z.array(z.string()).min(1).optional() },
		annotations: reads,
	}, async (a) => {
		const key = a.key ?? (a.id === undefined ? undefined : [a.id]);
		if (!key || (a.key && a.id !== undefined)) return text(['error: supply either id or key']);
		return run(a.pack, `:row ${args(a.kind, ...key)}`);
	});
	server.registerTool('search', {
		description: 'Complete a row identifier prefix in this role’s publication, in the REPL’s key order.',
		inputSchema: { pack, kind: nonempty, prefix: z.string().default('') },
		annotations: reads,
	}, async (a) => run(a.pack, () => session.search(a.kind, a.prefix)));
	server.registerTool('grounds', {
		description: 'The grounds named question for a row, as far as this role may read.',
		inputSchema: { pack, target },
		annotations: reads,
	}, async (a) => run(a.pack, `:grounds ${args(...a.target)}`));
	server.registerTool('reach', {
		description: 'The reach named question, which shows what depends on a row.',
		inputSchema: { pack, target },
		annotations: reads,
	}, async (a) => run(a.pack, `:reach ${args(...a.target)}`));
	server.registerTool('sweep', {
		description: 'The published sweep grid and variants this role can read.',
		inputSchema: { pack, name: nonempty.optional() },
		annotations: reads,
	}, async (a) => run(a.pack, a.name === undefined ? ':sweep' : `:sweep ${args(a.name)}`));
	server.registerTool('ask', {
		description: 'A Rezono ask expression over this role’s pinned publication, with value states and undecided reasons.',
		inputSchema: { pack, text: z.string().regex(/^\s*ask(?:\s|$)/) },
		annotations: reads,
	}, async (a) => run(a.pack, a.text));
	server.registerTool('more', {
		description: 'Continue the last answer or a row source cursor in this session.',
		inputSchema: { cursor: nonempty.optional() },
		annotations: reads,
	}, async (a) => run(undefined, a.cursor === undefined ? ':more' : `:more ${args(a.cursor)}`));

	const proposal = options.access?.mode === 'gate' ? options.access.proposal : undefined;
	if (proposal?.[verifiedProposal] && options.lockedPin === undefined) {
		server.registerTool('propose', {
			description: 'Submit a proposal for one slot value through the configured gate for review.',
			inputSchema: { pack, kind: nonempty, id: nonempty, slot: nonempty, value: z.string(), title: nonempty },
			annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: false, openWorldHint: true },
		}, (a) => turn(async () => {
			const used = text(await session.exec(`:use ${args(a.pack, 'latest')} as ${args(role)}`));
			if (used.isError) return used;
			const pin = session.pin;
			if (!pin || pin.pack !== a.pack) return text(['error: the gate has no pinned publication for the proposal']);
			const delta = {
				format: 'rezono.delta/1', pack: pin.pack, base_manifest: pin.manifest,
				changes: [{ op: 'set', kind: a.kind, key: a.id, slot: a.slot, value: a.value }],
			};
			const response = await proposal.submit(pin.pack, { delta, title: a.title });
			if (response.status === 202) return text([response.text]);
			if (response.status === 401 || response.status === 403) return text([`error: role ${role} may not propose`]);
			return text([`error: the gate refused the proposal (${response.status})`]);
		}));
	}
	return server;
}
