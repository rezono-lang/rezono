import { bare, declaration, leafDeclaration, named, type ModuleComponent } from './module-support.ts';

type UnitDecl = { unit: string; is: string };

export const unit = {
	lineRules: ['UnitLine'],
	grammar: String.raw`
  UnitLine = kw<"unit"> typeName "=" UnitBody
  UnitBody = kw<"money"> kw<"minor">? typeName (kw<"per"> name)?  -- money
           | kw<"integer">                                         -- integer
           | number "^" number typeName                             -- power
           | typeName kw<"per"> typeName                            -- per
           | Expr                                                   -- quantity
  `,
	actions: {
		UnitLine(_k, t, _eq, body) {
			// A quantity is an expression: read as one, so that what v0 reserves in it is an R015 at its span. The form
			// keeps its text.
			const kind = body.child(0);
			if (kind.ctorName === 'UnitBody_quantity') kind.child(0).tree();
			else if (kind.ctorName === 'UnitBody_power') {
				kind.child(0).lit();
				kind.child(2).lit();
			}
			return named(t, { line: 'unit', unit: t.sourceString, is: bare(body).replace(/\s+/g, ' ') });
		}
	},
	declarations: { unit: declaration<UnitDecl>('unit', leafDeclaration, d => [`unit ${d.unit} = ${d.is}`]) }
} satisfies ModuleComponent;
