// Evaluation (docs/rezono/expressions.md §7, §7a, §8a, Appendix A), where the conformance cases do not show
// it: the truth tables against the data of S1 (docs/semantics/value-cases.yaml), the reasons of A.4, exact
// units, aggregates and filters, open relations, missing values, suppose lines, the rows of an answer as Row
// JSON, and its pages.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import { parse as yaml } from 'yaml';
import { amount, answer, check, isError, load, NotEvaluated, NotLoaded, OverBudget, page, publish, suppose, type Answer, type Data, type Schema } from '../src/index.ts';

const read = (file: string) => readFileSync(new URL(file, import.meta.url), 'utf8');
const fixture = JSON.parse(read('fixture.schema.json')) as Schema;
function schemaWith(change: (s: Schema) => void): Schema {
	const s = structuredClone(fixture);
	change(s);
	return s;
}

/** A small world over the fixture schema: two providers, four hosts (those of Appendix B), clusters and plans. */
const rows: Record<string, unknown>[] = [
	{ $kind: 'Provider', $id: 'cherry' },
	{ $kind: 'Provider', $id: 'scw' },
	{ $kind: 'Team', $id: 'team-platform' },
	{ $kind: 'ClusterSpec', $id: 'small', nodes: 3, memory_per_node: '16 GiB' },
	{ $kind: 'ClusterSpec', $id: 'large', nodes: 5, memory_per_node: '64 GiB' },
	{ $kind: 'Host', $id: 'host-a', provider: { $ref: 'cherry' }, owner: { $unknown: 'not_assigned' }, memory_need: '400 GiB' },
	{ $kind: 'Host', $id: 'host-b', provider: { $ref: 'scw' }, owner: { $na: '' }, memory_need: '200 GiB' },
	{ $kind: 'Host', $id: 'host-c', provider: { $ref: 'cherry' }, owner: { $ref: 'team-platform' }, memory_need: '512 GiB' },
	{ $kind: 'Host', $id: 'host-d', provider: { $unknown: 'no_contract' }, owner: { $na: '' }, memory_need: { $unknown: 'no_spec' } },
	{ $kind: 'HostCluster', $id: 'x1', host: { $ref: 'host-a' }, spec: { $ref: 'small' }, count: 2 },
	{ $kind: 'HostCluster', $id: 'x2', host: { $ref: 'host-a' }, spec: { $ref: 'large' }, count: 1 },
	{ $kind: 'HostCluster', $id: 'x3', host: { $ref: 'host-c' }, spec: { $ref: 'large' }, count: { $unknown: 'not_counted' } },
	{ $kind: 'Plan', $id: 'p-256', provider: { $ref: 'scw' }, memory: '256 GiB', hourly_price: '€ 0.1740/h', monthly_price: '€ 127.02' },
	{ $kind: 'Plan', $id: 'p-512', provider: { $ref: 'cherry' }, memory: '512 GiB', hourly_price: '€ 0.2500/h', monthly_price: '€ 182.50' },
	{ $kind: 'Plan', $id: 'p-x', provider: { $ref: 'cherry' }, memory: { $unknown: 'not_published' }, hourly_price: '€ 0.2000/h', monthly_price: { $unknown: 'not_published' } }
];
const more = {
	rules: { fits: [['host-b', 'p-256'], ['host-b', 'p-512'], ['host-a', 'p-512'], ['host-c', 'p-512']] },
	params: { host_reserve: '16 GiB' }
};
const world = load(fixture, rows, more);

async function ask(text: string, data: Data = world, schema: Schema = fixture): Promise<Answer> {
	const checked = check(text, schema);
	assert.deepEqual(checked.diagnostics.filter(isError), [], text);
	return (await answer(checked, schema, data))!;
}
/** An answer in one line: its rows, its undecided rows with state and reason, and its not-applicable count. */
const brief = async (text: string, data?: Data, schema?: Schema): Promise<string> => {
	const a = await ask(text, data, schema);
	return `${a.rows.map((r) => r.$id).join(',')} | ${a.undecided.map((u) => `${u.$id} ${u.state} ${u.reason}`).join(',')} | ${a.counts.not_applicable}`;
};
const given = (data: Data, ...lines: string[]): Data => lines.reduce((d, line) => suppose(d, check(line, fixture), fixture), data);
const found = (text: string, schema = fixture): string[] => check(text, schema).diagnostics.map((d) => `${d.code} at ${d.span.text}${d.suggest ? ` (${d.suggest.join(', ')})` : ''}`);

// ---- Appendix A, against S1's tables ----

const tables = (yaml(read('../../docs/semantics/value-cases.yaml')) as { tables: Record<string, unknown> }).tables as {
	order: string[];
	and: Record<string, string[]>;
	or: Record<string, string[]>;
	imply: Record<string, string[]>;
	not: string[];
	is: Record<string, string[]>;
	strict_order: string[];
};
/** Each of the five values as a condition a question can write. */
const SPELL: Record<string, string> = { T: 'true', F: 'false', N: 'n/a', U: 'unknown u', I: 'invalid i' };
const one = load(fixture, [{ $kind: 'Team', $id: 't' }]);
/** The value of a condition over the one row of `one`, by what the top of an `ask` makes of it (A.5). */
async function valueOf(condition: string): Promise<string> {
	const a = await ask(`ask Team where ${condition}`, one);
	if (a.counts.rows) return 'T';
	if (a.counts.not_applicable) return 'N';
	if (a.counts.undecided) return a.undecided[0].state === 'unknown' ? 'U' : 'I';
	return 'F';
}

test('A.1 and A.2: `and`, `or`, `=>` and `not` are the tables of S1, cell for cell', async () => {
	assert.deepEqual(tables.order, ['T', 'F', 'N', 'U', 'I']);
	for (const [word, table] of [['and', tables.and], ['or', tables.or], ['=>', tables.imply]] as const)
		for (const a of tables.order)
			for (const [j, b] of tables.order.entries()) assert.equal(await valueOf(`(${SPELL[a]}) ${word} (${SPELL[b]})`), table[a][j], `${a} ${word} ${b}`);
	for (const [i, a] of tables.order.entries()) assert.equal(await valueOf(`not (${SPELL[a]})`), tables.not[i], `not ${a}`);
});

test('A.3 and A.3b: a strict operator takes the highest state, and `is` is always true or false', async () => {
	const rank = (v: string) => tables.strict_order.indexOf(v);
	for (const a of tables.order)
		for (const b of tables.order) {
			const want = rank(a) < 0 && rank(b) < 0 ? (a === b ? 'T' : 'F') : rank(a) > rank(b) ? a : b;
			assert.equal(await valueOf(`(${SPELL[a]}) = (${SPELL[b]})`), want, `${a} = ${b}`);
		}
	const states = ['T', 'N', 'U', 'I'];
	for (const [word, row] of Object.entries(tables.is)) for (const [i, x] of states.entries()) assert.equal(await valueOf(`(${SPELL[x]}) is ${word}`), row[i], `${x} is ${word}`);
	// `when` with a condition in a state takes that state (A.2).
	for (const [a, want] of [['T', 'T'], ['F', 'F'], ['N', 'N'], ['U', 'U'], ['I', 'I']]) assert.equal(await valueOf(`when (${SPELL[a]}) then true else false`), want);
});

