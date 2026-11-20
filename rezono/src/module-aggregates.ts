import type { Module } from './module.ts';
import type { Diagnostic, Span } from './parse.ts';
import { printExpr } from './print-expression.ts';
import type { Expr } from './tree.ts';

/** Strips leading `it.` from column paths in the current element scope, without descending into inner scopes. */
function stripIt(e: Expr): Expr {
	if ('path' in e) return e.path.length > 1 && e.path[0] === 'it' ? { path: e.path.slice(1) } : e;
	if ('dot' in e) return { dot: [stripIt(e.dot[0]), e.dot[1]] };
	if ('agg' in e) {
		const [name, of, arg] = e.agg;
		return arg === undefined ? { agg: [name, stripIt(of)] } : { agg: [name, stripIt(of), arg] };
	}
	if ('filter' in e) return { filter: [stripIt(e.filter[0]), e.filter[1]] };
	if ('cmp' in e) return { cmp: [e.cmp[0], stripIt(e.cmp[1]), stripIt(e.cmp[2])] };
	if ('in' in e) return { in: [stripIt(e.in[0]), stripIt(e.in[1])] };
	if ('is' in e) return { is: [stripIt(e.is[0]), e.is[1]] };
	if ('range' in e) return { range: [stripIt(e.range[0]), e.range[1], stripIt(e.range[2])] };
	if ('and' in e) return { and: e.and.map(stripIt) };
	if ('or' in e) return { or: e.or.map(stripIt) };
	if ('not' in e) return { not: stripIt(e.not) };
	if ('imply' in e) return { imply: [stripIt(e.imply[0]), stripIt(e.imply[1])] };
	if ('arith' in e) return { arith: [e.arith[0], stripIt(e.arith[1]), stripIt(e.arith[2])] };
	if ('neg' in e) return { neg: stripIt(e.neg) };
	if ('when' in e) return { when: [stripIt(e.when[0]), stripIt(e.when[1]), stripIt(e.when[2])] };
	if ('call' in e) return { call: [e.call[0], e.call[1].map(stripIt)] };
	if ('timesel' in e) return { timesel: [stripIt(e.timesel[0]), e.timesel[1]] };
	return e;
}

/** Builds the rezono 1 tuple-set spelling hint for a refused positional aggregate. */
function tupleSetHint(
	callName: string,
	callArgs: Expr[],
	filters: Expr[],
	aggName: string,
	aggArg: Expr | undefined,
	relationColumns: Map<string, string[]>,
): string {
	const parts = callName.split('.');
	const isKindSlot = parts.length >= 2 && /^[A-Z]/.test(parts[parts.length - 2]);
	const baseName = isKindSlot ? parts.slice(0, -1).join('.') : callName;
	const argPreds: string[] = [];
	if (isKindSlot && callArgs.length === 2) {
		const slotName = parts[parts.length - 1];
		if (!('wildcard' in callArgs[0])) argPreds.push(`it = ${printExpr(callArgs[0])}`);
		if (!('wildcard' in callArgs[1])) argPreds.push(`${slotName} = ${printExpr(callArgs[1])}`);
	} else {
		const cols = relationColumns.get(callName);
		if (cols && cols.length === callArgs.length) {
			callArgs.forEach((arg, i) => {
				if (!('wildcard' in arg)) argPreds.push(`${cols[i]} = ${printExpr(arg)}`);
			});
		}
	}
	const conds = [...argPreds, ...filters.map((f) => printExpr(stripIt(f)))];
	const argText = aggArg ? printExpr(stripIt(aggArg)) : '';
	if (aggName === 'count') {
		const allConds = aggArg ? [...conds, argText] : conds;
		return `${baseName}.count(${allConds.join(' and ')})`;
	}
	const prefix = conds.length ? `${baseName}.where(${conds.join(' and ')})` : baseName;
	return `${prefix}.${aggName}(${argText})`;
}

/**
 * R028: in `rezono 1`, a positional relation call with `_` standing in an aggregate's collection position
 * (directly or through a filter) is removed in favor of the tuple-set method form
 * (decisions/language-rezono-1-aggregate-spelling.md, section 1).
 */
export function positionalAggregates(module: Module, spans: WeakMap<object, Span>): Diagnostic[] {
	if (module.rezono !== '1') return [];
	const relationColumns = new Map<string, string[]>();
	for (const decl of module.decls) {
		if ('derived' in decl && typeof decl.derived === 'string' && decl.params?.length) {
			relationColumns.set(decl.derived, decl.params.map((p) => p.name));
		}
	}
	const diagnostics: Diagnostic[] = [];
	const visit = (value: unknown): void => {
		if (Array.isArray(value)) {
			for (const item of value) visit(item);
			return;
		}
		if (typeof value !== 'object' || value === null) return;
		const record = value as Record<string, unknown>;
		if (Array.isArray(record.agg) && typeof record.agg[0] === 'string' && Object.keys(record).length === 1) {
			const [aggName, receiver, aggArg] = record.agg as [string, Expr, Expr | undefined];
			let cur: Expr = receiver;
			const filters: Expr[] = [];
			while (true) {
				if ('filter' in cur) {
					filters.unshift(cur.filter[1]);
					cur = cur.filter[0];
				} else if ('timesel' in cur) {
					cur = cur.timesel[0];
				} else {
					break;
				}
			}
			if ('call' in cur && cur.call[1].some((arg) => 'wildcard' in arg)) {
				const span = spans.get(cur) ?? spans.get(record);
				if (span) {
					const replacement = tupleSetHint(cur.call[0], cur.call[1], filters, aggName, aggArg, relationColumns);
					diagnostics.push({
						code: 'R028',
						span,
						args: [span.text, '1'],
						hint: { id: 'hint.use_instead', args: [replacement] },
					});
				}
				for (const arg of cur.call[1]) visit(arg);
				for (const f of filters) visit(f);
				if (aggArg) visit(aggArg);
				return;
			}
			visit(receiver);
			if (aggArg) visit(aggArg);
			return;
		}
		for (const [key, entry] of Object.entries(record)) {
			if (key !== 'annotations') visit(entry);
		}
	};
	visit(module.decls);
	return diagnostics;
}
