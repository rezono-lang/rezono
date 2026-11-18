import { printSlotPattern, slotPattern, type PatternConstraint } from './module-slot-pattern.ts';
import { block, named, opt, printWorld, typeOf, type Build, type Card, type Line, type Logical, type World, type ModuleComponent } from './module-support.ts';

type SlotConstraint = PatternConstraint;

export interface SlotDecl {
	slot: string;
	type: string;
	card?: Card;
	inverse?: string;
	world?: World;
	identifier?: true;
	embedded?: true;
	constraints?: SlotConstraint[];
}

export function readSlot(line: Logical, build: Build): SlotDecl {
	const decl = build.strip<SlotDecl>(line.read!);
	for (const child of line.block) {
		if (child.read!.line !== 'slot-pattern') {
			build.refuse(child, 'no line under this one');
			continue;
		}
		build.leaf(child);
		if (decl.constraints) {
			build.refuse(child, 'one pattern constraint per slot');
			continue;
		}
		decl.constraints = [build.strip<PatternConstraint>(child.read!)];
	}
	return decl;
}

export function printSlot(s: SlotDecl): string[] {
	const head = `${s.slot}: ${s.type}${s.card ?? ''}${s.inverse !== undefined ? ` inverse ${s.inverse}` : ''}${printWorld(s.world)}${s.identifier ? ' identifier' : ''}${s.embedded ? ' embedded' : ''}`;
	return block(head, (s.constraints ?? []).map(printSlotPattern));
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
