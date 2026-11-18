import { listOf, printWorld, type World, declaration, leafDeclaration, named, type ModuleComponent } from './module-support.ts';

type EnumerationDecl = { enum: string; world?: World; values: string[] };

export const enumeration = {
	lineRules: ['EnumLine'],
	grammar: String.raw`
  EnumLine = kw<"enum"> typeName World? "=" NonemptyListOf<name, "|">
  `,
	actions: {
		EnumLine: (_k, t, world, _eq, values) => named(t, { line: 'enum', enum: t.sourceString, ...(world.numChildren ? { world: world.child(0).decl() } : {}), values: listOf(values) })
	},
	declarations: { enum: declaration<EnumerationDecl>('enum', leafDeclaration, d => [`enum ${d.enum}${printWorld(d.world)} = ${d.values.join(' | ')}`]) }
} satisfies ModuleComponent;
