import assert from 'node:assert/strict';
import { isDeepStrictEqual } from 'node:util';
import type { Place } from '../src/module-json.ts';
import type { Schema, World } from '../src/schema.ts';

// These native records are assembled directly. The source fragments provide
// independent places for their nodes without using the reader or printer.
type Column = { name: string; type: string };
type Path = { path: string[] };
type Expr =
	| Path | { lit: string } | { wildcard: true }
	| { call: [string, Expr[]] }
	| { and: Expr[] } | { or: Expr[] } | { not: Expr }
	| { cmp: [string, Expr, Expr] } | { arith: [string, Expr, Expr] }
	| { agg: [string, Expr] | [string, Expr, Expr] };
type Rule =
	| { rule: string; columns: Column[]; options?: { absence: true }[] }
	| { rule: string; args: Expr[]; locals?: Column[]; when: Expr };
type NativeForm = {
	format: 'rezono.module/3';
	module: { rezono: '0'; pack: 'sample'; use: []; decls: Rule[] };
	spans: Place[];
};
type Signature = {
	columns: Column[]; world: World; role: 'input' | 'derived'; absence?: true;
	predicate?: { states: readonly string[] };
};
type SignatureEnvironment = { schema: Schema; relations: Record<string, Signature> };
type Diagnosis = { code: string; args: string[]; span: Place; related?: Place[] };

type Fragment<T> = { text: string; tree: T; spans: Place[] };
type Part = string | [string, Fragment<unknown>];

function fragment<T>(tree: T, ...parts: Part[]): Fragment<T> {
	let text = '';
	const spans: Place[] = [];
	for (const part of parts) {
		if (typeof part === 'string') {
			text += part;
			continue;
		}
		const [prefix, child] = part;
		const start = [...text].length;
		const line = text.split('\n').length - 1;
		for (const place of child.spans) {
			spans.push({
				at: prefix + place.at,
				line: String(line + Number(place.line)),
				start: String(start + Number(place.start)),
				end: String(start + Number(place.end)),
			});
		}
		text += child.text;
	}
	return { text, tree, spans: [{ at: '', line: '1', start: '0', end: String([...text].length) }, ...spans] };
}

const path = (...names: string[]): Fragment<Path> => fragment({ path: names }, names.join('.'));
const lit = (text: string): Fragment<Expr> => fragment({ lit: text }, text);
const wildcard: Fragment<Expr> = fragment({ wildcard: true }, '_');
const x = path('x'), y = path('y'), n = path('n'), m = path('m'), k = path('k');
const one = lit('1');

function list(prefix: string, items: Fragment<unknown>[], separator: string): Part[] {
	return items.flatMap<Part>((item, index) => index
		? [separator, [prefix + '/' + index, item]]
		: [[prefix + '/' + index, item]]);
}

function call(name: string, ...args: Fragment<Expr>[]): Fragment<Expr> {
	return fragment<Expr>({ call: [name, args.map(arg => arg.tree)] },
		name, '(', ...list('/call/1', args, ', '), ')');
}

function joined(op: 'and' | 'or', ...parts: Fragment<Expr>[]): Fragment<Expr> {
	const items = parts.map(part => part.tree);
	const tree = op === 'and' ? { and: items } : { or: items };
	return fragment(tree, ...list('/' + op, parts, ' ' + op + ' '));
}

const and = (...parts: Fragment<Expr>[]) => joined('and', ...parts);
const or = (...parts: Fragment<Expr>[]) => joined('or', ...parts);

function not(body: Fragment<Expr>): Fragment<Expr> {
	return fragment({ not: body.tree }, 'not ', ['/not', body]);
}

function compare(op: string, left: Fragment<Expr>, right: Fragment<Expr>): Fragment<Expr> {
	return fragment<Expr>({ cmp: [op, left.tree, right.tree] }, ['/cmp/1', left], ' ' + op + ' ', ['/cmp/2', right]);
}

function add(left: Fragment<Expr>, right: Fragment<Expr>): Fragment<Expr> {
	return fragment<Expr>({ arith: ['+', left.tree, right.tree] }, ['/arith/1', left], ' + ', ['/arith/2', right]);
}

function count(rows: Fragment<Expr>): Fragment<Expr> {
	return fragment<Expr>({ agg: ['count', rows.tree] }, ['/agg/1', rows], '.count()');
}

function sum(rows: Fragment<Expr>, measure: Fragment<Expr>): Fragment<Expr> {
	return fragment<Expr>({ agg: ['sum', rows.tree, measure.tree] },
		['/agg/1', rows], '.sum(', ['/agg/2', measure], ')');
}

