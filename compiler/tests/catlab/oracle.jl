# The independent oracle for schema operations (docs/compiler.md#the-oracle-catlab, decision R3). Tests only.
#
#   julia --project=compiler/tests/catlab compiler/tests/catlab/oracle.jl cases.json results.json
#
# A case is a schema in normal form (one table per kind and per slot), the fact states as rows of text, and the
# operation as the author wrote it, with its names resolved. From the operation alone the oracle builds the new
# schema and the functor between the two, and migrates every state with Catlab's Δ (`migrate!`), and back with
# the inverse functor. It shares no code with the compiler: it derives the engine names, which the embedded ids
# are made of, from the declared names alone (decision S8), before and after the operation.
#
# One case is no operation: `glue` (B10). It gives the parts of a pack and the modules they share, and the oracle
# builds the one pack as their colimit, the schema and every fact state, without ever seeing that pack.
#
# Encoding: an ACSet has total functions, so a dangling reference cannot be a span between kind tables. One
# object `Id` holds every identifier, with its text as `label`; each table is an object with `src` into `Id`,
# and for a slot either `dst` into `Id` (an arrow) or `val` (an attribute, as text). Duplicates stay parts.

using ACSets, Catlab, JSON

struct Table
  key::String            # "module#Class" for a kind, "module#Class.slot" for a slot
  kind::String           # "module#Class"
  slot::Union{Nothing,String}
  arrow::Bool
  enum::Union{Nothing,String}
end

function schema(tables::Vector{Table})
  obs = Symbol[:Id]
  homs = Tuple{Symbol,Symbol,Symbol}[]
  attrs = Tuple{Symbol,Symbol,Symbol}[(:label, :Id, :Label)]
  for (i, t) in enumerate(tables)
    push!(obs, Symbol("T$i"))
    push!(homs, (Symbol("src$i"), Symbol("T$i"), :Id))
    if t.slot !== nothing
      t.arrow ? push!(homs, (Symbol("dst$i"), Symbol("T$i"), :Id)) :
                push!(attrs, (Symbol("val$i"), Symbol("T$i"), :Val))
    end
  end
  BasicSchema(obs, homs, [:Label, :Val], attrs)
end

acset_type(s) = AnonACSetType(s; type_assignment=Dict{Symbol,Type}(:Label => String, :Val => String))

function instance(T, tables::Vector{Table}, rows::Dict)
  X = T()
  ids = Dict{String,Int}()
  id(x) = get!(ids, x) do
    add_part!(X, :Id; label=x)
  end
  for (i, t) in enumerate(tables)
    for r in get(rows, t.key, [])
      if t.slot === nothing
        add_part!(X, Symbol("T$i"); Symbol("src$i") => id(r[1]))
      elseif t.arrow
        add_part!(X, Symbol("T$i"); Symbol("src$i") => id(r[1]), Symbol("dst$i") => id(r[2]))
      else
        add_part!(X, Symbol("T$i"); Symbol("src$i") => id(r[1]), Symbol("val$i") => r[2])
      end
    end
  end
  X
end

function rows(X, tables::Vector{Table})
  out = Dict{String,Vector{Vector{String}}}()
  label(p) = subpart(X, p, :label)
  for (i, t) in enumerate(tables)
    rs = Vector{String}[]
    for p in parts(X, Symbol("T$i"))
      src = label(subpart(X, p, Symbol("src$i")))
      if t.slot === nothing
        push!(rs, [src])
      elseif t.arrow
        push!(rs, [src, label(subpart(X, p, Symbol("dst$i")))])
      else
        push!(rs, [src, subpart(X, p, Symbol("val$i"))])
      end
    end
    isempty(rs) || (out[t.key] = sort(rs))
  end
  out
end

"""Δ along the functor that sends table `i` of `to` to table `source[i]` of `from`, and Id, label and the
attribute types to themselves."""
function delta(X, from::Vector{Table}, to::Vector{Table}, source::Vector{Int})
  Sf, St = schema(from), schema(to)
  Pf, Pt = Presentation(Sf), Presentation(St)
  FOb = Dict{Any,Any}(Pt[:Id] => Pf[:Id], Pt[:Label] => Pf[:Label], Pt[:Val] => Pf[:Val])
  FHom = Dict{Any,Any}(Pt[:label] => Pf[:label])
  for (i, t) in enumerate(to)
    j = source[i]
    FOb[Pt[Symbol("T$i")]] = Pf[Symbol("T$j")]
    FHom[Pt[Symbol("src$i")]] = Pf[Symbol("src$j")]
    if t.slot !== nothing
      g = t.arrow ? "dst" : "val"
      FHom[Pt[Symbol("$g$i")]] = Pf[Symbol("$g$j")]
    end
  end
  migrate!(acset_type(St)(), X, FOb, FHom; homtype=:hom)
end

# --- Engine names (S8), from the declared classes and enums --------------------------------------------------

snake(n::AbstractString) = lowercase(replace(n, r"(?<=[a-z0-9])(?=[A-Z])" => "_"))

"""The engine name of every class and enum, keyed "module#Name": its snake-case name, or with the module in
front when another module declares the same snake-case name."""
function engine_names(declared::Vector{Tuple{String,String}})
  count = Dict{String,Int}()
  for (_, n) in unique(declared)
    count[snake(n)] = get(count, snake(n), 0) + 1
  end
  Dict("$m#$n" => (count[snake(n)] > 1 ? replace(m, r"[/:-]" => "_") * "_" * snake(n) : snake(n))
       for (m, n) in declared)
end

"""The engine element of a table key: the kind's engine name, then `.slot` for a slot."""
function element_of(names::Dict, key::String)
  kind, _, slot = partition(key, '.')
  isempty(slot) ? names[kind] : names[kind] * "." * slot
end

# --- rename, from the operation ------------------------------------------------------------------------------

"""The declared names after a rename of a class or an enum."""
function renamed_declared(op, declared::Vector{Tuple{String,String}})
  target = op["what"] == "kind" ? op["kind"] : op["what"] == "enum" ? op["enum"] : nothing
  [("$m#$n" == target ? (m, String(op["to"])) : (m, n)) for (m, n) in declared]
