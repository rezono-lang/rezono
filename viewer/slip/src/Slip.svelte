<script lang="ts">
	import type { AnswerTable, SignInfo, SlipLine, SlipView } from './types.ts';

	let { view }: { view: SlipView } = $props();

	let activeAnswer = $state<AnswerTable | undefined>(undefined);
	let focusedLine = $state<number | undefined>(undefined);
	let rootEl: HTMLElement | undefined;

	function activateVerb(lineIndex: number, verbName: string): void {
		const found = view.answersByKey[`${lineIndex}:${verbName}`];
		if (!found) return;
		activeAnswer = found;
		focusedLine = lineIndex;
		queueMicrotask(() => {
			const rowEl = rootEl?.querySelector<HTMLElement>(`tr[data-line="${lineIndex}"]`);
			rowEl?.focus();
		});
	}

	function handleLineKeydown(event: KeyboardEvent, line: SlipLine): void {
		const pressed = event.key.toLowerCase();
		const matched = line.verbs.find((verb) => verb.key.toLowerCase() === pressed);
		if (!matched) return;
		event.preventDefault();
		activateVerb(line.index, matched.verb);
	}

	function closeAnswer(): void {
		activeAnswer = undefined;
		if (focusedLine !== undefined) {
			const target = focusedLine;
			queueMicrotask(() => {
				const rowEl = rootEl?.querySelector<HTMLElement>(`tr[data-line="${target}"]`);
				rowEl?.focus();
			});
		}
	}

	const legendEntries = $derived.by((): SignInfo[] => {
		const drawn = new Set<string>();
		for (const line of view.lines) {
			if (line.valueSign) drawn.add(line.valueSign.name);
			if (line.originSign) drawn.add(line.originSign.name);
		}
		if (activeAnswer) {
			for (const row of activeAnswer.rows) {
				for (const cell of row.cells) {
					if (cell.sign) drawn.add(cell.sign.name);
				}
			}
		}
		if (view.seal.sealSign) {
			drawn.add(view.seal.sealSign.name);
		}
		return view.signCatalog.filter((entry) => drawn.has(entry.name));
	});
</script>

