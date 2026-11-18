import { declaration, type ModuleComponent } from './module-support.ts';
import { print } from './print-expression.ts';
import type { CheckDecl } from './tree.ts';

export const check = {
	lineRules: ['Check'],
	actions: {
		Check(_verb, _name, _colon, _cond) {
			return { line: 'check', check: this.tree() };
		}
	},
	declarations: {
		check: declaration<CheckDecl>('check', (line, build) => {
			build.leaf(line);
			return line.read!.check as CheckDecl;
		}, d => [print(d)])
	}
} satisfies ModuleComponent;
