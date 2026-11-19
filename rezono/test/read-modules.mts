// Read each module source given as a JSON list on the command line. Write per source the module the reader
// produced and the text the printer writes back for it, or null for both, with the diagnostics as code and span.
// Rezono's Python tests use this probe to compare the reader with a decision without the module writer.
import { moduleForm } from '../src/module-json.ts';
import { printModule } from '../src/print.ts';

const sources = JSON.parse(process.argv[2]) as string[];
const read = sources.map((source) => {
	const { form, diagnostics } = moduleForm(source);
	return {
		module: form?.module ?? null,
		printed: form ? printModule(form.module) : null,
		diagnostics: diagnostics.map(({ code, span }) => ({ code, span })),
	};
});
process.stdout.write(JSON.stringify(read));
