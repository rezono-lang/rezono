// The normal form of a question and the question hash taken from it (src/normal.ts): two ways of
// writing one question hash equal, two questions hash apart, the normal form is a question that checks and is
// its own normal form, and the output schema of an answer is named by the hash. The written variants are
// generated with a fixed seed from the questions of the conformance cases and a few more, each checked and
// answered over the rows of Appendix B: a variant that checks gives the same rows, undecided rows and counts as
// the question it was made from, and the same hash.
import assert from 'node:assert/strict';
import { readdirSync, readFileSync } from 'node:fs';
import { test } from 'node:test';
import { parse as yaml } from 'yaml';
import { canonicalSha256 } from '../../viewer/src/lib/canon.ts';
import { answer, check, fromJson, isAsk, isError, load, NORMAL_QUESTION, normalQuestion, outputSchema, print, questionHash, toJson, type Ask, type Checked, type Question, type Schema } from '../src/index.ts';

const read = (file: string) => JSON.parse(readFileSync(new URL(file, import.meta.url), 'utf8'));
const fixture = read('fixture.schema.json') as Schema;
const appendixB = (read('appendix-b.json') as { rows: Record<string, unknown>[] }).rows;

function valid(text: string): Checked {
	const checked = check(text, fixture);
	assert.deepEqual(checked.diagnostics.filter(isError), [], text);
	return checked;
}
const hash = (text: string) => questionHash(valid(text), fixture);
const normal = (text: string) => print(normalQuestion(valid(text), fixture));

test('the normal form: the binder by its canonical name, every path in full, `and` and `or` sorted, one orientation of a comparison', () => {
	for (const [text, printed] of [
		['ask Host where memory_need > 384 GiB', 'ask Host where 384 GiB < host.memory_need'],
		['ask h: Host where h.memory_need > 384 GiB show h, h.memory_need', 'ask Host where 384 GiB < host.memory_need show host, host.memory_need'],
		['ask Host where owner = team-platform and memory_need > 300 GiB', 'ask Host where 300 GiB < host.memory_need and team-platform = host.owner'],
		['ask Host where clusters.any(count > 1)', 'ask Host where host.clusters.any(1 < it.count)'],
		['ask HostCluster where spec.nodes >= 2', 'ask HostCluster where 2 <= host_cluster.spec.nodes'],
		// A parameter, an id, a kind and a call keep their names; a literal stays as it was written.
		['ask p: Plan where fits(host-b, p) and memory >= 0.5 TiB', 'ask Plan where fits(host-b, plan) and 0.5 TiB <= plan.memory'],
		['ask Host where memory_need > host_reserve', 'ask Host where host_reserve < host.memory_need'],
		// `show` keeps its order: it is the order of the columns.
		['ask h: Host where true show owner, h', 'ask Host where true show host.owner, host']
	]) {
		assert.equal(normal(text), printed, text);
	}
});

test('where the canonical name is a slot of a kind in scope, the binder takes the next free one (§5 rule 7)', () => {
	// `HostCluster` has a slot `host`, so inside `clusters.any(…)` the name `host` would be that slot (R011).
	const text = 'ask x: Host where clusters.any(it.spec.memory_per_node >= x.memory_need)';
	assert.equal(normal(text), 'ask host_2: Host where host_2.clusters.any(host_2.memory_need <= it.spec.memory_per_node)');
	// A bare slot of the row inside that scope is the same question.
	assert.equal(normal('ask Host where clusters.any(spec.memory_per_node >= memory_need)'), normal(text));
	// Outside every such scope the binder keeps its canonical name.
	assert.equal(normal('ask x: Host where x.clusters.any(count > 1)'), 'ask Host where host.clusters.any(1 < it.count)');
	// An id spelled like the canonical name keeps its meaning: the binder takes another name.
	assert.equal(valid('ask h: Host where owner = host').resolve.host, 'Team');
	assert.equal(normal('ask h: Host where owner = host'), 'ask host_2: Host where host = host_2.owner');
});