test('A.4: the least reason wins, a constant before any cause, then the cause that sorts first', async () => {
	// Commutative in reason: the order of the operands does not show.
	for (const text of ['ask Team where unknown b and unknown a', 'ask Team where unknown a and unknown b', 'ask Team where unknown b or unknown a']) assert.equal((await ask(text, one)).undecided[0].reason, 'a');
	// The highest state decides before the reason does.
	assert.equal(await brief('ask Team where unknown a and invalid z', one), ' | t invalid z | 0');
	// Two operands with one reason: the one written as a constant has no cause, and sorts first.
	const [a] = (await ask('ask Host where owner = team-platform and unknown not_assigned')).undecided;
	assert.deepEqual([a.$id, a.reason, a.cause_relation, a.cause_key], ['host-a', 'not_assigned', '', '']);
	const [b] = (await ask('ask Host where owner = team-platform')).undecided;
	assert.deepEqual([b.$id, b.reason, b.cause_relation, b.cause_key], ['host-a', 'not_assigned', 'host__owner', '["host-a"]']);
	// Two causes with one reason: the row that sorts first, whichever is read first.
	const two = given(world, '+ x0.host = host-c', '+ x0.count = unknown not_counted');
	for (const text of ['ask Host where clusters.any(count > 1)', 'ask Host where clusters.all(count > 1)']) {
		const [c] = (await ask(text, two)).undecided;
		assert.deepEqual([c.$id, c.reason, c.cause_relation, c.cause_key], ['host-c', 'not_counted', 'host_cluster__count', '["x0"]']);
	}
	// Two reasons: the least, with its own cause.
	const [d] = (await ask('ask Host where provider = cherry or memory_need > 1 GiB')).undecided;
	assert.deepEqual([d.$id, d.reason, d.cause_relation], ['host-d', 'no_contract', 'host__provider']);
});

// ---- exact numbers ----

test('units convert exactly, and nothing is rounded but by `round`', async () => {
	assert.deepEqual(amount(fixture, '0.5 TiB'), amount(fixture, '512 GiB'));
	assert.deepEqual(amount(fixture, '€ 0.20/h'), amount(fixture, '€ 0.2000/h'));
	assert.deepEqual(amount(fixture, '12 %'), amount(fixture, '3/25'));
	assert.equal(amount(fixture, 'twelve'), undefined);
	assert.equal(await brief('ask Plan where memory = 0.5 TiB'), 'p-512 | p-x unknown not_published | 0');
	assert.equal(await brief('ask Plan where hourly_price <= € 0.20/h'), 'p-256,p-x |  | 0');
	assert.equal(await brief('ask Plan where memory in 256 GiB..512 GiB'), 'p-256,p-512 | p-x unknown not_published | 0');
	assert.equal(await brief('ask Plan where memory in 256 GiB..<512 GiB'), 'p-256 | p-x unknown not_published | 0');
	assert.equal(await brief('ask Plan where hourly_price * 730 h = € 127.02'), 'p-256 |  | 0');
	assert.equal(await valueOf('1/3 + 1/3 + 1/3 = 1 and 50 % = 0.5 and -(1 - 3) = 2 and 7 / 2 * 2 = 7'), 'T');
	assert.equal(await valueOf('2026-11-01 < 2026-12-01 and "abc" = "abc" and "abc" != "abd"'), 'T');
	// A division by zero is invalid; no row caused it.
	const [zero] = (await ask('ask Team where 1 / 0 = 1', one)).undecided;
	assert.deepEqual([zero.state, zero.reason, zero.cause_relation], ['invalid', '', '']);
});

test('`round` takes the places of the type and a named rounding', async () => {
	for (const [mode, to] of [['half_even', '0.12'], ['half_up', '0.13'], ['down', '0.12'], ['up', '0.13']]) assert.equal(await valueOf(`round(€ 0.125, ${mode}) = € ${to}`), 'T', mode);
	assert.equal(await valueOf('round(€ 0.135, half_even) = € 0.14 and round(€ 0.1349, half_up) = € 0.13'), 'T');
	assert.equal(await brief('ask Plan where round(hourly_price * 1 h / 3, half_even) = € 0.06'), 'p-256 |  | 0');
	// Without a mode it is the pack's one rounding; a pack that names none cannot round.
	const rounding = schemaWith((s) => (s.rounding = { money: 'half_up' }));
	assert.equal((await ask('ask Team where round(€ 0.125) = € 0.13', one, rounding)).counts.rows, 1);
	await assert.rejects(ask('ask Team where round(€ 0.125) = € 0.13', one), NotEvaluated);
});

// ---- sets ----

test('aggregates are strict in their members; quantifiers fold `or` and `and`', async () => {
	assert.equal(await brief('ask Host where clusters.count() = 2'), 'host-a |  | 0');
	assert.equal(await brief('ask Host where clusters.sum(count * spec.nodes) >= 6'), 'host-a | host-c unknown not_counted | 0');
	// `min` and `max` of an empty set are `n/a empty`.
	assert.equal(await brief('ask Host where clusters.max(spec.memory_per_node) > 32 GiB'), 'host-a,host-c |  | 2');
	assert.equal(await brief('ask Host where clusters.min(spec.memory_per_node) = 16 GiB'), 'host-a |  | 2');
	assert.equal(await brief('ask Host where clusters.any(count > 1)'), 'host-a | host-c unknown not_counted | 0');
	assert.equal(await brief('ask Host where clusters.all(count >= 1)'), 'host-a,host-b,host-d | host-c unknown not_counted | 0');
	assert.equal(await brief('ask Host where clusters.none(spec = large)'), 'host-b,host-d |  | 0');
	assert.equal(await brief('ask Host where clusters.any()'), 'host-a,host-c |  | 0');
	// A kind is the set of its rows; a count with a condition is strict in that condition.
	assert.equal(await valueOf('true'), 'T');
	assert.equal(await brief('ask Provider where Plan.count() = 3 and Plan.min(hourly_price) = € 0.174/h'), 'cherry,scw |  | 0');
	assert.equal(await brief('ask Provider where Plan.count(memory >= 256 GiB) = 2'), ' | cherry unknown not_published,scw unknown not_published | 0');
	// A path through a set reads every member.
	assert.equal(await brief('ask Host where clusters.spec.nodes.sum() = 8'), 'host-a |  | 0');
	// `count` is strict in its members as `sum`, `min` and `max` are (A.3): a member in a state is not counted as a value.
	assert.equal(await brief('ask Provider where Host.memory_need.count() = 4'), ' | cherry unknown no_spec,scw unknown no_spec | 0');
	assert.equal(await brief('ask Provider where Host.memory_need.max() > 1 GiB'), ' | cherry unknown no_spec,scw unknown no_spec | 0');
	assert.equal(await brief('ask Provider where Host.owner.count() = 4'), ' | cherry unknown not_assigned,scw unknown not_assigned | 0');
	assert.equal(await brief('ask Provider where Plan.provider.count() = 3'), 'cherry,scw |  | 0');
	// A parameter is read like a value.
	assert.equal(await brief('ask Host where memory_need > host_reserve * 20'), 'host-a,host-c | host-d unknown no_spec | 0');
});

