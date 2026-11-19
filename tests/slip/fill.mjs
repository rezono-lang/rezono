// Fill messages with viewer/messages/src/fill.ts: a JSON list of {resources, lang, id, args} on standard input,
// a JSON list of {text}, {absent: true} or {error: <the error's name>} on standard output.
import { readFileSync } from 'node:fs';
import { fill } from '../../viewer/messages/src/fill.ts';

const out = JSON.parse(readFileSync(0, 'utf8')).map(({ resources, lang, id, args }) => {
	try {
		const text = fill(resources, lang, id, args);
		return text === undefined ? { absent: true } : { text };
	} catch (error) {
		return { error: error instanceof Error ? error.name : String(error) };
	}
});
process.stdout.write(JSON.stringify(out));
