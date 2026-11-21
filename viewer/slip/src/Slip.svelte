<script lang="ts">
	import type { SlipView } from './types.ts';

	let { view }: { view: SlipView } = $props();
</script>

<main data-pack={view.pack} data-lang={view.lang}>
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
				</tr>
			</thead>
			<tbody>
				{#each view.lines as line (line.index)}
					<tr
						id="line-{line.index}"
						data-line={String(line.index)}
						data-relation={line.relation}
						data-key={line.key}
						data-depth={String(line.depth)}
						data-polarity={line.polarity}
						data-part={line.part}
					>
						<td data-part="label">{line.label}</td>
						<td
							data-part="value"
							data-state={line.state}
							data-reason={line.state !== 'known' && line.reason ? line.reason : undefined}
						>
							{line.value}
						</td>
						<td data-part="origin">{line.origin}</td>
					</tr>
				{/each}
			</tbody>
		</table>
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

	<footer data-part="seal">
		<span data-check="reader-hashes">{view.seal.readerHashesLabel}</span>
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

	table[data-sheet='slip'] {
		width: 100%;
		border-collapse: collapse;
		font-variant-numeric: tabular-nums;
	}

	table[data-sheet='slip'] th,
	table[data-sheet='slip'] td {
		text-align: left;
		padding: 6px 8px;
		border-bottom: 1px solid #d0d7de;
	}

	tr[data-depth='1'] td[data-part='label'] {
		padding-left: 24px;
	}

	tr[data-part='total'] {
		font-weight: 600;
		border-top: 1px solid #24292f;
		border-bottom: 3px double #24292f;
	}

	footer[data-part='seal'] {
		margin-top: 24px;
		font-size: 12px;
		display: flex;
		gap: 16px;
		flex-wrap: wrap;
	}
</style>
