import { named, opt, printWorld, typeOf, type Card, type Line, type World, type ModuleComponent } from './module-support.ts';

export interface SlotDecl {
	slot: string;
	type: string;
	card?: Card;
	inverse?: string;
	world?: World;
	identifier?: true;
	embedded?: true;
}

export function printSlot(s: SlotDecl): string {
	return `${s.slot}: ${s.type}${s.card ?? ''}${s.inverse !== undefined ? ` inverse ${s.inverse}` : ''}${printWorld(s.world)}${s.identifier ? ' identifier' : ''}${s.embedded ? ' embedded' : ''}`;
}

export const slot = {
	lineRules: ['SlotLine'],
	grammar: String.raw`
  SlotLine = name ":" Type Card? (kw<"inverse"> name)? World? kw<"identifier">? kw<"embedded">?
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
		}
	},
} satisfies ModuleComponent;