test('a filter decides like an `ask`, and keeps a member it cannot decide as undecided', async () => {
	assert.equal(await brief('ask Host where (clusters where count > 1).count() = 1'), 'host-a | host-c unknown not_counted | 0');
	// x3 may be a member; that it is not `small` is known, so `any` is false whatever its count is.
	assert.equal(await brief('ask Host where (clusters where count > 1).any(spec = small)'), 'host-a |  | 0');
	assert.equal(await brief('ask Host where (clusters where count > 1).any(spec = large)'), ' | host-c unknown not_counted | 0');
	assert.equal(await brief('ask Host where (clusters where count > 1).all(spec = small)'), 'host-a,host-b,host-d | host-c unknown not_counted | 0');
	assert.equal(await brief('ask p: Provider where (Plan where provider = p).count() = 2'), 'cherry |  | 0');
});

test('`in` reads a set and a range; a member in a state may be the one', async () => {
	assert.equal(await brief('ask Plan where provider in Host.provider'), 'p-256,p-512,p-x |  | 0');
	assert.equal(await brief('ask Provider where Provider:`none` in Host.provider'), ' | cherry unknown no_contract,scw unknown no_contract | 0');
	assert.equal(await brief('ask Host where owner in Team'), 'host-c | host-a unknown not_assigned | 2');
});

test('rules: a call reads the rows of the rule; no row is false only for a closed rule', async () => {
	assert.equal(await brief('ask Plan where fits(host-b, plan)'), 'p-256,p-512 |  | 0');
	assert.equal(await brief('ask Plan where not fits(host-a, plan)'), 'p-256,p-x |  | 0');
	assert.equal(await brief('ask Host where Plan.any(fits(host, it))'), 'host-a,host-b,host-c |  | 0');
	const open = schemaWith((s) => (s.rules!.fits.world = 'open'));
	const [x] = (await ask('ask Plan where fits(host-b, plan)', world, open)).undecided;
	assert.deepEqual([x.$id, x.state, x.reason, x.cause_relation, x.cause_key], ['p-x', 'unknown', 'open_world', 'fits', '["host-b","p-x"]']);
});

test('over an open relation "no member found" is unknown with the reason open_world, never false', async () => {
	const noTeam = given(world, '- Team team-platform');
	assert.equal(await brief('ask Host where Team.any(true)'), 'host-a,host-b,host-c,host-d |  | 0');
	assert.equal(await brief('ask Host where Team.any(true)', noTeam), ' | host-a unknown open_world,host-b unknown open_world,host-c unknown open_world,host-d unknown open_world | 0');
	assert.equal(await brief('ask Host where owner in Team', noTeam), ' | host-a unknown not_assigned,host-c unknown open_world | 2');
	// A set over an open kind has no row to name: the reason stands without a cause.
	const [u] = (await ask('ask Host where Team.any(true) = false', noTeam)).undecided;
	assert.deepEqual([u.state, u.reason, u.cause_relation, u.cause_key], ['unknown', 'open_world', '', '']);
	// The same question over a closed kind is decided.
	assert.equal(await brief('ask Host where Plan.any(memory > 1 TiB)', given(world, '- Plan p-x')), ' |  | 0');
});

test('an inverse set that is open is never read as complete, whichever slot says `closed`', async () => {
	// `HostCluster` is open and its slot `host` says closed: the shape a writer gives. host-b and host-d have no
	// listed cluster, and that proves nothing.
	const open = schemaWith((s) => ((s.kinds.HostCluster.world = 'open'), (s.kinds.HostCluster.slots.host.world = 'closed')));
	const data = load(open, rows, more);
	assert.equal(await brief('ask Host where clusters.any(true) = false', data, open), ' | host-b unknown open_world,host-d unknown open_world | 0');
	assert.equal(await brief('ask Host where (x1 in clusters) = false', data, open), ' | host-b unknown open_world,host-c unknown open_world,host-d unknown open_world | 0');
	assert.equal(await brief('ask Host where clusters.any(count > 1)', data, open), 'host-a | host-b unknown open_world,host-c unknown not_counted,host-d unknown open_world | 0');
	for (const q of ['clusters.count() = 0', 'clusters.all(count > 5)']) assert.deepEqual(check(`ask Host where ${q}`, open).diagnostics.map((d) => d.code), ['R004'], q);
});

test('an element whose forward value is in a state is a member of every inverse set, undecided', async () => {
	// x9 is placed on a host nobody knows: asked from either end, the one relation gives one answer.
	const counted = rows.map((r) => (r.$id === 'x3' ? { ...r, count: 1 } : r));
	const placed = (host: unknown) => load(fixture, [...counted, { $kind: 'HostCluster', $id: 'x9', ...(host === undefined ? {} : { host }), spec: { $ref: 'small' }, count: 4 }], more);
	const all = (state: string, reason: string) => ['host-a', 'host-b', 'host-c', 'host-d'].map((h) => `${h} ${state} ${reason}`).join(',');
	for (const [data, state, reason] of [[placed({ $unknown: 'not_placed' }), 'unknown', 'not_placed'], [placed({ $invalid: 'two_hosts' }), 'invalid', 'two_hosts'], [placed(undefined), 'unknown', '']] as const) {
		assert.equal(await brief('ask HostCluster where not (host = host-b)', data), `x1,x2,x3 | x9 ${state} ${reason} | 0`);
		assert.equal(await brief('ask Host where not (x9 in clusters)', data), ` | ${all(state, reason)} | 0`);
		// A count does not reason about bounds: host-a has two clusters for sure, and its count is undecided too.
		assert.equal(await brief('ask Host where clusters.count() = 0', data), ` | ${all(state, reason)} | 0`);
		assert.equal(await brief('ask Host where clusters.none(count > 3)', data), ` | ${all(state, reason)} | 0`);
		assert.equal(await brief('ask Host where clusters.all(count < 3)', data), ` | ${all(state, reason)} | 0`);
		assert.equal(await brief('ask Host where not clusters.any(count = 4)', data), ` | ${all(state, reason)} | 0`);
		assert.equal(await brief('ask Host where clusters.sum(count) = 3', data), ` | ${all(state, reason)} | 0`);
		// A known member still decides: `any` is true where one shows it, `all` false where one fails it; and x9
		// itself has a count above one, so "in => count > 1" holds for it whether it is a member or not.
		assert.equal(await brief('ask Host where clusters.any(count > 1)', data), `host-a | ${['host-b', 'host-c', 'host-d'].map((h) => `${h} ${state} ${reason}`).join(',')} | 0`);
		assert.equal(await brief('ask Host where clusters.all(count > 1)', data), 'host-b,host-d |  | 0');
		// The cause is the row of the forward value.
		const [u] = (await ask('ask Host where clusters.count() = 0', data)).undecided;
		assert.deepEqual([u.cause_relation, u.cause_key], ['host_cluster__host', '["x9"]']);
	}
	// A forward value that is `n/a` names no element: an optional slot without a value.
	const optional = schemaWith((s) => ((s.kinds.HostCluster.slots.host.card = '?'), s.kinds.HostCluster.slots.host.states.push('not_applicable')));
	for (const host of [{ $na: '' }, undefined]) {
		const data = load(optional, [...rows, { $kind: 'HostCluster', $id: 'x9', ...(host ? { host } : {}), spec: { $ref: 'small' }, count: 4 }], more);
		assert.equal(await brief('ask Host where clusters.count() = 0', data, optional), 'host-b,host-d |  | 0');
	}
	// Through a second set the two memberships both have to hold.
	const data = placed({ $unknown: 'not_placed' });
	assert.equal(await brief('ask p: Provider where (Host where provider = p).clusters.count() = 3', data), ' | cherry unknown no_contract,scw unknown no_contract | 0');
});

