// Text to tree (docs/rezono/expressions.md §4), with the diagnostics the parse itself can give:
//
//   R000  a plain syntax error (a working choice: v0 §14 point 17 leaves the code open); and a line end inside a
//         text literal or an id between backticks (v0 §11), with the same test and span as in a module
//   R014  `ask` needs a kind name
//   R016  comparisons do not chain
//   R018  a context axis is given twice
//   R015  a reserved construct, at its span: from its first keyword to the end of its operand (§1)
//
// Parse-level checks come first (§1): with an R000, R014, R016 or R018 there is no tree and no R015. A text
// with only R015s has a tree, so it prints; it is not evaluated.
import type { Node } from 'ohm-js';
import { grammar, nativeRuleGrammar } from './grammar.ts';
import { readRuleName } from './rule-names.ts';
import type { Ask, CheckDecl, Context, Expr, Path, Question, Suppose, SupposeSlot, Tail, TimeSel } from './tree.ts';

import { placed, points, refused, reserved, run, spanAt, spanOf, startRun, type Diagnostic, type Span } from './parse-support.ts';

export { points, type Diagnostic, type Span } from './parse-support.ts';

export interface Parsed {
	/** Absent when a parse-level check failed. */
	tree?: Question;
	/** In source order. */
	diagnostics: Diagnostic[];
	/** The place of every node of the tree, for the checks that follow the parse. */
	spans: WeakMap<object, Span>;
}

const semantics = grammar.createSemantics();

/** The text of a literal as it prints: its parts one space apart, digits normalized without grouping underscores (§9). */
semantics.addOperation<string>('lit', {
	num(_whole, _sep, _rest) {
		if (run.version === '0' && this.sourceString.includes('_')) {
			refused(this, 'R000', ['a number without digit grouping']);
		}
		return this.sourceString.replaceAll('_', '');
	},
	quantity: (n, _sp, unit) => `${n.lit()} ${unit.sourceString}`,
	percent: (n, _sp, _pct) => `${n.lit()} %`,
	money: (symbol, _sp, n, _slash, unit) => `${symbol.sourceString} ${n.lit()}${unit.children.map((u) => `/${u.sourceString}`).join("")}`,
	stateLit_unknown: (_w, _sp, reason) => `unknown ${reason.sourceString}`,
	stateLit_invalid: (_w, _sp, reason) => `invalid ${reason.sourceString}`,
	_nonterminal(...children) {
		return children.length === 1 && children[0].ctorName !== '_terminal' && children[0].ctorName !== '_iter' ? children[0].lit() : this.sourceString;
	},
	_terminal() {
		return this.sourceString;
	}
});

const all = (list: Node): Expr[] => list.asIteration().children.map((c) => c.tree());
/** `and` and `or` are n-ary in the tree: a chain and its parenthesised spelling are one question (§4a). */
function chain(node: Node, op: 'and' | 'or', list: Node): Expr {
	const items = all(list);
	if (items.length === 1) return items[0];
	const flat = items.flatMap((e) => (op in e ? (e as Record<string, Expr[]>)[op] : [e]));
	return placed(node, { [op]: flat } as Expr);
}

