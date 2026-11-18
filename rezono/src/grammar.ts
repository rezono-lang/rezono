// The grammar of the question slice of Rezono v0 (docs/rezono/expressions.md §3 and §4; v0.md §3) and of its
// check statements (v0 §5, §11), as an Ohm grammar: the executable form of the EBNF there, rule for rule. Rules with a capital skip white space and
// comments between their parts; rules in lower case are tokens and skip nothing.
//
// What the EBNF leaves to the lexer is written out here:
// - a word with a hyphen inside is one token, an id (`host-b`); a minus between names needs spaces (§3);
// - a number followed by a unit word is one literal (`384 GiB`, `730 h`), a symbol before a number too
//   (`€ 0.20/h`: the symbol is any character that is no letter, digit, space or punctuation of the language, so
//   no currency is named here; which symbols exist is a pack's, v0 §3);
// - anything else that starts with a digit and holds no space is a literal token (`10.12.0.1`), read later by
//   the type the context expects.
//
// A token rule carries a description (`name (a name)`), so that a syntax error names what was expected at the
// start of the token, not a character inside it.
//
// A reserved construct (a second binder, `order by`, `group by`, `limit`, a context, a time selection) is in the
// grammar, so that it parses and prints; parse.ts reports it as R015 at its span (§1).
//
// A decision table (docs/rezono/tables.md §2) has its own two rules, `TableHead` and `TableRow`: module.ts reads
// the lines under a `table` line with them. A value of a table is a literal, an id or a bare word, never a state.
import * as ohm from 'ohm-js';

