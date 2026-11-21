// Names, types and the output schema (docs/rezono/expressions.md §5, §6, §8a), where the conformance cases do
// not show them: every code with the span it is reported at, what a role that reads less is offered, when W105
// fires, the default `show`, and the output schema as a publication schema document.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import { check, dataSchema, isError, outputSchema, schemaId, type Ask, type Diagnostic, type Schema } from '../src/index.ts';

const read = (file: string) => JSON.parse(readFileSync(new URL(file, import.meta.url), 'utf8'));
const fixture = read('fixture.schema.json') as Schema;
/** The fixture with a change, as a role that reads more or less would have it. */
function schemaWith(change: (s: Schema) => void): Schema {
	const s = structuredClone(fixture);
	change(s);
	return s;
}
/** The diagnostics of a question as `code at text`, with what was suggested. */
const found = (text: string, schema = fixture): string[] => check(text, schema).diagnostics.map((d) => `${d.code} at ${d.span.text}${d.suggest ? ` (${d.suggest.join(', ')})` : ''}`);
const clean = (text: string, schema = fixture) => assert.deepEqual(found(text, schema), [], text);

test('R001: a name the schema does not have, with what it may have meant', () => {
	assert.deepEqual(found('ask Hots where true'), ['R001 at Hots (Host)']);
	assert.deepEqual(found('ask h: Host where h.memory_ned > 1 GiB'), ['R001 at memory_ned (memory_need)']);
	assert.deepEqual(found('ask Host where memory_need > 384 Gib'), ['R001 at Gib (GiB)']);
	assert.deepEqual(found('ask Plan where fit(host-b, plan)'), ['R001 at fit (fits)']);
	assert.deepEqual(found('ask Plan where monthly_price > $ 5'), ['R001 at $ ()']);
	assert.deepEqual(found('ask Host where Plam.count() > 1'), ['R001 at Plam (Plan)']);
	assert.deepEqual(found('ask Host where owner = Tean:`team-platform`'), ['R001 at Tean (Team)']);
	assert.deepEqual(found('- Plam scw-pro2-l'), ['R001 at Plam (Plan)']);
	// An error inside a set is reported once: its element scope is not looked into.
	assert.deepEqual(found('ask Host where clustrs.any(count > 1)'), ['R001 at clustrs (clusters)']);
});

test('R001 never names what the role does not read (§5 rule 8)', () => {
	const narrow = schemaWith((s) => {
		delete s.kinds.Host.slots.memory_need;
		delete s.kinds.Plan;
		delete s.rules!.fits;
	});
	assert.deepEqual(found('ask Host where memory_ned > 0 GiB', narrow), ['R001 at memory_ned']);
	assert.deepEqual(found('ask Host where memory_need > 0 GiB', narrow), ['R001 at memory_need']);
	assert.deepEqual(found('ask Plan where true', narrow), ['R001 at Plan ()']);
	assert.deepEqual(found('ask Host where fits(host, host)', narrow), ['R001 at fits ()']);
});

test('R002: an id where no kind is expected', () => {
	assert.deepEqual(found('ask Host where host-b is known'), ['R002 at host-b']);
	assert.deepEqual(found('ask Host where host-a = host-b'), ['R002 at host-a', 'R002 at host-b']);
	assert.deepEqual(found('ask Host where memory_need > host-b'), ['R002 at host-b']);
	// `provider` is a slot of two kinds, so the id's kind does not follow from it.
	assert.deepEqual(found('+ x-1.provider = cherry'), ['R002 at x-1']);
	clean('ask Host where Host:`host-b` is known');
	clean('ask Host where owner = Team:`team-platform`');
	assert.deepEqual(check('+ host-a.owner = team-platform', fixture).resolve, { 'host-a': 'Host', 'team-platform': 'Team' });
	assert.deepEqual(check('- Plan scw-pro2-l', fixture).resolve, { 'scw-pro2-l': 'Plan' });
	assert.deepEqual(check('ask Host where provider = cherry', fixture).resolve, { cherry: 'Provider' });
});

