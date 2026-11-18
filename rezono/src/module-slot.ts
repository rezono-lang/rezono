import { block, named, opt, printWorld, typeOf, type Build, type Card, type Line, type Logical, type World, type ModuleComponent } from './module-support.ts';

type CardinalityConstraint = { cardinality: [minimum: string, maximum: string] };

export interface SlotDecl {
	slot: string;
	type: string;
	card?: Card;
	inverse?: string;
	world?: World;
	identifier?: true;
	embedded?: true;
	constraints?: CardinalityConstraint[];
}

export function readSlot(line: Logical, build: Build): SlotDecl {
	const decl = build.strip<SlotDecl>(line.read!);
	for (const child of line.block) {
		if (child.read!.line !== 'slot-cardinality') {
			build.refuse(child, 'no line under this one');
			continue;
		}
		build.leaf(child);
		if (decl.constraints) {
			build.refuse(child, 'one cardinality constraint per slot');
			continue;
		}
		const constraint = build.strip<CardinalityConstraint>(child.read!);
		const [minimum, maximum] = constraint.cardinality;
		if (BigInt(minimum) > BigInt(maximum)) {
			build.refuse(child, 'a cardinality with a minimum no larger than its maximum');
			continue;
		}
		decl.constraints = [constraint];
	}
	return decl;
}

export function printSlot(s: SlotDecl): string[] {
	const head = `${s.slot}: ${s.type}${s.card ?? ''}${s.inverse !== undefined ? ` inverse ${s.inverse}` : ''}${printWorld(s.world)}${s.identifier ? ' identifier' : ''}${s.embedded ? ' embedded' : ''}`;
	return block(head, (s.constraints ?? []).map(({ cardinality: [minimum, maximum] }) => `cardinality ${minimum}..${maximum}`));
}

export const slot = {
	lineRules: ['SlotLine', 'CardinalityLine'],
	grammar: String.raw`
  SlotLine = name ":" Type Card? (kw<"inverse"> name)? World? kw<"identifier">? kw<"embedded">?
  CardinalityLine = kw<"cardinality"> cardinalityBound ".." cardinalityBound
  cardinalityBound = "0"             -- zero
                   | ("1".."9") digit* -- positive
  `,
	actions: {
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
		},
	},
} satisfies ModuleComponent;