end

"""The new key of an element: a renamed class carries its slots along; a renamed slot only itself."""
function renamed_key(op, key::String)
  kind, _, slot = partition(key, '.')
  if op["what"] == "kind" && kind == op["kind"]
    module_ = split(kind, '#')[1]
    kind = "$(module_)#$(op["to"])"
  elseif op["what"] == "slot" && kind == op["kind"] && slot == op["slot"]
    slot = op["to"]
  end
  isempty(slot) ? kind : "$kind.$slot"
end

function partition(s::String, c::Char)
  i = findfirst(==(c), s)
  i === nothing ? (s, "", "") : (s[1:prevind(s, i)], string(c), s[nextind(s, i):end])
end

const UNRESERVED = Set(collect("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.-~"))
escape(s::String) = join(Char(b) in UNRESERVED ? string(Char(b)) : "%" * uppercase(string(b, base=16, pad=2))
                         for b in codeunits(s))

function unescape_all(s::String)
  bytes, i, cu = UInt8[], 1, codeunits(s)
  while i <= length(cu)
    if cu[i] == UInt8('%') && i + 2 <= length(cu)
      push!(bytes, parse(UInt8, String(cu[i+1:i+2]), base=16))
      i += 3
    else
      push!(bytes, cu[i])
      i += 1
    end
  end
  String(bytes)
end

"""The id of an embedded element after the operation: owner (itself mapped), then the engine element of the
slot it sits in, then its position. The engine element names come from the case."""
function relabel(x::String, embedded::Set{String}, element::Dict{String,String}, memo::Dict{String,String};
                 absorbed::Union{Nothing,String}=nothing)
  x in embedded || return x
  haskey(memo, x) && return memo[x]
  parts = split(x, '/')
  n = length(parts) == 3 ? "/" * parts[3] : ""
  owner = relabel(unescape_all(String(parts[1])), embedded, element, memo; absorbed=absorbed)
  # with `absorbed` (the element of the arrow a combine absorbs), what that arrow held is its owner now
  memo[x] = (absorbed !== nothing && length(parts) == 2 && parts[2] == absorbed) ? owner :
            escape(owner) * "/" * get(element, String(parts[2]), String(parts[2])) * n
end

# --- drop, from the operation --------------------------------------------------------------------------------

"""The owner of a derived id made by the slot whose engine element is `element`, or nothing."""
function owner_of(v::String, element::String)
  parts = split(v, '/')
  (length(parts) in (2, 3) && parts[2] == element && (length(parts) == 2 || all(isdigit, parts[3]))) || return nothing
  unescape_all(String(parts[1]))
end

function drop_case(case)
  op = case["op"]
  info = Dict(String(t["key"]) => t for t in case["tables"])
  tables = [Table(t["key"], t["kind"], t["slot"], t["arrow"], t["enum"]) for t in case["tables"]]
  kinds = [t for t in tables if t.slot === nothing]
  slots_of(k) = [t.key for t in tables if t.slot !== nothing && t.kind == k]
  function ancestors(k)  # a local of its own: a nested function shares the enclosing function's `out`
    local chain = String[]
    while k !== nothing
      push!(chain, k)
      k = info[k]["parent"]
    end
    chain
  end
  # What goes: the kind with its slots, or the slot; then every kind without an identifier that no slot left
  # can hold.
  selection = op["op"] == "select"
  D = Set{String}(selection ? op["kinds"] : op["what"] == "kind" ? [op["kind"]] : String[])
  S = selection ? union(Set{String}(op["slots"]), Set{String}(s for k in D for s in slots_of(k))) :
                 Set{String}(op["what"] == "kind" ? slots_of(op["kind"]) : ["$(op["kind"]).$(op["slot"])"])
  # A select names its entire retained schema explicitly; unlike drop, it does not implicitly remove types.
  grow = !selection
  while grow
    grow = false
    for k in kinds
      (k.key in D || info[k.key]["ident"]) && continue
      holders = [t for t in tables if t.slot !== nothing && info[t.key]["owned"] && !(t.key in S) &&
                 info[t.key]["range"] in ancestors(k.key)]
      if isempty(holders)
        push!(D, k.key)
        union!(S, slots_of(k.key))
        grow = true
      end
    end
  end
  going = union(D, S)
  declared = [(String(d[1]), String(d[2])) for d in case["declared"]]
  names_old = engine_names(declared)
  names_new = engine_names([d for d in declared if !("$(d[1])#$(d[2])" in D)])
  element = Dict(element_of(names_old, t.key) => element_of(names_new, t.key) for t in tables
                 if t.slot !== nothing && !(t.key in going))
  root(k) = ancestors(k)[end]
  new_tables = [t for t in tables if !(t.key in going)]
  forward = Int[findfirst(x -> x.key == t.key, tables) for t in new_tables]
  embedded = Set{String}(case["embedded"])
  T = acset_type(schema(tables))
  out = []
  for state in case["states"]
    rows_in = state["rows"]
    gone = Set{Tuple{String,String}}()
    seeds = selection ? D : op["what"] == "kind" ? [op["kind"]] : String[]
    for k in seeds
      foreach(r -> push!(gone, (root(k), r[1])), get(rows_in, k, []))
    end
    grow = true
    while grow
      grow = false
      for t in tables
        (t.slot !== nothing && info[t.key]["owned"]) || continue
        for r in get(rows_in, t.key, [])
          owner_of(String(r[2]), element_of(names_old, t.key)) == r[1] || continue
          key = (root(info[t.key]["range"]), String(r[2]))
          removed_slot = selection ? t.key in op["slots"] :
                         (op["what"] == "slot" && t.key == "$(op["kind"]).$(op["slot"])")
          if !(key in gone) && ((root(t.kind), r[1]) in gone || removed_slot)
            push!(gone, key)
            grow = true
          end
        end
      end
    end
    X = instance(T, tables, rows_in)
    for (i, t) in enumerate(tables)  # the rows of the elements that go: a selection before Δ
      ob, src = Symbol("T$i"), Symbol("src$i")
      doomed = [p for p in parts(X, ob) if (root(t.kind), subpart(X, subpart(X, p, src), :label)) in gone]
      rem_parts!(X, ob, sort(doomed))
    end
    kept = rows(X, tables)
    lost = Dict{String,Vector{Vector{String}}}()
    for t in tables
      have = Dict{Vector{String},Int}()
      t.key in going || foreach(r -> have[r] = get(have, r, 0) + 1, get(kept, t.key, []))  # a table that goes loses all
      miss = Vector{String}[]
      for r in sort([Vector{String}(r) for r in get(rows_in, t.key, [])])
        if get(have, r, 0) > 0
          have[r] -= 1
        else
          push!(miss, r)
        end
      end
      isempty(miss) || (lost[t.key] = miss)
    end
    Y = rows(delta(X, tables, new_tables, forward), new_tables)
    memo = Dict{String,String}()
    after = Dict(k => sort([begin
      r = [relabel(String(r[1]), embedded, element, memo); r[2:end]]
      if length(r) == 2 && info[k]["arrow"]
        r[2] = relabel(String(r[2]), embedded, element, memo)
      end
      r
    end for r in rs]) for (k, rs) in Y)
    push!(out, Dict{String,Any}("name" => state["name"], "after" => after, "lost" => lost))
  end
  out