function column(name: string, type: string): Fragment<Column> {
	const part = fragment({ name, type }, name, ': ', type);
	part.spans[0].end = String(name.length);
	return part;
}
const item = column('item', 'Item');
const result = column('result', 'Int');

function declaration(rule: string, columns: Fragment<Column>[], absence = false): Fragment<Rule> {
	const mode = fragment<{ absence: true }>({ absence: true }, 'absence');
	const tree: Rule = { rule, columns: columns.map(col => col.tree), ...(absence ? { options: [mode.tree] } : {}) };
	const signature = fragment(tree, rule, '(', ...list('/columns', columns, ', '), ')',
		...(absence ? [' ', ['/options/0', mode] as Part] : []));
	signature.spans[0].end = String(rule.length);
	return signature;
}

function clause(rule: string, args: Fragment<Expr>[], when: Fragment<Expr>, locals: Fragment<Column>[] = []): Fragment<Rule> {
	const tree: Rule = { rule, args: args.map(arg => arg.tree), when: when.tree,
		...(locals.length ? { locals: locals.map(local => local.tree) } : {}) };
	const head = fragment(tree, rule, '(', ...list('/args', args, ', '), ')',
		...(locals.length ? [' with ', ...list('/locals', locals, ', ')] : []),
		' when ', ['/when', when]);
	head.spans[0].end = String(rule.length);
	return head;
}

function record(decls: Fragment<Rule>[]) {
	const module: NativeForm['module'] = { rezono: '0', pack: 'sample', use: [], decls: decls.map(decl => decl.tree) };
	const authored = fragment(module, 'rezono 0\npack sample\n-- 🧭\nrule ',
		...list('/decls', decls, '\nrule '), '\n');
	const spans = authored.spans.slice(1).sort((a, b) => a.at < b.at ? -1 : a.at > b.at ? 1 : 0);
	const form: NativeForm = { format: 'rezono.module/3', module, spans };
	return { source: authored.text, form };
}

const schema: Schema = {
	rezono: '1.0', pack: 'sample', base: 'https://example.org/sample/',
	types: { Int: { of: 'Integer' } },
	kinds: {
		Item: {
			id: { type: 'Text' }, world: 'closed',
			slots: { amounts: { type: 'Int', card: '*', world: 'closed', states: ['known'] } },
		},
	},
};
const input = (columns: Fragment<Column>[], world: World = 'closed'): Signature =>
	({ columns: columns.map(col => col.tree), role: 'input', world });
const derived = (columns: Fragment<Column>[], absence = false): Signature =>
	({
		columns: columns.map(col => col.tree), role: 'derived', world: 'closed',
		// Linked evidence that the predicate is two-valued, which a negation or group of it needs.
		predicate: { states: ['known'] }, ...(absence ? { absence: true } : {}),
	});
const environment: SignatureEnvironment = {
	schema,
	relations: {
		item: input([item]),
		amount: input([item, result]),
		blocked: input([item]),
		selected: derived([item, result]),
		ready: derived([item]),
	},
};

type Sample = ReturnType<typeof record> & { environment: SignatureEnvironment };

function sample(head: 'selected' | 'ready', args: Fragment<Expr>[], body: Fragment<Expr>,
	locals: Fragment<Column>[] = [], env = environment): Sample {
	const columns = head === 'selected' ? [item, result] : [item];
	const signature = declaration(head, columns, env.relations[head].absence);
	return { ...record([signature, clause(head, args, body, locals)]), environment: env };
}

const itemRow = call('item', x);
const bound = call('amount', x, n);
const ranged = call('amount', x, wildcard);
const localN = column('n', 'Int');
const localM = column('m', 'Int');
const localY = column('y', 'Item');

function withWorld(relation: 'amount' | 'blocked', world: World): SignatureEnvironment {
	return { ...environment, relations: {
		...environment.relations, [relation]: { ...environment.relations[relation], world },
	} };
}

function dependency(...body: Fragment<Expr>[]): Sample {
	return {
		...record([
			declaration('ready', [item]),
			clause('ready', [x], and(itemRow, ...body)),
			declaration('selected', [item, result]),
			clause('selected', [x, n], and(bound, call('ready', x))),
		]),
		environment,
	};
}

type Finding = { code: string; at: string; token: string; related?: { at: string; token: string } };
type Pair = { name: string; safe: Sample; unsafe: Sample; finding: Finding };

