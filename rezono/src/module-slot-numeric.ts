import type { SlotConstraint } from './module-slot.ts';
import { named, type Build, type Logical, type ModuleComponent } from './module-support.ts';

export type NumericSlotBound = { minimum: string } | { maximum: string };

function decimal(value: string): { coefficient: bigint; scale: number } {
	const [whole, fraction = ''] = value.split('.');
	return { coefficient: BigInt(whole + fraction), scale: fraction.length };
}

function numericBoundsInOrder(minimum: string, maximum: string): boolean {
	const lower = decimal(minimum);
	const upper = decimal(maximum);
	const scale = Math.max(lower.scale, upper.scale);
	return lower.coefficient * 10n ** BigInt(scale - lower.scale)
		<= upper.coefficient * 10n ** BigInt(scale - upper.scale);
}

export function readNumericSlotBound(line: Logical, build: Build, constraints: SlotConstraint[]): void {
	build.leaf(line);
	const bound = build.strip<NumericSlotBound>(line.read!);
	const name = 'minimum' in bound ? 'minimum' : 'maximum';
	if (constraints.some(prior => name in prior)) {
		build.refuse(line, `one ${name} constraint per slot`);
		return;
	}
	const minimum = 'minimum' in bound ? bound.minimum : constraints.find(prior => 'minimum' in prior)?.minimum;
	const maximum = 'maximum' in bound ? bound.maximum : constraints.find(prior => 'maximum' in prior)?.maximum;
	if (minimum !== undefined && maximum !== undefined && !numericBoundsInOrder(minimum, maximum)) {
		build.refuse(line, 'a minimum no larger than the maximum');
		return;
	}
	constraints.push(bound);
}

export function printNumericSlotBound(bound: NumericSlotBound): string {
	return 'minimum' in bound ? `minimum ${bound.minimum}` : `maximum ${bound.maximum}`;
}

export const numericSlotBounds = {
	lineRules: ['NumericSlotBoundLine'],
	grammar: String.raw`
  NumericSlotBoundLine = (kw<"minimum"> | kw<"maximum">) slotDecimalBound
  slotDecimalBound = "-"? d+ ("." d+)? ~tokCont
  `,
	actions: {
		NumericSlotBoundLine(keyword, value) {
			return named(keyword, { line: 'slot-numeric-bound', [keyword.sourceString]: value.sourceString });
		}
	}
} satisfies ModuleComponent;
