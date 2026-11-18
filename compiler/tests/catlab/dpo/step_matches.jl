# Independent match enumeration for the authored cases in test_step_dpo_oracle.py.
using AlgebraicRewriting, Catlab

const CATEGORY = ACSetCategory(VarACSetCat(NamedGraph{String,String}()))

function graph(text)
    vertices, edges = split(text, '|'; limit=2, keepempty=true)
    result = NamedGraph{String,String}()
    parts_by_name = Dict{String,Int}()
    for name in split(vertices, ','; keepempty=false)
        value = startswith(name, "?") ? AttrVar(add_part!(result, :VName)) : String(name)
        parts_by_name[name] = add_part!(result, :V; vname=value)
    end
    for edge in split(edges, ','; keepempty=false)
        name, tail, head = split(edge, ':')
        add_part!(result, :E; ename=String(name), src=parts_by_name[tail], tgt=parts_by_name[head])
    end
    result
end

function rows(graph, vertices=parts(graph, :V), edges=parts(graph, :E))
    result = Set("item:$(graph[index, :vname])" for index in vertices)
    for index in edges
        name = graph[index, :ename]
        push!(result, "link:$name")
        push!(result, "link__tail:$name:$(graph[graph[index, :src], :vname])")
        push!(result, "link__head:$name:$(graph[graph[index, :tgt], :vname])")
    end
    result
end

function inclusion(left, right)
    left == right && return id[CATEGORY](left)
    homomorphism(left, right; cat=CATEGORY, monic=true)
end

for line in eachline(stdin)
    name, base_text, left_text, interface_text, right_text, guard_text = split(line, '\t'; keepempty=true)
    base, left, interface, right = graph.((base_text, left_text, interface_text, right_text))
    conditions = [NAC(inclusion(left, graph(text)); monic=true)
                  for text in split(guard_text, ';'; keepempty=false)]
    rule = Rule(inclusion(interface, left), inclusion(interface, right); cat=CATEGORY, monic=true, ac=conditions)
    before = rows(base)
    for match in get_matches(rule, base; cat=CATEGORY)
        matched = rows(base, (match[:V](index) for index in parts(left, :V)),
                       (match[:E](index) for index in parts(left, :E)))
        after = rows(rewrite_match(rule, match; cat=CATEGORY))
        println(join((name, join(sort!(collect(matched)), ","),
                      join(sort!(collect(setdiff(before, after))), ","),
                      join(sort!(collect(setdiff(after, before))), ","),
                      join(sort!(collect(intersect(before, after))), ",")), '\t'))
    end
end
