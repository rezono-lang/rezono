import type { Place } from './module-json.ts';
import { knownType, type Schema, type World } from './schema.ts';
import type { Path, State } from './tree.ts';

type Expression =
	| Path | { kind: string } | { lit: string } | { wildcard: true }
	| { call: [string, Expression[]] }
	| { and: Expression[] } | { or: Expression[] } | { not: Expression }
	| { cmp: [string, Expression, Expression] } | { arith: [string, Expression, Expression] }
	| { agg: [string, Expression] | [string, Expression, Expression] }
	| { in: [Expression, Expression] } | { is: [Expression, State] }
	| { neg: Expression };

type Column = { name: string; type: string };
type Declaration = { rule: string; locals?: Column[]; when?: Expression } &
	({ args: Expression[] } | { columns: Column[] });

type Signature = { columns: Column[]; world: World; role: 'input' | 'derived'; absence?: true };

export interface NativeRuleEnvironment {
	schema: Schema;
	relations: Record<string, Signature>;
}

export interface NativeRuleForm {
	format: 'rezono.module/3';
	module: { decls: readonly object[] };
	spans: readonly Place[];
}

export interface NativeRuleDiagnostic {
	code: string;
	args: string[];
	span: Place;
	related?: Place[];
}

type Premise = 'positive' | 'negative' | 'aggregate';
type Dependency = { from: string; to: string; at: string; premise: Premise };
// Computed results support later comparisons. Negative literals and groups require positive row grounds.
type Flow = { bound: Map<string, string>; positive: Set<string> };
type Value = { type: string; set?: boolean; integer?: bigint };

const INTEGER_TOKEN = /^-?[0-9]+$/;
const MIN_INTEGER = -(1n << 63n);
const MAX_INTEGER = (1n << 63n) - 1n;
const bare = (expr: Expression): string | undefined =>
	'path' in expr && expr.path.length === 1 ? expr.path[0] : undefined;

class RuleFault extends Error {
	readonly code: string;
	readonly at: string;
	readonly args: string[];

	constructor(code: string, at: string, args: string[]) {
		super(code);
		this.code = code;
		this.at = at;
		this.args = args;
	}
}

function refuse(code: string, at: string, ...args: string[]): never {
	throw new RuleFault(code, at, args);
}

function isDeclaration(value: object): value is Declaration {
	return 'rule' in value && typeof value.rule === 'string' && ('args' in value || 'columns' in value);
}

/** Check a linked /3 form using its supplied schema and signature environment. */
export function checkNativeRules(form: NativeRuleForm, environment: NativeRuleEnvironment): NativeRuleDiagnostic[] {
	const places = new Map(form.spans.map(place => [place.at, place]));
	const diagnostics: NativeRuleDiagnostic[] = [];
	const dependencies: Dependency[] = [];

	function place(at: string): Place {
		const span = places.get(at);
		if (!span) throw new TypeError('Missing place for native rule node ' + at);
		return span;
	}

	for (const [index, declaration] of form.module.decls.entries()) {
		if (!isDeclaration(declaration) || !declaration.when) continue;
		const at = '/decls/' + index;
		const checker = new ClauseCheck(environment, declaration.rule);
		try {
			checker.check(declaration, declaration.when, at);
			dependencies.push(...checker.dependencies);
		} catch (error) {
			if (!(error instanceof RuleFault)) throw error;
			diagnostics.push({ code: error.code, args: error.args, span: place(error.at) });
		}
	}

	const outgoing = new Map<string, Dependency[]>();
	for (const edge of dependencies) {
		const edges = outgoing.get(edge.from) ?? [];
		if (!outgoing.has(edge.from)) outgoing.set(edge.from, edges);
		edges.push(edge);
	}
	for (const edge of dependencies) {
		if (edge.premise === 'positive') continue;
		const related = returnPath(edge.to, edge.from, outgoing);
		if (related === undefined) continue;
		const diagnosis: NativeRuleDiagnostic = {
			code: 'R043', args: [edge.from, edge.to], span: place(edge.at),
		};
		if (related.length) diagnosis.related = related.map(previous => place(previous.at));
		diagnostics.push(diagnosis);
	}
	return diagnostics;
}

/** The first shortest dependency path, in source order. An empty path is a self edge. */
function returnPath(start: string, goal: string, outgoing: Map<string, Dependency[]>): Dependency[] | undefined {
	const pending = [start];
	const incoming = new Map<string, Dependency>();
	const reached = new Set(pending);
	for (const name of pending) {
		if (name === goal) {
			const path: Dependency[] = [];
			for (let current = goal; current !== start;) {
				const edge = incoming.get(current);
				if (!edge) throw new TypeError('Missing native rule dependency');
				path.push(edge);
				current = edge.from;
			}
			return path.reverse();
		}
		for (const edge of outgoing.get(name) ?? []) {
			if (reached.has(edge.to)) continue;
			reached.add(edge.to);
			incoming.set(edge.to, edge);
			pending.push(edge.to);
		}
	}
	return undefined;
}

