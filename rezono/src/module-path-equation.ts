import { listOf, named, type ModuleComponent } from './module-support.ts';

export interface PathEquationDecl {
	equal: string;
	left: string[];
	right: string[];
}

export function printPathEquation(equation: PathEquationDecl): string {
	return `equal ${equation.equal} = ${equation.left.join('.')}, ${equation.right.join('.')}`;
}

export const pathEquation = {
	lineRules: ['PathEquationLine'],
	grammar: String.raw`
  PathEquationLine = kw<"equal"> name "=" NonemptyListOf<name, "."> "," NonemptyListOf<name, ".">
  `,
	actions: {
		PathEquationLine(_equal, name, _equals, left, _comma, right) {
			return named(name, { line: 'pathEquation', equal: name.sourceString, left: listOf(left), right: listOf(right) });
		}
	}
} satisfies ModuleComponent;
