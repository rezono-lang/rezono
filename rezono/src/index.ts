// Rezono, the question slice of v0 (docs/rezono/expressions.md) and its check statements: text and JSON form to
// a tree, a tree to its normal form, the question hash, the check of names and types against a role's schema, the
// output schema of an answer, the answer itself over the rows a role reads, and what a check statement decides at
// publication. A module's text is read into its declarations (v0 §5, §11), a parse only, printed in its normal
// form and written as its JSON form, which is what the compiler reads (contracts/rezono-module.yaml). A decision
// table on a derived value (docs/rezono/tables.md) is checked against a schema and evaluated over the rows.
export { dataSchema, outputSchema, schemaId, type AnswerSchema } from './answer-schema.ts';
export { check, isError, type Checked, type Head, type RelationDef, type Shown, type Typed, type TypingOptions } from './check.ts';
export { checkModule } from './check-module.ts';
export { amount, answer, byteOrder, load, NotEvaluated, NotLoaded, OverBudget, page, publish, suppose, tabulate, type Answer, type AnswerRow, type Cell, type Cursor, type Data, type Frac, type Publication, type Ref, type RowRef, type RowWitness, type Tabulated, type UndecidedRow, type UndecidedViolation, type V } from './evaluate.ts';
export { grammar } from './grammar.ts';
export { fromJson, JsonFormError, toJson } from './json.ts';
export { parseDeclarations, parseModule, type Clause, type DecideAssign, type DecideDecl, type Decl, type DerivedDecl, type ExtendDecl, type FactRow, type FactTable, type KindDecl, type LanguageVersion, type Module, type ParamDecl, type ParsedModule, type ParseModuleOptions, type RequirementBound, type RequirementBoundOp, type RequirementDecl, type RequirementExists, type RequirementOption, type SlotDecl, type Table, type TableRow, type TableTest, type TableValue, type Valid, type VersionDecl } from './module.ts';
export { MODULE_FORMAT, REZONO_1_MODULE_FORMAT, moduleForm, moduleFromJson, moduleToJson, type FormOf, type ModuleForm, type Place } from './module-json.ts';
export { NORMAL_QUESTION, normalQuestion, questionHash } from './normal.ts';
export { parse, type Diagnostic, type Parsed, type Span } from './parse.ts';
export { grouping, print, printDeclarations, printExpr, printModule } from './print.ts';
export { inPart, NOT_READ_IN_FULL, STATES, type KindDef, type RuleDef, type Schema, type SlotDef, type StateName, type Ty, type TypeDef, type World } from './schema.ts';
export { declare, type DecisionTable, type Declared } from './table.ts';
export { classOf, formOf, isAsk, isCheck, type Ask, type CheckDecl, type Context, type Expr, type Path, type Question, type State, type Suppose, type Tail, type TimeSel } from './tree.ts';