test('where an explicit method binder uses the canonical name, the ask binder takes the next free one', async () => {
	for (const text of [
		'ask h: Host where clusters.any(host: count > 1)',
		'ask h: Host where clusters.any(host: true)',
		'ask h: Host where clusters.where(host: count > 1).count() > 0',
	]) {
		const checked = valid(text);
		const normalized = print(normalQuestion(checked, fixture));
		assert.match(normalized, /^ask host_2: Host where /);
		assert.deepEqual(check(normalized, fixture).diagnostics.filter(isError), [], normalized);
	}
	assert.equal(
		await hash('ask h: Host where clusters.any(host: count > 1)'),
		await hash('ask x: Host where x.clusters.any(host: 1 < host.count)')
	);
});

test('one question asked by two roles has one hash: the binder avoids the names of the pack, not of the role', async () => {
	// A role that does not read the relation of `HostCluster.host` and `Host.clusters`: its schema names neither.
	const role = structuredClone(fixture);
	delete role.kinds.HostCluster.slots.host;
	delete role.kinds.Host.slots.clusters;
	delete role.params;
	const text = 'ask x: Host where HostCluster.any(it.spec.memory_per_node >= x.memory_need)';
	const asRole = check(text, role);
	assert.deepEqual(asRole.diagnostics.filter(isError), [], text);
	assert.equal(print(normalQuestion(asRole, fixture)), print(normalQuestion(valid(text), fixture)));
	assert.equal(await questionHash(asRole, fixture), await hash(text));
	// Named against the role's own schema the binder would be `host`, and the hash would follow the role.
	assert.equal(print(normalQuestion(asRole, fixture)), 'ask host_2: Host where HostCluster.any(host_2.memory_need <= it.spec.memory_per_node)');
	assert.equal(print(normalQuestion(asRole, role)), 'ask Host where HostCluster.any(host.memory_need <= it.spec.memory_per_node)');
	assert.notEqual(await questionHash(asRole, role), await hash(text));
	// The output schema and the answer name it the same way for both roles.
	const base = async (checked: Checked, schema: Schema) => (await outputSchema(checked.tree as Ask, checked, schema, fixture))!.base;
	assert.equal(await base(asRole, role), await base(valid(text), fixture));
	const answered = await answer(asRole, role, load(role, appendixB), {}, fixture);
	assert.equal(answered!.schema.base, `${fixture.base}ask/${await hash(text)}/`);
});

test('a check statement keeps its binder; a slot of its row is written from it where the binder can be named', async () => {
	assert.equal(normal('require memory_bound: memory_need <= 600 GiB and host.owner is known'), 'require memory_bound: host.memory_need <= 600 GiB and host.owner is known');
	assert.equal(await hash('require memory_bound: host.owner is known and memory_need <= 600 GiB'), await hash('require memory_bound: 600 GiB >= host.memory_need and owner is known'));
	assert.notEqual(await hash('require memory_bound: host.owner is known'), await hash('warn memory_bound: host.owner is known'));
	// Inside `clusters.any(…)` the name `host` is a slot of `HostCluster`: the bare slot of the row is its only spelling.
	assert.equal(normal('warn host.clusters.any(count > 1 or memory_need > 1 GiB)'), 'warn host.clusters.any(1 GiB < memory_need or 1 < it.count)');
});

