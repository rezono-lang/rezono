import type { ActionDict } from 'ohm-js';
import { check } from './module-check.ts';
import { context } from './module-context.ts';
import { derived } from './module-derived.ts';
import { enumeration } from './module-enum.ts';
import { facts } from './module-facts.ts';
import { header } from './module-header.ts';
import { kind } from './module-kind.ts';
import { metadata } from './module-metadata.ts';
import { nativeRule } from './module-native-rule.ts';
import { parameter } from './module-parameter.ts';
import { reason } from './module-reason.ts';
import { rounding } from './module-rounding.ts';
import { rules } from './module-rules.ts';
import { scalarAlias } from './module-scalar-alias.ts';
import { source } from './module-source.ts';
import { slot } from './module-slot.ts';
import { numericSlotBounds } from './module-slot-numeric.ts';
import { step, stepEffect } from './module-step.ts';
import { table } from './module-table.ts';
import { unit } from './module-unit.ts';
import { unless } from './module-unless.ts';
import { version } from './module-version.ts';
import type { BlockSyntax, Declaration, ModuleComponent } from './module-support.ts';

// Ohm tries these alternatives in order. Generic assignments stand after slots and specific statements.
const components = [header, context, metadata, rounding, reason, unit, enumeration, parameter, kind, derived, version, unless, table, source, facts, check, rules, slot, numericSlotBounds] as const;
// Native signatures have columns, so their printer must precede the fact table printer.
const registered: readonly ModuleComponent[] = [nativeRule, scalarAlias, step, stepEffect, ...components];

type DeclOf<T> = T extends { declarations: infer Entries } ? Entries[keyof Entries] extends Declaration<infer D> ? D : never : never;
export type Decl = DeclOf<typeof components[number] | typeof nativeRule | typeof scalarAlias | typeof step>;

const lines = [...registered.flatMap(c => c.lineRules), ...registered.flatMap(c => c.trailingRules ?? [])];
export const moduleGrammar = `  Line = ${lines.join(' | ')}
${registered.flatMap(c => c.grammar ?? []).join('\n')}`;

export const declarationActions: ActionDict<unknown> = {
	Line: (line) => line.decl(),
	World: (_k, which) => which.sourceString,
	Src: (_at, ref) => ref.sourceString
};
export const declarations = new Map<string, Declaration<object>>();
export const blockSyntax = new Map<string, BlockSyntax>();
export const verbatimBlocks = registered.flatMap(c => c.verbatimBlock ? [c.verbatimBlock] : []);
for (const component of registered) {
	for (const [rule, action] of Object.entries(component.actions)) {
		if (rule in declarationActions) throw new Error(`Duplicate module rule: ${rule}`);
		declarationActions[rule] = action;
	}
	for (const [tag, declaration] of Object.entries(component.declarations ?? {})) {
		if (declarations.has(tag)) throw new Error(`Duplicate module declaration: ${tag}`);
		declarations.set(tag, declaration);
	}
	if (component.block) {
		const block = component.block;
		if (blockSyntax.has(block.parent)) throw new Error(`Duplicate module block: ${block.parent}`);
		blockSyntax.set(block.parent, block);
	}
}

export function printDeclaration(decl: Decl): string[] {
	for (const declaration of declarations.values()) {
		const lines = declaration.print(decl);
		if (lines) return lines;
	}
	throw new TypeError('Unknown module declaration');
}
