import { block, declaration, named, opt, printWorld, type Build, type Line, type Logical, type World, type ModuleComponent } from './module-support.ts';
import { printDerived, readDerived, type DerivedDecl } from './module-derived.ts';
import { printMetadata, readMetadataLine, type Metadata } from './module-metadata.ts';
import { printSlot, readSlot, type SlotDecl } from './module-slot.ts';

export interface KindDecl extends Metadata {
	kind: string;
	embedded?: true;
	abstract?: true;
	world?: World;
	applies?: { axis: 'at' | 'during' | 'in'; slot: string };
	sealed?: string;
	slots: SlotDecl[];
	derived: DerivedDecl[];
}
export interface ExtendDecl {
	extend: string;
	derived: DerivedDecl[];
}

function readKind(line: Logical, build: Build): KindDecl {
	const decl: KindDecl = { ...build.strip<KindDecl>(line.read!), slots: [], derived: [] };
	build.spans.set(decl, build.spans.get(line.read!)!);
	for (const child of line.block) {
		if (readMetadataLine(decl, child, build)) continue;
		const member = child.read!;
		if (member.line === 'derived') decl.derived.push(readDerived(child, build));
		else if (!['applies', 'sealed', 'slot'].includes(member.line)) build.refuse(child, '`applies`, `sealed`, a slot or `derived`');
		// A second applies or sealed line would replace the first unseen (v0 section 5a).
		else if (member.line === 'sealed' ? decl.sealed !== undefined : member.line === 'applies' && decl.applies) build.refuse(child, `one \`${member.line}\``);
		else if (member.line === 'slot') {
			if (member.identifier && decl.embedded) build.refuse(child, 'no identifier in an embedded kind');
			else if (member.identifier && decl.slots.some((slot) => slot.identifier)) build.refuse(child, 'one identifier per kind');
			else decl.slots.push(readSlot(child, build));
		} else {
			build.leaf(child);
			if (member.line === 'sealed') decl.sealed = member.slot as string;
			else decl.applies = build.strip<NonNullable<KindDecl['applies']>>(member);
		}
	}
	return decl;
}

function readExtension(line: Logical, build: Build): ExtendDecl {
	const decl: ExtendDecl = { ...build.strip<ExtendDecl>(line.read!), derived: [] };
	build.spans.set(decl, build.spans.get(line.read!)!);
	for (const child of line.block) {
		if (child.read!.line === 'derived') decl.derived.push(readDerived(child, build));
		else build.refuse(child, '`derived`');
	}
	return decl;
}

function printKind(d: KindDecl): string[] {
	return block(`${d.embedded ? 'embedded ' : d.abstract ? 'abstract ' : ''}kind ${d.kind}${printWorld(d.world)}`, [
		...printMetadata(d),
		...(d.applies ? [`applies ${d.applies.axis}: ${d.applies.slot}`] : []),
		...(d.sealed !== undefined ? [`sealed at: ${d.sealed}`] : []),
		...d.slots.flatMap(printSlot),
		...d.derived.flatMap(printDerived)
	]);
}

export const kind = {
	lineRules: ['KindLine', 'ExtendLine', 'AppliesLine', 'SealedLine'],
	grammar: String.raw`
  KindLine = (kw<"embedded"> | kw<"abstract">)? kw<"kind"> typeName World?
  ExtendLine = kw<"extend"> typeName
  AppliesLine = kw<"applies"> (at | during | in) ":" name
  SealedLine = kw<"sealed"> at ":" name
  `,
	actions: {
		KindLine(modifier, _k, t, world) {
			const decl: Line = { line: 'kind', kind: t.sourceString };
			const kindModifier = opt(modifier);
			if (kindModifier === 'embedded') decl.embedded = true;
			if (kindModifier === 'abstract') decl.abstract = true;
			if (world.numChildren) decl.world = world.child(0).decl();
			return named(t, decl);
		},
		ExtendLine: (_k, t) => named(t, { line: 'extend', extend: t.sourceString }),
		AppliesLine: (_k, axis, _c, n) => named(n, { line: 'applies', axis: axis.sourceString, slot: n.sourceString }),
		SealedLine: (_k, _at, _c, n) => ({ line: 'sealed', slot: n.sourceString })
	},
	declarations: {
		kind: declaration<KindDecl>('kind', readKind, printKind),
		extend: declaration<ExtendDecl>('extend', readExtension, d => block(`extend ${d.extend}`, d.derived.flatMap(printDerived)))
	}
} satisfies ModuleComponent;