test('equal questions written differently hash equal', async () => {
	for (const texts of [
		['ask Host where memory_need > 384 GiB', 'ask h: Host where h.memory_need > 384 GiB', 'ask Host where host.memory_need > 384 GiB', 'ask host: Host where 384 GiB < memory_need'],
		['ask Host where owner = team-platform and memory_need > 300 GiB', 'ask h: Host where 300 GiB < h.memory_need and team-platform = owner'],
		['ask Host where (memory_need > 384 GiB or owner is unknown) and provider = cherry', 'ask Host where cherry = provider and (owner is unknown or 384 GiB < memory_need)'],
		['ask Host where clusters.any(count > 1)', 'ask Host where clusters.any(it.count > 1)', 'ask h: Host where h.clusters.any(1 < count)'],
		['ask Plan where memory in 256 GiB..512 GiB', 'ask p: Plan where p.memory in 256 GiB..512 GiB'],
		['ask h: Host where h.memory_need > 384 GiB show h, h.memory_need', 'ask Host where memory_need > 384 GiB show host, memory_need'],
		['ask Host where owner != team-platform', 'ask Host where team-platform != owner']
	]) {
		const all = await Promise.all(texts.map(hash));
		for (const [i, h] of all.entries()) assert.equal(h, all[0], `${texts[i]} and ${texts[0]}`);
	}
	// The JSON form and the text are one tree (E52).
	const json = { ask: 'Host', binder: 'h', where: { cmp: ['>', { path: ['h', 'memory_need'] }, { lit: '384 GiB' }] } };
	assert.equal(await hash(print(fromJson(json))), await hash('ask Host where memory_need > 384 GiB'));
});

test('different questions hash apart, and what the normal form keeps as written stays apart', async () => {
	for (const [a, b] of [
		['ask Host where memory_need > 300 GiB', 'ask Host where memory_need >= 300 GiB'],
		['ask Host where memory_need > 300 GiB', 'ask Host where memory_need < 300 GiB'],
		['ask Host where memory_need > 300 GiB and owner is known', 'ask Host where memory_need > 300 GiB or owner is known'],
		['ask Host where memory_need > 300 GiB => owner is known', 'ask Host where owner is known => memory_need > 300 GiB'],
		['ask Host where Host.any(it.memory_need > host.memory_need)', 'ask Host where Host.any(host.memory_need > it.memory_need)'],
		['ask Plan where fits(host-b, plan)', 'ask Plan where fits(host-c, plan)'],
		['ask Host where owner is known', 'ask HostCluster where host.owner is known'],
		['ask Host where true show owner, memory_need', 'ask Host where true show memory_need, owner'],
		['ask Host where memory_need > 300 GiB', 'ask Host where memory_need > 300 GiB show memory_need'],
		['ask Host where memory_need > 1 GiB + host_reserve', 'ask Host where memory_need > host_reserve + 1 GiB'],
		['ask Host where owner != team-platform', 'ask Host where not owner = team-platform'],
		['ask Plan where memory = 0.5 TiB', 'ask Plan where memory = 512 GiB']
	]) {
		assert.notEqual(await hash(a), await hash(b), `${a} and ${b}`);
	}
});

test('the hash is the SHA-256 of the canonical JSON of the normal form with its version', async () => {
	assert.equal(NORMAL_QUESTION, 'rezono.normal-question/1');
	const checked = valid('ask h: Host where h.memory_need > 384 GiB');
	const question = normalQuestion(checked, fixture);
	assert.deepEqual(question, { ask: 'Host', where: { cmp: ['<', { lit: '384 GiB' }, { path: ['host', 'memory_need'] }] } });
	assert.equal(await questionHash(checked, fixture), await canonicalSha256({ normal: NORMAL_QUESTION, question }));
	assert.notEqual(await questionHash(checked, fixture), await canonicalSha256(question));
	// The written tree is not changed: it is what is shown.
	assert.equal(print(checked.tree!), 'ask h: Host where h.memory_need > 384 GiB');
});

test('the output schema of an answer is named by the hash, so two writings of a question have one base', async () => {
	const texts = ['ask h: Host where h.memory_need > 300 GiB and owner is known show h.owner', 'ask Host where owner is known and 300 GiB < memory_need show owner'];
	const bases = await Promise.all(
		texts.map(async (text) => {
			const checked = valid(text);
			return (await outputSchema(checked.tree as Ask, checked, fixture))!.base;
		})
	);
	assert.equal(bases[0], bases[1]);
	assert.equal(bases[0], `${fixture.base}ask/${await hash(texts[0])}/`);
});