end

# --- move, from the operation --------------------------------------------------------------------------------

"""Rows per key as a multiset key -> sorted rows, minus another (the rows of `a` that `b` lacks)."""
function minus(a::Dict, b::Dict)
  out = Dict{String,Vector{Vector{String}}}()
  for (k, rs) in a
    have = Dict{Vector{String},Int}()
    foreach(r -> have[r] = get(have, r, 0) + 1, get(b, k, []))
    miss = Vector{String}[]
    for r in sort([Vector{String}(r) for r in rs])
      get(have, r, 0) > 0 ? (have[r] -= 1) : push!(miss, r)
    end
    isempty(miss) || (out[k] = miss)
  end
  out
end

const SETS = FinSetC()

"""The inner join of table `i` and table `j` of X on an Id column (`hi` of i equal to `hj` of j): Catlab's
pullback in FinSet of the two maps into Id. The pairs of parts (p of i, q of j), sorted.

Catlab 0.17.6 takes a leg with a one-element domain as a constant and then fails (`impl_type` of a
ConstantFunction). So each leg gets two extra elements on a point of its own, which never meet the other leg,
and the pairs keep only real parts."""
function join_parts(X, i::Int, hi::String, j::Int, hj::String)
  a = Int[subpart(X, p, Symbol("$hi$i")) for p in parts(X, Symbol("T$i"))]
  b = Int[subpart(X, q, Symbol("$hj$j")) for q in parts(X, Symbol("T$j"))]
  pullback_pairs(a, b, nparts(X, :Id))
end

"""The pullback in FinSet of a: A → n and b: B → n, as pairs of elements of A and B. Each leg is padded with two
elements of its own, which Catlab 0.17.6 needs (a one-element leg fails); they never meet."""
function pullback_pairs(a::Vector{Int}, b::Vector{Int}, n::Int)
  f = FinFunction([a; n + 1; n + 1], n + 2)
  g = FinFunction([b; n + 2; n + 2], n + 2)
  lim = pullback[SETS](f, g)
  π1, π2 = legs(lim)
  sort([(Int(π1(e)), Int(π2(e))) for e in ob(lim) if π1(e) <= length(a) && π2(e) <= length(b)])
end

# The elements of kind `k` in X: the sources of its own table.
members_of(X, tables, k) = Set(subpart(X, subpart(X, p, Symbol("src$(findfirst(t -> t.key == k, tables))")), :label)
                               for p in parts(X, Symbol("T$(findfirst(t -> t.key == k, tables))")))

