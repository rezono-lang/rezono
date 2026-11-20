import type { Answer, BoundSweepList } from '../../../contracts/typescript/generated/explain.ts';
import type { Manifest } from '../../../contracts/typescript/generated/manifest.ts';
import { catalogueKindsQuestion, catalogueSchemaQuestion } from '../../../edge/gate/src/catalogue-questions.ts';
import { rowQuestion, type RowSelection } from '../../../edge/gate/src/row-query.ts';
import { response, type Connection, type Fetch } from './client.ts';
import { answerText } from './explain.ts';
import { NOT_FOUND, ReplError, table, terminalLine, words } from './text.ts';

export type { Answer };
export type LockedPin = Readonly<{ pack: string; manifest: string }>;
export type Pin = LockedPin & Readonly<{ role: string; bundle: string; epoch: number }>;
type ManifestPin = Pick<Manifest, 'id' | 'epoch' | 'compiled'>;
type RequestOf = (after?: string) => { path: string; init?: RequestInit };
type QueryScope = { scope?: 'catalogue' } | { scope: 'row'; row: RowSelection };
type RowSource = (cursor: string) => RequestOf;

interface Page {
	pin: Pin;
	head: ManifestPin;
	next?: string;
	request: RequestOf;
	rowSource?: RowSource;
}

const COMMANDS = new Map([
	[':use', ['session', ':use <pack> <manifest|latest> [as <role>]', 'pin the publication for this role']],
	[':more', ['session', ':more [<source-cursor>]', 'continue the last answer or a source of the selected row']],
	[':complete', ['session', ':complete <partial line>', 'complete commands and offered arguments']],
	[':help', ['session', ':help', 'show this command mapping']],
	[':quit', ['session', ':quit', 'end the session']],
	[':grounds', ['named query', ':grounds <relation> <key-part>…', 'std-explain grounds']],
	[':reach', ['named query', ':reach <relation> <key-part>…', 'std-explain reach']],
	[':gap', ['named query', ':gap <relation> <part|_>…', 'std-explain gap']],
	[':suppose', ['named query', ':suppose proposal <id>|variant <id> [impact]', 'std-explain scenario or impact']],
	[':sweep', ['named query', ':sweep [<name>]', 'std-explain sweep']],
	[':kinds', ['language alias', ':kinds', `catalogue scope: ${catalogueKindsQuestion}`]],
	[':schema', ['language alias', ':schema <kind>', `catalogue scope: ${catalogueSchemaQuestion('<kind>')}`]],
	[':row', ['language alias', ':row <kind> <key-part>…', `row scope: ${rowQuestion}`]],
	['ask', ['language', 'ask [binder:] Kind where expr [show expr, …]', 'evaluate the Rezono question']]
]);

const HELP = table(['input', 'class', 'meaning'], [...COMMANDS.values()].map(([classification, syntax, meaning]) => [syntax, classification, meaning]));
const sameHead = (left: ManifestPin, right: ManifestPin) => left.id === right.id && left.epoch === right.epoch;
function encoded(part: string): string {
	if (!part || part === '.' || part === '..') throw new ReplError(NOT_FOUND);
	return encodeURIComponent(part);
}

export function classOf(line: string): string {
	const [command] = words(line);
	const info = COMMANDS.get(command);
	if (!info) throw new ReplError('unknown command; :help lists the commands');
	return info[0];
}

export function argument(value: string): string {
	return value === '' || /[\s\x00-\x1f\x7f-\x9f]/.test(value) || value.startsWith('"') ? JSON.stringify(value) : value;
}

export class Session {
	private readonly connection: Connection;
	private readonly locked?: LockedPin;
	private readonly pageSize?: number;
	private readonly rowSourceLimit: number;
	readonly role: string;
	private fetcher?: Promise<Fetch>;
	private selected?: Pin;
	private page?: Page;
	private last?: Answer;
	done = false;

	constructor(connection: Connection, role: string, locked?: LockedPin, options: { pageSize?: number; rowSourceLimit?: number } = {}) {
		this.connection = connection;
		this.role = role;
		this.locked = locked && Object.freeze({ ...locked });
		this.pageSize = options.pageSize;
		this.rowSourceLimit = options.rowSourceLimit ?? 50;
	}

	get pin(): Pin | undefined {
		return this.selected;
	}

	get lastAnswer(): Answer | undefined {
		return this.last;
	}

	private fetch(): Promise<Fetch> {
		return this.fetcher ??= this.connection.open(this.role);
	}

	private async read<T>(path: string, init?: RequestInit): Promise<T> {
		return response(await this.fetch(), path, init);
	}

	private head(pack: string): Promise<ManifestPin> {
		return this.read(`/${encoded(pack)}/head`);
	}