semantics.addOperation<unknown>('tree', {
	Ask(_ask, binder, _colon, kind, more, contexts, _where, cond, show, tails) {
		const named = kind.child(0);
		if (named.ctorName === 'name') {
			const text = named.sourceString;
			run.errors.push({ code: 'R014', span: spanOf(named), args: [text, text.replace(/(^|_)([a-z])/g, (_m, _u, c: string) => c.toUpperCase())] });
		}
		const ask: Ask = { ask: named.sourceString, where: undefined as unknown as Expr };
		if (binder.numChildren) ask.binder = binder.child(0).sourceString;
		if (more.numChildren) {
			ask.more = more.children.map((m) => m.tree() as [string, string]);
			for (const m of more.children) reserved(m, 'a second binder');
		}
		if (contexts.numChildren) {
			const context: Context = {};
			for (const c of contexts.children) {
				const [axis, value] = c.tree() as [keyof Context, Expr];
				if (axis in context) refused(c, 'R018', [axis.replace('_', ' ')]);
				else {
					context[axis] = value;
					reserved(c, `${axis.replace('_', ' ')} in a question context`);
				}
			}
			ask.context = context;
		}
		ask.where = cond.tree() as Expr;
		const start = `ask ${ask.binder ? `${ask.binder}: ` : ''}${ask.ask}`;
		for (const [d, axis] of run.misplaced) d.hint = { id: `hint.question_${axis}`, args: [`${start} ${d.span.text} where …`] };
		if (show.numChildren) ask.show = show.child(0).tree() as Expr[];
		if (tails.numChildren) {
			ask.tail = tails.children.map((t) => t.tree() as Tail);
			for (const t of tails.children) reserved(t, t.child(0).ctorName === 'Tail_limit' ? 'limit' : `${t.child(0).ctorName.slice(5)} by`);
		}
		return placed(this, ask);
	},
	MoreBinder: (_comma, name, _colon, type) => [name.sourceString, type.sourceString],
	Context_at: (_at, atom) => ['at', atom.tree()],
	Context_as_known: (_as, _known, atom) => ['as_known', atom.tree()],
	Context_during: (_during, atom) => ['during', atom.tree()],
	Context_in: (_in, atom) => ['in', atom.tree()],
	Show: (_show, list) => all(list),
	Tail_order: (_order, _by, list) => ({ order: all(list) }),
	Tail_group: (_group, _by, list) => ({ group: all(list) }),
	Tail_limit: (_limit, n) => ({ limit: n.lit() }),

	Check(verb, name, _colon, cond) {
		const decl: CheckDecl = { check: verb.sourceString as CheckDecl['check'], cond: undefined as unknown as Expr };
		if (name.numChildren) decl.name = name.child(0).sourceString;
		decl.cond = cond.tree() as Expr;
		// `norm` is about the world and reserved in v0 (§5): its span is the whole statement.
		if (decl.check === 'norm') reserved(this, 'norm');
		return placed(this, decl);
	},

	Suppose_set(_plus, path, _eq, value) {
		return placed(this, { set: [path.tree() as Path, value.tree() as Expr] } satisfies Suppose);
	},
	Suppose_insert_row(_plus, type, id, _open, slots, _close) {
		const read = slots.asIteration().children.map((slot) => slot.tree() as SupposeSlot);
		return placed(this, { insert_row: { kind: type.sourceString, key: id.sourceString, slots: read } } satisfies Suppose);
	},
	SupposeSlot(name, _eq, value) {
		return placed(this, { name: name.sourceString, value: value.tree() as Expr } satisfies SupposeSlot);
	},
	Suppose_retract_row(_minus, type, id) {
		return placed(this, { retract_row: [type.sourceString, id.sourceString] } satisfies Suppose);
	},
	Suppose_retract(_minus, path) {
		return placed(this, { retract: path.tree() as Path } satisfies Suppose);
	},
	SupposePath(first, _dots, names) {
		return placed(this, { path: [first.sourceString, ...names.children.map((n) => n.sourceString)] });
	},

	Cond(_when, c, _then, a, _else, b) {
		return placed(this, { when: [c.tree(), a.tree(), b.tree()] } as Expr);
	},
	Imply_imply(a, _op, b) {
		return placed(this, { imply: [a.tree(), b.tree()] } as Expr);
	},
	Or(list) {
		return chain(this, 'or', list);
	},
	And(list) {
		return chain(this, 'and', list);
	},
	Not_not(_not, e) {
		return placed(this, { not: e.tree() } as Expr);
	},
	Test_cmp(first, ops, rest) {
		if (ops.numChildren > 1) run.errors.push({ code: 'R016', span: spanOf(this), args: [] });
		return placed(this, { cmp: [ops.child(0).sourceString, first.tree(), rest.child(0).tree()] } as Expr);
	},
	Test_in(a, _in, b) {
		return placed(this, { in: [a.tree(), b.tree()] } as Expr);
	},
	Test_is(a, _is, state) {
		return placed(this, { is: [a.tree(), state.sourceString] } as Expr);
	},
	Range_range(a, op, b) {
		return placed(this, { range: [a.tree(), op.sourceString, b.tree()] } as Expr);
	},
	Add_binary(a, op, b) {
		return placed(this, { arith: [op.sourceString, a.tree(), b.tree()] } as Expr);
	},
	Mul_binary(a, op, b) {
		return placed(this, { arith: [op.sourceString, a.tree(), b.tree()] } as Expr);
	},
	Unary_neg(_minus, e) {
		return placed(this, { neg: e.tree() } as Expr);
	},
	Post(base, at, known, filter) {
		let e = base.tree() as Expr;
		if (at.numChildren || known.numChildren) {
			const sel: TimeSel = {};
			if (at.numChildren) {
				sel.at = at.child(0).tree() as Expr;
				const d = reserved(at.child(0), 'at on a value');
				if ('lit' in e) run.misplaced.push([d, 'at']);
			}
			if (known.numChildren) {
				sel.as_known = known.child(0).tree() as Expr;
				const d = reserved(known.child(0), 'as known on a value');
				if ('lit' in e) run.misplaced.push([d, 'as_known']);
			}
			e = { timesel: [e, sel] };
		}
		if (filter.numChildren) e = { filter: [e, filter.child(0).tree() as Expr] };
		return placed(this, e);
	},
	TimeAt: (_at, atom) => atom.tree(),
	TimeKnown: (_as, _known, atom) => atom.tree(),
	Filter: (_where, e) => e.tree(),
	Dotted_where(base, _dot, _where, _open, cond, _close) {
		return placed(this, { filter: [base.tree(), cond.tree()] } as Expr);
	},
	Dotted_agg(base, _dot, agg) {
		const [name, ...arg] = agg.tree() as [string, ...Expr[]];
		return placed(this, { agg: [name, base.tree(), ...arg] } as Expr);
	},
	Dotted_name(base, _dot, name) {
		const b = base.tree() as Expr;
		if ('path' in b) return placed(this, { path: [...b.path, readRuleName(name)] });
		if ('lit' in b && run.ids.has(b)) return placed(this, { path: [b.lit, readRuleName(name)] });
		return placed(this, { dot: [b, readRuleName(name)] } as Expr);
	},
	Agg(name, _open, arg, _close) {
		return [name.sourceString, ...arg.children.map((a) => a.tree())];
	},
	Atom(e) {
		const text = e.sourceString;
		switch (e.ctorName) {
			case 'literal':
				return placed(this, { lit: e.lit() as string });
			case 'idTok': {
				const id = placed(this, { lit: text });
				run.ids.add(id);
				return id;
			}
			case 'oddWord':
				return placed(this, { lit: text });
			case 'typeName':
				return placed(this, { kind: text });
			case 'name':
				return placed(this, { path: [text] });
			default:
				return e.tree();
		}
	},
	Atom_paren: (_open, e, _close) => e.tree(),
	Call(name, _open, args, _close) {
		return placed(this, { call: [name.sourceString, all(args)] } as Expr);
	}
});