function move_case(case)
  op = case["op"]
  info = Dict(String(t["key"]) => t for t in case["tables"])
  tables = [Table(t["key"], t["kind"], t["slot"], t["arrow"], t["enum"]) for t in case["tables"]]
  function ancestors(k)  # a local of its own: a nested function shares the enclosing function's `out`
    local chain = String[]
    while k !== nothing
      push!(chain, k)
      k = info[k]["parent"]
    end
    chain
  end
  ka = "$(op["kind"]).$(op["slot"])"
  la = "$(op["to"]).$(op["slot"])"
  src = tables[findfirst(t -> t.key == ka, tables)]
  new_tables = [t.key == ka ? Table(la, op["to"], t.slot, t.arrow, t.enum) : t for t in tables]
  forward = collect(1:length(tables))
  i_ka = findfirst(t -> t.key == ka, tables)
  # The direction, from the operation as written: along is_a, or across the arrow toward its source or target.
  if op["via"] === nothing
    mode = op["to"] in ancestors(op["kind"]) ? "up" : "down"
    f = nothing
  else
    mode = op["via"][1] == op["to"] ? "source" : "target"
    side_kind = mode == "source" ? op["to"] : op["kind"]
    f = first(k for k in ("$a.$(op["via"][2])" for a in ancestors(op["via"][1])) if haskey(info, k))
  end
  declared = [(String(d[1]), String(d[2])) for d in case["declared"]]
  names = engine_names(declared)
  element = Dict(element_of(names, ka) => element_of(names, la))
  embedded = Set{String}(case["embedded"])
  T = acset_type(schema(tables))
  out = []
  for state in case["states"]
    X = instance(T, tables, state["rows"])
    label(p) = subpart(X, p, :label)
    vals = [(label(subpart(X, p, Symbol("src$i_ka"))),
             src.arrow ? label(subpart(X, p, Symbol("dst$i_ka"))) : subpart(X, p, Symbol("val$i_ka")))
            for p in parts(X, Symbol("T$i_ka"))]
    by_x = Dict{String,Vector{String}}()
    foreach(((x, v),) -> push!(get!(by_x, x, String[]), v), vals)
    conflicts = String[]
    if mode in ("up", "down")
      if mode == "down"  # the selection: values of elements that are not in `to` stay behind
        j = findfirst(t -> t.key == op["to"], tables)
        members = Set(label(subpart(X, p, Symbol("src$j"))) for p in parts(X, Symbol("T$j")))
        rem_parts!(X, Symbol("T$i_ka"), sort([p for p in parts(X, Symbol("T$i_ka"))
                                              if !(label(subpart(X, p, Symbol("src$i_ka"))) in members)]))
      end
      moved = rows(delta(X, tables, new_tables, forward), new_tables)
    else  # across the arrow: a join of the arrow's table with the slot's table, Catlab's pullback in FinSet
      j = findfirst(t -> t.key == f, tables)
      fsrc = p -> label(subpart(X, p, Symbol("src$j")))
      fdst = p -> label(subpart(X, p, Symbol("dst$j")))
      value = q -> vals[q][2]
      # The arrow may be inherited from an ancestor: only its rows from elements of the kind on its side count.
      side = members_of(X, tables, side_kind)
      fparts = [p for p in parts(X, Symbol("T$j")) if fsrc(p) in side]
      nvals = Dict{String,Int}()
      foreach(p -> nvals[fsrc(p)] = get(nvals, fsrc(p), 0) + 1, fparts)
      for (a, n) in sort(collect(nvals))
        n > 1 && push!(conflicts, "$a has $n values of $f")
      end
      moved_rows = Vector{String}[]
      reached = Set{Int}()
      if mode == "source"  # to.f: y -> x; y takes the values of x: F ⋈ A on dst_F = src_A
        for (p, q) in join_parts(X, j, "dst", i_ka, "src")
          get(nvals, fsrc(p), 0) == 1 || continue
          push!(moved_rows, [fsrc(p), value(q)])
          push!(reached, q)
        end
      else  # kind.f: x -> y; A ⋈ F on src_A = src_F, then y takes the values its sources share
        bags = Dict{String,Dict{String,Vector{String}}}()  # y -> every source x -> its values
        for p in fparts
          nvals[fsrc(p)] == 1 && (get!(bags, fdst(p), Dict{String,Vector{String}}())[fsrc(p)] = String[])
        end
        for (q, p) in join_parts(X, i_ka, "src", j, "src")
          get(nvals, fsrc(p), 0) == 1 || continue
          push!(bags[fdst(p)][fsrc(p)], value(q))
          push!(reached, q)
        end
        for (y, by_source) in sort(collect(bags))
          kinds_of = unique([sort(v) for v in values(by_source)])
          length(kinds_of) > 1 && (push!(conflicts, "sources of $y differ"); continue)
          foreach(v -> push!(moved_rows, [y, v]), kinds_of[1])
        end
      end
      kept = Dict(t.key => [Vector{String}(r) for r in get(state["rows"], t.key, [])] for t in tables if t.key != ka)
      kept[la] = moved_rows
      moved = Dict(k => sort(v) for (k, v) in kept if !isempty(v))
    end
    lost_rows = Vector{String}[]
    if mode == "down"
      members = Set(r[1] for r in get(moved, la, []))
      foreach(((x, v),) -> (x in members || push!(lost_rows, [x, v])), vals)
    elseif mode in ("source", "target")
      foreach(q -> (q in reached || push!(lost_rows, collect(vals[q]))), 1:length(vals))
    end
    lost = isempty(lost_rows) ? Dict{String,Any}() : Dict{String,Any}(ka => sort(lost_rows))
    memo = Dict{String,String}()
    after = Dict(k => sort([begin
      r = [relabel(String(r[1]), embedded, element, memo); r[2:end]]
      (length(r) == 2 && info[k == la ? ka : k]["arrow"]) && (r[2] = relabel(String(r[2]), embedded, element, memo))
      r
    end for r in rs]) for (k, rs) in moved)
    back = nothing
    if isempty(lost) && isempty(conflicts)  # the inverse, from M(X) and the operation alone
      inv = Dict(v => k for (k, v) in memo)
      unl(x) = get(inv, x, x)
      Y = Dict(k => [[unl(r[1]); (length(r) == 2 && info[k == la ? ka : k]["arrow"]) ? [unl(r[2])] : r[2:end]]
                     for r in rs] for (k, rs) in after)
      back_rows = Dict{String,Vector{Vector{String}}}(k => rs for (k, rs) in Y if k != la)
      if mode in ("up", "down")
        give = get(Y, la, [])
      else  # the inverse joins on the migrated state, in the new schema, with Catlab's pullback again
        Xn = instance(acset_type(schema(new_tables)), new_tables, Y)
        nl = p -> subpart(Xn, p, :label)
        j = findfirst(t -> t.key == f, new_tables)
        nside = members_of(Xn, new_tables, side_kind)
        onside = p -> nl(subpart(Xn, p, Symbol("src$j"))) in nside
        nvalue = q -> src.arrow ? nl(subpart(Xn, q, Symbol("dst$i_ka"))) : subpart(Xn, q, Symbol("val$i_ka"))
        if mode == "target"  # x takes the values of f(x): F ⋈ A' on dst_F = src_A'
          give = [[nl(subpart(Xn, p, Symbol("src$j"))), nvalue(q)] for (p, q) in join_parts(Xn, j, "dst", i_ka, "src")
                  if onside(p)]
        else  # x takes the values of the first y that points to it: F ⋈ A' on src_F = src_A'
          firsts = Dict{String,String}()
          for p in sort(filter(onside, collect(parts(Xn, Symbol("T$j")))), by=p -> nl(subpart(Xn, p, Symbol("src$j"))))
            x, y = nl(subpart(Xn, p, Symbol("dst$j"))), nl(subpart(Xn, p, Symbol("src$j")))
            haskey(firsts, x) || (firsts[x] = y)
          end
          give = [[nl(subpart(Xn, p, Symbol("dst$j"))), nvalue(q)] for (p, q) in join_parts(Xn, j, "src", i_ka, "src")
                  if onside(p) && firsts[nl(subpart(Xn, p, Symbol("dst$j")))] == nl(subpart(Xn, p, Symbol("src$j")))]
        end
      end
      isempty(give) || (back_rows[ka] = sort(give))
      back = Dict(k => sort(v) for (k, v) in back_rows if !isempty(v))
      orig = Dict(String(k) => sort([Vector{String}(r) for r in rs]) for (k, rs) in state["rows"] if !isempty(rs))
      back == orig || push!(conflicts, "the round trip invents or loses rows")
    end
    push!(out, Dict{String,Any}("name" => state["name"], "after" => after, "lost" => lost, "conflicts" => conflicts,
                    "back" => back))
  end
  out
