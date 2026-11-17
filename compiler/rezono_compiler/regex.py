"""Regular expressions with one meaning on every engine.

Feldera matches with Rust's `regex` crate (`RLIKE`), DuckDB with RE2 (`regexp_matches`). Both search
(a pattern is not anchored unless it says `^` or `$`), but they differ in a few places: Unicode or ASCII
for `\\d`, `\\w`, `\\s` and `\\b`, nested classes and set operations (`[a-z&&[^x]]`) only in Rust, and
which escapes are allowed. `portable` accepts a subset on which they agree and writes it out explicitly:
shorthand classes become ASCII ranges and escaped characters become `\\xHH`. RE2 takes a count up to 1000,
also as the product of nested counts; Rust has no such limit, so a larger repetition is split into counts RE2
takes, with the same language (E10). What has no common meaning is an error with a reason.
"""

from __future__ import annotations

import re

HEX = "0123456789abcdefABCDEF"
SHORTHAND = {"d": "0-9", "w": "0-9A-Z_a-z", "s": "\\x09-\\x0D\\x20"}
CONTROL = {"n": 0x0A, "t": 0x09, "r": 0x0D, "f": 0x0C, "v": 0x0B}
REPEAT = re.compile(r"\{([0-9]+)(,([0-9]*))?\}")
MAX_REPEAT = 1000  # RE2's limit on a count, and on the product of nested counts


class PatternError(Exception):
    pass


def hexchar(c: str) -> str:
    return f"\\x{ord(c):02X}"


def repeat(atom: str, inner: int, low: int, high: int | None) -> tuple[str, int]:
    """`atom{low,high}` (high None: no upper bound) with no count above MAX_REPEAT // inner, where `inner` is
    the largest product of counts inside the atom, and the largest product of counts in the result.
    x{n,m} is x{n} x{0,m-n}, and x{a+b} is x{a} x{b}, so the language stays the same."""
    count = low if high is None else high
    if inner * count <= MAX_REPEAT:
        return f"{atom}{{{low}}}" if high == low else f"{atom}{{{low},{'' if high is None else high}}}", inner * max(count, 1)
    most = MAX_REPEAT // inner
    parts = [f"{atom}{{{most}}}"] * (low // most) + ([f"{atom}{{{low % most}}}"] if low % most else [])
    if high is None:
        parts.append(f"{atom}*")
    else:
        rest = high - low
        parts += [f"{atom}{{0,{most}}}"] * (rest // most) + ([f"{atom}{{0,{rest % most}}}"] if rest % most else [])
    return "".join(parts), inner * most


def portable(pattern: str) -> str:
    """The pattern in the portable subset, or PatternError with the reason."""
    out, i, n = [], 0, len(pattern)
    in_class = quantified = False
    class_start = 0  # where the open character class starts in `out`; set at its "["
    groups = [[0, 1]]  # per open group: where it starts in `out`, and the largest product of counts inside
    atom = None  # the last atom a repetition applies to: where it starts in `out`, the product of counts inside
    while i < n:
        c = pattern[i]
        start = len(out)
        if quantified and c == "+":  # Python 3.11+ accepts it, RE2 does not
            raise PatternError("a possessive quantifier ('*+', '++', '?+', '}+')")
        quantified = not in_class and (c in "*+?" or (c == "{" and REPEAT.match(pattern, i) is not None))
        if c == "\\":
            if i + 1 == n:
                raise PatternError("ends with a backslash")
            e = pattern[i + 1]
            i += 2
            if e.lower() in SHORTHAND:
                if in_class and (e.isupper() or (out[-1] == "-" and out[-2] not in ("[", "^"))
                                 or (pattern[i:i + 1] == "-" and pattern[i + 1:i + 2] != "]")):
                    raise PatternError(f"'\\{e}' inside a character class, negated or as the end of a range")
                body = SHORTHAND[e.lower()]
                out.append(body if in_class else (f"[^{body}]" if e.isupper() else f"[{body}]"))
            elif e in CONTROL:
                out.append(f"\\x{CONTROL[e]:02X}")
            elif e == "x":
                if pattern[i:i + 1] == "{":
                    end = pattern.find("}", i)
                    digits = pattern[i + 1:end] if end > 0 else ""
                    if not digits or len(digits) > 6 or any(d not in HEX for d in digits):
                        raise PatternError("'\\x{' needs one to six hex digits and '}'")
                    i, code = end + 1, int(digits, 16)
                else:
                    digits = pattern[i:i + 2]
                    if len(digits) != 2 or any(d not in HEX for d in digits):
                        raise PatternError("'\\x' needs two hex digits")
                    i, code = i + 2, int(digits, 16)
                if code > 0x10FFFF or 0xD800 <= code <= 0xDFFF:
                    raise PatternError(f"'\\x{{{code:X}}}' is not a character")
                out.append(f"\\x{code:02X}" if code < 0x80 else chr(code))
            elif e.isascii() and not e.isalnum() and e.isprintable():
                out.append(hexchar(e))
            else:
                raise PatternError(f"'\\{e}' has no meaning that Feldera and DuckDB share")
            if not in_class:
                atom = (start, 1)
        elif in_class:
            if c == "]":
                in_class = False
                out.append(c)
                atom = (class_start, 1)
            elif c == "[":
                raise PatternError("a '[' inside a character class (nested classes, POSIX classes)")
            elif pattern[i:i + 2] in ("&&", "--", "~~"):
                raise PatternError(f"'{pattern[i:i + 2]}' inside a character class (set operations)")
            else:
                out.append(c)
            i += 1
        elif c == "[":
            in_class, class_start = True, start
            out.append(c)
            i += 1
            if pattern[i:i + 1] == "^":
                out.append("^")
                i += 1
            if pattern[i:i + 1] == "]":  # a leading ']' is a literal
                out.append(hexchar("]"))
                i += 1
        elif c == "(" and pattern[i + 1:i + 2] == "?":
            if pattern[i + 2:i + 3] != ":":
                raise PatternError(f"'(?{pattern[i + 2:i + 3]}' (flags, names, look-around); only '(?:' is allowed")
            out.append("(?:")
            groups.append([start, 1])
            atom = None
            i += 3
        elif c == "{":
            m = REPEAT.match(pattern, i)
            if m is None:
                out.append(hexchar("{"))
                atom = (start, 1)
                i += 1
                continue
            low, high = int(m.group(1)), (None if m.group(3) == "" else int(m.group(3) or m.group(1)))
            if high is not None and high < low:
                raise PatternError(f"'{m.group(0)}' counts down")
            if atom is None:
                raise PatternError(f"'{m.group(0)}' has nothing to repeat")
            text, product = repeat("".join(out[atom[0]:]), atom[1], low, high)
            out[atom[0]:] = [text]
            groups[-1][1] = max(groups[-1][1], product)
            atom = None
            i = m.end()
        elif c == "}":
            out.append(hexchar("}"))
            atom = (start, 1)
            i += 1
        else:
            out.append(c)
            i += 1
            if c == "(":
                groups.append([start, 1])
                atom = None
            elif c == ")" and len(groups) > 1:
                begin, inner = groups.pop()
                groups[-1][1] = max(groups[-1][1], inner)
                atom = (begin, inner)
            elif c in "|^$*+?)":
                atom = None
            else:
                atom = (start, 1)
    if in_class:
        raise PatternError("an unclosed character class")
    result = "".join(out)
    try:
        re.compile(result)
    except re.error as e:
        raise PatternError(str(e)) from None
    return result