<main bind:this={rootEl} data-pack={view.pack} data-lang={view.lang}>
	{#if view.kind === 'slip'}
		<p data-part="sentence">
			{#each view.sentence as segment}
				{#if segment.line !== undefined}
					<a href="#line-{segment.line}" data-line={String(segment.line)}>{segment.text}</a>
				{:else}
					{segment.text}
				{/if}
			{/each}
		</p>

		<table data-sheet="slip">
			<thead>
				<tr>
					<th scope="col">{view.headers.line}</th>
					<th scope="col">{view.headers.value}</th>
					<th scope="col">{view.headers.origin}</th>
					<th scope="col">{view.headers.verbs}</th>
				</tr>
			</thead>
			<tbody>
				{#each view.lines as line (line.index)}
					<tr
						id="line-{line.index}"
						tabindex="0"
						data-line={String(line.index)}
						data-relation={line.relation}
						data-key={line.key}
						data-depth={String(line.depth)}
						data-polarity={line.polarity}
						data-part={line.part}
						data-path={line.path}
						onfocus={() => {
							focusedLine = line.index;
						}}
						onkeydown={(event) => handleLineKeydown(event, line)}
					>
						<td data-part="label">{line.label}</td>
						<td
							data-part="value"
							data-state={line.state}
							data-reason={line.state !== 'known' && line.reason ? line.reason : undefined}
						>
							{#if line.state === 'known'}
								{line.value}
							{:else}
								{#if line.valueSign}
									<span data-sign={line.valueSign.name} aria-hidden="true">
										{line.valueSign.glyph}
									</span>
								{/if}
								<span>{line.value}</span>
							{/if}
						</td>
						<td data-part="origin">
							{#if line.originSign}
								<span data-sign={line.originSign.name} aria-hidden="true">
									{line.originSign.glyph}
								</span>
							{/if}
							{line.origin}
						</td>
						<td data-part="verbs">
							{#each line.verbs as verb (verb.verb)}
								<button
									type="button"
									data-verb={verb.verb}
									data-key={verb.key}
									data-primary={verb.primary ? 'true' : undefined}
									onclick={() => activateVerb(line.index, verb.verb)}
								>
									{verb.label}
								</button>
							{/each}
						</td>
					</tr>
				{/each}
			</tbody>
		</table>

		{#if activeAnswer}
			<section data-part="answer">
				<table data-answer={activeAnswer.question}>
					<caption>{activeAnswer.heading}</caption>
					<thead>
						<tr>
							{#each activeAnswer.headers as heading}
								<th scope="col">{heading}</th>
							{/each}
						</tr>
					</thead>
					<tbody>
						{#each activeAnswer.rows as row}
							<tr data-depth={row.depth !== undefined ? String(row.depth) : undefined}>
								{#each row.cells as cell}
									<td>
										{#if cell.sign}
											<span data-sign={cell.sign.name} aria-hidden="true">
												{cell.sign.glyph}
											</span>
										{/if}
										{cell.text}
									</td>
								{/each}
							</tr>
						{/each}
					</tbody>
				</table>
				{#if activeAnswer.cutMessage}
					<p data-part="answer-cut">{activeAnswer.cutMessage}</p>
				{/if}
				{#if activeAnswer.moreLabel}
					<p data-part="answer-more">{activeAnswer.moreLabel}</p>
				{/if}
				<button type="button" data-action="close-answer" onclick={closeAnswer}>
					{view.labels.closeAnswer}
				</button>
			</section>
		{/if}
	{:else}
		<section data-part="relations">
			<h1>{view.labels.relationsHeading}</h1>
			<ul>
				{#each view.relations as rel (rel.id)}
					<li data-relation={rel.id}>{rel.label}</li>
				{/each}
			</ul>
		</section>
	{/if}

	<aside data-part="key">
		<table data-part="legend">
			<caption>{view.legendHeaders.title}</caption>
			<thead>
				<tr>
					<th scope="col">{view.legendHeaders.sign}</th>
					<th scope="col">{view.legendHeaders.meaning}</th>
				</tr>
			</thead>
			<tbody>
				{#each legendEntries as entry (entry.name)}
					<tr data-sign={entry.name}>
						<td data-part="legend-sign">{entry.glyph || entry.label}</td>
						<td data-part="legend-meaning">{entry.label}</td>
					</tr>
				{/each}
			</tbody>
		</table>
	</aside>

	<footer data-part="seal">
		<span data-check="reader-hashes" data-sign={view.seal.sealSign?.name}>
			{view.seal.readerHashesLabel}
		</span>
		{#if view.seal.witnessCheck}
			<span data-check="publisher-record" data-status={view.seal.witnessCheck}>
				{view.seal.witnessCheck}
			</span>
		{/if}
		<span data-part="manifest-hash">{view.seal.manifestSha256}</span>
	</footer>
</main>

<style>
	main {
		font-family: system-ui, sans-serif;
		max-width: 1280px;
		margin: 0 auto;
		padding: 16px;
	}

	[data-part='sentence'] {
		font-size: 18px;
		line-height: 1.5;
		margin: 0 0 16px;
	}

	table {
		width: 100%;
		border-collapse: collapse;
		font-variant-numeric: tabular-nums;
	}

	table th,
	table td {
		text-align: left;
		padding: 6px 8px;
		border-bottom: 1px solid #d0d7de;
	}

	table caption {
		text-align: left;
		font-weight: 600;
		margin: 16px 0 8px;
	}

	tr[data-depth='1'] td[data-part='label'] {
		padding-left: 24px;
	}

	tr[data-depth='2'] td[data-part='label'] {
		padding-left: 40px;
	}

	tr[data-part='total'] {
		font-weight: 600;
		border-top: 1px solid #24292f;
		border-bottom: 3px double #24292f;
	}

	td[data-part='verbs'] {
		display: flex;
		gap: 6px;
		flex-wrap: wrap;
	}

	section[data-part='answer'],
	aside[data-part='key'] {
		margin-top: 20px;
	}

	footer[data-part='seal'] {
		margin-top: 24px;
		font-size: 12px;
		display: flex;
		gap: 16px;
		flex-wrap: wrap;
	}
</style>
