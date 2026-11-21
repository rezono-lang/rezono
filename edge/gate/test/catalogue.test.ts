import assert from 'node:assert/strict';
import { test } from 'node:test';
import type { Bundle } from '../../../contracts/typescript/generated/bundle.ts';
import { roleBundle, roleCatalogue } from '../src/catalogue.ts';

function messageIds(resources: { lang: string; resource: string }[]): string[] {
	const ids: string[] = [];
	for (const entry of resources) {
		const body = entry.resource.split('\n---\n', 2)[1] ?? entry.resource;
		for (const line of body.split('\n')) {
			const match = /^([A-Za-z0-9_.-]+)\s*=/.exec(line);
			if (match) ids.push(match[1]);
		}
	}
	return ids.sort();
}

test('roleBundle allow-lists reason.* messages to readable rules without leaking hidden identifiers', () => {
	const bundle = {
		pack: { id: 'sample', base: 'https://example.org/sample/' },
		kinds: [
			{ id: 'alpha', class: 'Alpha', world: 'closed' },
			{ id: 'beta', class: 'Beta', world: 'closed' },
			{ id: 'gamma', class: 'Gamma', world: 'closed' },
			{ id: 'hidden_kind', class: 'HiddenKind', world: 'closed' }
		],
		attributes: [],
		arrows: [],
		enums: [],
		relations: [
			{
				id: 'missing_alpha_detail',
				world: 'closed',
				columns: [{ name: 'alpha', type: 'string' }]
			},
			{
				id: 'alpha_status',
				world: 'closed',
				outcome: 'alpha',
				columns: [
					{ name: 'alpha', type: 'string' },
					{ name: 'state', type: 'string' },
					{ name: 'reason', type: 'string' }
				]
			},
			{
				id: 'hidden_flag',
				world: 'closed',
				columns: [{ name: 'beta', type: 'string' }]
			},
			{
				id: 'beta_status',
				world: 'closed',
				outcome: 'beta',
				columns: [
					{ name: 'beta', type: 'string' },
					{ name: 'state', type: 'string' },
					{ name: 'reason', type: 'string' }
				]
			},
			// Non-outcome derived rule relation carrying an explicit `reason` column (e.g. a lowered table).
			{
				id: 'gamma_review',
				world: 'closed',
				columns: [
					{ name: 'subject', type: 'string' },
					{ name: 'value', type: 'string' },
					{ name: 'state', type: 'string' },
					{ name: 'reason', type: 'string' }
				]
			},
			// Outcome relation whose 3rd column is not named `reason`; outcome fallback applies only when `outcome` kind is visible.
			{
				id: 'opaque_outcome',
				world: 'closed',
				outcome: 'hidden_kind',
				columns: [
					{ name: 'subject', type: 'string' },
					{ name: 'state', type: 'string' },
					{ name: 'code', type: 'string' }
				]
			}
		],
		rules: [
			{
				id: 'alpha_status_1',
				relation: 'alpha_status',
				message: 'rule.alpha_status_1',
				head: {
					relation: 'alpha_status',
					terms: [
						{ kind: 'variable', value: '?a', type: 'string' },
						{ kind: 'constant', value: 'unknown', type: 'string' },
						{ kind: 'constant', value: 'missing_detail', type: 'string' }
					]
				},
				body: [{ kind: 'atom', position: 1, polarity: 'positive', relation: 'missing_alpha_detail', terms: [] }]
			},
			{
				id: 'alpha_status_2',
				relation: 'alpha_status',
				message: 'rule.alpha_status_2',
				head: {
					relation: 'alpha_status',
					terms: [
						{ kind: 'variable', value: '?a', type: 'string' },
						{ kind: 'constant', value: 'known', type: 'string' },
						{ kind: 'constant', value: '', type: 'string' }
					]
				},
				body: [{ kind: 'atom', position: 1, polarity: 'positive', relation: 'alpha', terms: [] }]
			},
			{
				id: 'beta_status_1',
				relation: 'beta_status',
				message: 'rule.beta_status_1',
				head: {
					relation: 'beta_status',
					terms: [
						{ kind: 'variable', value: '?b', type: 'string' },
						{ kind: 'constant', value: 'unknown', type: 'string' },
						{ kind: 'constant', value: 'unverified_entry', type: 'string' }
					]
				},
				body: [{ kind: 'atom', position: 1, polarity: 'positive', relation: 'beta', terms: [] }]
			},
			{
				id: 'beta_status_2',
				relation: 'beta_status',
				message: 'rule.beta_status_2',
				head: {
					relation: 'beta_status',
					terms: [
						{ kind: 'variable', value: '?b', type: 'string' },
						{ kind: 'constant', value: 'unknown', type: 'string' },
						{ kind: 'constant', value: 'hidden_flag', type: 'string' }
					]
				},
				body: [{ kind: 'atom', position: 1, polarity: 'positive', relation: 'hidden_flag', terms: [] }]
			},
			{
				id: 'beta_status_3',
				relation: 'beta_status',
				message: 'rule.beta_status_3',
				head: {
					relation: 'beta_status',
					terms: [
						{ kind: 'variable', value: '?b', type: 'string' },
						{ kind: 'constant', value: 'unknown', type: 'string' },
						{ kind: 'constant', value: 'hidden_kind', type: 'string' }
					]
				},
				body: [{ kind: 'atom', position: 1, polarity: 'positive', relation: 'beta', terms: [] }]
			},
			{
				id: 'gamma_review_unknown',
				relation: 'gamma_review',
				message: 'rule.gamma_review_unknown',
				head: {
					relation: 'gamma_review',
					terms: [
						{ kind: 'variable', value: '?g', type: 'string' },
						{ kind: 'constant', value: '', type: 'string' },
						{ kind: 'constant', value: 'unknown', type: 'string' },
						{ kind: 'constant', value: 'review_not_ready', type: 'string' }
					]
				},
				body: [{ kind: 'atom', position: 1, polarity: 'positive', relation: 'gamma', terms: [] }]
			},
			{
				id: 'opaque_outcome_1',
				relation: 'opaque_outcome',
				message: 'rule.opaque_outcome_1',
				head: {
					relation: 'opaque_outcome',
					terms: [
						{ kind: 'variable', value: '?a', type: 'string' },
						{ kind: 'constant', value: 'unknown', type: 'string' },
						{ kind: 'constant', value: 'opaque_outcome_code', type: 'string' }
					]
				},
				body: [{ kind: 'atom', position: 1, polarity: 'positive', relation: 'alpha', terms: [] }]
			}
		],
		reasons: [
			{ code: 'missing_detail', iri: 'https://example.org/sample/reason/missing_detail' },
			{ code: 'unverified_entry', iri: 'https://example.org/sample/reason/unverified_entry' },
			{ code: 'hidden_flag', iri: 'https://example.org/sample/reason/hidden_flag' },
			{ code: 'hidden_kind', iri: 'https://example.org/sample/reason/hidden_kind' },
			{ code: 'review_not_ready', iri: 'https://example.org/sample/reason/review_not_ready' },
			{ code: 'opaque_outcome_code', iri: 'https://example.org/sample/reason/opaque_outcome_code' },
			{ code: 'orphan_code', iri: 'https://example.org/sample/reason/orphan_code' }
		],
		labels: [],
		messages: [{
			lang: 'en',
			resource: [
				'@locale en',
				'---',
				'attribute.partial = {{Each {$kind} may have {$attribute}.}}',
				'rule.alpha_status_1 = {{Alpha {$a} is missing a detail.}}',
				'rule.alpha_status_2 = {{Alpha {$a} is known.}}',
				'rule.beta_status_1 = {{Beta {$b} is unverified.}}',
				'rule.beta_status_2 = {{Beta {$b} has a hidden flag.}}',
				'rule.beta_status_3 = {{Beta {$b} collides with hidden kind.}}',
				'rule.gamma_review_unknown = {{Gamma {$g} review is unknown.}}',
				'rule.opaque_outcome_1 = {{Opaque outcome {$a} is unknown.}}',
				'reason.missing_detail = {{Detail for {$alpha} has not arrived.}}',
				'reason.unverified_entry = {{Entry for {$beta} is unverified.}}',
				'reason.hidden_flag = {{Flag for {$beta} is active.}}',
				'reason.hidden_kind = {{Colliding reason for {$beta}.}}',
				'reason.review_not_ready = {{Review for {$gamma} is not ready.}}',
				'reason.opaque_outcome_code = {{Outcome for {$hidden_kind} is pending.}}',
				'reason.orphan_code = {{Unowned reason for {$secret}.}}',
				'reason.unlisted_leak = {{Undeclared reason for {$secret}.}}',
				'reason = {{Bare reason key.}}'
			].join('\n') + '\n'
		}],
		channels: {}
	} as unknown as Bundle;

	// Restricted role reading only `alpha` gets zero `reason.*` messages.
	const alphaOnly = roleBundle(bundle, [{ relation: 'alpha', complete: true, full: true }]);
	const alphaOnlyIds = messageIds(alphaOnly.messages);
	assert.deepEqual(alphaOnlyIds.filter((id) => id === 'reason' || id.startsWith('reason.')), []);
	assert.ok(alphaOnlyIds.includes('attribute.partial'));
	assert.ok(!JSON.stringify(alphaOnly).includes('unverified_entry'));
	assert.ok(!JSON.stringify(alphaOnly).includes('orphan_code'));
	assert.ok(!JSON.stringify(alphaOnly).includes('unlisted_leak'));

	// Role reading `alpha` and `alpha_status` WITHOUT helper `missing_alpha_detail` must NOT get `reason.missing_detail`.
	const alphaOutcomeHiddenHelper = roleBundle(bundle, [
		{ relation: 'alpha', complete: true, full: true },
		{ relation: 'alpha_status', complete: true, full: true }
	]);
	assert.deepEqual(
		messageIds(alphaOutcomeHiddenHelper.messages).filter((id) => id === 'reason' || id.startsWith('reason.')),
		[]
	);
	assert.ok(!JSON.stringify(alphaOutcomeHiddenHelper).includes('missing_detail'));
	assert.ok(!JSON.stringify(alphaOutcomeHiddenHelper).includes('missing_alpha_detail'));

	// Role reading `alpha`, `alpha_status`, AND helper `missing_alpha_detail` DOES get `reason.missing_detail`.
	const alphaOutcomeReadable = roleBundle(bundle, [
		{ relation: 'alpha', complete: true, full: true },
		{ relation: 'alpha_status', complete: true, full: true },
		{ relation: 'missing_alpha_detail', complete: true, full: true }
	]);
	assert.deepEqual(
		messageIds(alphaOutcomeReadable.messages).filter((id) => id === 'reason' || id.startsWith('reason.')),
		['reason.missing_detail']
	);

	// Role reading `beta` and `beta_status` WITHOUT `hidden_flag` or `hidden_kind` gets ONLY `reason.unverified_entry`:
	// - unreadable rule `beta_status_2` (over hidden `hidden_flag`) does NOT leak `reason.hidden_flag`;
	// - readable rule `beta_status_3` whose reason collides with hidden kind `hidden_kind` is still blocked by the hidden-segment guard.
	const betaOutcome = roleBundle(bundle, [
		{ relation: 'beta', complete: true, full: true },
		{ relation: 'beta_status', complete: true, full: true }
	]);
	assert.deepEqual(
		messageIds(betaOutcome.messages).filter((id) => id === 'reason' || id.startsWith('reason.')),
		['reason.unverified_entry']
	);
	assert.ok(!JSON.stringify(betaOutcome).includes('hidden_flag'));
	assert.ok(!JSON.stringify(betaOutcome.messages).includes('reason.hidden_kind'));

	// Role reading `beta`, `beta_status`, AND `hidden_flag` gets both `reason.hidden_flag` and `reason.unverified_entry`.
	const betaOutcomeWithHelper = roleBundle(bundle, [
		{ relation: 'beta', complete: true, full: true },
		{ relation: 'beta_status', complete: true, full: true },
		{ relation: 'hidden_flag', complete: true, full: true }
	]);
	assert.deepEqual(
		messageIds(betaOutcomeWithHelper.messages).filter((id) => id === 'reason' || id.startsWith('reason.')),
		['reason.hidden_flag', 'reason.unverified_entry']
	);

	// Non-outcome derived rule relation with a `reason` column gets its readable rule's reason code and nothing else.
	const gammaReview = roleBundle(bundle, [
		{ relation: 'gamma', complete: true, full: true },
		{ relation: 'gamma_review', complete: true, full: true }
	]);
	assert.deepEqual(
		messageIds(gammaReview.messages).filter((id) => id === 'reason' || id.startsWith('reason.')),
		['reason.review_not_ready']
	);

	// Outcome relation without a column named `reason` whose `outcome` kind (`hidden_kind`) is NOT visible
	// must NOT fall back to index 2 using the raw bundle's hidden `outcome` kind.
	const hiddenOutcomeKind = roleBundle(bundle, [
		{ relation: 'alpha', complete: true, full: true },
		{ relation: 'opaque_outcome', complete: true, full: true }
	]);
	assert.deepEqual(
		messageIds(hiddenOutcomeKind.messages).filter((id) => id === 'reason' || id.startsWith('reason.')),
		[]
	);
	assert.ok(!JSON.stringify(hiddenOutcomeKind.messages).includes('opaque_outcome_code'));
	assert.ok(!JSON.stringify(hiddenOutcomeKind).includes('hidden_kind'));
});