test('a slot of an element of an open kind that has no row is unknown, whatever its cardinality', async () => {
	const tiered = schemaWith((s) => (s.kinds.ClusterSpec.slots.tier = { type: 'Text', card: '?', states: ['known', 'not_applicable'] }));
	const data = load(tiered, [...rows, { $kind: 'HostCluster', $id: 'x7', host: { $ref: 'host-b' }, spec: { $ref: 'huge' }, count: 1 }], more);
	// Nothing is known of `huge`, also not that it has no tier.
	assert.equal(await brief('ask HostCluster where spec.tier is n/a', data, tiered), 'x1,x2,x3 |  | 0');
	assert.equal(await brief('ask HostCluster where spec.tier is unknown', data, tiered), 'x7 |  | 0');
	const [u] = (await ask('ask HostCluster where spec.nodes > 1', data, tiered)).undecided;
	assert.deepEqual([u.$id, u.state, u.reason, u.cause_relation, u.cause_key], ['x7', 'unknown', 'open_world', 'cluster_spec__nodes', '["huge"]']);
	// The output schema lists the state for a slot read through an open kind, also where the slot itself does not.
	const shown = await ask('ask HostCluster where true show spec.tier', data, tiered);
	assert.deepEqual([shown.rows[3].c1, shown.schema.kinds.Answer.slots.c1.states], [{ $unknown: 'open_world' }, ['known', 'not_applicable', 'unknown']]);
	// In a closed kind a value that is not there is read by its cardinality, as before.
	assert.equal(await brief('ask Host where owner = team-platform', load(fixture, [{ $kind: 'Host', $id: 'h1' }])), ' |  | 1');
});

// ---- the role's view ----

test('what is missing is read by the cardinality of its slot (§7a rule 1)', async () => {
	const bare = load(fixture, [{ $kind: 'Host', $id: 'h1' }, { $kind: 'Host', $id: 'h2' }, { $kind: 'Team', $id: 'team-platform' }]);
	// A missing `T` is unknown, and the cause is the row that would hold it.
	const a = await ask('ask Host where provider = cherry', bare);
	assert.deepEqual(a.undecided.map((u) => [u.$id, u.state, u.reason, u.cause_relation, u.cause_key]), [['h1', 'unknown', '', 'host__provider', '["h1"]'], ['h2', 'unknown', '', 'host__provider', '["h2"]']]);
	// A missing `T?` is `n/a`; an absent member of a closed set is absent.
	assert.equal(await brief('ask Host where owner = team-platform', bare), ' |  | 2');
	assert.equal(await brief('ask Host where clusters.count() = 0 and owner is n/a and provider is unknown', bare), 'h1,h2 |  | 0');
	// A parameter without a value is unknown.
	assert.equal(await brief('ask Host where host_reserve > 1 GiB', bare), ' | h1 unknown ,h2 unknown  | 0');
	// A kind the schema does not have is not read; a value that is not one of its slot is refused.
	assert.equal(load(fixture, [{ $kind: 'Secret', $id: 's' }]).kinds.size, 0);
	assert.throws(() => load(fixture, [{ $kind: 'Plan', $id: 'p', memory: 'much' }]), TypeError);
	// A reference into another pack names its element after the kind (publication §3.4).
	const far = load(fixture, [{ $kind: 'Host', $id: 'h', provider: { $ref: `other@s-${'0'.repeat(64)}:Provider/cher/ry` } }]);
	assert.deepEqual(far.kinds.get('Host')!.get('h')!.get('provider'), { s: 'known', v: { id: 'cher/ry' } });
});

