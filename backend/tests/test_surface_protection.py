"""Four layers, and the compiler-lookup regression that motivated the refactor."""
from app.domain.common import ViewRole
from app.domain.reference import ReferenceRequest, ReferenceSelector, contains_token
from app.ontology.graph import Principle, PrincipleProvenance
from app.ontology.index import MergedPrincipleIndex, OntologyPrincipleIndex
from app.prompt.compiler import compile_prompt
from app.references.injection import build_injection


def test_runtime_principle_tokens_reach_the_negative_prompt(container, ont, sangeeth_brief):
    """THE regression: the old `if principle_id in ont.principles` guard dropped a
    runtime principle's forbidden tokens silently, and passed every existing test."""
    rec = container.pipeline.run(sangeeth_brief, k=10, seed=42)
    dna = rec.concepts[0]

    runtime = Principle(
        id="refprin_probe", source_domain="a probe principle", domain_class="CINEMA",
        statements=["something abstract"], mappable_to=["geometry_system"], biases={},
        forbidden_surface_tokens=["zzunmistakabletoken"],
        provenance=PrincipleProvenance(source="REFERENCE"),
    )
    tagged = dna.model_copy(update={"principle_id": "refprin_probe"})
    index = MergedPrincipleIndex(ont, [runtime])

    with_index = compile_prompt(ont, tagged, rec.program, rec.scenes[dna.concept_id],
                                rec.antibrief, ViewRole.HERO, "GENERIC", 42, principles=index)
    assert "zzunmistakabletoken" in with_index.negative_prompt

    # and the default index (ontology only) simply cannot see it — proving the guard mattered
    without = compile_prompt(ont, tagged, rec.program, rec.scenes[dna.concept_id],
                             rec.antibrief, ViewRole.HERO, "GENERIC", 42,
                             principles=OntologyPrincipleIndex(ont))
    assert "zzunmistakabletoken" not in without.negative_prompt


def test_no_blocked_token_survives_into_a_delivered_concept(container, ont, ref_service,
                                                            sangeeth_brief, space):
    for rid in ("ref_bridgerton", "ref_stranger_things", "ref_palace_architecture"):
        req = ReferenceRequest(references=[ReferenceSelector(query=rid)], influence=0.55)
        out = ref_service.build(req, space, seed=42)
        rec = container.pipeline.run(sangeeth_brief, k=10, seed=42, injection=out.injection)
        blocked = out.injection.blocked_tokens() + [
            d.identity.display_name.lower() for d in out.injection.reference_dnas]
        for c in rec.concepts:
            blob = " ".join([
                c.phenotype.title, c.phenotype.one_line, c.phenotype.design_thesis,
                c.phenotype.spatial_explanation, c.phenotype.material_explanation,
                c.phenotype.experience_narrative,
                rec.prompts[c.concept_id].positive_prompt,
            ]).lower()
            for tok in blocked:
                # word-boundary matching, the same contract the engine enforces:
                # "arcade" must not license a hit inside the ontology's "arcaded edges"
                assert not contains_token(blob, tok), \
                    f"{rid}: {c.phenotype.title} leaked {tok!r}"
            assert c.reference_context.surface_leaks == []


def test_reference_tokens_appear_in_the_negative_prompt(container, ref_service,
                                                        sangeeth_brief, space):
    req = ReferenceRequest(references=[ReferenceSelector(query="ref_bridgerton")], influence=0.55)
    out = ref_service.build(req, space, seed=42)
    rec = container.pipeline.run(sangeeth_brief, k=10, seed=42, injection=out.injection)
    joined = " ".join(p.negative_prompt for p in rec.prompts.values())
    assert any(tok in joined for tok in out.injection.blocked_tokens())


def test_tokens_carry_their_transformation(fixtures):
    dna = fixtures["ref_stranger_things"]
    upside = next(t for t in dna.surface_lexicon.tokens if t.token == "upside down")
    assert upside.transformed_to and "invert" in upside.transformed_to.lower()
