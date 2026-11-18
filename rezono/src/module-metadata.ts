import { canonicalJson } from '../../viewer/src/lib/canon.ts';
import { block, named, typeOf, type Build, type Logical, type ModuleComponent } from './module-support.ts';

type AnnotationValue = string | boolean | AnnotationValue[] | { [name: string]: AnnotationValue };

export interface Metadata {
	description?: string;
	exactMappings?: string[];
	annotations?: Record<string, AnnotationValue>;
}

export interface SchemaMetadata extends Metadata {
	schema?: string;
	iri?: string;
	language?: string;
	prefixes?: Record<string, string>;
	imports?: string[];
	defaultRange?: string;
}

export function hasMetadata(metadata: Metadata): boolean {
	return metadata.description !== undefined || metadata.exactMappings !== undefined || metadata.annotations !== undefined;
}

/** Read one property shared by schema, kinds, slots and enumeration members. */
export function readMetadataLine(target: Metadata, line: Logical, build: Build): boolean {
	const property = line.read!;
	switch (property.line) {
		case 'description':
			if (target.description !== undefined) build.refuse(line, 'one `description`');
			else if (typeof property.value === 'string') target.description = property.value;
			else build.refuse(line, 'a JSON string');
			break;
		case 'exactMapping':
			if (typeof property.value === 'string') (target.exactMappings ??= []).push(property.value);
			else build.refuse(line, 'a JSON string');
			break;
		case 'annotation': {
			const name = property.name as string;
			if (target.annotations && Object.hasOwn(target.annotations, name)) build.refuse(line, 'one annotation per name');
			else if (property.value === undefined) build.refuse(line, 'a canonical JSON value with unique object keys');
			else (target.annotations ??= {})[name] = property.value as AnnotationValue;
			break;
		}
		default:
			return false;
	}
	build.leaf(line);
	return true;
}

export function printMetadata(target: Metadata): string[] {
	return [
		...(target.description === undefined ? [] : [`description ${JSON.stringify(target.description)}`]),
		...(target.exactMappings ?? []).map(value => `exact mapping ${JSON.stringify(value)}`),
		...Object.keys(target.annotations ?? {}).sort().map(name => `annotation ${name} = ${canonicalJson(target.annotations![name])}`)
	];
}

export function readSchema(target: SchemaMetadata, line: Logical, build: Build): void {
	target.schema = line.read!.name as string;
	build.spans.set(target, build.spans.get(line.read!)!);
	for (const child of line.block) {
		if (readMetadataLine(target, child, build)) continue;
		const { line: field, value, name } = child.read!;
		if (field !== 'iri' && field !== 'language' && field !== 'prefix' && field !== 'import' && field !== 'defaultRange') {
			build.refuse(child, 'a schema header field');
			continue;
		}
		build.leaf(child);
		if (typeof value !== 'string') build.refuse(child, 'a JSON string');
		else if (field === 'import') (target.imports ??= []).push(value);
		else if (field === 'prefix') {
			const prefixes = target.prefixes ??= {};
			if (Object.hasOwn(prefixes, name as string)) build.refuse(child, 'one prefix per name');
			else prefixes[name as string] = value;
		} else if (target[field] !== undefined) build.refuse(child, 'one value for this schema field');
		else target[field] = value;
	}
}

export function printSchema(target: SchemaMetadata): string[] {
	if (target.schema === undefined) return [];
	return block(`schema ${target.schema}`, [
		...(target.iri === undefined ? [] : [`iri ${JSON.stringify(target.iri)}`]),
		...(target.language === undefined ? [] : [`language ${target.language}`]),
		...Object.keys(target.prefixes ?? {}).sort().map(name => `prefix ${name} = ${JSON.stringify(target.prefixes![name])}`),
		...(target.imports ?? []).map(value => `import ${JSON.stringify(value)}`),
		...(target.defaultRange === undefined ? [] : [`default range ${target.defaultRange}`]),
		...printMetadata(target)
	]);
}

export const metadata = {
	lineRules: ['SchemaLine', 'IriLine', 'LanguageLine', 'PrefixLine', 'ImportLine', 'DefaultRangeLine', 'DescriptionLine', 'ExactMappingLine', 'AnnotationLine'],
	grammar: String.raw`
  SchemaLine = kw<"schema"> name
  IriLine = kw<"iri"> MetaString
  LanguageLine = kw<"language"> metaLanguage
  PrefixLine = kw<"prefix"> name "=" MetaString
  ImportLine = kw<"import"> MetaString
  DefaultRangeLine = kw<"default"> kw<"range"> Type
  DescriptionLine = kw<"description"> MetaString
  ExactMappingLine = kw<"exact"> kw<"mapping"> MetaString
  AnnotationLine = kw<"annotation"> name "=" MetaValue
  MetaValue = MetaString | metaDecimal | boolLit | MetaArray | MetaObject
  MetaArray = "[" ListOf<MetaValue, ","> "]"
  MetaObject = "{" ListOf<MetaEntry, ","> "}"
  MetaEntry = MetaString ":" MetaValue
  MetaString = text
  metaLanguage = letter alnum* ("-" alnum+)*
  metaDecimal = "-"? ("0" | metaNonzero) ("." d+)?
  metaNonzero = "1".."9" d*
  `,
	actions: {
		SchemaLine: (_kw, name) => named(name, { line: 'schema', name: name.sourceString }),
		IriLine: (_kw, value) => ({ line: 'iri', value: value.decl() }),
		LanguageLine: (_kw, value) => ({ line: 'language', value: value.sourceString }),
		PrefixLine: (_kw, name, _eq, value) => ({ line: 'prefix', name: name.sourceString, value: value.decl() }),
		ImportLine: (_kw, value) => ({ line: 'import', value: value.decl() }),
		DefaultRangeLine: (_default, _range, value) => ({ line: 'defaultRange', value: typeOf(value) }),
		DescriptionLine: (_kw, value) => ({ line: 'description', value: value.decl() }),
		ExactMappingLine: (_exact, _mapping, value) => ({ line: 'exactMapping', value: value.decl() }),
		AnnotationLine: (_kw, name, _eq, value) => ({ line: 'annotation', name: name.sourceString, value: value.decl() }),
		MetaValue: value => value.ctorName === 'metaDecimal' ? value.sourceString : value.ctorName === 'boolLit' ? value.sourceString === 'true' : value.decl(),
		MetaArray(_open, values, _close) {
			const items = values.asIteration().children.map(item => item.decl());
			return items.some(item => item === undefined) ? undefined : items;
		},
		MetaObject(_open, fields, _close) {
			const entries = fields.asIteration().children.map(field => field.decl() as [string | undefined, AnnotationValue | undefined]);
			if (entries.some(([key, value]) => key === undefined || value === undefined)) return undefined;
			const object = Object.fromEntries(entries as [string, AnnotationValue][]);
			return Object.keys(object).length === entries.length ? object : undefined;
		},
		MetaEntry: (key, _colon, value) => [key.decl(), value.decl()],
		MetaString(value) {
			try {
				const decoded = JSON.parse(value.sourceString) as string;
				return decoded.isWellFormed() ? decoded : undefined;
			} catch {
				return undefined;
			}
		}
	}
} satisfies ModuleComponent;
