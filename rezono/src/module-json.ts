// The JSON form of a module (contracts/rezono-module.yaml): what the compiler reads of a
// pack written in Rezono, so that it needs no second parser (docs/rezono/expressions.md §12). Its three members:
//
//   format  `rezono.module/1` or `rezono.module/2`, depending on the declarations
//   module  the tree of the module as module.ts reads it. The tree is the JSON form, as for a question (§4a)
//   spans   the place in the text of every node of `module` that has one (module.ts, `spans`): its JSON pointer
//           (RFC 6901) into `module`, its 1-based line and its 0-based code-point offsets, end exclusive. They
//           are in the order of the canonical JSON of `module`, and they are decimal text, because canonical
//           JSON has no numbers (docs/contracts.md#canonical-hash)
//
// A form exists only for a module without an error. A text the reader does not read (R000) and a construct that
// v0 reserves (R015: a time selection on a value, `norm`) leave no form: the diagnostic at its span says why,
// and no form with a part left out is ever written. A warning (W108) does not stop the form. A decision table
// is in the form as the tree of docs/rezono/tables.md §2; whether its rows overlap or leave a gap is the check's
// (table.ts), which needs a schema and is not made here.
//
// Unknown is never an absent member here. An absent member is something the text did not write (a slot without
// a cardinality, a parameter without a value); a value that is unknown, not applicable or invalid is written as
// the literal it has in the text (`{"lit": "unknown no_estimate"}`, `{"lit": "n/a"}`, `{"lit": "invalid r"}`),
// and canonical JSON refuses `null`.
import { canonicalJson } from '../../viewer/src/lib/canon.ts';
import { isError } from './check.ts';
import { JsonFormError } from './json.ts';
import { hasMetadata } from './module-metadata.ts';
import { parseModule, type Module, type ParseModuleOptions } from './module.ts';
import type { Diagnostic, Span } from './parse.ts';
import { printModule } from './print.ts';

export const MODULE_FORMAT = 'rezono.module/1';
const EXTENDED_MODULE_FORMAT = 'rezono.module/2';
const NATIVE_RULE_MODULE_FORMAT = 'rezono.module/3';
const SAFE_STEP_MODULE_FORMAT = 'rezono.module/4';
export const REZONO_1_MODULE_FORMAT = 'rezono.module/5';
const SUPPORTED_MODULE_FORMATS = new Set<string>([
	MODULE_FORMAT,
	EXTENDED_MODULE_FORMAT,
	NATIVE_RULE_MODULE_FORMAT,
	SAFE_STEP_MODULE_FORMAT,
	REZONO_1_MODULE_FORMAT,
]);

function hasIntermediateInvariant(decl: Module['decls'][number]): boolean {
	return 'rule' in decl && (decl.options?.some(option => 'invariant' in option && option.invariant === 'intermediate') ?? false);
}

function formatOf(module: Module): ModuleForm['format'] {
	if (module.rezono === '1') return REZONO_1_MODULE_FORMAT;
	if (module.decls.some(decl => 'step' in decl || hasIntermediateInvariant(decl))) return SAFE_STEP_MODULE_FORMAT;
	if (module.decls.some(decl => 'rule' in decl)) return NATIVE_RULE_MODULE_FORMAT;
	const extended = module.schema !== undefined || module.decls.some(decl => {
		if ('dataset' in decl || 'rules' in decl || ('source' in decl && 'fields' in decl)) return true;
		if ('kind' in decl) {
			if (decl.parent !== undefined) return true;
			return decl.abstract || decl.embedded || decl.relationship || decl.keys?.length || decl.deprecated !== undefined || hasMetadata(decl)
				|| decl.slots.some(slot => slot.identifier || slot.embedded || slot.slotUri !== undefined
					|| slot.constraints !== undefined || hasMetadata(slot))
				|| decl.equations?.length || decl.checks?.length;
		}
		if ('base' in decl || 'asOf' in decl) return true;
		if ('param' in decl && decl.source !== undefined) return true;
		if ('derived' in decl && Array.isArray(decl.derived) && decl.derived.some(d => d.output !== undefined || d.definitions !== undefined
			|| d.unit !== undefined || d.versions?.some(v => v.definitions !== undefined))) return true;
		return 'enum' in decl && (decl.deprecated !== undefined || decl.memberMetadata !== undefined || hasMetadata(decl));
	});
	return extended ? EXTENDED_MODULE_FORMAT : MODULE_FORMAT;
}

/** The place of one node of `module`; the numbers are decimal text. */
export interface Place {
	at: string;
	line: string;
	start: string;
	end: string;
}
export interface ModuleForm {
	format:
		| typeof MODULE_FORMAT
		| typeof EXTENDED_MODULE_FORMAT
		| typeof NATIVE_RULE_MODULE_FORMAT
		| typeof SAFE_STEP_MODULE_FORMAT
		| typeof REZONO_1_MODULE_FORMAT;
	module: Module;
	spans: Place[];
}
export interface FormOf {
	/** Absent when the module has an error. */
	form?: ModuleForm;
	/** What the reader reports, in source order. An error among them leaves no form; a warning does not. */
	diagnostics: Diagnostic[];
}