const source = String.raw`
Rezono {
  Question = Ask | Suppose | Check

  // A check statement (v0 §5, "Checks, norms and requirements"): the one declaration read so far. A check that
  // has versions, "requires n sources" or "because" is not read yet (R000).
  Check = checkVerb (name ":")? Expr

  Ask = ask (name ":")? AskKind MoreBinder* Context* where Expr Show? Tail*
  AskKind = typeName | name
  MoreBinder = "," name ":" typeName
  Context = at Atom        -- at
          | as known Atom  -- as_known
          | during Atom    -- during
          | in Atom        -- in
  Show = show NonemptyListOf<Expr, ",">
  Tail = order by NonemptyListOf<Expr, ",">  -- order
       | group by NonemptyListOf<Expr, ",">  -- group
       | limit number                        -- limit

  Suppose = "+" SupposePath "=" Unary  -- set
          | "-" typeName rowId         -- retract_row
          | "-" SupposePath            -- retract
  SupposePath = rowId ("." name)+

  Expr = Cond | Imply
  Cond = when Expr then Expr else Expr
  Imply = Or "=>" Imply  -- imply
        | Or
  Or = NonemptyListOf<And, or>
  And = NonemptyListOf<Not, and>
  Not = not Not  -- not
      | Test
  Test = Range (cmpOp Range)+  -- cmp
       | Range in Range        -- in
       | Range is state        -- is
       | Range
  Range = Add rangeOp Add  -- range
        | Add
  Add = Add addOp Mul  -- binary
      | Mul
  Mul = Mul mulOp Unary  -- binary
      | Unary
  Unary = "-" Unary  -- neg
        | Post
  Post = Dotted TimeAt? TimeKnown? Filter?
  Dotted = Dotted "." Agg   -- agg
         | Dotted "." name  -- name
         | Atom
  Agg = aggName "(" Expr? ")"
  TimeAt = at Atom
  TimeKnown = as known Atom
  Filter = where Expr
  Atom = literal
       | Call
       | "(" Expr ")"  -- paren
       | idTok
       | typeName
       | name
       | oddWord
  Call = name "(" ListOf<Expr, ","> ")"

  // One logical line of a module (v0 §5, §11). module.ts splits a file into lines by their indentation (the
  // layout tokens of §11) and reads each with this rule; which line may stand under which is module.ts's.
  // What v0 reserves still parses, so that it is reported as R015 at its span (norm, a time selection).
  Line = RezonoLine | PackLine | UseLine | RoundingLine | ReasonLine | UnitLine | EnumLine | ParamLine
       | KindLine | ExtendLine | AppliesLine | SealedLine | DerivedLine | VersionLine | UnlessLine | WhenLine
       | TableLine | RowLine | FactLine | Check | SlotLine | AssignLine
  RezonoLine = kw<"rezono"> number
  PackLine = kw<"pack"> name
  UseLine = kw<"use"> NonemptyListOf<name, "."> (as name)?
  RoundingLine = kw<"rounding"> (kw<"date"> | kw<"money">) name
  ReasonLine = kw<"reason"> name "=" text
  UnitLine = kw<"unit"> typeName "=" UnitBody
  UnitBody = kw<"money"> kw<"minor">? typeName (kw<"per"> name)?  -- money
           | kw<"integer">                                         -- integer
           | Expr                                                   -- quantity
  EnumLine = kw<"enum"> typeName World? "=" NonemptyListOf<name, "|">
  World = kw<"world"> (kw<"open"> | kw<"closed">)
  ParamLine = kw<"param"> name ":" Type (kw<"per"> typeName)? ("=" Expr)?
  KindLine = kw<"embedded">? kw<"kind"> typeName World?
  ExtendLine = kw<"extend"> typeName
  AppliesLine = kw<"applies"> (at | during | in) ":" name
  SealedLine = kw<"sealed"> at ":" name
  DerivedLine = kw<"total">? kw<"derived"> name ":" Type Card? ("=" Expr)?
  SlotLine = name ":" Type Card? (kw<"inverse"> name)? World? kw<"identifier">? kw<"embedded">?
  Type = typeName ("<" NonemptyListOf<Type, ","> ">")?
  Card = "?" | "*" | "+"
  VersionLine = kw<"version"> number ("," VContext)* ("=" Expr Src?)?
  VContext = kw<"valid"> date "..<" date    -- closed
           | kw<"valid"> date ".."           -- open
           | known date                      -- known
  UnlessLine = kw<"unless"> (Expr then Expr Src?)?
  WhenLine = when Expr then Expr Src?
  TableLine = kw<"table"> (kw<"unique"> | kw<"first"> | kw<"priority"> | kw<"collect">)
  // The header and a row of a decision table (tables.md §2). The last cell of a row is its output: a cell is
  // one of the tests only while something follows its closing bar.
  TableHead = "|" (Expr "|")+ "->" name "|"
  TableRow = "|" (TCell "|" &rowValue)+ TValue "|"
  TCell = dash                         -- any
        | NonemptyListOf<TTest, ",">  -- tests
  TTest = TValue rangeOp TValue  -- between
        | TValue rangeOp         -- from
        | rangeOp TValue         -- to
        | TValue
  // A value is also a keyword written as a bare word (tables.md §7 point 1): an enum of the schema may have
  // the value valid or open, and a cell is the only place it is written. true and false stay Bool.
  TValue = ~stateLit literal | idTok | typeName | name | oddWord | valueWord
  RowLine = "|" NonemptyListOf<Cell, "|"> "|"
  Cell = "->" Expr  -- out
       | dash       -- any
       | Expr       -- test
  FactLine = kw<"fact"> typeName                    -- table
           | kw<"fact"> name rowId ("," VContext)*  -- row
  AssignLine = name "=" Expr Src?
  Src = "@" sourceRef

  // Tokens.
  kw<word> = word wordEnd
  rowValue (the value of the row, after its cells) = any
  dash = "-" &(hsp* "|")
  sourceRef (a source) = (~space any)+
  space += comment
  comment = "--" (~"\n" any)*
  az = "a".."z"
  cap = "A".."Z"
  d = "0".."9"
  wordChar = az | cap | d | "_"
  // A word ends where no word character follows and no hyphen that continues an id: not-ready is one
  // token, an id, and never the word "not" (§3).
  wordEnd = ~wordChar ~("-" wordChar)
  hsp = " " | "\t"

  ask = "ask" wordEnd
  where = "where" wordEnd
  show = "show" wordEnd
  when = "when" wordEnd
  then = "then" wordEnd
  else = "else" wordEnd
  not = "not" wordEnd
  and = "and" wordEnd
  or = "or" wordEnd
  in = "in" wordEnd
  is = "is" wordEnd
  at = "at" wordEnd
  as = "as" wordEnd
  by = "by" wordEnd
  known = "known" wordEnd
  during = "during" wordEnd
  order = "order" wordEnd
  group = "group" wordEnd
  limit = "limit" wordEnd
  checkVerb (check, require, warn or norm) = ("check" | "require" | "warn" | "norm") wordEnd

  // The keywords of v0 §3, with the two literals of Bool (§3 here). None of them is a name.
  keyword = ( "pack" | "use" | "as" | "private" | "unit" | "enum" | "param" | "kind" | "extend" | "derived"
            | "rule" | "check" | "warn" | "require" | "fact" | "decide" | "assume" | "theory" | "view"
            | "example" | "ask" | "suppose" | "propose" | "when" | "then" | "else" | "unless" | "where" | "show"
            | "not" | "and" | "or" | "in" | "is" | "version" | "valid" | "known" | "at" | "by" | "on"
            | "because" | "until" | "requires" | "sources" | "world" | "open" | "closed" | "inverse" | "rezono"
            | "norm" | "exception" | "applies" | "replaces" | "deprecated" | "true" | "false" ) wordEnd
  // A contextual word is a name wherever it is not expected as a word; it is never a unit.
  contextual = ("during" | "order" | "group" | "limit") wordEnd

  name (a name) = ~keyword az (az | d | "_")* ~wordChar ~("-" wordChar)
  typeName (a kind name) = cap (az | cap | d)* ~wordChar ~("-" wordChar)
  idTok (an id) = (az | cap) wordChar* ("-" wordChar+)+
  oddWord (a word) = ~keyword (az | cap) wordChar* ~("-" wordChar)
  valueWord (a word) = keyword
  rowId (an id) = idTok | numTok | name | typeName | oddWord
  aggName (an aggregate) = ("sum" | "count" | "min" | "max" | "any" | "all" | "none") ~wordChar

  cmpOp = "<=" | ">=" | "!=" | "=" ~">" | "<" | ">"
  rangeOp = "..<" | ".."
  addOp = "+" | "-"
  mulOp = "*" | "/"
  state (a state: known, unknown, n/a or invalid) = known | stateWord
  stateWord = ("unknown" | "n/a" | "invalid") wordEnd

  literal (a value) = stateLit | boolLit | datetime | date | money | percent | quantity | number | text | typedText
          | typedId | numTok
  num = d+ ("." d+)? ("/" d+)?
  tokCont = wordChar | joint
  joint = ("-" | "." | "/" | ":") wordChar
  number (a number) = num ~tokCont
  quantity = num hsp+ unitWord
  percent = num hsp* "%"
  money = symbol+ hsp* num ("/" unitWord)? ~tokCont
  unitWord = ~(keyword | contextual) (az | cap) wordChar*
  symbol = ~(wordChar | letter | space | punct) any
  punct = "(" | ")" | "[" | "]" | "{" | "}" | "," | "." | ":" | ";" | "=" | "<" | ">" | "!" | "+" | "-" | "*"
        | "/" | "\"" | "'" | "\x60" | "|" | "@" | "#" | "%" | "&" | "?" | "^" | "~" | "\\"
  date = d d d d "-" d d "-" d d ~tokCont
  datetime = d d d d "-" d d "-" d d "T" d d ":" d d (":" d d)? zone? ~tokCont
  zone = "Z" | offset
  offset = ("+" | "-") d d ":" d d
  text = "\"" textChar* "\""
  textChar = escape | ~("\"" | "\\") any
  escape = "\\" any
  typedText = typeName text
  typedId = typeName ":" "\x60" (~"\x60" any)+ "\x60"
  stateLit = "n/a" wordEnd                     -- na
           | "unknown" hsp+ (reasonCode | text)  -- unknown
           | "invalid" hsp+ reasonCode           -- invalid
  reasonCode = ~keyword az (az | d | "_")* ~wordChar
  boolLit = ("true" | "false") wordEnd
  numTok = d (wordChar | inner)*
  inner = ("-" | "." | "/" | ":") &wordChar
}
`;

/** The grammar, built once: Ohm reads the text above, without generated code and without `eval`. */
export const grammar = ohm.grammar(source);