test('a single value missing from a relation the role reads in part is unknown, also an optional one (§7a rule 1)', async () => {
	// The role reads a part of the owners, of the providers and of the hosts of clusters; the document of its
	// form would say `world: open` for them, here only `in_part` does, and that is enough.
	const part = schemaWith((s) => {
		s.in_part = { Host: ['owner', 'provider'], HostCluster: ['host'] };
		s.kinds.Host.slots.owner.states = ['known', 'not_applicable'];
	});
	const common = [{ $kind: 'Team', $id: 'team-platform' }, { $kind: 'Provider', $id: 'cherry' }, { $kind: 'ClusterSpec', $id: 'small', nodes: 3, memory_per_node: '16 GiB' }];
	const h2 = { $kind: 'Host', $id: 'h2', owner: { $ref: 'team-platform' }, provider: { $ref: 'cherry' } };
	const h3 = { $kind: 'Host', $id: 'h3', owner: { $na: '' }, provider: { $ref: 'cherry' } };
	const x1 = { $kind: 'HostCluster', $id: 'x1', spec: { $ref: 'small' }, count: 2 };
	const bare = load(part, [...common, { $kind: 'Host', $id: 'h1' }, h2, h3, x1]);
	// An optional value: unknown with the code, and the row that would hold it as the cause. An `n/a` the role
	// does read stays `n/a`.
	const a = await ask('ask Host where owner = team-platform', bare, part);
	assert.deepEqual([a.rows.map((r) => r.$id), a.counts], [['h2'], { rows: 1, undecided: 1, not_applicable: 1 }]);
	assert.deepEqual(a.undecided.map((u) => [u.$id, u.state, u.reason, u.cause_relation, u.cause_key]), [['h1', 'unknown', 'not_read_in_full', 'host__owner', '["h1"]']]);
	assert.equal(await brief('ask Host where owner is n/a', bare, part), 'h3 |  | 0');
	assert.equal(await brief('ask Host where owner is unknown', bare, part), 'h1 |  | 0');
	// A required value: the same code, where a relation read in full gives none.
	assert.equal(await brief('ask Host where provider = cherry', bare, part), 'h2,h3 | h1 unknown not_read_in_full | 0');
	// The role's form writes these absences out (publication §3.3): the same answer, byte for byte.
	const state = { $unknown: 'not_read_in_full' };
	const written = load(part, [...common, { $kind: 'Host', $id: 'h1', owner: state, provider: state }, h2, h3, { ...x1, host: state }]);
	for (const text of ['ask Host where owner = team-platform show owner, provider', 'ask Host where clusters.any(count > 1)', 'ask HostCluster where host.owner is known']) {
		assert.equal(JSON.stringify(await ask(text, bare, part)), JSON.stringify(await ask(text, written, part)), text);
	}
	// A value a suppose line takes away is read the same way: the role cannot tell it from one it does not read.
	const without = suppose(load(part, [...common, h2]), check('- h2.owner', part), part);
	assert.equal(await brief('ask Host where owner = team-platform', without, part), ' | h2 unknown not_read_in_full | 0');
	// From the other end: a cluster whose host the role may not read may be any host's.
	assert.equal(await brief('ask Host where clusters.any(count > 1)', bare, part), ' | h1 unknown not_read_in_full,h2 unknown not_read_in_full,h3 unknown not_read_in_full | 0');
	// The check knows it without a row: the shown value can be unknown, and nothing is counted or denied over
	// a relation that is open for the role.
	const shown = await ask('ask Host where true show owner', bare, part);
	assert.deepEqual(shown.schema.kinds.Answer.slots.c1.states, ['known', 'not_applicable', 'unknown']);
	assert.deepEqual(check('ask Host where clusters.count() = 0', part).diagnostics.filter(isError).map((d) => d.code), ['R004']);
	assert.deepEqual(check('ask Host where clusters.count() = 0', fixture).diagnostics.filter(isError), []);
	// It is no part of the pack's schema: the id of the role's document is that of the document.
	const { in_part: _inPart, ...document } = part;
	assert.equal(shown.schema.imports.p.schema, (await ask('ask Host where true show owner', bare, document as Schema)).schema.imports.p.schema);
});

test('rows come in the canonical order of their key, whatever order the data has', async () => {
	const teams = ['b', 'é', 'B', 'a-1', 'a"'].map(($id) => ({ $kind: 'Team', $id }));
	const forward = await ask('ask Team where true', load(fixture, teams));
	const backward = await ask('ask Team where true', load(fixture, [...teams].reverse()));
	// The order is that of the canonical JSON of the key, not of the id: `a"` is written `a\"` there, after `a-1`.
	assert.deepEqual(forward.rows.map((r) => r.$id), ['B', 'a-1', 'a"', 'b', 'é']);
	assert.deepEqual(backward, forward);
});

// ---- suppose lines ----

test('a suppose line changes the rows for the question only', async () => {
	const before = JSON.stringify(await ask('ask Host where true show clusters.sum(count * spec.nodes), owner, memory_need'));
	assert.equal(await brief('ask Host where clusters.sum(count * spec.nodes) = 21', given(world, '+ x2.count = 3')), 'host-a | host-c unknown not_counted | 0');
	assert.equal(await brief('ask Provider where Plan.count() = 2', given(world, '- Plan p-x')), 'cherry,scw |  | 0');
	assert.equal(await brief('ask Host where owner = team-platform', given(world, '- host-a.owner')), 'host-c |  | 3');
	assert.equal(await brief('ask Host where owner = team-platform', given(world, '+ host-a.owner = team-platform')), 'host-a,host-c |  | 2');
	// A state that a line sets stands in the row it is set on.
	const [d] = (await ask('ask Host where memory_need > 1 GiB', given(world, '+ host-d.memory_need = invalid versions_overlap'))).undecided;
	assert.deepEqual([d.$id, d.state, d.reason, d.cause_relation, d.cause_key], ['host-d', 'invalid', 'versions_overlap', 'host__memory_need', '["host-d"]']);
	// A line can make an element; a path through a slot writes where it leads.
	assert.equal(await brief('ask Host where memory_need > 500 GiB', given(world, '+ host-e.memory_need = 600 GiB')), 'host-c,host-e | host-d unknown no_spec | 0');
	assert.equal(await brief('ask Host where clusters.any(spec.nodes = 9)', given(world, '+ x1.spec.nodes = 9')), 'host-a |  | 0');
	// The rows handed in are as they were.
	assert.equal(JSON.stringify(await ask('ask Host where true show clusters.sum(count * spec.nodes), owner, memory_need')), before);
	assert.throws(() => suppose(world, check('ask Host where true', fixture), fixture), TypeError);
	assert.throws(() => suppose(world, check('+ x2.cout = 3', fixture), fixture), TypeError);
	// An inverse slot is no data of its own: a line that writes one is refused, not kept as a cell nothing reads.
	assert.throws(() => suppose(world, check('- host-b.clusters', fixture), fixture), /inverse slot/);
});

test('suppose lines: states on many-valued slots and canonical Integer keys', async () => {
	const keyed = schemaWith((s) => {
		s.kinds.Host.slots.host_tags = { type: 'Text', card: '*', states: ['known', 'unknown'] };
		s.kinds.Ticket = {
			world: 'closed',
			id: { type: 'Integer' },
			slots: {
				title: { type: 'Text', card: '1', states: ['known'] },
				labels: { type: 'Text', card: '*', states: ['known', 'unknown'] },
			},
		};
	});
	const base = load(keyed, [
		{ $kind: 'Host', $id: 'host-a', host_tags: ['ops'] },
		{ $kind: 'Ticket', $id: '7', title: 'open', labels: ['ops'] },
	]);
	// Setting a state on a many-valued slot makes that slot undecided on the row, in both `set` and `insert_row`.
	const viaSet = suppose(base, check('+ host-a.host_tags = unknown not_collected', keyed), keyed);
	const setAnswer = await ask('ask Host where host_tags.any(it = "ops")', viaSet, keyed);
	assert.deepEqual(
		setAnswer.undecided.map((u) => [u.$id, u.state, u.reason, u.cause_relation, u.cause_key]),
		[['host-a', 'unknown', 'not_collected', 'host__host_tags', '["host-a"]']],
	);
	const viaInsert = suppose(base, check('+ Ticket 8 {title = "next", labels = unknown not_collected}', keyed), keyed);
	const insertAnswer = await ask('ask Ticket where labels.any(it = "ops")', viaInsert, keyed);
	assert.deepEqual(insertAnswer.rows.map((r) => r.$id), ['7']);
	assert.deepEqual(
		insertAnswer.undecided.map((u) => [u.$id, u.state, u.reason, u.cause_relation, u.cause_key]),
		[['8', 'unknown', 'not_collected', 'ticket__labels', '["8"]']],
	);
	// Integer keys are canonicalized in suppose: retracting `007` removes `7`, and an already-present `7` blocks `007`.
	const retracted = suppose(base, check('- Ticket 007', keyed), keyed);
	assert.deepEqual((await ask('ask Ticket where true', retracted, keyed)).rows, []);
	const crafted = check('+ Ticket 8 {title = "dup"}', keyed);
	if (crafted.tree && 'insert_row' in crafted.tree) crafted.tree.insert_row.key = '007';
	assert.throws(() => suppose(base, crafted, keyed), /Ticket 7 already exists/);
});