/** The 1-based line of a code-point offset of `text`. */
export function lineOf(text: string): (offset: number) => number {
	const line: number[] = [];
	let n = 1;
	for (const c of text) {
		line.push(n);
		if (c === '\n') n++;
	}
	line.push(n);
	return (offset) => line[offset];
}

function places(module: Module, spans: WeakMap<object, Span>, text: string): Place[] {
	const line = lineOf(text);
	const out: Place[] = [];
	const walk = (v: unknown, at: string) => {
		if (Array.isArray(v)) v.forEach((x, i) => walk(x, `${at}/${i}`));
		else if (typeof v === 'object' && v !== null) {
			const span = spans.get(v);
			if (span) out.push({ at, line: String(line(span.start)), start: String(span.start), end: String(span.end) });
			// The order of canonical JSON: keys by their UTF-16 code units, which is what `sort` compares.
			for (const k of Object.keys(v).sort()) walk((v as Record<string, unknown>)[k], `${at}/${k.replace(/~/g, '~0').replace(/\//g, '~1')}`);
		}
	};
	walk(module, '');
	return out;
}

/** Builds and round-trip verifies the JSON form of an already-parsed module. */
export function formOfModule(text: string, module: Module, spans: WeakMap<object, Span>, options?: ParseModuleOptions): ModuleForm {
	const again = parseModule(printModule(module), options);
	if (!again.module || again.diagnostics.some(isError) || canonicalJson(again.module) !== canonicalJson(module))
		throw new JsonFormError('the module is not the tree of its own printed text');
	return { format: formatOf(module), module, spans: places(module, spans, text) };
}

/**
 * The form of a module's text, or the diagnostics that leave it without one. A form is the tree of its own
 * printed text: that is checked here for every form made, so a tree the printer and the reader do not agree on
 * is refused, never written.
 */
export function moduleForm(text: string, options?: ParseModuleOptions): FormOf {
	const { module, diagnostics, spans } = parseModule(text, options);
	if (!module || diagnostics.some(isError)) return { diagnostics };
	return { form: formOfModule(text, module, spans, options), diagnostics };
}

/** The bytes of a form: canonical JSON (RFC 8785), so the same text gives the same bytes. */
export const moduleToJson = (form: ModuleForm): string => canonicalJson(form);

const WHOLE = /^(0|[1-9][0-9]*)$/;

/**
 * Reads a module from its JSON form. A value is one exactly when its `module` is the tree of its own printed
 * text, as for a question (json.ts), and its `spans` place the nodes of that tree, each once and in their order.
 * So a member the reader does not know, a reserved construct, a `null` and a part left out are all refused by
 * the one test, with no second description of the tree. Whether the offsets are those of one text is not
 * checked here: `moduleForm` of that text gives the form to compare with.
 */
export function moduleFromJson(value: unknown): ModuleForm {
	const not = (why: string) => new JsonFormError(`not the JSON form of a module: ${why}`);
	if (typeof value !== 'object' || value === null || Array.isArray(value)) throw not('it is not an object');
	const { format, module, spans, ...rest } = value as Record<string, unknown>;
	if (typeof format !== 'string' || !SUPPORTED_MODULE_FORMATS.has(format) || Object.keys(rest).length)
		throw not('its members are a supported `format`, `module` and `spans`');
	let canonical: string;
	let text: string;
	try {
		canonical = canonicalJson(module);
		text = printModule(module as Module);
	} catch (e) {
		throw not(e instanceof Error ? e.message : String(e));
	}
	const own = parseModule(text);
	const errors = own.diagnostics.filter(isError);
	if (errors.length) throw not(`its text is refused: ${errors.map((d) => `${d.code} at \`${d.span.text}\``).join(', ')}`);
	if (!own.module || canonicalJson(own.module) !== canonical) throw not('`module` is not the tree of its own text');
	const expectedFormat = formatOf(own.module);
	if (format !== expectedFormat) throw not('`format` does not match the module tree');
	const expected = places(own.module, own.spans, text);
	const placed = (s: unknown, i: number): s is Place => {
		if (typeof s !== 'object' || s === null || Object.keys(s).sort().join() !== 'at,end,line,start') return false;
		const p = s as Place;
		return p.at === expected[i].at && [p.line, p.start, p.end].every((n) => typeof n === 'string' && WHOLE.test(n)) && p.line !== '0' && BigInt(p.start) <= BigInt(p.end);
	};
	if (!Array.isArray(spans) || spans.length !== expected.length || !spans.every(placed)) throw not('`spans` does not place the nodes of `module`, each once and in their order');
	return { format: expectedFormat, module: own.module, spans: spans.map(({ at, line, start, end }) => ({ at, line, start, end })) };
}
