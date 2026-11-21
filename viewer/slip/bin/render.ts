import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { Window } from 'happy-dom';
import { openLocalGate } from '../../../edge/gate/src/local.ts';
import { buildSlip } from '../src/build.ts';
import type { FetchLike, RenderRequest } from '../src/types.ts';

type GateHandler = (request: Request) => Promise<Response>;

const DOM_GLOBALS = [
	'window',
	'document',
	'Node',
	'Element',
	'HTMLElement',
	'HTMLMediaElement',
	'HTMLInputElement',
	'HTMLButtonElement',
	'SVGElement',
	'Text',
	'Comment',
	'DocumentFragment',
	'Event',
	'CustomEvent',
	'FocusEvent',
	'InputEvent',
	'KeyboardEvent',
	'MouseEvent',
	'MutationObserver',
	'navigator',
	'location',
] as const;

async function main(): Promise<void> {
	const raw = readFileSync(0, 'utf8');
	const request = JSON.parse(raw) as RenderRequest;
	let handle: GateHandler = await openLocalGate(request.store, request.role);
	if (request.reader) {
		const mod = (await import(pathToFileURL(resolve(request.reader)).href)) as {
			default?: (next: GateHandler) => GateHandler;
		};
		if (typeof mod.default !== 'function') {
			throw new Error(`Reader wrapper ${request.reader} does not have a default export function`);
		}
		handle = mod.default(handle);
	}

	const { files, hashes } = await buildSlip();
	const stage = mkdtempSync(join(tmpdir(), 'rezono-slip-'));
	const win = new Window({ url: 'http://localhost/' });
	const saved = new Map<string, PropertyDescriptor | undefined>();

	try {
		for (const key of DOM_GLOBALS) {
			saved.set(key, Object.getOwnPropertyDescriptor(globalThis, key));
			const value = key === 'window' ? win : (win as unknown as Record<string, unknown>)[key];
			Object.defineProperty(globalThis, key, {
				value,
				configurable: true,
				writable: true,
			});
		}

		const bundlePath = join(stage, 'slip.js');
		writeFileSync(bundlePath, files.get('slip.js')!);

		const fetchViaGate: FetchLike = async (input, init) => {
			if (input instanceof Request) {
				return handle(input);
			}
			const url = new URL(String(input), 'http://localhost');
			return handle(new Request(url, init));
		};

		const app = (await import(pathToFileURL(bundlePath).href)) as {
			flush: () => void;
			renderSlip: (
				target: HTMLElement,
				options: {
					pack: string;
					lang: string;
					row?: RenderRequest['row'];
					fetch: FetchLike;
				},
			) => Promise<() => void>;
		};

		await app.renderSlip(win.document.body as unknown as HTMLElement, {
			pack: request.pack,
			lang: request.lang,
			row: request.row,
			fetch: fetchViaGate,
		});

		for (const action of request.keys ?? []) {
			const rowEl = win.document.querySelector(`tr[data-line="${action.line}"]`) as
				| (HTMLElement & { focus?: () => void })
				| null;
			if (!rowEl) {
				throw new Error(`No line with index ${action.line}`);
			}
			if (action.key !== undefined) {
				rowEl.focus?.();
				const event = new win.KeyboardEvent('keydown', {
					key: action.key,
					bubbles: true,
					cancelable: true,
				});
				rowEl.dispatchEvent(event);
				app.flush();
				await Promise.resolve();
			}
		}

		const html = win.document.body.innerHTML;
		process.stdout.write(JSON.stringify({ html, files: hashes }));
	} finally {
		for (const [key, desc] of saved) {
			if (desc) {
				Object.defineProperty(globalThis, key, desc);
			} else {
				delete (globalThis as unknown as Record<string, unknown>)[key];
			}
		}
		await win.happyDOM.close();
		rmSync(stage, { recursive: true, force: true });
	}
}

await main();
