import { block, declaration, named, opt, optTree, printValue, typeOf, type Build, type Line, type Logical, type ModuleComponent } from './module-support.ts';
import { printVersion, readVersion, type VersionDecl } from './module-version.ts';
import type { Expr } from './tree.ts';

export interface ParamDecl {
	param: string;
	type: string;
	per?: string;
	value?: Expr;
	source?: { kind: string; slot: string; nameSlot: string };
	versions?: VersionDecl[];
}

function readParameter(line: Logical, build: Build): ParamDecl {
	const decl = build.strip<ParamDecl>(line.read!);
	const versions: VersionDecl[] = [];
	for (const child of line.block) {
		if (child.read!.line === 'version') versions.push(readVersion(child, build));
		else build.refuse(child, 'version');
	}
	if (versions.length) decl.versions = versions;
	return decl;
}

export const parameter = {
	lineRules: ['ParamLine'],
	grammar: String.raw`
  ParamLine = kw<"param"> name ":" Type (kw<"per"> typeName)? ParamTail?
  ParamTail = kw<"from"> typeName "." name by name  -- source
            | "=" Expr                             -- value
  `,
	actions: {
		ParamTail_source: (_f, kind, _dot, slot, _by, nameSlot) => ({
			source: { kind: kind.sourceString, slot: slot.sourceString, nameSlot: nameSlot.sourceString }
		}),
		ParamTail_value: (_eq, value) => ({ value: value.tree() as Expr }),
		ParamLine(_k, n, _c, type, _per, per, tail) {
			const decl: Line = { line: 'param', param: n.sourceString, type: typeOf(type) };
			if (per.numChildren) decl.per = opt(per);
			if (tail.numChildren) Object.assign(decl, tail.child(0).decl());
			return named(n, decl);
		}
	},
	declarations: {
		param: declaration<ParamDecl>('param', readParameter, d => block(
			`param ${d.param}: ${d.type}${d.per !== undefined ? ` per ${d.per}` : ''}${printValue(d.value)}${d.source ? ` from ${d.source.kind}.${d.source.slot} by ${d.source.nameSlot}` : ''}`,
			(d.versions ?? []).map(printVersion)
		))
	}
} satisfies ModuleComponent;
