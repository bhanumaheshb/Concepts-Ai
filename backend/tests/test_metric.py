"""Distance-metric properties. This is the core IP and the first thing to test."""
import itertools

from app.core.seeded import SeededRandom
from app.diversity.metric import D_MIN, d_ordered_seq, d_weighted_set, genotype_distance
from app.diversity.vendi import vendi_score
from app.domain.common import MaterialRole
from app.domain.genotype import MaterialAssignment
from app.genotype.solve import solve_genotype


def _sample(ont, space, n=12):
    return [solve_genotype(ont, space, SeededRandom(9000 + i, "m")) for i in range(n)]


def test_identity_and_symmetry_and_range(ont, space):
    gs = _sample(ont, space)
    for g in gs:
        assert genotype_distance(ont, g, g) == 0.0
    for a, b in itertools.combinations(gs, 2):
        d1, d2 = genotype_distance(ont, a, b), genotype_distance(ont, b, a)
        assert abs(d1 - d2) < 1e-12
        assert 0.0 <= d1 <= 1.0


def test_monotonic_in_ontology_distance(ont, space):
    """Moving one facet to an ontologically farther value never decreases d."""
    from app.domain.genotype import FacetAssignment
    base = solve_genotype(ont, space, SeededRandom(5, "mono"))
    same_group, far = None, None
    cur = base.architectural_language.value
    parent = ont.node(cur).parent
    for ref in space.legal("architectural_language"):
        if ref == cur:
            continue
        if ont.node(ref).parent == parent and same_group is None:
            same_group = ref
        elif ont.node(ref).parent != parent and far is None:
            far = ref
    assert same_group and far
    near_g = base.model_copy(update={"architectural_language": FacetAssignment(value=same_group)})
    far_g = base.model_copy(update={"architectural_language": FacetAssignment(value=far)})
    assert genotype_distance(ont, base, near_g) < genotype_distance(ont, base, far_g)


def test_more_flowers_case_is_a_duplicate(ont, space):
    """The spec's worked example: adding one accent material is NOT a new concept."""
    base = solve_genotype(ont, space, SeededRandom(11, "flowers"))
    used = {m.material for m in base.material_palette}
    extra = next(v for v in space.legal("material_palette") if v not in used)
    remaining = 1.0 - sum(m.share for m in base.material_palette)
    plus = base.model_copy(update={"material_palette": list(base.material_palette) + [
        MaterialAssignment(material=extra, role=MaterialRole.ACCENT,
                           share=round(max(0.01, min(0.05, remaining)), 3))]})
    d = genotype_distance(ont, base, plus)
    assert d < 0.05, f"one accent material moved the metric by {d}"
    assert d < D_MIN


def test_weighted_set_and_sequence_distance():
    assert d_weighted_set([("a", 0.6)], [("a", 0.6)]) == 0.0
    assert d_weighted_set([("a", 0.6)], [("b", 0.6)]) == 1.0
    assert d_ordered_seq(["x", "y"], ["x", "y"]) == 0.0
    assert d_ordered_seq(["x", "y"], ["y", "x"]) > 0.0     # order matters
    assert d_ordered_seq(["x"], ["z"]) == 1.0


def test_vendi_identities():
    n = 8
    identical = [[1.0] * n for _ in range(n)]
    orthogonal = [[1.0 if i == j else 0.0 for j in range(n)] for i in range(n)]
    assert abs(vendi_score(identical) - 1.0) < 1e-6
    assert abs(vendi_score(orthogonal) - n) < 1e-6