test('suppose lines: multi-hop Integer alias keys validate and canonicalize cleanly', async () => {
	const keyed = schemaWith((s) => {
		s.types = {
			...(s.types ?? {}),
			TicketNo: { of: 'Integer' },
			SubTicketNo: { of: 'TicketNo' },
			LoopA: { of: 'LoopB' },
			LoopB: { of: 'LoopA' },
		};
		s.kinds.Ticket = {
			world: 'closed',
			id: { type: 'SubTicketNo' },
			slots: {
				title: { type: 'Text', card: '1', states: ['known'] },
			},
		};
		s.kinds.LoopKind = {
			world: 'closed',
			id: { type: 'LoopA' },
			slots: {},
		};
	});
	assert.deepEqual(
		check('+ Ticket 007 {title = "bad"}', keyed).diagnostics.filter(isError).map((d) => d.code),
		['R012'],
	);
	assert.deepEqual(
		check('+ Ticket abc {title = "bad"}', keyed).diagnostics.filter(isError).map((d) => d.code),
		['R012'],
	);
	assert.deepEqual(check('+ Ticket 8 {title = "ok"}', keyed).diagnostics.filter(isError), []);
	assert.deepEqual(check('+ LoopKind k1 {}', keyed).diagnostics.filter(isError), []);

	const base = load(keyed, [
		{ $kind: 'Ticket', $id: '7', title: 'open' },
		{ $kind: 'LoopKind', $id: 'k1' },
	]);
	const retracted = suppose(base, check('- Ticket 007', keyed), keyed);
	assert.deepEqual((await ask('ask Ticket where true', retracted, keyed)).rows, []);
	const crafted = check('+ Ticket 8 {title = "dup"}', keyed);
	if (crafted.tree && 'insert_row' in crafted.tree) crafted.tree.insert_row.key = '007';
	assert.throws(() => suppose(base, crafted, keyed), /Ticket 7 already exists/);
	const loopRetracted = suppose(base, check('- LoopKind k1', keyed), keyed);
	assert.deepEqual((await ask('ask LoopKind where true', loopRetracted, keyed)).rows, []);
});

// ---- the answer as a dataset ----

test('an answer is Row JSON of its output schema: values in their normal form, states with their reason', async () => {
	const a = await ask('ask h: Host where true show h, memory_need, memory_need / 3, clusters.count(), owner, memory_need > 300 GiB, provider');
	const pack = `fixture@${a.schema.imports.p.schema}`;
	assert.match(a.$schema, /^s-[0-9a-f]{64}$/);
	assert.deepEqual(a.rows[0], {
		$kind: 'Answer',
		$id: 'host-a',
		binder: { $ref: `${pack}:Host/host-a` },
		c1: { $ref: `${pack}:Host/host-a` },
		c2: '400 GiB',
		// 400 GiB / 3 is no whole number of bytes: the type cannot hold it, so this column of this row is unknown.
		c3: { $unknown: 'not_exact' },
		c4: '2',
		c5: { $unknown: 'not_assigned' },
		c6: true,
		c7: { $ref: `${pack}:Provider/cherry` }
	});
	assert.deepEqual([a.rows[1].c5, a.rows[3].c2, a.rows[3].c3, a.rows[3].c6, a.rows[3].c7], [{ $na: '' }, { $unknown: 'no_spec' }, { $unknown: 'no_spec' }, { $unknown: 'no_spec' }, { $unknown: 'no_contract' }]);
	// Every state a row shows is one the output schema lists for its slot.
	const code = { $na: 'not_applicable', $unknown: 'unknown', $invalid: 'invalid' } as Record<string, string>;
	for (const row of a.rows)
		for (const [name, slot] of Object.entries(a.schema.kinds.Answer.slots)) {
			const value = row[name];
			const state = typeof value === 'object' && value !== null && !('$ref' in value) ? code[Object.keys(value)[0]] : 'known';
			assert.ok((slot.states as string[]).includes(state), `${row.$id}.${name}: ${state}`);
		}
	// Money keeps the places of its type; a computed amount takes the pack's type of its dimension.
	const m = await ask('ask Plan where true show hourly_price, hourly_price * 2, hourly_price * 730 h, monthly_price / 2, memory / 1024');
	assert.deepEqual([m.rows[0].c1, m.rows[0].c2, m.rows[0].c3, m.rows[0].c4, m.rows[0].c5], ['€ 0.1740/h', '€ 0.3480/h', '€ 127.02', '€ 63.51', '0.25 GiB']);
	assert.deepEqual([m.rows[2].c4, m.rows[2].c5], [{ $unknown: 'not_published' }, { $unknown: 'not_published' }]);
	// An amount its type cannot hold is `unknown not_exact`, per row and in that column only; the row stays and the
	// question is answered. Money has exactly the places of its type; a quantity is a whole number of its storage
	// unit, written as a fraction of its unit where no decimal is exact; a plain number is a ratio as it stands.
	const x = await ask('ask Plan where memory is known show monthly_price / 4, monthly_price / 3, hourly_price * 1 h, hourly_price / 3, memory / 3, 1 h / 7 * 7, 2 B / 3 * 3, 1 / 3, round(monthly_price / 3, half_even)');
	assert.deepEqual(x.rows.map((r) => r.$id), ['p-256', 'p-512']);
	assert.deepEqual(Object.values(x.rows[0]).slice(3), [{ $unknown: 'not_exact' }, '€ 42.34', { $unknown: 'not_exact' }, '€ 0.0580/h', { $unknown: 'not_exact' }, '1 h', '2 B', '1/3', '€ 42.34']);
	assert.deepEqual(Object.values(x.rows[1]).slice(3), [{ $unknown: 'not_exact' }, { $unknown: 'not_exact' }, '€ 0.25', { $unknown: 'not_exact' }, { $unknown: 'not_exact' }, '1 h', '2 B', '1/3', '€ 60.83']);
	assert.equal((await ask('ask Team where true show 1 s * 5', one)).rows[0].c1, '5 s');
	assert.equal((await ask('ask Team where true show 1 h / 3600 * 7', one)).rows[0].c1, '7/3600 h');
	for (const name of ['c1', 'c2', 'c3', 'c4', 'c5']) assert.ok(x.schema.kinds.Answer.slots[name].states.includes('unknown'), name);
	// A percent that has no number is rejected at check time (R012) and has no amount; a type whose factor is no number above zero is a defect.
	assert.deepEqual(check('ask Team where 1/0 % = 0', fixture).diagnostics.filter(isError).map((d) => d.code), ['R012']);
	assert.equal(amount(fixture, '1/0 %'), undefined);
	await assert.rejects(ask('ask Team where round(1 GiB, half_even) = 1 GiB', one, schemaWith((s) => (s.types!.GiB.factor = '0'))), TypeError);
	// The default `show` is what the condition reads.
	const d = await ask('ask Host where memory_need > 300 GiB or owner is known');
	assert.deepEqual(d.rows.map((r) => [r.$id, r.c1, r.c2]), [['host-a', '400 GiB', { $unknown: 'not_assigned' }], ['host-c', '512 GiB', { $ref: `${pack}:Team/team-platform` }]]);
	// Not an `ask`, or one that does not check: no answer.
	assert.equal(await answer(check('+ x2.count = 3', fixture), fixture, world), undefined);
	assert.equal(await answer(check('ask Host where memory_ned > 1 GiB', fixture), fixture, world), undefined);
});

