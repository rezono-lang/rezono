// Read each question source given as a JSON list on the command line. Write per source the tree the reader
// produced and the text the printer writes back for it, or null for both, with the diagnostics as code and span.
// Rezono's Python tests use this probe to compare the question reader with a decision.
import { parse } from '../src/parse.ts';
import { print } from '../src/print.ts';

const sources = JSON.parse(process.argv[2]) as string[];
const read = sources.map((source) => {
	const { tree, diagnostics } = parse(source);
	return {
		question: tree ?? null,
		printed: tree ? print(tree) : null,
		diagnostics: diagnostics.map(({ code, span }) => ({ code, span })),
	};
});
process.stdout.write(JSON.stringify(read));