end

# --- split_by, from the operation ----------------------------------------------------------------------------

function split_case(case)
  op = case["op"]
  tables = [Table(t["key"], t["kind"], t["slot"], t["arrow"], t["enum"]) for t in case["tables"]]
  info = Dict(String(t["key"]) => t for t in case["tables"])
  kd = "$(op["kind"]).$(op["slot"])"
  mod = split(op["kind"], '#')[1]
  cases = Dict(String(c[1]) => "$mod#$(c[2])" for c in op["cases"])
  subs = sort(unique(collect(values(cases))))
  kept = [t for t in tables if t.key != kd]
  new_tables = vcat(kept, [Table(s, s, nothing, false, nothing) for s in subs])
  declared = [(String(d[1]), String(d[2])) for d in case["declared"]]
  names_old = engine_names(declared)
  names_new = engine_names(vcat(declared, [(String(mod), String(c[2])) for c in op["cases"]]))
  element = Dict(element_of(names_old, t.key) => element_of(names_new, t.key) for t in tables
                 if t.slot !== nothing && t.key != kd)
  embedded = Set{String}(case["embedded"])
  i_k = findfirst(t -> t.key == op["kind"], tables)
  i_d = findfirst(t -> t.key == kd, tables)
  T = acset_type(schema(tables))
  out = []
  for state in case["states"]
    X = instance(T, tables, state["rows"])
    label = p -> subpart(X, p, :label)
    n = nparts(X, :Id)
    ksrc = Int[subpart(X, p, Symbol("src$i_k")) for p in parts(X, Symbol("T$i_k"))]
    dsrc = Int[subpart(X, q, Symbol("src$i_d")) for q in parts(X, Symbol("T$i_d"))]
    dval = String[subpart(X, q, Symbol("val$i_d")) for q in parts(X, Symbol("T$i_d"))]
    # The values as a finite set, every case value included, so a selection is a pullback along a point
    V = sort(unique(vcat(dval, collect(keys(cases)))))
    at = Dict(v => i for (i, v) in enumerate(V))
    dv = Int[at[v] for v in dval]
    # The kinds and slots that stay: Δ along their inclusion in the old schema
    moved = rows(delta(X, tables, kept, Int[findfirst(u -> u.key == t.key, tables) for t in kept]), kept)
    kept_rows = Set{Int}()  # the value rows a subkind keeps
    for (v, s) in sort(collect(cases))
      sel = Int[q for (q, _) in pullback_pairs(dv, [at[v]], length(V))]  # σ_{d = v}: the pullback along v
      # the subkind: σ ⋉ K, the image of the pullback's leg on σ, one row per value row (its record moves)
      qs = sort(unique(Int[sel[i] for (i, _) in pullback_pairs(dsrc[sel], ksrc, n)]))
      isempty(qs) || (moved[s] = sort([[label(dsrc[q])] for q in qs]))
      union!(kept_rows, qs)
    end
    # Checks, not the migration: an element with two values, and in an abstract kind one without a case
    conflicts = String[]
    with_k = Set(Int[q for (q, _) in pullback_pairs(dsrc, ksrc, n)])
    for x in sort(unique(ksrc))
      vs = unique(dval[[q for q in eachindex(dsrc) if dsrc[q] == x]])
      length(vs) > 1 && push!(conflicts, "$(label(x)) has $(length(vs)) values")
      op["abstract"] && (isempty(vs) || !haskey(cases, vs[1])) && push!(conflicts, "$(label(x)) has no case")
    end
    # The loss: every value row that no subkind keeps (without a case, or without an element)
    lost_rows = [[label(dsrc[q]), dval[q]] for q in eachindex(dsrc) if !(q in kept_rows)
                 && !(op["abstract"] && q in with_k)]
    memo = Dict{String,String}()
    after = Dict(k => sort([begin
      r = [relabel(String(r[1]), embedded, element, memo); r[2:end]]
      (length(r) == 2 && haskey(info, k) && info[k]["arrow"]) && (r[2] = relabel(String(r[2]), embedded, element, memo))
      r
    end for r in rs]) for (k, rs) in moved if !isempty(rs))  # a subkind table is new: not in info
    lost = isempty(lost_rows) ? Dict{String,Any}() : Dict{String,Any}(kd => sort(lost_rows))
    back = nothing
    if isempty(lost_rows) && isempty(conflicts)  # the inverse, from M(X) and the operation alone
      inv = Dict(v => k for (k, v) in memo)
      Y = Dict(k => [[get(inv, r[1], r[1]); (length(r) == 2 && haskey(info, k) && info[k]["arrow"]) ?
                      [get(inv, r[2], r[2])] : r[2:end]] for r in rs] for (k, rs) in after)
      Xn = instance(acset_type(schema(new_tables)), new_tables, Y)
      # Δ back along the inclusion of the kept tables, and Σ of the subkinds into the slot: x ↦ (x, v)
      back = rows(delta(Xn, new_tables, kept, collect(1:length(kept))), kept)
      give = Vector{String}[]
      for (v, s) in cases
        j = findfirst(t -> t.key == s, new_tables)
        append!(give, [[subpart(Xn, subpart(Xn, p, Symbol("src$j")), :label), v] for p in parts(Xn, Symbol("T$j"))])
      end
      isempty(give) || (back[kd] = sort(give))
    end
    push!(out, Dict{String,Any}("name" => state["name"], "after" => after, "lost" => lost, "conflicts" => conflicts,
                    "back" => back))
  end
  out
end

# --- combine, from the operation -----------------------------------------------------------------------------