test('a question with an error keeps its names as written; its operands are still sorted', async () => {
	const checked = check('ask h: Host where h.memory_ned > 1 GiB and b', fixture);
	assert.ok(checked.diagnostics.some(isError));
	assert.equal(print(normalQuestion(checked, fixture)), 'ask h: Host where 1 GiB < h.memory_ned and b');
	assert.equal(await questionHash(checked, fixture), await questionHash(check('ask h: Host where b and h.memory_ned > 1 GiB', fixture), fixture));
});

// ---- generated variants ----

/** The questions variants are made from: every `ask` and check statement of the cases that checks against the fixture, and a few more. */
function questions(): string[] {
	const dir = new URL('../../docs/rezono/cases/', import.meta.url);
	const out: string[] = [];
	for (const f of readdirSync(dir).filter((f) => /^[EP][0-9]{2}\.yaml$/.test(f))) {
		const c = yaml(readFileSync(new URL(f, dir), 'utf8')) as { source?: string; json?: unknown; declare?: string; reads_in_part?: string[] };
		if (c.declare !== undefined || c.reads_in_part !== undefined) continue;
		const text = c.json !== undefined ? print(fromJson(c.json)) : c.source;
		if (text === undefined || !/^(ask|require|warn|check)\b/.test(text)) continue;
		if (!check(text, fixture).diagnostics.some(isError)) out.push(text);
	}
	return [
		...new Set([
			...out,
			'ask h: Host where clusters.any(spec.memory_per_node * spec.nodes >= h.memory_need and count > 1) or owner is unknown',
			'ask Host where (memory_need > 300 GiB or owner = team-platform) and not clusters.any(count > 2) show owner, memory_need',
			'ask Plan where memory >= 256 GiB and hourly_price < € 0.30/h and provider = cherry or memory < 128 GiB',
			'ask Host where Host.any(it.memory_need > host.memory_need) and (owner is known or provider = cherry)',
			'ask Host where (Host where it.owner is known and it.memory_need >= 300 GiB).count() = 2 or memory_need <= 200 GiB',
			'require memory_bound: host.memory_need <= 600 GiB and owner is known and clusters.any(count > 1)'
		])
	];
}

// A small generator with a fixed seed (mulberry32): the same variants on every run.
function generator(seed: number) {
	let s = seed;
	const next = () => {
		s = (s + 0x6d2b79f5) | 0;
		let t = Math.imul(s ^ (s >>> 15), 1 | s);
		t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
		return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
	};
	const pick = <T>(xs: T[]): T => xs[Math.floor(next() * xs.length)];
	const shuffle = <T>(xs: T[]): T[] => {
		const out = [...xs];
		for (let i = out.length - 1; i > 0; i--) {
			const j = Math.floor(next() * (i + 1));
			[out[i], out[j]] = [out[j], out[i]];
		}
		return out;
	};
	return { next, pick, shuffle };
}

/**
 * A way of writing a checked question that the normal form is to undo: another name or none for the binder of an
 * `ask`, a path of the row bare or from the binder, a slot of an element bare or from `it`, the operands of `and`
 * and `or` in any order, a comparison in either orientation.
 */
