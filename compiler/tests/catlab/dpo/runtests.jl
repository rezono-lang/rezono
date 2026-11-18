# Run from the repository root with Julia 1.11.9.
# julia --startup-file=no --project=compiler/tests/catlab/dpo -e 'using Pkg; Pkg.instantiate()'
# julia --startup-file=no --project=compiler/tests/catlab/dpo compiler/tests/catlab/dpo/runtests.jl
# Oracle license: https://github.com/AlgebraicJulia/AlgebraicRewriting.jl/blob/v0.5.0/LICENSE

using AlgebraicRewriting, Catlab, Test

@testset "DPO rejects a dangling incidence" begin
  category = ACSetCategory(Graph())
  interface = Graph()
  left = Graph(1)
  inclusion = ACSetTransformation(interface, left; V=Int[])
  delete_vertex = Rule(inclusion, id[category](interface); monic=true)

  linked = path_graph(Graph, 2)
  endpoint = ACSetTransformation(left, linked; V=[1])
  @test !can_pushout_complement[category](inclusion, endpoint)
  @test isempty(get_matches(delete_vertex, linked; cat=category))
  @test rewrite(delete_vertex, linked; cat=category) === nothing

  with_isolated = deepcopy(linked)
  add_vertex!(with_isolated)
  @test length(get_matches(delete_vertex, with_isolated; cat=category)) == 1
  @test rewrite(delete_vertex, with_isolated; cat=category) == linked
  @test nv(with_isolated) == 3
end