class ClauseCheck {
	readonly dependencies: Dependency[] = [];
	private readonly schema: Schema;
	private readonly relations: Record<string, Signature>;
	private readonly rule: string;
	private readonly types = new Map<string, string>();
	private absence = false;

	constructor(environment: NativeRuleEnvironment, rule: string) {
		this.schema = environment.schema;
		this.relations = environment.relations;
		this.rule = rule;
	}

	check(declaration: Declaration, body: Expression, at: string): void {
		const signature = this.relation(declaration.rule);
		if (!signature || signature.role !== 'derived') refuse('R040', at, declaration.rule);
		this.absence = signature.absence === true;
		const head = 'args' in declaration
			? declaration.args
			: declaration.columns.map(({ name }) => ({ path: [name] }));
		const headPointer = at + ('args' in declaration ? '/args/' : '/columns/');
		this.arity(declaration.rule, head.length, signature, at);
		if ('columns' in declaration) {
			declaration.columns.forEach(({ name, type }, index) => {
				const pointer = headPointer + index;
				this.requireType(type, signature.columns[index].type, pointer);
				this.annotate({ name, type }, pointer);
			});
		}
		declaration.locals?.forEach((column, index) => this.annotate(column, at + '/locals/' + index));

		const flow: Flow = { bound: new Map(), positive: new Set() };
		this.guard(body, at + '/when', flow);
		head.forEach((term, index) => {
			const pointer = headPointer + index;
			if ('wildcard' in term) refuse('R042', pointer, '_');
			const expected = signature.columns[index].type;
			this.requireType(this.scalar(term, pointer, flow, expected).type, expected, pointer);
		});
	}

	private annotate(column: Column, at: string): void {
		const previous = this.types.get(column.name);
		if (previous) this.requireType(column.type, previous, at);
		this.types.set(column.name, column.type);
	}

	private bind(name: string, type: string, at: string, flow: Flow, positive: boolean): void {
		const previous = flow.bound.get(name) ?? this.types.get(name);
		if (previous) this.requireType(type, previous, at);
		flow.bound.set(name, previous ?? type);
		if (positive) flow.positive.add(name);
	}

	private relation(name: string): Signature | undefined {
		if (Object.hasOwn(this.relations, name)) return this.relations[name];
		const [owner, member, rest] = name.split('.');
		if (rest !== undefined || !Object.hasOwn(this.schema.kinds, owner)) return undefined;
		const kind = this.schema.kinds[owner];
		if (!member || !Object.hasOwn(kind.slots, member)) return undefined;
		const slot = kind.slots[member];
		return {
			columns: [{ name: 'subject', type: owner }, { name: member, type: slot.ref ?? slot.type ?? 'Text' }],
			world: slot.world ?? kind.world,
			role: 'input',
		};
	}

	private arity(name: string, count: number, signature: Signature, at: string): void {
		if (count !== signature.columns.length) refuse('R041', at, name, String(signature.columns.length), String(count));
	}

	private requireClosed(name: string, signature: Signature, at: string): void {
		if (signature.world === 'open' && !this.absence) refuse('R004', at, name);
	}

	private row(call: [string, Expression[]], at: string, flow: Flow, premise: Premise, dependencyAt = at): Signature {
		const [name, terms] = call;
		const signature = this.relation(name);
		if (!signature) refuse('R001', at, name);
		this.arity(name, terms.length, signature, at);
		terms.forEach((term, index) => {
			const pointer = at + '/call/1/' + index;
			const expected = signature.columns[index].type;
			if ('wildcard' in term) {
				if (premise === 'negative') refuse('R042', pointer, '_');
				return;
			}
			const name = bare(term);
			if (name !== undefined) {
				if (premise === 'positive') {
					this.bind(name, expected, pointer, flow, true);
					return;
				}
				if (!flow.positive.has(name)) refuse('R042', pointer, name);
			}
			this.requireType(this.scalar(term, pointer, flow, expected).type, expected, pointer);
		});
		if (premise !== 'positive') this.requireClosed(name, signature, dependencyAt);
		if (signature.role === 'derived') this.dependencies.push({ from: this.rule, to: name, at: dependencyAt, premise });
		return signature;
	}

