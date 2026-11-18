import { listOf, named, opt, type ModuleComponent } from './module-support.ts';
import type { Module } from './module.ts';

export function printHeader(m: Module): string[] {
	return [
		...(m.rezono !== undefined ? [`rezono ${m.rezono}`] : []),
		`pack ${m.pack}`,
		...m.use.map((u) => `use ${u.use}${u.as !== undefined ? ` as ${u.as}` : ''}`)
	];
}

export const header = {
	lineRules: ['RezonoLine', 'PackLine', 'UseLine'],
	grammar: String.raw`
  RezonoLine = kw<"rezono"> number
  PackLine = kw<"pack"> name
  UseLine = kw<"use"> NonemptyListOf<name, "."> (as name)?
  `,
	actions: {
		RezonoLine: (_k, n) => ({ line: 'rezono', rezono: n.sourceString }),
		PackLine: (_k, n) => ({ line: 'pack', pack: n.sourceString }),
		UseLine: (_k, names, _as, alias) => named(names, { line: 'use', use: listOf(names).join('.'), ...(alias.numChildren ? { as: opt(alias) } : {}) })
	},
} satisfies ModuleComponent;
