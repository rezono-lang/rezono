import { printDeprecated, type Deprecation } from './module-deprecation.ts';
import { printMetadata, readMetadataLine, type Metadata } from './module-metadata.ts';
import { block, listOf, printWorld, type World, declaration, named, type Build, type Logical, type ModuleComponent } from './module-support.ts';

interface EnumerationDecl extends Metadata {
	enum: string;
	deprecated?: Deprecation;
	world?: World;
	values: string[];
	memberMetadata?: Record<string, Metadata>;
}

function readEnumeration(line: Logical, build: Build): EnumerationDecl {
	const enumeration = build.strip<EnumerationDecl>(line.read!);
	const inline = enumeration.values.length > 0;
	for (const child of line.block) {
		if (readMetadataLine(enumeration, child, build)) continue;
		const member = child.read!;
		const name = member.name as string;
		if (!inline && member.line === 'enumBareValue') {
			if (enumeration.values.includes(name)) {
				build.refuse(child, 'a distinct enumeration value');
				continue;
			}
			enumeration.values.push(name);
			if (child.block.length) {
				const members = enumeration.memberMetadata ??= {};
				const metadata: Metadata = {};
				build.spans.set(metadata, build.spans.get(member)!);
				for (const property of child.block) {
					if (!readMetadataLine(metadata, property, build)) build.refuse(property, 'enumeration member metadata');
				}
				members[name] = metadata;
			}
			continue;
		}
		if (member.line !== 'enumValue' || !enumeration.values.includes(name)) {
			build.refuse(child, 'an enumeration member');
			continue;
		}
		const members = enumeration.memberMetadata ??= {};
		if (Object.hasOwn(members, name)) {
			build.refuse(child, 'one metadata block per enumeration member');
			continue;
		}
		const metadata: Metadata = {};
		build.spans.set(metadata, build.spans.get(member)!);
		for (const property of child.block) {
			if (!readMetadataLine(metadata, property, build)) build.refuse(property, 'enumeration member metadata');
		}
		members[name] = metadata;
	}
	if (!enumeration.values.length) build.refuse(line, 'at least one enumeration value');
	return enumeration;
}

function printEnumeration(decl: EnumerationDecl): string[] {
	return [
		...printDeprecated(decl.deprecated),
		...block(`enum ${decl.enum}${printWorld(decl.world)} = ${decl.values.join(' | ')}`, [
			...printMetadata(decl),
			...decl.values.flatMap(name => decl.memberMetadata && Object.hasOwn(decl.memberMetadata, name)
				? block(`value ${name}`, printMetadata(decl.memberMetadata[name])) : [])
		])
	];
}

export const enumeration = {
	lineRules: ['EnumLine', 'EnumValueLine'],
	grammar: String.raw`
  EnumLine = kw<"enum"> typeName World? ("=" NonemptyListOf<EnumValue, "|">)?
  EnumValueLine = kw<"value"> EnumValue
  EnumBlockLine = EnumValueLine | DescriptionLine | ExactMappingLine | CloseMappingLine | BroadMappingLine | AnnotationLine | EnumBareValueLine | Line
  EnumBareValueLine = EnumValue end
  EnumValue = name | valueWord
  `,
	actions: {
		EnumLine: (_k, t, world, _eq, values) =>
			named(t, {
				line: 'enum',
				enum: t.sourceString,
				...(world.numChildren ? { world: world.child(0).decl() } : {}),
				values: values.numChildren ? listOf(values.child(0)) : [],
			}),
		EnumValueLine: (_kw, value) => named(value, { line: 'enumValue', name: value.sourceString }),
		EnumBlockLine: (line) => line.decl(),
		EnumBareValueLine: (value, _end) => named(value, { line: 'enumBareValue', name: value.sourceString }),
	},
	declarations: { enum: declaration('enum', readEnumeration, printEnumeration) },
	block: { parent: 'enum', first: 'EnumBlockLine', rest: 'EnumBlockLine', invalidFirst: () => undefined },
} satisfies ModuleComponent;
