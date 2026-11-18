import { createHash } from 'node:crypto';
import { argument, type Pin, type Session } from './session.ts';
import { ReplError } from './text.ts';

export const FORMAT = '# rezono-repl-session/1';
export const PROMPT = 'rezono> ';
const INPUT = '> ';
const OUTPUT = '| ';
const PIN = '# pin ';

const linesOf = (text: string): string[] => text.slice(0, -1).split('\n');
const sha256 = (text: string): string => createHash('sha256').update(text, 'utf8').digest('hex');
const selection = (pin: Pin): string => `:use ${argument(pin.pack)} ${argument(pin.manifest)} as ${argument(pin.role)}`;

export class Recorder {
	private readonly lines: string[] = [FORMAT];
	private readonly session: Session;

	constructor(session: Session) {
		this.session = session;
	}

	async exec(source: string): Promise<string[]> {
		const before = this.session.pin;
		const output = await this.session.exec(source);
		const pin = this.session.pin;
		let input = source;
		if (pin && pin !== before) {
			this.lines.push(`${PIN}${JSON.stringify(pin)}`);
			input = selection(pin);
		}
		this.lines.push(`${INPUT}${JSON.stringify(input)}`, ...output.map((line) => `${OUTPUT}${JSON.stringify(line)}`));
		return output;
	}

	text(): string {
		return `${this.lines.join('\n')}\n`;
	}
}

export function inputs(text: string): string[] {
	const invalid = new ReplError('invalid session transcript');
	if (!text.startsWith(`${FORMAT}\n`) || !text.endsWith('\n') || text.includes('\r')) throw invalid;
	const json = (value: string): unknown => {
		try {
			return JSON.parse(value);
		} catch {
			throw invalid;
		}
	};
	const input: string[] = [];
	let pin: Pin | undefined;
	for (const line of linesOf(text).slice(1)) {
		if (line.startsWith(PIN) && !pin) {
			const value = json(line.slice(PIN.length)) as Partial<Pin> | null;
			if (!value || typeof value.pack !== 'string' || typeof value.manifest !== 'string' || value.manifest === 'latest' ||
				typeof value.role !== 'string' || typeof value.bundle !== 'string' || !/^[0-9a-f]{64}$/.test(value.bundle) ||
				!Number.isSafeInteger(value.epoch)) throw invalid;
			pin = value as Pin;
		} else if (line.startsWith(INPUT)) {
			const value = json(line.slice(INPUT.length));
			if (typeof value !== 'string' || (pin && value !== selection(pin))) throw invalid;
			input.push(value);
			pin = undefined;
		} else if (!line.startsWith(OUTPUT) || pin || input.length === 0 || typeof json(line.slice(OUTPUT.length)) !== 'string') {
			throw invalid;
		}
	}
	if (pin) throw invalid;
	return input;
}

export function hashes(text: string): { session_sha256: string; input_sha256: string } {
	const asked = linesOf(text).filter((line) => !line.startsWith(OUTPUT));
	return { session_sha256: sha256(text), input_sha256: sha256(`${asked.join('\n')}\n`) };
}

function difference(recorded: string, replayed: string): string[] {
	const left = linesOf(recorded);
	const right = linesOf(replayed);
	let first = 0;
	while (left[first] === right[first] && first < left.length) first++;
	let start = first;
	while (start > 1 && !left[start]?.startsWith(INPUT) && !left[start]?.startsWith(PIN)) start--;
	const turn = (lines: string[]) => {
		let end = start + 1;
		while (end < lines.length && (lines[end].startsWith(OUTPUT) || (end === start + 1 && lines[start].startsWith(PIN))))
			end++;
		return lines.slice(start, end);
	};
	const before = turn(left);
	const after = turn(right);
	return [
		'--- recorded',
		'+++ replayed',
		`@@ -${start + 1},${before.length} +${start + 1},${after.length} @@`,
		...before.map((line) => `-${line}`),
		...after.map((line) => `+${line}`)
	];
}

export async function replay(text: string, session: Session): Promise<{ same: true; session_sha256: string } | { same: false; diff: string[] }> {
	const recorder = new Recorder(session);
	for (const input of inputs(text)) {
		await recorder.exec(input);
		const actual = recorder.text();
		if (!text.startsWith(actual)) return { same: false, diff: difference(text, actual) };
	}
	const actual = recorder.text();
	return actual === text ? { same: true, session_sha256: hashes(text).session_sha256 } : { same: false, diff: difference(text, actual) };
}