test('roleCatalogue scopes semantic.enum and semantic.derived and keeps catalogue.enums consistent', () => {
	const bundle = {
		pack: { id: 'sample', base: 'https://example.org/sample/' },
		kinds: [
			{ id: 'item', class: 'Item', world: 'closed' },
			{ id: 'secret_kind', class: 'SecretKind', world: 'closed' }
		],
		attributes: [
			{
				id: 'item.grade', kind: 'item', name: 'grade', table: 'item__grade',
				type: 'enum', schema_type: 'VisibleTier', enum: 'visible_tier',
				required: false, multivalued: false, world: 'closed',
				semantic: { case: 'enum', base: 'string', range: 'VisibleTier', enum: 'visible_tier' }
			},
			{
				id: 'secret_kind.level', kind: 'secret_kind', name: 'level', table: 'secret_kind__level',
				type: 'enum', schema_type: 'HiddenTier', enum: 'hidden_tier',
				required: false, multivalued: false, world: 'closed',
				semantic: { case: 'enum', base: 'string', range: 'HiddenTier', enum: 'hidden_tier' }
			}
		],
		arrows: [],
		enums: [
			{ id: 'visible_tier', values: ['visible_tier.high', 'visible_tier.low'] },
			{ id: 'rel_only_tier', values: ['rel_only_tier.gold', 'rel_only_tier.silver'] },
			{ id: 'hidden_tier', values: ['hidden_tier.priv'] }
		],
		relations: [
			{
				id: 'item_summary',
				world: 'closed',
				columns: [
					{
						name: 'tier',
						type: 'string',
						semantic: { case: 'enum', base: 'string', range: 'RelOnlyTier', enum: 'rel_only_tier' }
					},
					{
						name: 'undeclared_col',
						type: 'string',
						semantic: { case: 'enum', base: 'string', range: 'GhostTier', enum: 'ghost_tier' }
					},
					{
						name: 'hidden_derived_col',
						type: 'string',
						semantic: { case: 'derived', base: 'number', unit: 'points', derived: 'secret_calc' }
					},
					{
						name: 'visible_derived_col',
						type: 'string',
						semantic: { case: 'derived', base: 'number', unit: 'points', derived: 'public_calc' }
					},
					{
						name: 'hidden_rel_derived_col',
						type: 'string',
						semantic: { case: 'derived', base: 'string', derived: 'secret_rel' }
					},
					{
						name: 'visible_rel_derived_col',
						type: 'string',
						semantic: { case: 'derived', base: 'string', derived: 'item_summary' }
					},
					{
						name: 'bad_combo',
						type: 'string',
						semantic: { case: 'enum', base: 'string', enum: 'hidden_tier', target: 'secret_kind' }
					}
				]
			},
			{
				id: 'relation_with_hidden_derived',
				world: 'closed',
				semantic: { case: 'derived', base: 'number', unit: 'points', derived: 'secret_calc' },
				columns: [{ name: 'subject', type: 'string' }]
			},
			{
				id: 'calc__public_calc',
				world: 'closed',
				calc: 'public_calc',
				semantic: { case: 'derived', base: 'number', unit: 'points', derived: 'public_calc' },
				columns: [
					{ name: 'subject', type: 'string' },
					{ name: 'value', type: 'string' },
					{ name: 'state', type: 'string' },
					{ name: 'reason', type: 'string' }
				]
			},
			{
				id: 'calc__secret_calc',
				world: 'closed',
				calc: 'secret_calc',
				semantic: { case: 'derived', base: 'number', unit: 'points', derived: 'secret_calc' },
				columns: [
					{ name: 'subject', type: 'string' },
					{ name: 'value', type: 'string' },
					{ name: 'state', type: 'string' },
					{ name: 'reason', type: 'string' }
				]
			},
			{
				id: 'secret_rel',
				world: 'closed',
				columns: [
					{
						name: 'tier',
						type: 'string',
						semantic: { case: 'enum', base: 'string', range: 'HiddenTier', enum: 'hidden_tier' }
					}
				]
			}
		],
		labels: [
			{ element: 'item', lang: 'en', text: 'Item' },
			{ element: 'visible_tier', lang: 'en', text: 'Visible tier' },
			{ element: 'visible_tier.high', lang: 'en', text: 'High' },
			{ element: 'visible_tier.low', lang: 'en', text: 'Low' },
			{ element: 'rel_only_tier', lang: 'en', text: 'Relation tier' },
			{ element: 'rel_only_tier.gold', lang: 'en', text: 'Gold' },
			{ element: 'rel_only_tier.silver', lang: 'en', text: 'Silver' },
			{ element: 'hidden_tier', lang: 'en', text: 'Hidden tier' },
			{ element: 'hidden_tier.priv', lang: 'en', text: 'Private' }
		],
		messages: [{ lang: 'en', resource: '@locale en\n---\n' }],
		channels: {}
	} as unknown as Bundle;

	const snapshots = [
		{ relation: 'item', complete: true, full: true },
		{ relation: 'item__grade', complete: true, full: true },
		{ relation: 'item_summary', complete: true, full: true },
		{ relation: 'relation_with_hidden_derived', complete: true, full: true },
		{ relation: 'calc__public_calc', complete: true, full: true }
	];

	const catalogue = roleCatalogue(bundle, snapshots);
	const enumIds = new Set(catalogue.enums.map((entry) => entry.id));
	assert.deepEqual([...enumIds].sort(), ['rel_only_tier', 'visible_tier']);

	const summary = catalogue.relations.find((rel) => rel.id === 'item_summary');
	assert.ok(summary);
	const colByName = new Map(summary.columns.map((col) => [col.name, col]));
	assert.deepEqual(colByName.get('tier')?.semantic, {
		case: 'enum', base: 'string', range: 'RelOnlyTier', enum: 'rel_only_tier'
	});
	assert.equal(colByName.get('undeclared_col')?.semantic, undefined);
	assert.equal(colByName.get('hidden_derived_col')?.semantic, undefined);
	assert.deepEqual(colByName.get('visible_derived_col')?.semantic, {
		case: 'derived', base: 'number', unit: 'points', derived: 'public_calc'
	});
	assert.equal(colByName.get('hidden_rel_derived_col')?.semantic, undefined);
	assert.deepEqual(colByName.get('visible_rel_derived_col')?.semantic, {
		case: 'derived', base: 'string', derived: 'item_summary'
	});
	assert.equal(colByName.get('bad_combo')?.semantic, undefined);

	const relHiddenDerived = catalogue.relations.find((rel) => rel.id === 'relation_with_hidden_derived');
	assert.ok(relHiddenDerived);
	assert.equal(relHiddenDerived.semantic, undefined);

	const publicCalc = catalogue.relations.find((rel) => rel.id === 'calc__public_calc');
	assert.deepEqual(publicCalc?.semantic, {
		case: 'derived', base: 'number', unit: 'points', derived: 'public_calc'
	});

	// Every visible semantic.enum must exist in catalogue.enums.
	for (const slot of [...catalogue.attributes, ...catalogue.arrows]) {
		if (slot.semantic?.enum !== undefined) assert.ok(enumIds.has(slot.semantic.enum));
	}
	for (const rel of catalogue.relations) {
		if (rel.semantic?.enum !== undefined) assert.ok(enumIds.has(rel.semantic.enum));
		for (const col of rel.columns) {
			if (col.semantic?.enum !== undefined) assert.ok(enumIds.has(col.semantic.enum));
		}
	}

	// roleBundle retains labels for visible enums and their values, and omits hidden enum labels.
	const scopedBundle = roleBundle(bundle, snapshots);
	const labelElements = new Set(scopedBundle.labels.map((label) => label.element));
	for (const expected of [
		'item', 'visible_tier', 'visible_tier.high', 'visible_tier.low',
		'rel_only_tier', 'rel_only_tier.gold', 'rel_only_tier.silver'
	]) {
		assert.ok(labelElements.has(expected), `expected label for ${expected}`);
	}
	assert.ok(!labelElements.has('hidden_tier'));
	assert.ok(!labelElements.has('hidden_tier.priv'));

	const serialized = JSON.stringify(scopedBundle);
	for (const forbidden of ['hidden_tier', 'HiddenTier', 'ghost_tier', 'GhostTier', 'secret_calc', 'secret_rel', 'secret_kind']) {
		assert.ok(!serialized.includes(forbidden), `roleBundle leaked ${forbidden}`);
	}
});