function variant(checked: Checked, g: ReturnType<typeof generator>): Question {
	const tree = checked.tree!;
	const binder = isAsk(tree) ? g.pick([undefined, 'h', 'x', 'row', tree.binder]) : undefined;
	const written = isAsk(tree) ? (tree.binder ?? tree.ask.replace(/(?<=[a-z0-9])(?=[A-Z])/g, '_').toLowerCase()) : undefined;
	const named = isAsk(tree) ? (binder ?? tree.ask.replace(/(?<=[a-z0-9])(?=[A-Z])/g, '_').toLowerCase()) : undefined;
	const flips: Record<string, string> = { '<': '>', '<=': '>=', '>': '<', '>=': '<=', '=': '=', '!=': '!=' };
	const vary = (x: unknown): unknown => {
		if (Array.isArray(x)) return x.map(vary);
		if (typeof x !== 'object' || x === null) return x;
		const o = x as Record<string, unknown>;
		if ('path' in o) {
			const path = o.path as string[];
			const head = checked.heads.get(o);
			if (head?.as === 'row' && path[0] !== 'it') {
				// The binder: renamed with the `ask`, and in front of a slot left out at random.
				const rest = path.slice(1);
				if (rest.length && g.next() < 0.5) return { path: rest };
				return { path: [path[0] === written && named ? named : path[0], ...rest] };
			}
			if (head?.as === 'slot' && head.level === 0 && written !== undefined && g.next() < 0.5) return { path: [named, ...path] };
			if (path[0] === 'it' && path.length > 1 && g.next() < 0.5) return { path: path.slice(1) };
			if (head?.as === 'slot' && head.level > 0 && g.next() < 0.5) return { path: ['it', ...path] };
			return { path };
		}
		if ('and' in o || 'or' in o) {
			const op = 'and' in o ? 'and' : 'or';
			return { [op]: g.shuffle((o[op] as unknown[]).map(vary)) };
		}
		if ('cmp' in o) {
			const [op, a, b] = o.cmp as [string, unknown, unknown];
			return g.next() < 0.5 ? { cmp: [flips[op], vary(b), vary(a)] } : { cmp: [op, vary(a), vary(b)] };
		}
		return Object.fromEntries(Object.entries(o).map(([k, v]) => [k, vary(v)]));
	};
	const out = vary(tree) as Question;
	if (isAsk(out)) {
		if (binder === undefined) delete out.binder;
		else out.binder = binder;
	}
	return out;
}

/** What an answer says of each row, whatever the order of its columns. */
async function outcome(checked: Checked): Promise<unknown> {
	if (!isAsk(checked.tree!)) return undefined;
	try {
		const a = (await answer(checked, fixture, load(fixture, appendixB)))!;
		return { rows: a.rows.map((r) => r.$id), undecided: a.undecided.map(({ $id, state, reason, cause_relation, cause_key }) => ({ $id, state, reason, cause_relation, cause_key })), counts: a.counts };
	} catch {
		return 'not evaluated';
	}
}

test('generated variants (seed 20261115): every one that checks has the hash and the answer of its question; a changed operator changes the hash', async () => {
	const g = generator(20261115);
	let checkedVariants = 0;
	let answeredVariants = 0;
	let differ = 0;
	const bases = questions();
	assert.ok(bases.length >= 40, `${bases.length} questions`);
	for (const text of bases) {
		const checked = valid(text);
		const want = await questionHash(checked, fixture);
		const answered = await outcome(checked);
		// The normal form checks, and it is its own normal form.
		const normalForm = normalQuestion(checked, fixture);
		const again = check(print(normalForm), fixture);
		assert.deepEqual(again.diagnostics.filter(isError), [], `${text}: ${print(normalForm)}`);
		assert.equal(toJson(normalQuestion(again, fixture)), toJson(normalForm), text);
		assert.deepEqual(await outcome(again), answered, `${text}: the answer of the normal form`);
		for (let i = 0; i < 16; i++) {
			const written = print(variant(checked, g));
			const v = check(written, fixture);
			if (v.diagnostics.some(isError)) continue;
			checkedVariants++;
			assert.equal(await questionHash(v, fixture), want, `${written} is ${text}`);
			if (answered !== undefined && answered !== 'not evaluated') {
				assert.deepEqual(await outcome(v), answered, `${written}: the answer of ${text}`);
				answeredVariants++;
			}
		}
		// One operator changed in the normal form: a comparison made strict or loose, `and` made `or`, or the reverse.
		const changed = print(normalForm).replace(/ (<=|<|and|or) /, (_, op: string) => ` ${({ '<=': '<', '<': '<=', and: 'or', or: 'and' } as Record<string, string>)[op]} `);
		if (changed !== print(normalForm) && !check(changed, fixture).diagnostics.some(isError)) {
			assert.notEqual(await questionHash(check(changed, fixture), fixture), want, `${changed} and ${text}`);
			differ++;
		}
	}
	assert.ok(checkedVariants >= 400, `${checkedVariants} variants checked`);
	assert.ok(answeredVariants >= 300, `${answeredVariants} variants answered`);
	assert.ok(differ >= 30, `${differ} changed questions`);
});