test('a page is a slice of the one answer, and its cursor is the pair of last keys (§8a)', async () => {
	const a = await ask('ask Host where owner is n/a or provider = cherry');
	assert.deepEqual([a.rows.map((r) => r.$id), a.undecided.map((u) => u.$id)], [['host-a', 'host-b', 'host-c', 'host-d'], []]);
	const b = await ask('ask Host where memory_need > 100 GiB and owner = team-platform');
	assert.deepEqual([b.rows.map((r) => r.$id), b.undecided.map((u) => u.$id), b.counts], [['host-c'], ['host-a', 'host-d'], { rows: 1, undecided: 2, not_applicable: 1 }]);
	const first = page(a, 3);
	assert.deepEqual([first.rows.map((r) => r.$id), first.next], [['host-a', 'host-b', 'host-c'], { rows: 'host-c' }]);
	const second = page(a, 3, first.next);
	assert.deepEqual([second.rows.map((r) => r.$id), second.next], [['host-d'], undefined]);
	// Rows and undecided rows page side by side; the pages together are the answer.
	const all = await ask('ask Host where memory_need > 300 GiB or owner = team-platform or provider = scw');
	const seen: string[] = [];
	for (let next: ReturnType<typeof page>['next'] = {}; next; ) {
		const p = page(all, 1, next);
		assert.ok(p.rows.length <= 1 && p.undecided.length <= 1);
		seen.push(...p.rows.map((r) => r.$id), ...p.undecided.map((u) => `? ${u.$id}`));
		next = p.next;
	}
	assert.deepEqual(seen.sort(), [...all.rows.map((r) => r.$id), ...all.undecided.map((u) => `? ${u.$id}`)].sort());
	assert.deepEqual(page(all, 10), { rows: all.rows, undecided: all.undecided });
});

// ---- check statements at publication (v0 §5, §7b) ----

/** What a check statement decides, in one line: the outcome, the violations, the undecided ones, what blocks. */
function decided(text: string, data: Data = world): string {
	const checked = check(text, fixture);
	assert.deepEqual(checked.diagnostics.filter(isError), [], text);
	const p = publish(checked, fixture, data)!;
	return `${p.outcome} | ${p.violations.join(',')} | ${p.undecided.map((u) => `${u.id} ${u.state} ${u.reason}`).join(',')} | ${p.blocking.join(',')}`;
}

test('a check statement passes on true and n/a, and blocks as its word says (v0 §7b)', () => {
	// A false condition is a violation: `check` and `require` block on it, `warn` never does.
	assert.equal(decided('check small: host.memory_need <= 450 GiB'), 'blocked | host-c | host-d unknown no_spec | host-c');
	assert.equal(decided('require small: host.memory_need <= 450 GiB'), 'blocked | host-c | host-d unknown no_spec | host-c,host-d');
	assert.equal(decided('warn host.memory_need <= 450 GiB'), 'publishes | host-c | host-d unknown no_spec | ');
	// n/a passes: host-b and host-d have no owner.
	assert.equal(decided('check owned: host.owner = team-platform'), 'publishes |  | host-a unknown not_assigned | ');
	// An invalid value blocks a `check`, and not a `warn`.
	const contradicted = given(world, '+ host-d.memory_need = invalid versions_overlap');
	assert.equal(decided('check fits: host.memory_need <= 600 GiB', contradicted), 'blocked |  | host-d invalid versions_overlap | host-d');
	assert.equal(decided('warn host.memory_need <= 600 GiB', contradicted), 'publishes |  | host-d invalid versions_overlap | ');
	// The kind is named in lowercase anywhere in the condition; an undecided violation keeps its cause.
	const p = publish(check('check placed: host.clusters.count() >= 1 or host.memory_need < 300 GiB', fixture), fixture, world)!;
	assert.deepEqual(p, { verb: 'check', name: 'placed', outcome: 'publishes', violations: [], undecided: [{ id: 'host-d', state: 'unknown', reason: 'no_spec', cause: { relation: 'host__memory_need', key: ['host-d'] } }], blocking: [] });
});

test('what a check statement cannot be decided over yet, and what is no check statement', () => {
	// Two kinds in one condition are two binders, reserved as in an `ask` (§1); `norm` is reserved (v0 §5).
	assert.deepEqual(check('check pair: host.memory_need <= plan.memory', fixture).diagnostics.map((d) => [d.code, d.span.text]), [['R015', 'plan']]);
	assert.deepEqual(check('norm fresh: host.memory_need <= 600 GiB', fixture).diagnostics.map((d) => [d.code, d.span.text]), [['R015', 'norm fresh: host.memory_need <= 600 GiB']]);
	assert.equal(check('norm fresh: host.memory_need <= 600 GiB', fixture).publication, undefined);
	// A condition that names no kind checks, and is not evaluated yet.
	assert.throws(() => publish(check('check always: 1 GiB <= 2 GiB', fixture), fixture, world), NotEvaluated);
	// A condition that does not check is never decided; an `ask` is no check statement.
	assert.equal(publish(check('check typo: host.memory_ned <= 1 GiB', fixture), fixture, world), undefined);
	assert.equal(publish(check('ask Host where memory_need <= 1 GiB', fixture), fixture, world), undefined);
});

test('a bare word where an enum is expected is one of its values', async () => {
	const tiered = schemaWith((s) => {
		s.types!.Tier = { of: 'Enum', enum: 'Tier' };
		s.enums = { Tier: ['low', 'high'] };
		s.kinds.Plan.slots.tier = { type: 'Tier', card: '1', states: ['known'] };
	});
	const data = load(tiered, rows.filter((r) => r.$kind === 'Plan' || r.$kind === 'Provider').map((r) => (r.$kind === 'Plan' ? { ...r, tier: r.$id === 'p-512' ? 'high' : 'low' } : r)));
	assert.equal(await brief('ask Plan where tier = high', data, tiered), 'p-512 |  | 0');
	assert.equal(await brief('ask Plan where tier != Tier"high"', data, tiered), 'p-256,p-x |  | 0');
	// A word that is no value of the enum is no name, with the values it may have meant.
	assert.deepEqual(found('ask Plan where tier = hgh', tiered), ['R001 at hgh (high)']);
	// A slot of the same name is that slot, not the value.
	assert.deepEqual(check('ask Plan where tier = memory', tiered).diagnostics.map((d) => d.code), ['R003']);
});

