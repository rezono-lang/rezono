import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { z } from 'zod';
import type { Fetch } from '../../repl/src/client.ts';
import type { Answer, Session } from '../../repl/src/session.ts';

export type Pin = { pack: string; manifest: string };
export type SessionInput = Pick<Session, 'exec' | 'search'> & {
	readonly pin?: Pin;
	readonly lastAnswer?: Answer;
};
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
const gapTarget = z.array(z.string().nullable()).min(2)
	.describe('A relation and its key parts, using null or "_" for wildcard positions.');
const args = (...parts: string[]) => parts.map(part => JSON.stringify(part)).join(' ');

function parseJson(raw: string): unknown {
	try {
		return JSON.parse(raw);
	} catch {
		return raw;
	}
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

	function reply(tool: string, lines: string[], extra: Record<string, unknown> = {}) {
		const error = lines.length === 1 && lines[0].startsWith('error: ');
		const pin = session.pin;
		const header = {
			tool,
			ok: !error,
			role,
			...(pin ? { pack: pin.pack, manifest: pin.manifest } : {}),
		};
		const structuredContent = error
			? { ...header, error: lines[0].slice('error: '.length), lines }
			: { ...header, lines, ...extra };
		return {
			content: [{ type: 'text' as const, text: lines.join('\n') }],
			structuredContent,
			...(error ? { isError: true } : {}),
		};
	}

	async function select(tool: string, on: string) {
		const locked = options.lockedPin;
		if (locked && locked.pack !== on) return reply(tool, ['error: pack is outside this recording']);
		const selector = locked?.manifest ?? 'latest';
		const picked = session.pin;
		if (picked?.pack === on && (!locked || picked.manifest === locked.manifest)) return;
		const used = reply(tool, await session.exec(`:use ${args(on, selector)} as ${args(role)}`));
		if (used.isError) return used;
	}

	function run(
		tool: string,
		on: string | undefined,
		line: string | (() => Promise<string[]>),
		structured?: (lines: string[]) => Record<string, unknown>,
	) {
		return turn(async () => {
			const refused = on === undefined ? undefined : await select(tool, on);
			if (refused) return refused;
			const lines = await (typeof line === 'string' ? session.exec(line) : line());
			const extra = structured
				? structured(lines)
				: (session.lastAnswer !== undefined ? { answer: session.lastAnswer } : {});
			return reply(tool, lines, extra);
		});
	}

	server.registerTool('kinds', {
		description: 'The kinds in this role’s pinned publication, via the catalogue question.',
		inputSchema: { pack },
		annotations: reads,
	}, async (a) => run('kinds', a.pack, ':kinds'));
	server.registerTool('schema', {
		description: 'The available slots, types, and coverage for one kind in this role’s pinned catalogue.',
		inputSchema: { pack, kind: nonempty },
		annotations: reads,
	}, async (a) => run('schema', a.pack, `:schema ${args(a.kind)}`));
	server.registerTool('row', {
		description: 'The typed cells and outcomes of one row this role can read.',
		inputSchema: { pack, kind: nonempty, id: nonempty.optional(), key: z.array(z.string()).min(1).optional() },
		annotations: reads,
	}, async (a) => {
		const key = a.key ?? (a.id === undefined ? undefined : [a.id]);
		if (!key || (a.key && a.id !== undefined)) return reply('row', ['error: supply either id or key']);
		return run('row', a.pack, `:row ${args(a.kind, ...key)}`);
	});
	server.registerTool('search', {
		description: 'Complete a row identifier prefix in this role’s publication, in the REPL’s key order.',
		inputSchema: { pack, kind: nonempty, prefix: z.string().default('') },
		annotations: reads,
	}, async (a) => run('search', a.pack, () => session.search(a.kind, a.prefix), (matches) => ({ matches })));
	server.registerTool('grounds', {
		description: 'The grounds named question for a row, as far as this role may read.',
		inputSchema: { pack, target },
		annotations: reads,
	}, async (a) => run('grounds', a.pack, `:grounds ${args(...a.target)}`));
	server.registerTool('reach', {
		description: 'The reach named question, which shows what depends on a row.',
		inputSchema: { pack, target },
		annotations: reads,
	}, async (a) => run('reach', a.pack, `:reach ${args(...a.target)}`));
	server.registerTool('gap', {
		description: 'The gap named question for an absent row or partial key, as far as this role may read.',
		inputSchema: { pack, target: gapTarget },
		annotations: reads,
	}, async (a) => {
		const [relation, ...parts] = a.target;
		if (typeof relation !== 'string' || !relation) return reply('gap', ['error: supply a relation name first']);
		return run('gap', a.pack, `:gap ${args(relation, ...parts.map(part => part === null ? '_' : part))}`);
	});
	server.registerTool('suppose', {
		description: 'Evaluate a proposal or variant through the scenario or impact named question.',
		inputSchema: {
			pack,
			proposal: nonempty.optional().describe('Proposal identifier to evaluate.'),
			variant: nonempty.optional().describe('Variant identifier to evaluate.'),
			impact: z.boolean().optional().describe('When true, ask the impact named question instead of scenario.'),
		},
		annotations: reads,
	}, async (a) => {
		if ((a.proposal === undefined) === (a.variant === undefined)) {
			return reply('suppose', ['error: supply either proposal or variant']);
		}
		const kind = a.proposal !== undefined ? 'proposal' : 'variant';
		const id = a.proposal ?? a.variant!;
		const command = a.impact ? `:suppose ${args(kind, id, 'impact')}` : `:suppose ${args(kind, id)}`;
		return run('suppose', a.pack, command);
	});
	server.registerTool('sweep', {
		description: 'The published sweep grid and variants this role can read.',
		inputSchema: { pack, name: nonempty.optional() },
		annotations: reads,
	}, async (a) => run('sweep', a.pack, a.name === undefined ? ':sweep' : `:sweep ${args(a.name)}`));
	server.registerTool('ask', {
		description: 'A Rezono ask expression over this role’s pinned publication, with value states and undecided reasons.',
		inputSchema: { pack, text: z.string().regex(/^\s*ask(?:\s|$)/) },
		annotations: reads,
	}, async (a) => run('ask', a.pack, a.text));
	server.registerTool('more', {
		description: 'Continue the last answer or a row source cursor in this session.',
		inputSchema: { cursor: nonempty.optional() },
		annotations: reads,
	}, async (a) => run('more', undefined, a.cursor === undefined ? ':more' : `:more ${args(a.cursor)}`));

	const proposal = options.access?.mode === 'gate' ? options.access.proposal : undefined;
	if (proposal?.[verifiedProposal] && options.lockedPin === undefined) {
		server.registerTool('propose', {
			description: 'Submit a proposal for one slot value through the configured gate for review.',
			inputSchema: { pack, kind: nonempty, id: nonempty, slot: nonempty, value: z.string(), title: nonempty },
			annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: false, openWorldHint: true },
		}, (a) => turn(async () => {
			const used = reply('propose', await session.exec(`:use ${args(a.pack, 'latest')} as ${args(role)}`));
			if (used.isError) return used;
			const pin = session.pin;
			if (!pin || pin.pack !== a.pack) return reply('propose', ['error: the gate has no pinned publication for the proposal']);
			const delta = {
				format: 'rezono.delta/1', pack: pin.pack, base_manifest: pin.manifest,
				changes: [{ op: 'set', kind: a.kind, key: a.id, slot: a.slot, value: a.value }],
			};
			const response = await proposal.submit(pin.pack, { delta, title: a.title });
			if (response.status === 202) {
				return reply('propose', [response.text], { status: response.status, delta, response: parseJson(response.text) });
			}
			if (response.status === 401 || response.status === 403) return reply('propose', [`error: role ${role} may not propose`]);
			return reply('propose', [`error: the gate refused the proposal (${response.status})`]);
		}));
	}
	return server;
}