test('R003: types that do not go together', () => {
	assert.deepEqual(found('ask Host where owner = 3 GiB'), ['R003 at owner = 3 GiB']);
	assert.deepEqual(found('ask Plan where memory > 5 h'), ['R003 at memory > 5 h']);
	assert.deepEqual(found('ask Plan where hourly_price * 730 h > 5 GiB'), ['R003 at hourly_price * 730 h > 5 GiB']);
	assert.deepEqual(found('ask Plan where memory in 1 h..2 h'), ['R003 at memory in 1 h..2 h']);
	assert.deepEqual(found('ask Plan where provider < cherry'), ['R003 at provider < cherry']);
	assert.deepEqual(found('ask Plan where fits(plan, plan)'), ['R003 at plan']);
	assert.deepEqual(found('ask Plan where fits(plan)'), ['R003 at fits(plan)']);
	assert.deepEqual(found('ask Host where when owner is known then memory_need else owner'), ['R003 at when owner is known then memory_need else owner']);
	assert.deepEqual(found('+ host-e.memory_need = € 5'), ['R003 at € 5']);
	assert.deepEqual(found('ask Host where clusters.sum(spec) > 1'), ['R003 at spec']);
	// Units of one dimension go together, and a product has the dimension of its parts.
	clean('ask Plan where memory = 0.5 TiB + 1 GiB');
	clean('ask Plan where hourly_price * 730 h <= monthly_price');
	clean('ask Plan where monthly_price / 730 h <= hourly_price');
	clean('ask Host where clusters.sum(count * spec.nodes * spec.memory_per_node) + host_reserve >= memory_need');
	clean('ask Host where memory_need = unknown no_spec or owner = n/a');
	clean('+ host-d.memory_need = invalid versions_overlap');
});

test('R004: a missing row is read as false only over a closed relation', () => {
	assert.deepEqual(found('ask Host where Team.none(true)'), ['R004 at Team.none(true)']);
	assert.deepEqual(found('ask Host where Team.all(true)'), ['R004 at Team.all(true)']);
	assert.deepEqual(found('ask Host where Team.any(true) => owner is known'), ['R004 at Team.any(true) => owner is known']);
	assert.deepEqual(found('ask Host where not owner in Team'), ['R004 at not owner in Team']);
	const open = schemaWith((s) => {
		s.rules!.fits.world = 'open';
		s.kinds.Host.slots.clusters.world = 'open';
	});
	assert.deepEqual(found('ask Plan where not fits(host-b, plan)', open), ['R004 at not fits(host-b, plan)']);
	assert.deepEqual(found('ask Host where clusters.none(count > 1)', open), ['R004 at clusters.none(count > 1)']);
	clean('ask Plan where not fits(host-b, plan)');
	clean('ask Host where not Plan.any(memory > 1 GiB) and clusters.all(count > 1) and Team.any(true)');
});

test('R004: an aggregate over an open relation', () => {
	// `Team.count() = 0` is `Team.none(true)` in other words: a set that is not known complete cannot be counted.
	assert.deepEqual(found('ask Host where Team.count() = 0'), ['R004 at Team.count()']);
	assert.deepEqual(found('ask Host where Team.count() < 1'), ['R004 at Team.count()']);
	assert.deepEqual(found('ask Host where ClusterSpec.sum(nodes) = 0'), ['R004 at ClusterSpec.sum(nodes)']);
	assert.deepEqual(found('ask Host where ClusterSpec.count(nodes > 1) = 0'), ['R004 at ClusterSpec.count(nodes > 1)']);
	assert.deepEqual(found('ask Host where (ClusterSpec where nodes > 1).count() = 0'), ['R004 at (ClusterSpec where nodes > 1).count()']);
	assert.deepEqual(found('ask Host where ClusterSpec.min(nodes) > 1'), ['R004 at ClusterSpec.min(nodes)']);
	assert.deepEqual(found('ask Host where ClusterSpec.max(nodes) > 1'), ['R004 at ClusterSpec.max(nodes)']);
	// A closed set counted by a condition that reads an open one: a member whose condition is not found is not counted.
	assert.deepEqual(found('ask Host where Plan.count(Team.any(true)) > 0'), ['R004 at Plan.count(Team.any(true))']);
	const open = schemaWith((s) => {
		s.rules!.fits.world = 'open';
		s.kinds.Host.slots.clusters.world = 'open';
	});
	assert.deepEqual(found('ask Host where clusters.count() = 0', open), ['R004 at clusters.count()']);
	assert.deepEqual(found('ask Plan where Host.count(fits(it, plan)) = 0', open), ['R004 at Host.count(fits(it, plan))']);
	// Reported once: the aggregate has said it, a `not` around it does not say it again.
	assert.deepEqual(found('ask Host where not Team.count() = 0'), ['R004 at Team.count()']);
	// Over closed relations (E04, E06, E32) nothing changes; a slot read through an open kind is one value, not a set.
	clean('ask Host where clusters.sum(count * spec.nodes) >= 6');
	clean('ask Host where clusters.count() > 2');
	clean('ask Plan where Plan.count() > 10');
	clean('ask Host where clusters.max(spec.nodes) > 1 and clusters.min(count) >= 1');
	clean('ask Plan where Host.count(fits(it, plan)) = 0');
});

