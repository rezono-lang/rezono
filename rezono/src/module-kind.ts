import { block, declaration, named, opt, printWorld, type Build, type Line, type Logical, type World, type ModuleComponent } from './module-support.ts';
import { printDerived, readDerived, type DerivedDecl } from './module-derived.ts';
import { key, printKey, type KeyDecl } from './module-key.ts';
import { printMetadata, readMetadataLine, type Metadata } from './module-metadata.ts';
import { pathEquation, printPathEquation, type PathEquationDecl } from './module-path-equation.ts';
import { printSlot, readSlot, type SlotDecl } from './module-slot.ts';
import { printExpr } from './print-expression.ts';
import type { Expr } from './tree.ts';

interface ConditionalCheckDecl extends Pick<Metadata, 'description'> {
	check: 'require';
	name: string;
	when: Expr;
	then: Expr;
}

export interface KindDecl extends Metadata {
	kind: string;
	embedded?: true;
	abstract?: true;
	parent?: string;
	world?: World;
	applies?: { axis: 'at' | 'during' | 'in'; slot: string };
	sealed?: string;
	equations?: PathEquationDecl[];
	slots: SlotDecl[];
	derived: DerivedDecl[];
	keys?: KeyDecl[];
	checks?: ConditionalCheckDecl[];
}
export interface ExtendDecl {
	extend: string;
	derived: DerivedDecl[];
}

function readConditionalCheck(line: Logical, build: Build): ConditionalCheckDecl {
	const decl = build.strip<ConditionalCheckDecl>(line.read!);
	for (const child of line.block) {
		if (child.read!.line === 'description') readMetadataLine(decl, child, build);
		else build.refuse(child, '`description`');
	}
	return decl;
}

function readKind(line: Logical, build: Build): KindDecl {
	const decl: KindDecl = { ...build.strip<KindDecl>(line.read!), slots: [], derived: [] };
	build.spans.set(decl, build.spans.get(line.read!)!);
	for (const child of line.block) {
		if (readMetadataLine(decl, child, build)) continue;
		const member = child.read!;
		if (member.line === 'pathEquation') {
			build.leaf(child);
			(decl.equations ??= []).push(build.strip<PathEquationDecl>(member));
			continue;
		}
		if (member.line === 'derived') decl.derived.push(readDerived(child, build));
		else if (member.line === 'conditionalCheck') (decl.checks ??= []).push(readConditionalCheck(child, build));
		else if (member.line === 'key') {
			build.leaf(child);
			(decl.keys ??= []).push(build.strip<KeyDecl>(member));
		}
		else if (!['applies', 'sealed', 'slot'].includes(member.line)) build.refuse(child, '`applies`, `sealed`, a slot, `derived`, `unique`, `equal` or `require`');
		// A second applies or sealed line would replace the first unseen (v0 section 5a).
		else if (member.line === 'sealed' ? decl.sealed !== undefined : member.line === 'applies' && decl.applies) build.refuse(child, `one \`${member.line}\``);
		else if (member.line === 'slot') {
			if (member.identifier && decl.embedded) build.refuse(child, 'no identifier in an embedded kind');
			else if (member.identifier && decl.slots.some((slot) => slot.identifier)) build.refuse(child, 'one identifier per kind');
			else decl.slots.push(readSlot(child, build));
		} else {
			build.leaf(child);
			if (member.line === 'sealed') decl.sealed = member.slot as string;
			else decl.applies = build.strip<NonNullable<KindDecl['applies']>>(member);
		}
	}
	return decl;
}

function readExtension(line: Logical, build: Build): ExtendDecl {
	const decl: ExtendDecl = { ...build.strip<ExtendDecl>(line.read!), derived: [] };
	build.spans.set(decl, build.spans.get(line.read!)!);
	for (const child of line.block) {
		if (child.read!.line === 'derived') decl.derived.push(readDerived(child, build));
		else build.refuse(child, '`derived`');
	}
	return decl;
}

function printKind(d: KindDecl): string[] {
	const parent = d.parent === undefined ? '' : ` is ${d.parent}`;
	return block(`${d.embedded ? 'embedded ' : d.abstract ? 'abstract ' : ''}kind ${d.kind}${parent}${printWorld(d.world)}`, [
		...printMetadata(d),
		...(d.applies ? [`applies ${d.applies.axis}: ${d.applies.slot}`] : []),
		...(d.sealed !== undefined ? [`sealed at: ${d.sealed}`] : []),
		...d.slots.flatMap(printSlot),
		...(d.equations ?? []).map(printPathEquation),
		...d.derived.flatMap(printDerived),
		...(d.keys ?? []).map(printKey),
		...(d.checks ?? []).flatMap(check => block(
			`${check.check} ${check.name} when ${printExpr(check.when)} then ${printExpr(check.then)}`,
			printMetadata(check)
		))
	]);
}

export const kind = {
	lineRules: ['KindLine', 'ExtendLine', 'AppliesLine', 'SealedLine', 'ConditionalCheckLine', ...key.lineRules, ...pathEquation.lineRules],
	grammar: String.raw`
  KindLine = (kw<"embedded"> | kw<"abstract">)? kw<"kind"> typeName (is typeName)? World?
  ExtendLine = kw<"extend"> typeName
  AppliesLine = kw<"applies"> (at | during | in) ":" name
  SealedLine = kw<"sealed"> at ":" name
  ConditionalCheckLine = kw<"require"> name kw<"when"> Expr kw<"then"> Expr
  ${key.grammar}
  ${pathEquation.grammar}`,
	actions: {
		KindLine(modifier, _k, t, _is, parent, world) {
			const decl: Line = { line: 'kind', kind: t.sourceString };
			const kindModifier = opt(modifier);
			if (kindModifier === 'embedded') decl.embedded = true;
			if (kindModifier === 'abstract') decl.abstract = true;
			if (parent.numChildren) decl.parent = opt(parent);
			if (world.numChildren) decl.world = world.child(0).decl();
			return named(t, decl);
		},
		ExtendLine: (_k, t) => named(t, { line: 'extend', extend: t.sourceString }),
		AppliesLine: (_k, axis, _c, n) => named(n, { line: 'applies', axis: axis.sourceString, slot: n.sourceString }),
		SealedLine: (_k, _at, _c, n) => ({ line: 'sealed', slot: n.sourceString }),
		ConditionalCheckLine: (_require, name, _when, when, _then, then) => named(name, {
			line: 'conditionalCheck', check: 'require', name: name.sourceString, when: when.tree(), then: then.tree()
		}),
		...key.actions,
		...pathEquation.actions
	},
	declarations: {
		kind: declaration<KindDecl>('kind', readKind, printKind),
		extend: declaration<ExtendDecl>('extend', readExtension, d => block(`extend ${d.extend}`, d.derived.flatMap(printDerived)))
	}
} satisfies ModuleComponent;
