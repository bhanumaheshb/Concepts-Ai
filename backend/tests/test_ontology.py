from app.ontology.graph import Ontology


def test_loads_and_validates(ont):
    stats = ont.stats()
    assert stats["nodes"] >= 180
    assert stats["active_facets"] == 12
    assert stats["principles"] >= 10


def test_active_facet_weights_sum_to_one(ont):
    total = sum(f.weight for f in ont.facets.values())
    assert abs(total - 1.0) < 1e-9


def test_every_geometry_value_maps_to_a_scene_primitive(ont):
    """R-SCENE-02: the single guarantee that keeps the V3 3D path reachable."""
    for ref in ont.values("geometry_system"):
        assert ont.node(ref).primitive, f"{ref} has no primitive"


def test_every_active_leaf_has_a_prompt_phrase(ont):
    for facet in ont.active_facets():
        source = "material" if facet == "material_palette" else facet
        for ref in ont.values(source):
            assert ont.node(ref).phrase, f"{ref} has no prompt_phrase"


def test_tree_depth_uses_facet_as_virtual_root(ont):
    a = "architectural_language:rajasthani_stepwell"
    b = "architectural_language:kerala_nalukettu"     # same group
    c = "architectural_language:parametric"           # different group
    assert ont.lca_depth(a, b) == 1
    assert ont.lca_depth(a, c) == 0
    assert ont.lca_depth(a, a) == ont.depth(a)


def test_principles_satisfy_authoring_rules(ont):
    for p in ont.principles.values():
        assert len(p.mappable_to) >= 2, f"{p.id} maps to fewer than 2 facets"
        assert p.forbidden_surface_tokens, f"{p.id} has no forbidden surface tokens"
        assert p.statements, f"{p.id} has no statements"
        for v in (v for vs in p.biases.values() for v in vs):
            assert v in ont.nodes, f"{p.id} biases toward unknown ref {v}"


def test_inverse_edges_are_symmetric(ont):
    for e in ont.edges:
        if e.type == "inverse_of":
            assert e.src in ont.inverse_of(e.dst)
            assert e.dst in ont.inverse_of(e.src)