const nativeRuleSemantics = nativeRuleGrammar.extendSemantics(semantics);
nativeRuleSemantics.extendOperation<unknown>('tree', {
	QualifiedKind(pack, _dot, kind) {
		return placed(this, { kind: [readRuleName(pack), kind.sourceString].join('.') });
	},
	quotedName(_open, _first, _rest, _close) {
		return placed(this, { path: [readRuleName(this)] });
	},
	wildcard(_mark) {
		return placed(this, { wildcard: true });
	},
	Call(name, _open, args, _close) {
		return placed(this, { call: [name.tree(), all(args)] } as Expr);
	},
	NativeCallName_schema(kind, _dot, member) {
		return [(kind.tree() as { kind: string }).kind, readRuleName(member)].join('.');
	},
	NativeCallName_kind(kind, _dot, member) {
		return [kind.sourceString, readRuleName(member)].join('.');
	},
	NativeCallName_imported(pack, _dot, member) {
		return [readRuleName(pack), readRuleName(member)].join('.');
	},
	NativeCallName_local: readRuleName,
});

/** The token at a place where the parse could not go on: a word, or one other character; empty at the end. */
function tokenAt(text: string, at: number): [number, number] {
	const m = /[A-Za-z0-9_]+|\S/uy;
	m.lastIndex = at;
	const found = m.exec(text);
	return found ? [at, at + found[0].length] : [at, at];
}