const pairs: Pair[] = [
	{
		name: 'a local annotation gives a head variable a type but supplies no row',
		safe: sample('selected', [x, n], bound, [localN]),
		unsafe: sample('selected', [x, n], call('amount', x, m), [localN]),
		finding: { code: 'R042', at: '/decls/1/args/1', token: 'n' },
	},
	{
		name: 'every alternative grounds its head independently',
		safe: sample('selected', [x, n], or(bound, and(itemRow, bound)), [localN]),
		unsafe: sample('selected', [x, n], or(bound, and(itemRow, call('amount', x, m))), [localN]),
		finding: { code: 'R042', at: '/decls/1/args/1', token: 'n' },
	},
	{
		name: 'negation uses the bound key of the closed relation',
		safe: sample('ready', [x], and(itemRow, not(call('blocked', x))), [localY]),
		unsafe: sample('ready', [x], and(itemRow, not(call('blocked', y))), [localY]),
		finding: { code: 'R042', at: '/decls/1/when/and/1/not/call/1/0', token: 'y' },
	},
	{
		name: 'a wildcard matches positive rows but cannot identify an exact negative key',
		safe: sample('ready', [x], and(ranged, not(call('blocked', x)))),
		unsafe: sample('ready', [x], and(ranged, not(call('blocked', wildcard)))),
		finding: { code: 'R042', at: '/decls/1/when/and/1/not/call/1/0', token: '_' },
	},
	{
		name: 'a correlated aggregate uses a key from a positive row',
		safe: sample('selected', [x, n], and(itemRow, compare('=', n, count(ranged))), [localY]),
		unsafe: sample('selected', [x, n],
			and(itemRow, compare('=', n, count(call('amount', y, wildcard)))), [localY]),
		finding: { code: 'R042', at: '/decls/1/when/and/1/cmp/2/agg/1/call/1/0', token: 'y' },
	},
	{
		name: 'a scalar comparison cannot consume the amount set',
		safe: sample('ready', [x], and(bound, compare('=', n, one))),
		unsafe: sample('ready', [x], and(bound, compare('=', n, path('x', 'amounts')))),
		finding: { code: 'R005', at: '/decls/1/when/and/1', token: 'n = x.amounts' },
	},
	{
		name: 'fresh arithmetic results are usable in a later grounded comparison',
		safe: sample('selected', [x, n],
			and(call('amount', x, m), compare('=', n, add(m, one)), compare('>=', n, m)), [column('k', 'Int')]),
		unsafe: sample('selected', [x, n],
			and(call('amount', x, m), compare('=', n, add(m, one)), compare('>=', k, m)), [column('k', 'Int')]),
		finding: { code: 'R042', at: '/decls/1/when/and/2/cmp/1', token: 'k' },
	},
	{
		name: 'the second aggregate result needs its own fresh binder',
		safe: sample('ready', [x], and(itemRow, compare('=', n, count(ranged)), compare('=', m, count(ranged)))),
		unsafe: sample('ready', [x], and(itemRow, compare('=', n, count(ranged)), compare('=', n, count(ranged)))),
		finding: { code: 'R045', at: '/decls/1/when/and/2/cmp/1', token: 'n' },
	},
	{
		name: 'the integer quotient assignment needs a nonzero constant divisor',
		safe: sample('selected', [x, n], and(call('amount', x, m), compare('=', n, call('quotient', m, one)))),
		unsafe: sample('selected', [x, n], and(call('amount', x, m), compare('=', n, call('quotient', m, lit('0'))))),
		finding: { code: 'R045', at: '/decls/1/when/and/1/cmp/2/call/1/1', token: '0' },
	},
	{
		name: 'sum needs the ranged integer column of the selected rows',
		safe: sample('selected', [x, n], and(itemRow, compare('=', n, sum(ranged, path('it', 'result'))))),
		unsafe: sample('selected', [x, n], and(itemRow, compare('=', n, sum(ranged, path('it', 'item'))))),
		finding: { code: 'R044', at: '/decls/1/when/and/1/cmp/2/agg/2', token: 'it.item' },
	},
	{
		name: 'equality between scalar variables is a test and introduces no binding',
		safe: sample('ready', [x], and(bound, compare('=', n, n)), [localM]),
		unsafe: sample('ready', [x], and(bound, compare('=', m, n)), [localM]),
		finding: { code: 'R042', at: '/decls/1/when/and/1/cmp/1', token: 'm' },
	},
	{
		name: 'ordering requires whole numbers and does not coerce numeric text',
		safe: sample('ready', [x], and(bound, compare('>=', n, one))),
		unsafe: sample('ready', [x], and(bound, compare('>=', n, lit('"1"')))),
		finding: { code: 'R003', at: '/decls/1/when/and/1', token: 'n >= "1"' },
	},
	{
		name: 'grounded negation needs a closed input for an ordinary conclusion',
		safe: sample('ready', [x], and(itemRow, not(call('blocked', x)))),
		unsafe: sample('ready', [x], and(itemRow, not(call('blocked', x))), [], withWorld('blocked', 'open')),
		finding: { code: 'R004', at: '/decls/1/when/and/1', token: 'not blocked(x)' },
	},
	{
		name: 'an absence rule can report what the open register records',
		safe: sample('ready', [x], and(itemRow, not(call('blocked', x))), [], {
			...environment, relations: { ...withWorld('blocked', 'open').relations, ready: derived([item], true) },
		}),
		unsafe: sample('ready', [x], and(itemRow, not(call('blocked', x))), [], withWorld('blocked', 'open')),
		finding: { code: 'R004', at: '/decls/1/when/and/1', token: 'not blocked(x)' },
	},
	{
		name: 'whole-group counts need a closed input for an ordinary conclusion',
		safe: sample('selected', [x, n], and(itemRow, compare('=', n, count(ranged)))),
		unsafe: sample('selected', [x, n], and(itemRow, compare('=', n, count(ranged))), [], withWorld('amount', 'open')),
		finding: { code: 'R004', at: '/decls/1/when/and/1/cmp/2', token: 'amount(x, _).count()' },
	},
	{
		name: 'positive recursion is legal but a negative edge cannot close the cycle',
		safe: dependency(call('selected', x, one)),
		unsafe: dependency(not(call('selected', x, one))),
		finding: { code: 'R043', at: '/decls/1/when/and/1', token: 'not selected(x, 1)',
			related: { at: '/decls/3/when/and/1', token: 'ready(x)' } },
	},
	{
		name: 'an aggregate may read a lower stratum but cannot close a cycle',
		safe: dependency(call('selected', x, wildcard), compare('=', k, count(ranged))),
		unsafe: dependency(call('selected', x, wildcard), compare('=', k, count(call('selected', x, wildcard)))),
		finding: { code: 'R043', at: '/decls/1/when/and/2/cmp/2', token: 'selected(x, _).count()',
			related: { at: '/decls/3/when/and/1', token: 'ready(x)' } },
	},
];

