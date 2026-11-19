// A reader in the test that answers one question more than the local reader: `gap`, for an absent row of a
// derived relation, with an empty walk. viewer/slip/bin/render.ts loads it as `reader` and wraps the local
// reader's handler with it (decisions/viewer-slip.md, The page and how it gets its answers).
export default function answersGap(handle) {
	return async (request) => {
		const url = new URL(request.url);
		const parts = url.pathname.split('/').filter(Boolean).map(decodeURIComponent);
		if (request.method === 'GET' && parts.length === 4 && parts[2] === 'ask' && parts[3] === 'gap') {
			const start = { relation: url.searchParams.get('relation'), key: url.searchParams.get('key') };
			return Response.json({
				format: 'rezono.answer/1', question: 'gap', manifest_id: parts[1], start,
				nodes: [{ distance: 0, ...start }], gap: { premises: [], cut: false }
			});
		}
		return handle(request);
	};
}