/** What one rule read: its result, unless the text did not match; the parse-level errors and the R015s apart. */
export interface Read<T> {
	value?: T;
	errors: Diagnostic[];
	reserved: Diagnostic[];
	spans: WeakMap<object, Span>;
}
/** The semantics of the grammar and the helpers its actions use, for the lines of a module (module.ts). */
export { semantics, placed, refused, reserved };

/**
 * Reads `text` with one rule of the grammar, its result made by `read` from the match. module.ts reads one
 * logical line of a file as a slice with `offset` set to the slice's UTF-16 start in the file, and passes
 * the file's code-point map (`at`), so reported spans keep exact file code-point offsets in O(|line|) time.
 */
const nativeRules = new Set(['NativeRuleLine', 'StepClauseLine', 'StepChangeLine']);

export function readRule<T>(
	text: string,
	rule: string,
	read: (node: Node) => T,
	spans = new WeakMap<object, Span>(),
	at = points(text),
	native = nativeRules.has(rule),
	version?: '0' | '1',
	offset = 0
): Read<T> {
	startRun(text, spans, at, version, offset);
	const match = (native ? nativeRuleGrammar : grammar).match(text, rule);
	if (match.failed()) {
		const failAt = Math.min(match.getRightmostFailurePosition(), text.length);
		return { errors: [{ code: 'R000', span: spanAt(...tokenAt(text, failAt)), args: [match.getExpectedText()] }], reserved: [], spans };
	}
	const value = read((native ? nativeRuleSemantics : semantics)(match) as unknown as Node);
	return { value, errors: run.errors, reserved: run.reserved, spans };
}

export const inOrder = (a: Diagnostic, b: Diagnostic) => a.span.start - b.span.start || a.span.end - b.span.end;

/**
 * A text literal or an id between backticks that holds a line end: where it starts in `code` and where its
 * first line ends. Neither goes on over lines (v0 §11), in a question as in a module: the line end and the
 * indent after it would be part of the value, and the layout tests of module.ts read each line by itself.
 */
export function torn(code: string): [number, number] | undefined {
	let mark = '';
	let from = 0;
	for (let i = 0; i < code.length; i++) {
		const c = code[i];
		if (!mark) {
			if (c === '"' || c === '`') [mark, from] = [c, i];
			else if (c === '-' && code[i + 1] === '-') while (i + 1 < code.length && code[i + 1] !== '\n') i++;
		} else if (c === '\n' || c === '\r') return [from, i];
		else if (c === mark) mark = '';
		else if (c === '\\' && mark === '"' && code[i + 1] !== '\n' && code[i + 1] !== '\r') i++;
	}
	return undefined;
}
/** The R000 of a torn text or id of `text`: from its opening mark to the end of its first line (UTF-16 offsets). */
export function tornAt(text: string, from: number, to: number, cp: (at: number) => number): Diagnostic {
	return { code: 'R000', span: { text: text.slice(from, to), start: cp(from), end: cp(to) }, args: [`${text[from] === '"' ? 'a text' : 'an id'} that ends on its line`] };
}

/** Parses one question (an `ask` or a suppose line) or one check statement. */
export function parse(text: string): Parsed {
	// A text ends on its line here as in a module (v0 §11): the same test and the same R000 as module.ts.
	const cut = torn(text);
	if (cut) {
		const at = points(text);
		return { diagnostics: [tornAt(text, cut[0], cut[1], (i) => (at ? at[i] : i))], spans: new WeakMap() };
	}
	const { value, errors, reserved: later, spans } = readRule(text, 'Question', (m) => m.tree() as Question);
	if (errors.length) return { diagnostics: errors.sort(inOrder), spans };
	return { tree: value, diagnostics: later.sort(inOrder), spans };
}