"""`kind` absorbs `absorb` across the arrow `via`: kind.f -> absorb (target) or absorb.f -> kind (source). Each
absorbed slot table joins the arrow's table on the absorbed element (Catlab's pullback in FinSet), so its values
land on the kind's element; with `key` the arrow's rows to an existing absorbed element become the key. The
inverse joins the key with the landed tables on the migrated state, or rebuilds an absorbed element without an
identifier of its own from its owner and the arrow (a derived id)."""
function combine_case(case)
  op = case["op"]
  info = Dict(String(t["key"]) => t for t in case["tables"])
  tables = [Table(t["key"], t["kind"], t["slot"], t["arrow"], t["enum"]) for t in case["tables"]]
  k, a = String(op["kind"]), String(op["absorb"])
  f = "$(op["via"][1]).$(op["via"][2])"
  target = op["via"][1] == op["kind"]
  key = op["key"] === nothing ? nothing : String(op["key"])
  keyed = key === nothing ? nothing : "$k.$key"
  derived = !info[a]["ident"]
  back_ids = key !== nothing || derived
  absorbed = [t for t in tables if t.slot !== nothing && t.kind == a && t.key != f]
  landed(t) = "$k.$(t.slot)"
  going = Set{String}(vcat([a, f], [t.key for t in absorbed]))
  new_tables = vcat([t for t in tables if !(t.key in going)],
                    [Table(landed(t), k, t.slot, t.arrow, t.enum) for t in absorbed],
                    key === nothing ? Table[] : [Table(keyed, k, key, false, nothing)])
  arrow_keys = Set{String}(t.key for t in new_tables if t.arrow)
  declared = [(String(d[1]), String(d[2])) for d in case["declared"]]
  names_old = engine_names(declared)
  names_new = engine_names([d for d in declared if "$(d[1])#$(d[2])" != a])
  f_el = element_of(names_old, f)
  element = Dict{String,String}()
  for t in tables
    (t.slot === nothing || t.key == f) && continue
    element[element_of(names_old, t.key)] = element_of(names_new, t.kind == a ? landed(t) : t.key)
  end
  embedded = Set{String}(case["embedded"])
  T = acset_type(schema(tables))
  j = findfirst(t -> t.key == f, tables)
  out = []
  for state in case["states"]
    rows_in = state["rows"]
    X = instance(T, tables, rows_in)
    label(p) = subpart(X, p, :label)
    fsrc = p -> label(subpart(X, p, Symbol("src$j")))
    fdst = p -> label(subpart(X, p, Symbol("dst$j")))
    mine(p) = target ? fsrc(p) : fdst(p)  # the kind's element of an arrow row
    theirs(p) = target ? fdst(p) : fsrc(p)  # the absorbed element
    members = members_of(X, tables, a)
    conflicts = String[]
    nlinks = Dict{String,Int}()
    foreach(p -> nlinks[fsrc(p)] = get(nlinks, fsrc(p), 0) + 1, parts(X, Symbol("T$j")))
    for (s, n) in sort(collect(nlinks))
      n > 1 && push!(conflicts, "$s has $n values of $f")
    end
    reach = Dict{String,Set{String}}()  # the arrow's target, reached by more than one source: one absorbed
    # element on two elements of the kind (k.f -> a), or two absorbed elements on one (a.f -> k)
    foreach(p -> push!(get!(reach, fdst(p), Set{String}()), fsrc(p)), parts(X, Symbol("T$j")))
    for (y, xs) in sort(collect(reach), by=first)  # a Set has no order: sort by the element
      length(xs) > 1 && push!(conflicts, "$y is reached by $(length(xs))")
    end
    nrec = Dict{String,Int}()
    foreach(r -> nrec[r[1]] = get(nrec, r[1], 0) + 1, get(rows_in, a, []))
    for (y, n) in sort(collect(nrec))
      n > 1 && push!(conflicts, "$y has $n records")
    end
    moved = Dict{String,Vector{Vector{String}}}()
    for t in tables
      t.key in going && continue
      rs = [Vector{String}(r) for r in get(rows_in, t.key, [])]
      isempty(rs) || (moved[t.key] = rs)
    end
    lost = Dict{String,Vector{Vector{String}}}()
    used_links = Set{Int}()
    carried = Set{String}()  # absorbed elements with a value that came along
    for t in absorbed  # A ⋈ F on the absorbed element: the values land on the kind's element
      i = findfirst(x -> x.key == t.key, tables)
      value = q -> t.arrow ? label(subpart(X, q, Symbol("dst$i"))) : subpart(X, q, Symbol("val$i"))
      reached = Set{Int}()
      for (p, q) in join_parts(X, j, target ? "dst" : "src", i, "src")
        nlinks[fsrc(p)] == 1 || continue
        y = theirs(p)
        back_ids && !(y in members) && continue
        push!(get!(moved, landed(t), Vector{String}[]), [mine(p), value(q)])
        push!(reached, q)
        push!(carried, y)
        back_ids && push!(used_links, p)
      end
      for q in parts(X, Symbol("T$i"))
        q in reached || push!(get!(lost, t.key, Vector{String}[]), [label(subpart(X, q, Symbol("src$i"))), value(q)])
      end
    end
    if key !== nothing  # the arrow's rows to an existing absorbed element: the key
      for p in parts(X, Symbol("T$j"))
        theirs(p) in members || continue
        push!(get!(moved, keyed, Vector{String}[]), [mine(p), theirs(p)])
        push!(used_links, p)
      end
    end
    keyed_ids = Set(theirs(p) for p in used_links)
    kept_a(y) = key !== nothing ? y in keyed_ids : (derived && y in carried)
    for r in get(rows_in, a, [])
      kept_a(String(r[1])) || push!(get!(lost, a, Vector{String}[]), Vector{String}(r))
    end
    for p in parts(X, Symbol("T$j"))
      p in used_links || push!(get!(lost, f, Vector{String}[]), [fsrc(p), fdst(p)])
    end
    memo = Dict{String,String}()
    # an absorbed id collapses into its owner only as the owner of what it held; as a value it is no id of an
    # element that stays, so it is left as it is (another kind's explicit id may have the same text)
    is_absorbed(x) = derived && x in embedded && split(x, '/')[2:end] == [f_el]
    rl(x) = is_absorbed(x) ? x : relabel(x, embedded, element, memo; absorbed=f_el)
    after = Dict(kk => sort([begin
      r = [rl(String(r[1])); r[2:end]]
      (length(r) == 2 && kk in arrow_keys) && (r[2] = rl(String(r[2])))
      r
    end for r in rs]) for (kk, rs) in moved if !isempty(rs))
    lost = Dict{String,Any}(kk => sort(rs) for (kk, rs) in lost)
    back = nothing
    if isempty(lost) && isempty(conflicts) && back_ids  # the inverse, from M(X) and the operation alone
      gone_ids = Set(x for x in keys(memo) if is_absorbed(x))
      inv = Dict(v => x for (x, v) in memo if !(x in gone_ids))
      unl(x) = get(inv, x, x)
      Y = Dict(kk => [[unl(r[1]); (length(r) == 2 && kk in arrow_keys) ? [unl(r[2])] : r[2:end]] for r in rs]
               for (kk, rs) in after)
      back_rows = Dict{String,Vector{Vector{String}}}(kk => rs for (kk, rs) in Y
                                                      if !(kk in [landed(t) for t in absorbed]) && kk != keyed)
      if key !== nothing  # K' ⋈ A' on the kind's element, with Catlab's pullback on the migrated state
        Xn = instance(acset_type(schema(new_tables)), new_tables, Y)
        nl = p -> subpart(Xn, p, :label)
        jk = findfirst(t -> t.key == keyed, new_tables)
        keyval = p -> subpart(Xn, p, Symbol("val$jk"))
        joined = [(nl(subpart(Xn, p, Symbol("src$jk"))), keyval(p)) for p in parts(Xn, Symbol("T$jk"))]
        for t in absorbed
          i = findfirst(x -> x.key == landed(t), new_tables)
          value = q -> t.arrow ? nl(subpart(Xn, q, Symbol("dst$i"))) : subpart(Xn, q, Symbol("val$i"))
          for (p, q) in join_parts(Xn, jk, "src", i, "src")
            push!(get!(back_rows, t.key, Vector{String}[]), [keyval(p), value(q)])
          end
        end
      else  # derived: the owner and the arrow make the id
        xs = sort(unique([r[1] for t in absorbed for r in get(Y, landed(t), [])]))
        joined = [(x, escape(x) * "/" * f_el) for x in xs]
        gi = Dict(joined)
        for t in absorbed, r in get(Y, landed(t), [])
          push!(get!(back_rows, t.key, Vector{String}[]), [gi[r[1]], r[2]])
        end
      end
      for (x, y) in joined
        push!(get!(back_rows, a, Vector{String}[]), [y])
        push!(get!(back_rows, f, Vector{String}[]), target ? [x, y] : [y, x])
      end
      back = Dict(kk => sort(v) for (kk, v) in back_rows if !isempty(v))
      orig = Dict(String(kk) => sort([Vector{String}(r) for r in rs]) for (kk, rs) in rows_in if !isempty(rs))
      back == orig || push!(conflicts, "the round trip invents or loses rows")
    end
    push!(out, Dict{String,Any}("name" => state["name"], "after" => after, "lost" => lost, "conflicts" => conflicts,
                    "back" => back))
  end
  out
