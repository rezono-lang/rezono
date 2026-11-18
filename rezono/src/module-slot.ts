import { printMetadata, readMetadataLine, type Metadata } from './module-metadata.ts';
import { printSlotPattern, slotPattern, type PatternConstraint } from './module-slot-pattern.ts';
import { block, named, opt, printWorld, typeOf, type Build, type Card, type Line, type Logical, type World, type ModuleComponent } from './module-support.ts';

type CardinalityConstraint = { cardinality: [minimum: string, maximum: string] };

export interface SlotDecl extends Metadata {
	slot: string;
	type: string;
	card?: Card;
	inverse?: string;
	world?: World;
	identifier?: true;
	embedded?: true;
	slotUri?: string;
	constraints?: (PatternConstraint | CardinalityConstraint)[];
}

export function readSlot(line: Logical, build: Build): SlotDecl {
	const slot = build.strip<SlotDecl>(line.read!);
	for (const child of line.block) {
		if (readMetadataLine(slot, child, build)) continue;
		const property = child.read!;
		if (property.line === 'iri') {
			build.leaf(child);
			if (slot.slotUri !== undefined) build.refuse(child, 'one slot IRI');
			else if (typeof property.value !== 'string') build.refuse(child, 'a JSON string');
			else slot.slotUri = property.value;
		} else if (property.line === 'slot-cardinality') {
			build.leaf(child);
			const constraint = build.strip<CardinalityConstraint>(property);
			const [minimum, maximum] = constraint.cardinality;
			if (slot.constraints?.some(constraint => 'cardinality' in constraint)) build.refuse(child, 'one cardinality constraint per slot');
			else if (BigInt(minimum) > BigInt(maximum)) build.refuse(child, 'a cardinality with a minimum no larger than its maximum');
			else (slot.constraints ??= []).push(constraint);
		} else if (property.line === 'slot-pattern') {
			build.leaf(child);
			if (slot.constraints?.some(constraint => 'pattern' in constraint)) build.refuse(child, 'one pattern constraint per slot');
			else (slot.constraints ??= []).push(build.strip<PatternConstraint>(property));
		} else build.refuse(child, 'no line under this one');
	}
	return slot;
}

export function printSlot(s: SlotDecl): string[] {
	return block(`${s.slot}: ${s.type}${s.card ?? ''}${s.inverse !== undefined ? ` inverse ${s.inverse}` : ''}${printWorld(s.world)}${s.identifier ? ' identifier' : ''}${s.embedded ? ' embedded' : ''}`, [
		...(s.slotUri === undefined ? [] : [`iri ${JSON.stringify(s.slotUri)}`]),
		...printMetadata(s),
		...(s.constraints ?? []).map(constraint => 'pattern' in constraint
			? printSlotPattern(constraint)
			: `cardinality ${constraint.cardinality[0]}..${constraint.cardinality[1]}`)
	]);
}

export const slot = {
	lineRules: ['SlotLine', 'CardinalityLine', ...slotPattern.lineRules],
	grammar: String.raw`
  SlotLine = name ":" Type Card? (kw<"inverse"> name)? World? kw<"identifier">? kw<"embedded">?
  CardinalityLine = kw<"cardinality"> cardinalityBound ".." cardinalityBound
  cardinalityBound = "0"             -- zero
                   | ("1".."9") digit* -- positive
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
		},
		CardinalityLine(keyword, minimum, _range, maximum) {
			return named(keyword, { line: 'slot-cardinality', cardinality: [minimum.sourceString, maximum.sourceString] });
		}
	},
} satisfies ModuleComponent;
