import { listOf, named, type ModuleComponent } from './module-support.ts';
import type { Module } from './module.ts';
import { placed } from './parse-support.ts';
import { readRuleName, spellName } from './rule-names.ts';
import { printSchema } from './module-metadata.ts';

export function printHeader(m: Module): string[] {
	return [
		...(m.rezono !== undefined ? [`rezono ${m.rezono}`] : []),
		`pack ${m.pack}`,
		...m.use.map((u) => `use ${u.use}${u.as !== undefined ? ` as ${spellName(u.as)}` : ''}`),
		...printSchema(m)
	];
}

export const header = {
	lineRules: ['RezonoLine', 'PackLine', 'UseLine'],
	grammar: String.raw`
  RezonoLine = kw<"rezono"> number
  PackLine = kw<"pack"> packName
  UseLine = kw<"use"> NonemptyListOf<packName, "."> (as rName)?

  packName (a name) = hyphenatedPackName | name
  hyphenatedPackName = az (az | d)* ("-" (az | d)+)+ ~wordChar
  `,
	actions: {
		RezonoLine(_k, n) {
			return placed(this, { line: 'rezono', rezono: n.sourceString });
		},
		PackLine: (_k, n) => ({ line: 'pack', pack: n.sourceString }),
		UseLine: (_k, names, _as, alias) => named(names, { line: 'use', use: listOf(names).join('.'), ...(alias.numChildren ? { as: readRuleName(alias.child(0)) } : {}) })
	},
} satisfies ModuleComponent;