test('R004: an inverse set is open when its forward slot, or the kind that carries it, is (publication §3.4)', () => {
	// `Host.clusters` is the relation `HostCluster.host` read the other way: the same rows, one world.
	const openClusters = schemaWith((s) => (s.kinds.HostCluster.world = 'open'));
	assert.deepEqual(found('ask Host where HostCluster.all(count > 1)', openClusters), ['R004 at HostCluster.all(count > 1)']);
	assert.deepEqual(found('ask Host where clusters.all(count > 1)', openClusters), ['R004 at clusters.all(count > 1)']);
	assert.deepEqual(found('ask Host where clusters.count() = 0', openClusters), ['R004 at clusters.count()']);
	// The world of the kind that owns the inverse slot says nothing of those rows.
	const openHosts = schemaWith((s) => (s.kinds.Host.world = 'open'));
	clean('ask Host where clusters.all(count > 1) and clusters.count() = 0', openHosts);
	assert.deepEqual(found('ask Host where clusters.all(count > 1)', schemaWith((s) => (s.kinds.HostCluster.slots.host.world = 'open'))), ['R004 at clusters.all(count > 1)']);
	assert.deepEqual(found('ask Host where clusters.all(count > 1)', schemaWith((s) => (s.kinds.Host.slots.clusters.world = 'open'))), ['R004 at clusters.all(count > 1)']);
	// A `closed` written on either slot does not close it: an element nobody listed may point here. A writer
	// gives a slot its world exactly where it differs from its kind's, so the first is the shape a pack has.
	const questions = ['clusters.count() = 0', 'clusters.all(count > 1)', 'clusters.none(count > 1)', 'not clusters.any(count > 1)'];
	const closedWritten: ((s: Schema) => void)[] = [
		(s) => ((s.kinds.HostCluster.world = 'open'), (s.kinds.HostCluster.slots.host.world = 'closed')),
		(s) => ((s.kinds.HostCluster.world = 'open'), (s.kinds.Host.slots.clusters.world = 'closed')),
		(s) => ((s.kinds.HostCluster.slots.host.world = 'open'), (s.kinds.Host.slots.clusters.world = 'closed'))
	];
	for (const change of closedWritten) for (const q of questions) assert.deepEqual(found(`ask Host where ${q}`, schemaWith(change)).map((d) => d.slice(0, 4)), ['R004'], q);
	clean('ask Host where not owner = team-platform');
});

