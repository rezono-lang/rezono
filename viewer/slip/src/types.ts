import type {
	Label,
	MessageResource,
	Question,
	Rule,
	SemanticType,
} from '../../../contracts/typescript/generated/bundle.ts';
import type { Source } from '../../../contracts/typescript/generated/explain.ts';
import type { Snapshot } from '../../../contracts/typescript/generated/manifest.ts';
import type { CalcWitness, RowRef, Witness } from '../../../contracts/typescript/generated/proof.ts';

export type WitnessCheckStatus = 'green' | 'warning' | 'red';

export interface HeadResponse {
	id: string;
	epoch: number;
	knowledge_time?: string;
	access_semantics?: number;
	definition_sha256?: string;
	manifest_sha256: string;
	witness_check?: WitnessCheckStatus;
	snapshots: Pick<Snapshot, 'relation' | 'role' | 'complete' | 'full' | 'format'>[];
}

export interface RoleSlot {
	id: string;
	kind: string;
	name: string;
	table: string;
	target?: string;
	type?: string;
	currency?: string;
	semantic?: SemanticType;
	world?: 'open' | 'closed';
}

export interface RoleRelationColumn {
	name: string;
	currency?: string;
	semantic?: SemanticType;
}

export interface RoleRelation {
	id: string;
	world?: 'open' | 'closed';
	calc?: string;
	outcome?: string;
	semantic?: SemanticType;
	columns: RoleRelationColumn[];
}

export interface RoleKind {
	id: string;
	class: string;
	parent?: string;
	world?: 'open' | 'closed';
	name_attribute?: string;
	name_arrows?: string[];
}

export interface RoleBundleResponse {
	pack: { id: string; base?: string };
	kinds: RoleKind[];
	attributes: RoleSlot[];
	arrows: RoleSlot[];
	relations: RoleRelation[];
	enums: { id: string; values: string[] }[];
	rules: Rule[];
	labels: Label[];
	messages: MessageResource[];
	home: { claim: string[] };
	questions: Question[];
}

export interface GroundsNode extends RowRef {
	distance: number;
	sources?: Source[];
}

export interface GroundsStep {
	conclusion: RowRef;
	premise: RowRef;
	how: string;
	position: number;
	value?: string;
}

export interface GroundsAnswer {
	format: string;
	question: string;
	manifest_id: string;
	start?: RowRef;
	nodes: GroundsNode[];
	steps: GroundsStep[];
	witnesses: Witness[];
	calc_witnesses?: CalcWitness[];
	next?: string;
	more?: RowRef[];
}

export interface StdVerb {
	verb: string;
	label_message: string;
	key: string;
	question?: string;
	primary?: boolean;
}

export interface StdSign {
	sign: string;
	form: string;
	glyph?: string;
	label_message: string;
}

export interface StdStatus {
	status: string;
	tone: string;
	glyph?: string;
	label_message: string;
}

export interface StdPacks {
	viewMessages: MessageResource[];
	explainMessages: MessageResource[];
	verbs: StdVerb[];
	signs: StdSign[];
	statuses: StdStatus[];
}

export interface RowSelection {
	relation: string;
	key: string[];
}

export interface SentenceSegment {
	text: string;
	line?: number;
}

export type ValueState = 'known' | 'unknown' | 'not_applicable' | 'invalid' | 'absent';

export interface SlipLine {
	index: number;
	relation: string;
	key: string;
	depth: number;
	polarity: 'positive' | 'negative';
	part?: 'total';
	label: string;
	value: string;
	state: ValueState;
	reason: string;
	origin: string;
}

export interface SlipSeal {
	manifestSha256: string;
	witnessCheck?: WitnessCheckStatus;
	manifestLabel: string;
	readerHashesLabel: string;
}

export interface SlipView {
	kind: 'slip' | 'relations';
	lang: string;
	pack: string;
	row?: RowSelection;
	sentence: SentenceSegment[];
	lines: SlipLine[];
	relations: Array<{ id: string; label: string }>;
	seal: SlipSeal;
	headers: {
		line: string;
		value: string;
		origin: string;
	};
	labels: {
		relationsHeading: string;
	};
}

export type FetchLike = (input: string | URL | Request, init?: RequestInit) => Promise<Response>;

export interface RenderRequest {
	store: string;
	role: string;
	pack: string;
	lang: string;
	row?: RowSelection;
	keys?: Array<{ line: number; key?: string; stop?: number }>;
	reader?: string;
}
