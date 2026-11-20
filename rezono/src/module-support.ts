import type { ActionDict, Node } from 'ohm-js';
import { codeOf, type Logical } from './module-layout.ts';
import { placed, type Diagnostic, type Span } from './parse-support.ts';
import { printExpr } from './print-expression.ts';
import type { Expr } from './tree.ts';

export type { Logical } from './module-layout.ts';

export type World = 'open' | 'closed';
export type Card = '?' | '*' | '+';
export type LanguageVersion = '0' | '1';
export const isLanguageVersion = (version: string): version is LanguageVersion => version === '0' || version === '1';

/** One logical line as the grammar reads it, before any block is interpreted. */
export type Line = { line: string; [member: string]: unknown };

export interface Build {
	version: LanguageVersion;
	spans: WeakMap<object, Span>;
	later: Diagnostic[];
	refuse(line: Logical, expected: string, to?: number): void;
	error(diagnostic: Diagnostic): void;
	removed(line: Logical, what: string, span?: Span, hint?: Diagnostic['hint']): void;
	leaf(line: Logical): void;
	leaves(line: Logical, tag: string, expected: string): Line[];
	strip<T>(line: Line): T;
}

export interface Declaration<T extends object> {
	read(line: Logical, build: Build): T;
	print(decl: object): string[] | undefined;
}

export function declaration<T extends object>(
	member: keyof T,
	read: Declaration<T>['read'],
	print: (decl: T) => string[]
): Declaration<T> {
	return { read, print: decl => member in decl ? print(decl as T) : undefined };
}

export interface BlockSyntax {
	parent: string;
	first: string;
	rest: string;
	invalidFirst(text: string, line: Logical, cp: (at: number) => number, matches: (rule: string) => boolean): Diagnostic | undefined;
}

export interface ModuleComponent {
	grammar?: string;
	lineRules: readonly string[];
	trailingRules?: readonly string[];
	actions: ActionDict<unknown>;
	declarations?: Record<string, Declaration<object>>;
	block?: BlockSyntax;
	verbatimBlock?: { keyword: string; header: string; tag: string };
}

export function leafDeclaration<T extends object>(line: Logical, build: Build): T {
	build.leaf(line);
	return build.strip(line.read!);
}

export function named<T extends object>(name: Node, decl: T): T {
	return placed(name, decl);
}

export const opt = (iter: Node): string | undefined => (iter.numChildren ? iter.child(0).sourceString : undefined);
export const optTree = (iter: Node): Expr | undefined => (iter.numChildren ? (iter.child(0).tree() as Expr) : undefined);
/** An optional group ending in Src?: an iteration of an iteration. */
export const optSrc = (iter: Node): string | undefined => (iter.numChildren && iter.child(0).numChildren ? iter.child(0).child(0).decl() : undefined);
export const bare = (node: Node) => node.sourceString.split('\n').map(codeOf).join(' ');
export const typeOf = (node: Node) => bare(node).replace(/\s+/g, '');
export const listOf = (node: Node) => node.asIteration().children.map((c: Node) => c.sourceString);

export const printValue = (value?: Expr) => (value ? ` = ${printExpr(value)}` : '');
export const printWorld = (world?: World) => (world ? ` world ${world}` : '');
export const printRow = (cells: string[]) => `| ${cells.join(' | ')} |`;
export const block = (head: string, lines: string[]) => [head, ...lines.map((line) => `  ${line}`)];

export const printSource = (source?: string) => (source !== undefined ? ` @ ${source}` : '');