test('what passed unexamined: the mode of `round`, a date beside a truth value, the branches of `when`, `in` without a set', () => {
	// R030: the second argument of `round` is one of the four roundings by its bare name, and nothing else.
	assert.deepEqual(found('ask Plan where round(monthly_price, nonsense_name) > € 1'), ['R030 at nonsense_name']);
	assert.deepEqual(found('ask Plan where round(monthly_price, not Team.any(true)) > € 1'), ['R030 at not Team.any(true)']);
	assert.deepEqual(found('ask Plan where round(monthly_price, plan.memory) > € 1'), ['R030 at plan.memory']);
	for (const mode of ['half_even', 'half_up', 'down', 'up']) clean(`ask Plan where round(monthly_price, ${mode}) > € 1`);
	clean('ask Plan where round(hourly_price * 730 h) > € 500');
	// A date takes a time/calendar duration or a date beside it; a date moved by a duration is a date, so no condition.
	assert.deepEqual(found('ask Host where 2026-11-01 + true'), ['R003 at 2026-11-01 + true']);
	assert.deepEqual(found('ask Host where 2026-11-01 * 2 > 2026-11-01'), ['R003 at 2026-11-01 * 2']);
	assert.deepEqual(found('ask Host where 2026-11-01 + 3 > 2026-11-02'), ['R003 at 2026-11-01 + 3']);
	assert.deepEqual(found('ask Host where 2026-11-01 + 5 GiB > 2026-11-02'), ['R003 at 2026-11-01 + 5 GiB']);
	assert.deepEqual(found('ask Host where 2026-11-01 + 24 h'), ['R017 at 2026-11-01 + 24 h']);
	clean('ask Host where 2026-11-01 + 24 h > 2026-11-02');
	clean('ask Host where 2026-12-01 - 2026-11-01 > 3');
	// Both branches of `when` are one value, or both a set.
	assert.deepEqual(found('ask Host where (when true then clusters else HostCluster:`x2`).count() > 0'), ['R005 at when true then clusters else HostCluster:`x2`']);
	clean('ask Host where (when owner is known then clusters else HostCluster where count > 1).count() > 0');
	clean('ask Host where when owner is known then memory_need > 400 GiB else unknown no_rule');
	// The right side of `in` is a set or a range.
	assert.deepEqual(found('ask Host where 1 in 2'), ['R003 at 1 in 2']);
	assert.deepEqual(found('ask Host where provider in provider'), ['R003 at provider in provider']);
	assert.deepEqual(found('ask Host where memory_need in 3 GiB'), ['R003 at memory_need in 3 GiB']);
	clean('ask Host where memory_need in 1 GiB..3 GiB and owner in Team and provider in Plan.provider');
	clean('ask Host where not owner = team-platform');
});

test('R005: a set where one value is needed', () => {
	assert.deepEqual(found('ask Host where clusters.count() > 1 show clusters'), ['R005 at clusters']);
	assert.deepEqual(found('ask Host where clusters.spec.nodes + 1 > 2'), ['R005 at clusters.spec.nodes + 1']);
	assert.deepEqual(found('ask Plan where fits(Host, plan)'), ['R005 at Host']);
	assert.deepEqual(found('ask Host where clusters'), ['R005 at clusters']);
	clean('ask Host where host in Host and clusters.spec.nodes.max() > 2 show clusters.count()');
	clean('ask Host where (Plan where memory >= host.memory_need).count() > 0');
});

test('suppose assignments: states stand for a many-valued slot; non-state cardinality mismatches report R005; Integer keys are canonical', () => {
	const keyed = schemaWith((s) => {
		s.types!.TicketNo = { of: 'Integer' };
		s.kinds.Ticket = {
			world: 'closed',
			id: { type: 'Integer' },
			slots: {
				title: { type: 'Text', card: '1', states: ['known'] },
				tags: { type: 'Text', card: '*', states: ['known', 'unknown'] },
			},
		};
		s.kinds.AliasTicket = {
			world: 'closed',
			id: { type: 'TicketNo' },
			slots: {},
		};
	});
	// A state stands for the whole set on a many-valued slot in both `set` and `insert_row`.
	clean('+ t-1.tags = unknown not_collected', keyed);
	clean('+ Ticket 7 {title = "open", tags = unknown not_collected}', keyed);
	// Non-state single-vs-set mismatches report R005 in both `set` and `insert_row`.
	assert.deepEqual(found('+ t-1.tags = "single"', keyed), ['R005 at "single"']);
	assert.deepEqual(found('+ Ticket 7 {title = "open", tags = "single"}', keyed), ['R005 at "single"']);
	assert.deepEqual(found('+ t-1.title = Ticket.title', keyed), ['R005 at Ticket.title']);
	assert.deepEqual(found('+ Ticket 7 {title = Ticket.title}', keyed), ['R005 at Ticket.title']);
	// Integer keys must be in canonical decimal form: leading zeros are refused with R012.
	clean('+ Ticket 0 {title = "zero"}', keyed);
	clean('+ Ticket 7 {title = "seven"}', keyed);
	clean('+ AliasTicket 42 {}', keyed);
	assert.deepEqual(found('+ Ticket 007 {title = "padded"}', keyed), ['R012 at 007']);
	assert.deepEqual(found('+ Ticket 00 {title = "zeros"}', keyed), ['R012 at 00']);
	assert.deepEqual(found('+ AliasTicket 007 {}', keyed), ['R012 at 007']);
});

