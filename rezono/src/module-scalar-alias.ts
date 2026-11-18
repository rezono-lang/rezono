import { declaration, leafDeclaration, named, type ModuleComponent } from './module-support.ts';

type ScalarAliasDecl = { type: string; base: string };

export const scalarAlias = {
	lineRules: ['ScalarAliasLine'],
	grammar: String.raw`
  ScalarAliasLine = kw<"type"> typeName "=" typeName
  `,
	actions: {
		ScalarAliasLine: (_keyword, name, _equals, base) =>
			named(name, { line: 'scalarAlias', type: name.sourceString, base: base.sourceString })
	},
	declarations: {
		scalarAlias: declaration<ScalarAliasDecl>('base', leafDeclaration, decl => [`type ${decl.type} = ${decl.base}`])
	}
} satisfies ModuleComponent;
