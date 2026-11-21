import { flushSync, mount, unmount } from 'svelte';
import { stdPacks } from 'virtual:std-packs';
import { loadSlip } from './model.ts';
import Slip from './Slip.svelte';
import type { FetchLike, RowSelection } from './types.ts';

export interface MountOptions {
	pack: string;
	lang: string;
	row?: RowSelection;
	fetch?: FetchLike;
}

const pending = new Set<Promise<unknown>>();

function trackPending(promise: Promise<unknown>): void {
	pending.add(promise);
	void promise.finally(() => {
		pending.delete(promise);
	});
}

export function flush(): void {
	flushSync();
}

export async function whenIdle(): Promise<void> {
	while (pending.size > 0) {
		await Promise.allSettled([...pending]);
		flushSync();
	}
	flushSync();
}

export async function renderSlip(target: HTMLElement, options: MountOptions): Promise<() => void> {
	const fetchFn: FetchLike = options.fetch ?? ((input, init) => globalThis.fetch(input, init));
	const view = await loadSlip(
		fetchFn,
		{ pack: options.pack, lang: options.lang, row: options.row },
		stdPacks,
	);
	target.innerHTML = '';
	const instance = mount(Slip, {
		target,
		props: { view, onPending: trackPending },
	});
	flushSync();
	return () => {
		unmount(instance);
	};
}

if (typeof document !== 'undefined') {
	const boot = (globalThis as { __REZONO_SLIP__?: MountOptions }).__REZONO_SLIP__;
	const root = document.getElementById('slip-root');
	if (boot && root) {
		void renderSlip(root, boot);
	}
}