	private guard(expr: Expression, at: string, flow: Flow): void {
		if ('and' in expr) {
			expr.and.forEach((term, index) => this.guard(term, at + '/and/' + index, flow));
			return;
		}
		if ('or' in expr) {
			// Every alternative must supply the bindings used after the disjunction.
			const branches = expr.or.map((term, index) => {
				const branch: Flow = { bound: new Map(flow.bound), positive: new Set(flow.positive) };
				this.guard(term, at + '/or/' + index, branch);
				return branch;
			});
			for (const [name, type] of branches[0]?.bound ?? []) {
				if (branches.some(branch => !branch.bound.has(name))) continue;
				for (const branch of branches) this.requireType(branch.bound.get(name)!, type, at);
				flow.bound.set(name, type);
				if (branches.every(branch => branch.positive.has(name))) flow.positive.add(name);
			}
			return;
		}
		if ('call' in expr) {
			this.row(expr.call, at, flow, 'positive');
			return;
		}
		if ('not' in expr && 'call' in expr.not) {
			this.row(expr.not.call, at + '/not', flow, 'negative', at);
			return;
		}
		if ('in' in expr) {
			const [item, rows] = expr.in;
			const pointer = at + '/in/1';
			let type: string;
			if ('kind' in rows) {
				if (!Object.hasOwn(this.schema.kinds, rows.kind)) refuse('R001', pointer, rows.kind);
				type = rows.kind;
			} else {
				const value = this.value(rows, pointer, flow);
				if (!value.set) refuse('R005', at);
				type = value.type;
			}
			const name = bare(item);
			if (name !== undefined) this.bind(name, type, at + '/in/0', flow, true);
			else this.requireType(this.scalar(item, at + '/in/0', flow, type).type, type, at + '/in/0');
			return;
		}
		if ('cmp' in expr) {
			this.comparison(expr.cmp, at, flow, true);
			return;
		}
		if ('not' in expr && 'cmp' in expr.not) {
			this.comparison(expr.not.cmp, at + '/not', flow, false);
			return;
		}
		if ('is' in expr) refuse('R047', at, expr.is[1]);
		const body = this.scalar(expr, at, flow);
		if (body.type !== 'Bool') refuse('R017', at, body.type);
	}

	private whole(type: string): boolean {
		return type === 'Int' || type === 'Integer' || this.schema.types?.[type]?.of === 'Integer';
	}

	private requireType(actual: string, expected: string, at: string): void {
		if (actual !== expected && !(this.whole(actual) && this.whole(expected))) refuse('R003', at, actual, expected);
	}

	private comparison([op, left, right]: [string, Expression, Expression], at: string, flow: Flow,
		assignments: boolean): void {
		const lhs = at + '/cmp/1', rhs = at + '/cmp/2';
		if (op === '=' && ('agg' in right || 'arith' in right || 'neg' in right
			|| ('call' in right && right.call[0] === 'quotient'))) {
			const name = bare(left);
			if (!assignments || name === undefined || flow.bound.has(name)) refuse('R045', lhs, name ?? '=');
			const type = 'agg' in right ? this.aggregate(right.agg, rhs, flow) : this.scalar(right, rhs, flow).type;
			this.bind(name, type, lhs, flow, false);
			return;
		}
		if (op === '=' && assignments
			&& (this.bindPath(left, lhs, right, rhs, flow) || this.bindPath(right, rhs, left, lhs, flow))) return;
		const knownRight = 'lit' in left ? this.value(right, rhs, flow) : undefined;
		const a = this.value(left, lhs, flow, knownRight?.type);
		const b = knownRight ?? this.value(right, rhs, flow, a.type);
		if (a.set || b.set) refuse('R005', at);
		if (!['=', '!=', '<', '<=', '>', '>='].includes(op)) refuse('R049', at, op);
		if (op !== '=' && op !== '!=' && !(this.whole(a.type) && this.whole(b.type))) refuse('R003', at, a.type, b.type);
		this.requireType(a.type, b.type, at);
	}

	/** Equality to a single-valued path can contribute the positive slot read that binds a value. */
	private bindPath(output: Expression, outputAt: string, input: Expression, inputAt: string, flow: Flow): boolean {
		const name = bare(output);
		if (name === undefined || flow.bound.has(name) || !('path' in input) || input.path.length < 2) return false;
		const value = this.value(input, inputAt, flow);
		if (value.set) return false;
		this.bind(name, value.type, outputAt, flow, true);
		return true;
	}

	private aggregate([operator, domain, measure]: [string, Expression] | [string, Expression, Expression],
		at: string, flow: Flow): string {
		if (!['count', 'sum', 'min', 'max'].includes(operator) || !('call' in domain)) refuse('R044', at, operator);
		const signature = this.row(domain.call, at + '/agg/1', flow, 'aggregate', at);
		if (operator === 'count') {
			if (measure) refuse('R044', at + '/agg/2', operator);
			return 'Int';
		}
		const names = measure && 'path' in measure ? measure.path : [];
		const index = names.length === 2 && names[0] === 'it'
			? signature.columns.findIndex(column => column.name === names[1])
			: -1;
		const column = signature.columns[index];
		if (!column || !this.whole(column.type) || !('wildcard' in domain.call[1][index])) {
			refuse('R044', measure ? at + '/agg/2' : at, operator);
		}
		return column.type;
	}