	async use(pack: string, chosen: string): Promise<Pin> {
		this.last = undefined;
		if (this.locked && this.locked.pack !== pack) throw new ReplError('publication does not match the locked pin');
		const manifest = chosen === 'latest'
			? await this.head(pack)
			: await this.read<ManifestPin>(`/${encoded(pack)}/manifests/${encoded(chosen)}`);
		if ((chosen !== 'latest' && manifest.id !== chosen) || (this.locked && this.locked.manifest !== manifest.id))
			throw new ReplError('publication does not match the locked pin');
		const bundle = manifest.compiled?.find((asset) => asset.file === 'bundle/schema-bundle.json')?.sha256;
		if (typeof manifest.id !== 'string' || !Number.isSafeInteger(manifest.epoch) || !bundle || !/^[a-f0-9]{64}$/.test(bundle))
			throw new ReplError('publication has no verifiable session pin');
		const pin = Object.freeze({ pack, manifest: manifest.id, role: this.role, bundle, epoch: manifest.epoch });
		this.selected = pin;
		this.page = undefined;
		return pin;
	}

	private current(): Pin {
		if (!this.selected) throw new ReplError('select a publication with :use');
		return this.selected;
	}

	private async answered(pin: Pin, request: RequestOf, after?: string, expectedHead?: ManifestPin, rowSource?: RowSource): Promise<Answer> {
		const head = await this.head(pin.pack);
		if (expectedHead && !sameHead(head, expectedHead))
			throw new ReplError(after === undefined
				? 'the publication changed during the question; ask again'
				: 'the publication changed since the last page; ask again');
		const { path, init } = request(after);
		const answer = await this.read<Answer>(path, init);
		if (this.selected !== pin || !sameHead(await this.head(pin.pack), head))
			throw new ReplError('the publication changed during the question; ask again');
		if (answer.format !== 'rezono.answer/1' || answer.manifest_id !== pin.manifest || !Array.isArray(answer.nodes))
			throw new ReplError('gate returned an answer for a different publication or format');
		this.page = answer.next || rowSource ? { pin, head, next: answer.next, request, rowSource } : undefined;
		this.last = answer;
		return answer;
	}

	private questionRequest(pin: Pin, source: string, scope: QueryScope): RequestOf {
		return (after) => ({
			path: `/${encoded(pin.pack)}/${encoded(pin.manifest)}/ask`,
			init: {
				method: 'POST',
				headers: { 'content-type': 'application/json' },
				body: JSON.stringify({ text: source, limit: this.pageSize, after, ...scope })
			}
		});
	}

	async query(source: string, scope?: 'catalogue'): Promise<Answer> {
		const pin = this.current();
		this.page = undefined;
		return this.answered(pin, this.questionRequest(pin, source, { scope }));
	}

	private async row(kind: string, key: string[]): Promise<Answer> {
		const pin = this.current();
		this.page = undefined;
		const request = (continuation?: string) => this.questionRequest(pin, rowQuestion, {
			scope: 'row', row: { kind, key, source_limit: this.rowSourceLimit, continuation }
		});
		return this.answered(pin, request(), undefined, undefined, request);
	}

	async named(term: string, params: Readonly<Record<string, string>>): Promise<Answer> {
		return this.namedAt(this.current(), term, params);
	}

	private async namedAt(pin: Pin, term: string, params: Readonly<Record<string, string>>, head?: ManifestPin): Promise<Answer> {
		this.page = undefined;
		if (!/^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$/.test(term)) throw new ReplError('invalid question name');
		const query = new URLSearchParams(params);
		query.delete('after');
		if (this.pageSize !== undefined) query.set('limit', String(this.pageSize));
		return this.answered(pin, (after) => {
			const page = new URLSearchParams(query);
			if (after !== undefined) page.set('after', after);
			return { path: `/${encoded(pin.pack)}/${encoded(pin.manifest)}/ask/${encoded(term)}?${page}` };
		}, undefined, head);
	}

	async more(sourceCursor?: string): Promise<Answer> {
		const page = this.page;
		if (!page || this.selected !== page.pin) throw new ReplError('no further page');
		const request = sourceCursor === undefined ? page.request : page.rowSource?.(sourceCursor);
		const after = sourceCursor === undefined ? page.next : undefined;
		if (!request || (sourceCursor === undefined && !after)) throw new ReplError('no further page');
		this.page = undefined;
		return this.answered(page.pin, request, after, page.head, page.rowSource);
	}

