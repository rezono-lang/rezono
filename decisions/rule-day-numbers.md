# Read a date text as a day number in a rule

A rule sometimes needs the day number of a date that is itself a conclusion. An example is the support end date of a published release series compared with a caller's day and horizon. A theory view can read a base date slot as days, but it cannot reach a derived relation. A rule file cannot yet write the `days` reading at all. So such a comparison cannot be stated.

## Choice

A `.dl` rule may write the existing `days` assignment as a user-functor call:

```prolog
ending_day(r, d) :- ending(r, e), d = @days(e, "1970-01-01").
```

- The first argument is a variable bound by a positive literal to text. The second is a constant ISO date in the `YYYY-MM-DD` spelling, the origin. The result is the whole number of days from the origin to the date, in the proleptic Gregorian calendar.
- A text that is not a calendar day derives nothing for that binding. That covers a malformed spelling, a day that does not exist and a word. It is not an error and not a zero.
- The call lowers to the rule IR's `days` assignment, which views already produce. Its DuckDB and Feldera SQL, its Soufflé text and the checker's recomputation stay as they are. The witness binds the text and the resulting number.
- A variable origin, a malformed origin constant and a non-text operand are compile errors.

`@name(...)` is Soufflé's spelling for a functor, so a rule file stays readable as Datalog. No `.functor` declaration is needed, because `days` is reserved by the compiler.

## Alternatives considered

- **Read a DATE column in rules.** The independent date equality decision adds `date` columns to rules, but only for equality. It does not give arithmetic on a date that a rule derived as text.
- **A view over the derived relation.** Views read base slots by design. Letting them read conclusions would mix layers.
- **A precomputed day-number fact.** That copies the date into a second fact with no link to the first, which is the kind of supplied value a rule should derive.
