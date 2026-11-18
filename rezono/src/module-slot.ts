import { printMetadata, readMetadataLine, type Metadata } from './module-metadata.ts';
import { printSlotPattern, slotPattern, type PatternConstraint } from './module-slot-pattern.ts';
import { block, named, opt, printWorld, typeOf, type Build, type Card, type Line, type Logical, type World, type ModuleComponent } from './module-support.ts';

export interface SlotDecl extends Metadata {
	slot: string;
	type: string;
	card?: Card;
	inverse?: string;
	world?: World;
	identifier?: true;
	embedded?: true;
	slotUri?: string;
	constraints?: PatternConstraint[];
}

export function readSlot(line: Logical, build: Build): SlotDecl {
	const slot = build.strip<SlotDecl>(line.read!);
	for (const child of line.block) {
		if (readMetadataLine(slot, child, build)) continue;
		if (child.read!.line === 'slot-pattern') {
			build.leaf(child);
			if (slot.constraints?.some(constraint => 'pattern' in constraint)) build.refuse(child, 'one pattern constraint per slot');
			else (slot.constraints ??= []).push(build.strip<PatternConstraint>(child.read!));
		} else if (child.read!.line !== 'iri') build.refuse(child, 'no line under this one');
		else {
			build.leaf(child);
			if (slot.slotUri !== undefined) build.refuse(child, 'one slot IRI');
			else if (typeof child.read!.value !== 'string') build.refuse(child, 'a JSON string');
			else slot.slotUri = child.read!.value;
		}
	}
	return slot;
}

export function printSlot(s: SlotDecl): string[] {
	return block(`${s.slot}: ${s.type}${s.card ?? ''}${s.inverse !== undefined ? ` inverse ${s.inverse}` : ''}${printWorld(s.world)}${s.identifier ? ' identifier' : ''}${s.embedded ? ' embedded' : ''}`, [
		...(s.slotUri === undefined ? [] : [`iri ${JSON.stringify(s.slotUri)}`]),
		...printMetadata(s),
		...(s.constraints ?? []).map(printSlotPattern)
	]);
}

export const slot = {
	lineRules: ['SlotLine', ...slotPattern.lineRules],
	grammar: String.raw`
  SlotLine = name ":" Type Card? (kw<"inverse"> name)? World? kw<"identifier">? kw<"embedded">?
  ${slotPattern.grammar}
  `,
	actions: {
		...slotPattern.actions,
		SlotLine(n, _c, type, card, _inverse, inverse, world, identifier, embedded) {
			const decl: Line = { line: 'slot', slot: n.sourceString, type: typeOf(type) };
			if (card.numChildren) decl.card = opt(card);
			if (inverse.numChildren) decl.inverse = opt(inverse);
			if (world.numChildren) decl.world = world.child(0).decl();
			if (identifier.numChildren) decl.identifier = true;
			if (embedded.numChildren) decl.embedded = true;
			return named(n, decl);
		}
	},
} satisfies ModuleComponent;
