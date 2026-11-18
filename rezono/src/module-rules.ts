import { block, declaration, named, type ModuleComponent } from './module-support.ts';

export interface RulesDecl {
	rules: string;
	lines: string[];
}

export const rules = {
	lineRules: ['RulesLine'],
	grammar: String.raw`
  RulesLine = kw<"rules"> name
  `,
	verbatimBlock: { keyword: 'rules', header: 'RulesLine', tag: 'rules' },
	actions: {
		RulesLine: (_keyword, name) => named(name, { line: 'rules', rules: name.sourceString })
	},
	declarations: {
		rules: declaration<RulesDecl>('rules', (line, build) => {
			if (!line.block.length) build.refuse(line, 'an indented rule block');
			const lines: string[] = [];
			for (const child of line.block) {
				build.leaf(child);
				if (!child.last.startsWith('| ') || child.last.includes('\r')) {
					build.refuse(child, 'a physical rule line beginning with `| `');
					continue;
				}
				lines.push(child.last.slice(2));
			}
			const result = build.strip<Pick<RulesDecl, 'rules'>>(line.read!);
			return Object.assign(result, { lines });
		}, d => block(`rules ${d.rules}`, d.lines.map(line => `| ${line}`)))
	}
} satisfies ModuleComponent;