function placeOf(sample: Sample, at: string, token: string): Place {
	const place = sample.form.spans.find(span => span.at === at);
	assert.ok(place, at);
	const points = [...sample.source];
	const start = Number(place.start), end = Number(place.end);
	assert.equal(points.slice(start, end).join(''), token, at);
	assert.equal(place.line, String(points.slice(0, start).join('').split('\n').length), at);
	const node = at.slice(1).split('/').reduce<unknown>((value, key) =>
		(value as Record<string, unknown>)[key], sample.form.module);
	assert.ok(node !== null && typeof node === 'object', at);
	return place;
}

const expected = pairs.map(({ name, safe, unsafe, finding }) => {
	assert.notDeepEqual([safe.form, safe.environment], [unsafe.form, unsafe.environment], name);
	const span = placeOf(unsafe, finding.at, finding.token);
	const related = finding.related ? [placeOf(unsafe, finding.related.at, finding.related.token)] : [];
	return { code: finding.code, span, related };
});

if (process.argv.includes('--fixtures')) {
	process.stdout.write(JSON.stringify(expected));
} else {
	const component = new URL('../src/native-rule-check.ts', import.meta.url);
	const checker = await import(component.href).catch((error: unknown) => {
		const missing = error as { code?: string; url?: string };
		if (missing.code === 'ERR_MODULE_NOT_FOUND' && missing.url === component.href) return undefined;
		throw error;
	});
	if (checker === undefined || !Object.hasOwn(checker, 'checkNativeRules')) {
		process.stdout.write(JSON.stringify(['The typed native rule checker does not expose checkNativeRules.']));
	} else {
		const check = checker.checkNativeRules as (form: NativeForm, environment: SignatureEnvironment) => Diagnosis[];
		const failures: unknown[] = [];

		function diagnoses(input: Sample) {
			return check(input.form, input.environment).filter(entry => !entry.code.startsWith('W')).map(entry => {
				assert.ok(Array.isArray(entry.args) && entry.args.every(arg => typeof arg === 'string'), entry.code);
				return { code: entry.code, span: entry.span, related: entry.related ?? [] };
			});
		}

		pairs.forEach(({ name, safe, unsafe }, index) => {
			const accepted = diagnoses(safe);
			const rejected = diagnoses(unsafe);
			if (accepted.length) failures.push({ name, safe: accepted });
			if (!isDeepStrictEqual(rejected, [expected[index]])) failures.push({ name, rejected, expected: expected[index] });
		});
		process.stdout.write(JSON.stringify(failures));
	}
}