end

# --- glue: a pack as the colimit of its parts (B10) ----------------------------------------------------------

const SKEL = SkelFinSet()

"""Catlab's colimit in FinSet of sets of sizes `ns` over `overlaps`. An overlap is a set with a leg into each
set that has it: (i, xs) sends its k-th element to element xs[k] of set i. That is the bipartite diagram of
inclusions, overlaps above and parts below. Gives the class of every element of every set, and their number."""
function glued(ns::Vector{Int}, overlaps::Vector{Vector{Tuple{Int,Vector{Int}}}})
  # Catlab 0.17.6 cannot build a diagram without an edge. The empty set, included in the first set, is an
  # overlap that changes no colimit, so it is always there.
  overlaps = pushfirst!(copy(overlaps), [(1, Int[])])
  homs = [(FinFunction(xs, ns[i]), o, i) for (o, legs_) in enumerate(overlaps) for (i, xs) in legs_]
  d = BipartiteFreeDiagram([FinSetInt(length(legs_[1][2])) for legs_ in overlaps], FinSetInt.(ns), homs; cat=SKEL)
  colim = colimit[SKEL](d)
  [Int[ι(x) for x in 1:n] for (ι, n) in zip(legs(colim), ns)], length(ob(colim))
end

"""A pack whose parts share modules is the colimit of the parts over what they share. From the parts and the
declared overlaps alone: the colimit of the parts' tables (an overlap is the tables of its modules, included
whole in each of its parts), and for every fact state the colimit of the parts' rows, each moved by Σ along
its part's inclusion. Without an identification Σ puts a part's rows in the colimit's tables; only a derived
id changes, because it holds the engine element of its slot, and that name comes from the names declared in
all parts together (S8). Rows of one table are one fact where two parts hold the same row: their overlap is
Catlab's pullback over the rows, and the table's rows are the colimit over those overlaps."""
function glue_case(case)
  parts = case["parts"]
  keys_ = [String[t["key"] for t in p["tables"]] for p in parts]
  conflicts = String[]
  overlaps = Vector{Tuple{Int,Vector{Int}}}[]
  for o in case["op"]["overlaps"]
    ps = Int[i + 1 for i in o["parts"]]
    own = [sort([k for k in keys_[i] if split(k, '#')[1] in o["modules"]]) for i in ps]
    all(==(own[1]), own) || push!(conflicts, "overlap $(join(o["modules"], ", ")) is not whole in each of its parts")
    shared = [k for k in own[1] if all(ks -> k in ks, own)]
    push!(overlaps, [(i, Int[findfirst(==(k), keys_[i]) for k in shared]) for i in ps])
  end
  class, n = glued(length.(keys_), overlaps)
  members = [Tuple{Int,Int}[] for _ in 1:n]  # per table of the colimit: (part, table of that part)
  for (i, cs) in enumerate(class), (t, c) in enumerate(cs)
    push!(members[c], (i, t))
  end
  tables = []
  for ms in members
    shapes = unique([parts[i]["tables"][t] for (i, t) in ms])
    length(shapes) > 1 && push!(conflicts, "$(shapes[1]["key"]) differs between the parts that share it")
    push!(tables, shapes[1])
  end
  times = Dict{String,Int}()
  foreach(t -> times[t["key"]] = get(times, t["key"], 0) + 1, tables)
  for (k, c) in sort(collect(times))
    c > 1 && push!(conflicts, "$k is in $c parts and in no overlap")
  end
  declared = [Tuple{String,String}[(String(d[1]), String(d[2])) for d in p["declared"]] for p in parts]
  names = engine_names(unique(vcat(declared...)))
  out = []
  for (s, state) in enumerate(case["states"])
    moved = Vector{Vector{Vector{String}}}[]  # Σ along each inclusion: per part and table, its rows in the one pack
    for (i, p) in enumerate(parts)
      p["states"][s]["name"] == state["name"] || push!(conflicts, "part $i has no state $(state["name"]) at $s")
      old = engine_names(declared[i])
      element = Dict{String,String}(element_of(old, String(t["key"])) => element_of(names, String(t["key"]))
                                    for t in p["tables"] if t["slot"] !== nothing)
      embedded, memo = Set{String}(p["embedded"]), Dict{String,String}()
      rl = x -> relabel(String(x), embedded, element, memo)
      push!(moved, [Vector{String}[length(r) == 1 ? [rl(r[1])] : [rl(r[1]), t["arrow"] ? rl(r[2]) : String(r[2])]
                                   for r in get(p["states"][s]["rows"], t["key"], [])] for t in p["tables"]])
    end
    after = Dict{String,Vector{Vector{String}}}()
    for (ms, t) in zip(members, tables)
      sets = [moved[i][j] for (i, j) in ms]
      at = Dict(r => x for (x, r) in enumerate(sort(unique(vcat(sets...)))))
      shared = Vector{Tuple{Int,Vector{Int}}}[]
      for a in 1:length(sets), b in a+1:length(sets)  # the same row in two parts: Catlab's pullback over the rows
        pairs = pullback_pairs(Int[at[r] for r in sets[a]], Int[at[r] for r in sets[b]], length(at))
        push!(shared, [(a, Int[p for (p, _) in pairs]), (b, Int[q for (_, q) in pairs])])
      end
      row_class, m = glued(length.(sets), shared)
      rs = Vector{Vector{String}}(undef, m)
      for (a, cs) in enumerate(row_class), (q, c) in enumerate(cs)
        rs[c] = sets[a][q]
      end
      isempty(rs) || (after[t["key"]] = sort(rs))
    end
    push!(out, Dict{String,Any}("name" => state["name"], "tables" => sort(tables, by=t -> t["key"]), "after" => after,
                                "conflicts" => conflicts))
  end
  out