test('R011: nothing shadows silently (§5 rules 2 and 7)', () => {
	assert.deepEqual(found('ask Host where Host.any(memory_need > 450 GiB)'), ['R011 at memory_need']);
	assert.deepEqual(found('ask Host where clusters.any(host = host-a)'), ['R011 at host']);
	assert.deepEqual(found('ask host: HostCluster where host = host-a'), ['R011 at host']);
	clean('ask Host where clusters.any(it.host = host-a)');
	clean('ask hc: HostCluster where host = host-a and hc.count > 1');
	clean('ask Host where Host.any(it.memory_need > host.memory_need)');
});

test('explicit method binders shadow slots cleanly, while forbidding `it` and schema parameter collisions', () => {
	// Explicit method binder colliding with a slot on its own element kind (`HostCluster.host`) or an outer kind (`Host.owner`).
	clean('ask h: Host where clusters.any(host: host.count > 1)');
	clean('ask h: Host where clusters.any(owner: owner.count > 1)');
	// `it` is forbidden as an explicit method binder (no bogus `R001` with `hint.row: ['it']`).
	assert.deepEqual(found('ask h: Host where clusters.any(it: it.count > 1)'), ['R011 at it']);
	assert.deepEqual(found('ask h: Host where clusters.any(it: true)'), ['R011 at it']);
	assert.deepEqual(found('ask h: Host where clusters.where(it: it.count > 1).count() > 0'), ['R011 at it']);
	// Collisions with `schema.params` (`host_reserve`) are refused at the binder.
	assert.deepEqual(found('ask h: Host where clusters.any(host_reserve: count > 1)'), ['R011 at host_reserve']);
});

test('R012 and R013: a literal token is read by the type its context expects', () => {
	const typed = schemaWith((s) => {
		s.types!.IPv4 = { of: 'Text', pattern: '[0-9]{1,3}(\\.[0-9]{1,3}){3}' };
		s.kinds.Host.slots.address = { type: 'IPv4', card: '1', states: ['known'] };
	});
	clean('ask Host where address = 10.12.0.1', typed);
	clean('ask Host where address = IPv4"10.12.0.1"', typed);
	assert.deepEqual(found('ask Host where address = 10.12.0', typed), ['R012 at 10.12.0']);
	assert.deepEqual(found('ask Host where address = IPv4"10.12"', typed), ['R012 at IPv4"10.12"']);
	assert.deepEqual(found('ask Host where memory_need = 10.12.0.1', typed), ['R013 at 10.12.0.1']);
	assert.deepEqual(found('ask Host where 10.12.0.1 is known', typed), ['R013 at 10.12.0.1']);
});

test('R017: a condition is a truth value', () => {
	assert.deepEqual(found('ask Host where memory_need and owner is known'), ['R017 at memory_need']);
	assert.deepEqual(found('ask Host where clusters.any(count)'), ['R017 at count']);
	assert.deepEqual(found('ask Host where (Plan where memory).count() > 1'), ['R017 at memory']);
	assert.deepEqual(found('ask Host where when owner then true else false'), ['R017 at owner']);
	assert.deepEqual(found('ask Host where foo'), ['R001 at foo']);
});