	private scalar(expr: Expression, at: string, flow: Flow, expected?: string): Value {
		const value = this.value(expr, at, flow, expected);
		if (value.set) refuse('R005', at);
		return value;
	}

	private value(expr: Expression, at: string, flow: Flow, expected?: string): Value {
		if ('path' in expr) return this.path(expr.path, at, flow);
		if ('lit' in expr) return this.literal(expr.lit, at, expected);
		if ('kind' in expr) {
			if (!Object.hasOwn(this.schema.kinds, expr.kind)) refuse('R001', at, expr.kind);
			return { type: expr.kind, set: true };
		}
		if ('arith' in expr) {
			const [op, left, right] = expr.arith;
			if (!['+', '-', '*'].includes(op)) refuse('R049', at, op);
			const a = this.integer(left, at + '/arith/1', flow);
			const b = this.integer(right, at + '/arith/2', flow);
			this.requireType(a.type, b.type, at);
			if (a.integer === undefined || b.integer === undefined) return { type: a.type };
			const value = op === '+' ? a.integer + b.integer : op === '-' ? a.integer - b.integer : a.integer * b.integer;
			return this.checkedInteger(value, at, a.type);
		}
		if ('neg' in expr) {
			if ('lit' in expr.neg && INTEGER_TOKEN.test(expr.neg.lit)) return this.checkedInteger(-BigInt(expr.neg.lit), at);
			const value = this.integer(expr.neg, at + '/neg', flow);
			return value.integer === undefined ? value : this.checkedInteger(-value.integer, at, value.type);
		}
		if ('call' in expr && expr.call[0] === 'quotient') {
			const [, operands] = expr.call;
			const [dividend, divisor] = operands;
			if (operands.length !== 2) refuse('R041', at, 'quotient', '2', String(operands.length));
			const pointer = at + '/call/1/1';
			if (!('lit' in divisor) || !INTEGER_TOKEN.test(divisor.lit) || BigInt(divisor.lit) === 0n) {
				refuse('R045', pointer, 'quotient');
			}
			const a = this.integer(dividend, at + '/call/1/0', flow);
			const b = this.checkedInteger(BigInt(divisor.lit), pointer);
			return a.integer === undefined ? a : this.checkedInteger(a.integer / b.integer!, at, a.type);
		}
		if ('wildcard' in expr) refuse('R042', at, '_');
		refuse('R049', at, Object.keys(expr)[0]);
	}

	private path([name, ...members]: string[], at: string, flow: Flow): Value {
		const bound = flow.bound.get(name);
		if (bound === undefined) refuse('R042', at, name);
		let type = bound;
		let set = false;
		for (const member of members) {
			const kind = Object.hasOwn(this.schema.kinds, type) ? this.schema.kinds[type] : undefined;
			if (!kind) refuse('R001', at, member);
			if (member === 'id') {
				type = kind.id.type;
				continue;
			}
			if (!Object.hasOwn(kind.slots, member)) refuse('R001', at, member);
			const slot = kind.slots[member];
			type = slot.ref ?? slot.type ?? 'Text';
			set ||= slot.card === '*' || slot.card === '+';
		}
		return { type, set };
	}

	private literal(text: string, at: string, expected?: string): Value {
		if (INTEGER_TOKEN.test(text)) return this.checkedInteger(BigInt(text), at);
		if (text === 'true' || text === 'false') return { type: 'Bool' };
		if (text.startsWith('"')) {
			let value: unknown;
			try {
				value = JSON.parse(text);
			} catch (error) {
				if (!(error instanceof SyntaxError)) throw error;
				refuse('R012', at, text, 'Text');
			}
			if (typeof value !== 'string') refuse('R012', at, text, 'Text');
			if (expected && this.schema.types?.[expected]?.of === 'Text') {
				const pattern = this.schema.types[expected].pattern;
				if (pattern !== undefined && !new RegExp('^(?:' + pattern + ')$', 'u').test(value)) {
					refuse('R012', at, text, expected);
				}
				return { type: expected };
			}
			return { type: 'Text' };
		}
		if (expected && knownType(this.schema, expected)) refuse('R012', at, text, expected);
		refuse('R049', at, text);
	}

	private integer(expr: Expression, at: string, flow: Flow): Value {
		const value = this.scalar(expr, at, flow);
		if (!this.whole(value.type)) refuse('R003', at, value.type, 'Int');
		return value;
	}

	private checkedInteger(value: bigint, at: string, type = 'Int'): Value {
		if (value < MIN_INTEGER || value > MAX_INTEGER) refuse('R045', at, String(value));
		return { type, integer: value };
	}
}