// ---- the budget of steps, and what was loaded ----

test('an evaluation stops when it passes its step limit, and its cost follows from the question and the rows', async () => {
	/** The fewest steps with which a question is answered over `data`. */
	const least = async (text: string, data: Data = world): Promise<number> => {
		const checked = check(text, fixture);
		let [lo, hi] = [0, 1_000_000];
		while (lo < hi) {
			const mid = Math.floor((lo + hi) / 2);
			const done = await answer(checked, fixture, data, { steps: mid }).then(
				() => true,
				(e) => {
					if (e instanceof OverBudget && e.limit === mid) return false;
					throw e;
				}
			);
			if (done) hi = mid;
			else lo = mid + 1;
		}
		return lo;
	};
	const text = 'ask Host where memory_need > 300 GiB';
	const enough = await least(text);
	// With the limit it needs, the answer is the answer without a limit; one step less gives nothing.
	const checked = check(text, fixture);
	assert.deepEqual(await answer(checked, fixture, world, { steps: enough }), await answer(checked, fixture, world));
	await assert.rejects(answer(checked, fixture, world, { steps: enough - 1 }), OverBudget);
	// The same question over the same rows costs the same; over more rows it costs more.
	assert.equal(await least(text), enough);
	const hosts = (n: number): Data => load(fixture, [...rows, ...Array.from({ length: n }, (_, i) => ({ $kind: 'Host', $id: `more-${i}`, memory_need: '1 GiB' }))], more);
	const [ten, twenty] = [await least(text, hosts(10)), await least(text, hosts(20))];
	assert.ok(enough < ten && ten < twenty);
	assert.equal(twenty - ten, ten - enough, 'a condition that reads one value of each row costs the same for each row');
	// A set that is counted or searched for every row costs rows times members: the limit bounds the work
	// where the number of rows read does not.
	const nested = 'ask Host where Plan.count(memory >= host.memory_need) > 0';
	const [a, b, c] = [await least(nested, hosts(0)), await least(nested, hosts(10)), await least(nested, hosts(20))];
	assert.ok(b - a > 10 * 3 && c - b === b - a, 'each host more costs a pass over every plan');
	const search = 'ask Host where host in Host';
	const [s0, s10, s20] = [await least(search, hosts(0)), await least(search, hosts(10)), await least(search, hosts(20))];
	assert.ok(s20 - s10 > s10 - s0, 'a search of the kind for every row grows with the square of the rows');
});

test('every member a read gives is a step: the work of an evaluation does not grow with the fan-out of the rows alone', async () => {
	const fan = schemaWith((s) => {
		const set = (ref: string, more: object = {}) => ({ ref, card: '*' as const, states: ['known' as const], ...more });
		s.kinds.Root = { world: 'closed', id: { type: 'Text' }, slots: { nodes: set('Node') } };
		s.kinds.Node = { world: 'closed', id: { type: 'Text' }, slots: { links: set('Node') } };
		s.kinds.Target = { world: 'closed', id: { type: 'Text' }, slots: { feeds: set('Source', { inverse: 'target' }) } };
		s.kinds.Source = { world: 'closed', id: { type: 'Text' }, slots: { target: { ref: 'Target', card: '1', states: ['known', 'unknown'] } } };
	});
	const least = async (text: string, data: Data): Promise<number> => {
		const checked = check(text, fan);
		assert.deepEqual(checked.diagnostics.filter(isError), [], text);
		let [lo, hi] = [0, 1_000_000];
		while (lo < hi) {
			const mid = Math.floor((lo + hi) / 2);
			const done = await answer(checked, fan, data, { steps: mid }).then(() => true, (e) => (e instanceof OverBudget ? false : Promise.reject(e)));
			if (done) hi = mid;
			else lo = mid + 1;
		}
		return lo;
	};
	const ids = (n: number, p: string) => Array.from({ length: n }, (_, i) => ({ $ref: `${p}${i}` }));
	// Forward: one root with n nodes, each linked to one sink, the sink linked to every node. The last hop
	// gives n members for each of n sources: n² members, each a step.
	const forward = (n: number): Data =>
		load(fan, [
			{ $kind: 'Root', $id: 'r', nodes: ids(n, 'n') },
			{ $kind: 'Node', $id: 'sink', links: ids(n, 'n') },
			...Array.from({ length: n }, (_, i) => ({ $kind: 'Node', $id: `n${i}`, links: [{ $ref: 'sink' }] }))
		]);
	for (const n of [10, 20]) assert.ok((await least('ask Root where nodes.links.links is known', forward(n))) >= n * n, `forward, ${n} nodes`);
	// Inverse: n targets and n sources whose target is unknown: each target's feeds are all n, undecided.
	const inverse = (n: number): Data =>
		load(fan, [
			...Array.from({ length: n }, (_, i) => ({ $kind: 'Target', $id: `t${i}` })),
			...Array.from({ length: n }, (_, i) => ({ $kind: 'Source', $id: `s${i}`, target: { $unknown: 'not_known' } }))
		]);
	for (const n of [10, 20]) assert.ok((await least('ask Target where feeds is known', inverse(n))) >= n * n, `inverse, ${n} sources`);
});

test('a kind or a slot that was not loaded is refused, never read as absent', async () => {
	const only = (kinds: Record<string, string[]>) => load(fixture, rows, { ...more, only: new Map(Object.entries(kinds).map(([k, slots]) => [k, new Set(slots)])) });
	const q = async (text: string, data: Data) => answer(check(text, fixture), fixture, data);
	// Loaded for what the question reads: answered. Everything loaded and nothing said: answered as before.
	assert.deepEqual((await q('ask Host where owner = team-platform', only({ Host: ['owner'], Team: [] })))!.rows.map((r) => r.$id), ['host-c']);
	// The slot the condition reads, the kind asked, a kind named as a set, and the forward slot of an inverse.
	await assert.rejects(q('ask Host where owner = team-platform', only({ Host: ['provider'], Team: [] })), NotLoaded);
	await assert.rejects(q('ask Host where owner = team-platform', only({ Team: [] })), NotLoaded);
	await assert.rejects(q('ask Host where Plan.count() > 1', only({ Host: [] })), NotLoaded);
	await assert.rejects(q('ask Host where clusters.count() > 1', only({ Host: ['clusters'], HostCluster: [] })), NotLoaded);
	assert.deepEqual((await q('ask Host where clusters.count() > 1', only({ Host: ['clusters'], HostCluster: ['host'] })))!.rows.map((r) => r.$id), ['host-a']);
});
