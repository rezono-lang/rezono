import { block, declaration, named, type Build, type Logical, type ModuleComponent } from './module-support.ts';

/** A source declaration (decisions/language-fact-provenance.md): the shared fields of the sources of fact tables. */
export interface SourceDecl {
	source: string;
	/** The fields of the source contract, as text. `kind` is written as a bare member, the others as text literals. */
	fields: Record<string, string>;
}

export function readSourceDecl(line: Logical, build: Build): SourceDecl {
	const fields: Record<string, string> = {};
	for (const child of line.block) {
		build.leaf(child);
		const { key, value, bare } = child.read as unknown as { key: string; value?: string; bare: boolean };
		if (Object.hasOwn(fields, key)) build.refuse(child, 'one line for each source field', child.start + key.length);
		else if (value === undefined) build.refuse(child, 'a JSON string', child.end);
		else if (bare !== (key === 'kind')) build.refuse(child, key === 'kind' ? 'a bare member of the source kinds' : 'a text literal', child.end);
		else fields[key] = value;
	}
	const decl: SourceDecl = { source: line.read!.source as string, fields };
	build.spans.set(decl, build.spans.get(line.read!)!);
	return decl;
}

export const printSourceDecl = (d: SourceDecl): string[] =>
	block(`source ${d.source}`, Object.entries(d.fields).map(([key, value]) => `${key} ${key === 'kind' ? value : JSON.stringify(value)}`));

export const source = {
	lineRules: ['SourceLine'],
	grammar: String.raw`
  SourceLine = kw<"source"> name
  SourceFieldLine = sourceKey (MetaString | sourceWord)
  sourceKey (a source field) = az (az | d | "_")* ~wordChar
  sourceWord (a bare word) = az (az | d | "_")* ~wordChar
  `,
	actions: {
		SourceLine: (_k, n) => named(n, { line: 'source', source: n.sourceString }),
		SourceFieldLine(key, value) {
			const bare = value.ctorName === 'sourceWord';
			return { line: 'sourceField', key: key.sourceString, bare, value: bare ? value.sourceString : value.decl() };
		}
	},
	declarations: { source: declaration<SourceDecl>('fields', readSourceDecl, printSourceDecl) },
	block: { parent: 'source', first: 'SourceFieldLine', rest: 'SourceFieldLine', invalidFirst: () => undefined }
} satisfies ModuleComponent;