	private async sweep(name?: string): Promise<Answer> {
		if (name !== undefined) return this.named('sweep', { sweep: name });
		const pin = this.current();
		this.page = undefined;
		const head = await this.head(pin.pack);
		const params = new URLSearchParams({ m: pin.manifest });
		const index = await this.read<BoundSweepList>(`/${encoded(pin.pack)}/sweeps?${params}`);
		if (index.manifest_id !== pin.manifest || !Array.isArray(index.sweeps) || index.sweeps.length !== 1 || this.selected !== pin)
			throw new ReplError(NOT_FOUND);
		return this.namedAt(pin, 'sweep', { sweep: index.sweeps[0].name }, head);
	}

	async search(relation: string, prefix: string): Promise<string[]> {
		this.last = undefined;
		const pin = this.current();
		const head = await this.head(pin.pack);
		const query = new URLSearchParams({ starts: prefix, limit: '50' });
		const route = `/${encoded(pin.pack)}/${encoded(pin.manifest)}/rows/${encoded(relation)}?${query}`;
		const data = await this.read<{ rows: { key: string[] }[] }>(route).catch((error: unknown) => {
			if (error instanceof ReplError && error.message === NOT_FOUND) return { rows: [] };
			throw error;
		});
		if (this.selected !== pin || !sameHead(await this.head(pin.pack), head)) return [];
		const ids = data.rows.map((row) => row.key[0]).filter((id) => typeof id === 'string' && id.startsWith(prefix));
		return [...new Set(ids)].map(argument);
	}

	async completions(partial: string): Promise<{ hits: string[]; word: string }> {
		const at = Math.max(partial.lastIndexOf(' '), partial.lastIndexOf('\t'));
		const [command, ...args] = words(partial.slice(0, at + 1));
		const word = partial.slice(at + 1);
		let offered: string[] = [];
		if (command === undefined) offered = [...COMMANDS.keys()];
		if (command === ':use' && args.length === 0) offered = await this.read<string[]>('/packs');
		if (command === ':use' && args.length === 1) offered = ['latest'];
		const prefix = word.startsWith('"') ? word.slice(1) : word;
		if (command === ':row' && args.length === 1 && this.pin)
			return { hits: await this.search(args[0], prefix), word };
		return { hits: offered.filter((hit) => hit.startsWith(prefix)).sort().map(argument), word };
	}

	private async run(line: string): Promise<string[]> {
		if (/^\s*ask(?:\s|$)/.test(line)) return answerText(await this.query(line));
		const complete = /^\s*:complete(?:[ \t](.*))?$/.exec(line);
		if (complete) return (await this.completions(complete[1] ?? '')).hits;
		const [command, ...args] = words(line);
		if (command === undefined) return [];
		if (command === ':use' && (args.length === 2 || (args.length === 4 && args[2] === 'as'))) {
			if (args.length === 4 && args[3] !== this.role) throw new ReplError('this session is locked to its startup role');
			const pin = await this.use(args[0], args[1]);
			return [`using ${pin.pack} ${pin.manifest} as ${pin.role}`];
		}
		if (command === ':more' && args.length <= 1) {
			const rowFields = this.page?.rowSource !== undefined;
			return answerText(await this.more(args[0]), rowFields);
		}
		if (command === ':kinds' && args.length === 0) return answerText(await this.query(catalogueKindsQuestion, 'catalogue'));
		if (command === ':schema' && args.length === 1) return answerText(await this.query(catalogueSchemaQuestion(args[0]), 'catalogue'));
		if (command === ':row' && args.length >= 2) return answerText(await this.row(args[0], args.slice(1)), true);
		if (command === ':help' && args.length === 0) return HELP;
		if (command === ':quit' && args.length === 0) {
			this.done = true;
			return [];
		}
		if ([':grounds', ':reach', ':gap'].includes(command) && args.length >= 2) {
			const [relation, ...parts] = args;
			const key = JSON.stringify(parts.map((part) => command === ':gap' && part === '_' ? null : part));
			return answerText(await this.named(command.slice(1), { relation, key }));
		}
		if (command === ':suppose' && ['proposal', 'variant'].includes(args[0]) && (args.length === 2 || (args.length === 3 && args[2] === 'impact')))
			return answerText(await this.named(args[2] === 'impact' ? 'impact' : 'scenario', { [args[0]]: args[1] }));
		if (command === ':sweep' && args.length <= 1) return answerText(await this.sweep(args[0]));
		const info = COMMANDS.get(command);
		throw new ReplError(info ? `usage: ${info[1]}` : 'unknown command; :help lists the commands');
	}

	async exec(line: string): Promise<string[]> {
		this.last = undefined;
		try {
			if (this.done) throw new ReplError('the session has ended');
			return (await this.run(line)).map(terminalLine);
		} catch (error) {
			this.last = undefined;
			return [`error: ${error instanceof ReplError ? error.message : 'gate request failed'}`];
		}
	}
}