test('W105: a shown value that can be unknown on a row of the answer (§13 point 9)', () => {
	const warned = (text: string) => check(text, fixture).diagnostics.filter((d) => d.code === 'W105').map((d) => d.span.text);
	assert.deepEqual(warned('ask Host where memory_need > 1 GiB show owner, memory_need, host'), ['owner']);
	assert.deepEqual(warned('ask Host where owner is known and memory_need > 1 GiB show owner, memory_need'), []);
	assert.deepEqual(warned('ask Host where owner is known or memory_need > 1 GiB show owner, memory_need'), ['owner', 'memory_need']);
	assert.deepEqual(warned('ask Host where not memory_need > 1 GiB show memory_need'), []);
	assert.deepEqual(warned('ask Host where owner is unknown show owner'), ['owner']);
	assert.deepEqual(warned('ask Host where owner is known => memory_need > 1 GiB show memory_need'), ['memory_need']);
	assert.deepEqual(warned('ask Host where true show owner is known, clusters.count(), memory_need + host_reserve'), ['memory_need + host_reserve']);
	assert.deepEqual(warned('ask Host where memory_need + host_reserve > 1 GiB show memory_need + host_reserve'), []);
	// A shown amount that divides, or multiplies by anything but a whole number, may be one its type cannot
	// hold: it is shown as `unknown not_exact` (§8a). `round` takes the warning away; a plain number is a ratio.
	const amounts = 'ask Plan where memory > 1 GiB and monthly_price > € 1 and hourly_price > € 0.01/h show ';
	assert.deepEqual(warned(`${amounts}memory / 3, monthly_price * 0.5, monthly_price * 12 %, hourly_price * 730 h, (memory + 1 GiB) / 2`), ['memory / 3', 'monthly_price * 0.5', 'monthly_price * 12 %', 'hourly_price * 730 h', '(memory + 1 GiB) / 2']);
	assert.deepEqual(warned(`${amounts}memory, memory * 2, memory + 1 GiB, 3 * monthly_price, round(monthly_price / 3, half_even), Plan.count() * memory`), []);
	assert.deepEqual(warned('ask Host where true show clusters.count() / 3'), []);
	// Every shown amount but a stored value and a rounded one lists the state, so the dataset is one of its schema.
	const sure = schemaWith((s) => (s.kinds.Plan.slots.monthly_price.states = ['known']));
	const states = (text: string) => check(text, sure).answer!.shown.map((s) => s.typed.states.has('unknown'));
	assert.deepEqual(states('ask Plan where true show monthly_price * 2, round(monthly_price / 3, half_even), monthly_price, Plan.count() / 3'), [true, false, false, false]);
	// A warning leaves the question valid: it has an answer.
	const checked = check('ask Host where true show owner', fixture);
	assert.equal(checked.diagnostics.some(isError), false);
	assert.ok(checked.answer);
});

test('the default show: every single value the condition reads, in source order (§8)', () => {
	const shown = (text: string) => check(text, fixture).answer!.shown.map((s) => s.text);
	assert.deepEqual(shown('ask Host where owner = team-platform or memory_need > 300 GiB'), ['owner', 'memory_need']);
	assert.deepEqual(shown('ask h: Host where h.memory_need > 1 GiB and clusters.count() > 2 and memory_need < 9 GiB'), ['h.memory_need', 'clusters.count()', 'memory_need']);
	assert.deepEqual(shown('ask Host where clusters.any(count > 1) and provider = cherry'), ['clusters.any(count > 1)', 'provider']);
	assert.deepEqual(shown('ask Plan where fits(host-b, plan)'), []);
	assert.deepEqual(shown('ask Host where memory_need > 1 GiB show host'), ['host']);
});

