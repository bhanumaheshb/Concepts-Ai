from app.core.seeded import SeededRandom
from app.diversity.metric import genotype_distance
from app.domain.brief import DesignBrief
from app.domain.common import IDENTITY_FACETS, ViewRole
from app.mutation.operators import REGISTRY, apply_operator
from app.prompt.compiler import compile_prompt
from app.repair.engine import ConceptIdentity, critics_to_rerun
from app.domain.common import CriticName


def _rec(container, seed=42):
    return container.pipeline.run(
        DesignBrief(brief_id=f"bf_pr_{seed}",
                    raw_text="Create a luxury Indian wedding mandap for 500 guests.",
                    location="Jaipur, May"), k=10, seed=seed)


def test_prompt_compilation_is_byte_deterministic(container):
    rec = _rec(container)
    c = rec.concepts[0]
    a = compile_prompt(container.ontology, c, rec.program, rec.scenes[c.concept_id],
                       rec.antibrief, ViewRole.HERO, "GENERIC", rec.seed)
    b = compile_prompt(container.ontology, c, rec.program, rec.scenes[c.concept_id],
                       rec.antibrief, ViewRole.HERO, "GENERIC", rec.seed)
    assert a.positive_prompt == b.positive_prompt
    assert a.negative_prompt == b.negative_prompt
    assert a.prompt_hash == b.prompt_hash and a.inputs_hash == b.inputs_hash


def test_prompt_has_all_segments_and_provenance(container):
    rec = _rec(container)
    pc = rec.prompts[rec.concepts[0].concept_id]
    kinds = {s.kind for s in pc.segments}
    assert {"SUBJECT", "LANGUAGE", "FORM", "MATERIAL", "LIGHTING", "CAMERA", "REGISTER"} <= kinds
    assert all(s.sources for s in pc.segments)
    assert not pc.degraded


def test_negative_prompt_carries_the_antibrief_and_anti_attributes(container):
    rec = _rec(container)
    tokens = set()
    for cl in rec.antibrief.cliche_clusters:
        tokens |= set(cl.surface_tokens)
    joined = " ".join(p.negative_prompt for p in rec.prompts.values())
    assert any(t in joined for t in tokens), "no cliché surface token reached a negative prompt"
    assert "cgi plastic" in joined


def test_prompt_degrades_without_a_scene_graph(container):
    rec = _rec(container)
    c = rec.concepts[0]
    pc = compile_prompt(container.ontology, c, rec.program, None, rec.antibrief,
                        ViewRole.HERO, "GENERIC", rec.seed)
    assert pc.degraded is True
    assert pc.positive_prompt          # still produces a usable prompt
    assert {"OCCUPANCY", "SCALE"} <= {s.kind for s in pc.segments}


def test_operators_never_touch_pinned_or_identity_facets(container):
    rec = _rec(container)
    ont, space = container.ontology, rec.space
    for c in rec.concepts[:4]:
        for op_id in REGISTRY:
            out = apply_operator(op_id, ont, space, c.genotype,
                                 SeededRandom(1, op_id), set(IDENTITY_FACETS), 0.5)
            if out.status != "APPLIED" or out.genotype is None:
                continue
            for facet in IDENTITY_FACETS:
                assert out.genotype.facet_value(facet) == c.genotype.facet_value(facet), \
                    f"{op_id} moved identity facet {facet}"
            assert list(out.genotype.spatial_narrative) == list(c.genotype.spatial_narrative)


def test_operators_produce_exclusion_free_genotypes(container):
    rec = _rec(container)
    ont, space = container.ontology, rec.space
    for c in rec.concepts[:4]:
        for op_id in REGISTRY:
            out = apply_operator(op_id, ont, space, c.genotype, SeededRandom(2, op_id), set(), 0.6)
            if out.status != "APPLIED" or out.genotype is None:
                continue
            refs = out.genotype.all_refs()
            for i, a in enumerate(refs):
                for b in refs[i + 1:]:
                    assert b not in ont.excludes(a), f"{op_id} produced {a} × {b}"


def test_identity_is_extractable_and_enforced(container):
    rec = _rec(container)
    c = rec.concepts[0]
    ident = ConceptIdentity.of(c)
    assert ident.holds_for(c.genotype)
    assert ident.signature_read


def test_critics_to_rerun_is_minimal_but_includes_coherence():
    s = critics_to_rerun(CriticName.FEASIBILITY, ["material_palette"])
    assert CriticName.COHERENCE in s and CriticName.FEASIBILITY in s
    assert CriticName.ALIGNMENT not in s