end

function run_case(case)
  case["op"]["op"] == "glue" && return glue_case(case)
  case["op"]["op"] == "combine" && return combine_case(case)
  case["op"]["op"] in ("drop", "select") && return drop_case(case)
  case["op"]["op"] == "move" && return move_case(case)
  case["op"]["op"] == "split_by" && return split_case(case)
  op = case["op"]
  tables = [Table(t["key"], t["kind"], t["slot"], t["arrow"], t["enum"]) for t in case["tables"]]
  new_tables = [Table(renamed_key(op, t.key), renamed_key(op, t.kind), op["what"] == "slot" && t.slot == op["slot"] &&
                      t.kind == op["kind"] ? op["to"] : t.slot, t.arrow, t.enum) for t in tables]
  forward = collect(1:length(tables))  # table i of the new schema comes from table i of the old one
  # The engine element of each slot, old -> new, for the ids of embedded elements, from the declared names.
  declared = [(String(d[1]), String(d[2])) for d in case["declared"]]
  names_old, names_new = engine_names(declared), engine_names(renamed_declared(op, declared))
  element = Dict{String,String}()
  for (t, n) in zip(tables, new_tables)
    t.slot === nothing && continue
    element[element_of(names_old, t.key)] = element_of(names_new, n.key)
  end
  values = op["what"] == "value" ? Dict(op["value"] => op["to"]) : Dict{String,String}()
  embedded = Set{String}(case["embedded"])
  T = acset_type(schema(tables))
  out = []
  for state in case["states"]
    X = instance(T, tables, state["rows"])
    Y = delta(X, tables, new_tables, forward)
    after = rows(Y, new_tables)
    memo = Dict{String,String}()
    mapped = Dict{String,Vector{Vector{String}}}()
    for (t, n) in zip(tables, new_tables)
      haskey(after, n.key) || continue
      mapped[n.key] = sort([begin
        r = [relabel(String(r[1]), embedded, element, memo); r[2:end]]
        if length(r) == 2
          r[2] = n.arrow ? relabel(String(r[2]), embedded, element, memo) :
                 (n.enum !== nothing && n.enum == get(op, "enum", nothing) ? get(values, r[2], r[2]) : r[2])
        end
        r
      end for r in after[n.key]])
    end
    # Back: the inverse functor on the migrated state, with the inverse value and id maps.
    inv_values = Dict(v => k for (k, v) in values)
    inv_ids = Dict(v => k for (k, v) in memo)
    Xn = instance(acset_type(schema(new_tables)), new_tables, mapped)
    back = rows(delta(Xn, new_tables, tables, forward), tables)
    restored = Dict{String,Vector{Vector{String}}}()
    for t in tables
      haskey(back, t.key) || continue
      restored[t.key] = sort([begin
        r = [get(inv_ids, String(r[1]), String(r[1])); r[2:end]]
        if length(r) == 2
          r[2] = t.arrow ? get(inv_ids, String(r[2]), String(r[2])) :
                 (t.enum !== nothing && t.enum == get(op, "enum", nothing) ? get(inv_values, r[2], r[2]) : r[2])
        end
        r
      end for r in back[t.key]])
    end
    push!(out, Dict{String,Any}("name" => state["name"], "after" => mapped, "back" => restored))
  end
  out
end

function main(args)
  cases = JSON.parsefile(args[1])
  results = [run_case(c) for c in cases]
  open(args[2], "w") do f
    JSON.print(f, results)
  end
end

main(ARGS)
