import { bare, declaration, leafDeclaration, named, type ModuleComponent } from './module-support.ts';

type UnitDecl = { unit: string; is: string };
type DefaultUnitDecl = { default_unit: string };

export const unit = {
	lineRules: ['DefaultUnitLine', 'UnitLine'],
	grammar: String.raw`
  DefaultUnitLine = kw<"default"> kw<"unit"> typeName
  UnitLine = kw<"unit"> typeName "=" UnitBody
  UnitBody = kw<"money"> kw<"minor">? typeName (kw<"per"> name)?  -- money
           | kw<"integer">                                         -- integer
           | number "^" number typeName                             -- power
           | typeName kw<"per"> typeName                            -- per
           | Expr                                                   -- quantity
  `,
	actions: {
		DefaultUnitLine: (_d, _u, t) => named(t, { line: 'default_unit', default_unit: t.sourceString }),
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
	declarations: {
		unit: declaration<UnitDecl>('unit', leafDeclaration, d => [`unit ${d.unit} = ${d.is}`]),
		default_unit: declaration<DefaultUnitDecl>('default_unit', leafDeclaration, d => [`default unit ${d.default_unit}`]),
	}
} satisfies ModuleComponent;