test('the output schema is a publication schema document (§8a)', async () => {
	const text = 'ask h: Host where memory_need > 300 GiB show h.memory_need, owner, clusters.count(), owner is known';
	const checked = check(text, fixture);
	const doc = (await outputSchema(checked.tree as Ask, checked, fixture))!;
	assert.deepEqual(doc.imports, { p: { pack: 'fixture', schema: await schemaId(dataSchema(fixture)) } });
	assert.match(doc.base, /^https:\/\/rezono\.example\/fixture\/ask\/[0-9a-f]{64}\/$/);
	assert.deepEqual(doc.kinds.Answer, {
		world: 'closed',
		id: { type: 'Text' },
		slots: {
			binder: { ref: 'p.Host', card: '1', states: ['known'], expr: 'h' },
			c1: { type: 'p.GiB', card: '1', states: ['known', 'unknown', 'invalid'], expr: 'h.memory_need' },
			c2: { ref: 'p.Team', card: '?', states: ['known', 'not_applicable', 'unknown'], expr: 'owner' },
			c3: { type: 'Ratio', card: '1', states: ['known'], expr: 'clusters.count()' },
			c4: { type: 'Bool', card: '1', states: ['known'], expr: 'owner is known' }
		}
	});
	assert.deepEqual(Object.keys(doc.kinds.Undecided.slots), ['binder', 'state', 'reason', 'cause_relation', 'cause_key']);
	// What a question needs beyond the publication is no part of the pack's schema document, so not of its id.
	assert.deepEqual(Object.keys(dataSchema(fixture) as object).sort(), ['base', 'kinds', 'pack', 'rezono', 'types']);
	// A computed value has the pack's type of its dimension; the same question gives the same document.
	const priced = check('ask Plan where true show hourly_price * 730 h, memory / 2', fixture);
	const again = (await outputSchema(priced.tree as Ask, priced, fixture))!;
	assert.equal(again.kinds.Answer.slots.c1.type, 'p.Eur');
	assert.equal(again.kinds.Answer.slots.c2.type, 'p.GiB');
	// The id of the fixture's document is the one rezono_publication computes for it (`l0.check_schema`, 11-11-2026).
	assert.equal(await schemaId(dataSchema(fixture)), 's-97acfa0f1e65866b9a32532da7f1328f6886f9541e707c215d40db58b7efa756');
	// A dimension the pack has no type for gets a type of its own, in the storage units of its parts.
	const novel = check('ask Plan where true show memory * 730 h', fixture);
	const own = (await outputSchema(novel.tree as Ask, novel, fixture))!;
	assert.equal(own.kinds.Answer.slots.c1.type, 'Q1');
	assert.deepEqual(own.types.Q1, { of: 'Quantity', dimension: 'data·time', unit: 'B·s', storage_unit: 'B·s', factor: '1' });
	assert.equal(await schemaId(again), await schemaId((await outputSchema(priced.tree as Ask, check('ask Plan where true show hourly_price * 730 h, memory / 2', fixture), fixture))!));
	// No output schema for a question with an error, or for a suppose line.
	const wrong = check('ask Host where memory_ned > 1 GiB', fixture);
	assert.equal(await outputSchema(wrong.tree as Ask, wrong, fixture), undefined);
});

test('a reserved construct is not looked into (§1), and diagnostics come in source order', () => {
	assert.deepEqual(found('ask Host at nonsense where memory_need > 1 GiB order by nonsense'), ['R015 at at nonsense', 'R015 at order by nonsense']);
	assert.deepEqual(found('ask Host where memory_ned > 1 GiB and owner as known nonsense = team-platform show clusters'), ['R001 at memory_ned (memory_need)', 'R015 at as known nonsense', 'R005 at clusters']);
	const hint = (d: Diagnostic) => d.hint && `${d.hint.id}: ${d.hint.args.join(' ')}`;
	assert.deepEqual(check('ask h: Host where memory_need > 384 GiB as known 2026-10-26', fixture).diagnostics.map(hint), ['hint.question_as_known: ask h: Host as known 2026-10-26 where …']);
	assert.deepEqual(check('ask Host where memory_need at 2026-11-01 > 384 GiB', fixture).diagnostics.map(hint), [undefined]);
});

test('every code the check reports has its sentence in both languages', () => {
	const [en, nl] = ['en', 'nl'].map((language) => read(`../messages/${language}.json`) as Record<string, string>);
	assert.deepEqual(Object.keys(nl), Object.keys(en));
	for (const id of ['R001', 'R002', 'R003', 'R004', 'R005', 'R011', 'R012', 'R013', 'R017', 'R030', 'W105', 'hint.row', 'hint.question_at', 'hint.question_as_known', 'suggest']) {
		assert.ok(en[id], id);
		assert.ok(nl[id], id);
	}
});
