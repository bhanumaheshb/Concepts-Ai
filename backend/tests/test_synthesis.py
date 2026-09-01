"""LLM creative synthesis: the engine decides, the model expresses, the validator checks.

No test here touches a network. The Cloudflare adapter is exercised through a stub
transport so the suite stays green with or without an API token.
"""
import pytest

from app.core.config import Settings
from app.creative.program import build_program
from app.creative.synthesis import CreativeSynthesizer
from app.creative.synthesis_prompt import (
    build_constraints, build_user_prompt, geometry_reading,
)
from app.creative.validator import ConceptLLMValidator
from app.domain.brief import DesignBrief
from app.domain.providers.protocols import CreativeSynthesisProvider
from app.domain.synthesis import StructuredArchitecturalConcept
from app.prompt.architectural import SECTION_ORDER, ArchitecturalPromptCompiler
from app.providers.llm.mock_synthesis import MockCreativeProvider

BRIEF = "Create a 500-person luxury Sangeeth mandap."


@pytest.fixture(scope="module")
def setup(container):
    ont = container.ontology
    brief = DesignBrief(brief_id="bf_syn", raw_text=BRIEF, location="Jaipur, May")
    program = build_program(ont, brief)
    rec = container.pipeline.run(brief, k=10, seed=42)
    return ont, brief, program, rec


# ─────────────────── provider independence ───────────────────

def test_mock_provider_satisfies_the_protocol(container):
    assert isinstance(MockCreativeProvider(container.ontology), CreativeSynthesisProvider)


def test_http_provider_satisfies_the_same_protocol():
    from app.providers.llm import cloudflare
    provider = cloudflare.build_provider(account_id="", api_token="")
    assert isinstance(provider, CreativeSynthesisProvider)


def test_swapping_the_provider_is_one_call_in_composition(container):
    from app.composition import build_synthesis_provider
    ont = container.ontology
    assert build_synthesis_provider(Settings(llm_provider="mock"), ont).name == "mock"
    assert build_synthesis_provider(
        Settings(llm_provider="cloudflare"), ont).name == "cloudflare"


def test_engine_modules_never_import_a_synthesis_adapter():
    import ast, pathlib
    root = pathlib.Path(__file__).resolve().parents[1] / "app"
    for pkg in ("creative", "prompt", "domain", "critics", "ontology"):
        for path in (root / pkg).rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                mod = (node.module if isinstance(node, ast.ImportFrom) else None)
                names = ([a.name for a in node.names] if isinstance(node, ast.Import)
                         else [mod or ""])
                for n in names:
                    assert "providers.llm" not in (n or ""), f"{path} imports {n}"


def test_the_schema_requires_everything_the_validator_demands():
    """The schema and the validator must not disagree about what is mandatory.

    A field the schema calls optional is one a well-behaved model will omit — and
    then be rejected for. This is not hypothetical: `spatial_sequence` and
    `anti_cliches` were absent from `required`, and a real local model obeyed the
    schema exactly and lost both, failing SEQUENCE_MISSING and ANTI_CLICHES_MISSING.
    The stricter the grammar enforcement, the more reliably that happened.
    """
    from app.providers.llm.schema import concept_json_schema
    required = set(concept_json_schema()["required"])
    # Fields the validator raises a hard error for when empty or too short.
    for field in ("spatial_sequence", "anti_cliches"):
        assert field in required, (
            f"validator rejects an empty {field!r} but the schema calls it optional")


def test_the_schema_encodes_the_validators_own_thresholds():
    """minItems mirrors the validator, so a grammar-enforcing server cannot produce
    output that is schema-valid and validator-invalid at the same time."""
    from app.providers.llm.schema import concept_json_schema
    props = concept_json_schema()["properties"]
    assert props["spatial_sequence"]["minItems"] == 3    # validator: len < 3 fails
    assert props["anti_cliches"]["minItems"] == 1        # validator: empty fails


# ─────────────────── the engine owns diversity (§1) ───────────────────

def test_ten_genotypes_produce_ten_distinct_concepts(setup, container):
    ont, brief, program, rec = setup
    synth = CreativeSynthesizer(ont, MockCreativeProvider(ont))
    titles = {synth.synthesize(dna=d, brief=brief, program=program, seed=42)
              .concept.concept_title for d in rec.concepts}
    assert len(titles) == len(rec.concepts), "synthesis collapsed distinct genotypes"


def test_the_provider_is_never_shown_more_than_one_concept(setup, container):
    """Diversity is settled before this layer; the model cannot influence it."""
    import inspect
    sig = inspect.signature(MockCreativeProvider.synthesize_concept)
    assert "concept_dna" in sig.parameters
    assert not any("concepts" in p or "portfolio" in p for p in sig.parameters)


# ─────────────────── constraints (§17/§19) ───────────────────

def test_hard_constraints_carry_the_briefs_own_numbers(setup):
    ont, brief, program, rec = setup
    cons = build_constraints(ont, program, brief, rec.concepts[0].genotype)
    assert cons.capacity == 500, "the brief said 500"
    assert any("500" in h for h in cons.hard)
    assert cons.typology == "WEDDING_MANDAP"


def test_adjectival_capacity_is_parsed(container):
    """'a 500-person mandap' must not silently become the typology default."""
    from app.creative.program import parse_capacity
    assert parse_capacity("Create a 500-person luxury Sangeeth mandap.", 200) == 500
    assert parse_capacity("a 250-guest mehendi", 100) == 250
    assert parse_capacity("no number at all", 137) == 137


def test_every_identity_facet_is_locked(setup):
    ont, brief, program, rec = setup
    cons = build_constraints(ont, program, brief, rec.concepts[0].genotype)
    locked = {lf.facet for lf in cons.locked_facets}
    for facet in ("architectural_language", "geometry", "structural_logic",
                  "spatial_narrative", "emotional_register"):
        assert facet in locked, facet


def test_the_prompt_states_the_locked_values_and_forbids_replacement(setup):
    ont, brief, program, rec = setup
    dna = rec.concepts[0]
    cons = build_constraints(ont, program, brief, dna.genotype,
                             forbidden_tokens=["palace"])
    text = build_user_prompt(brief, program, cons, dna.genotype)
    assert "HARD CONSTRAINTS" in text and "may not alter" in text
    assert "CONCEPT DNA" in text and "Express it." in text
    assert "palace" in text and "FORBIDDEN WORDS" in text


def test_geometry_is_translated_not_repeated(setup):
    assert geometry_reading(["geometry_system:radial_symmetry"])[0].startswith("radial structural")
    assert geometry_reading(["geometry_system:unknown_thing"]) == []


# ─────────────────── validation (§18) ───────────────────

def _valid(ont, brief, program, rec):
    synth = CreativeSynthesizer(ont, MockCreativeProvider(ont))
    r = synth.synthesize(dna=rec.concepts[0], brief=brief, program=program, seed=42)
    return r


def test_the_mock_provider_passes_its_own_validator(setup):
    ont, brief, program, rec = setup
    synth = CreativeSynthesizer(ont, MockCreativeProvider(ont))
    for dna in rec.concepts:
        r = synth.synthesize(dna=dna, brief=brief, program=program, seed=42)
        assert r.validation.passed, [f.code for f in r.validation.errors]


@pytest.mark.parametrize("mutation,code", [
    ({"concept_thesis": ""}, "FIELD_TOO_THIN"),
    ({"spatial_sequence": []}, "SEQUENCE_MISSING"),
    ({"anti_cliches": []}, "ANTI_CLICHES_MISSING"),
])
def test_validator_rejects_thin_output(setup, mutation, code):
    ont, brief, program, rec = setup
    r = _valid(ont, brief, program, rec)
    broken = r.concept.model_copy(update=mutation)
    v = ConceptLLMValidator(ont).validate(
        broken, genotype=rec.concepts[0].genotype, program=program, brief=brief,
        constraints=r.constraints)
    assert not v.passed
    assert code in [f.code for f in v.errors]


def test_validator_rejects_a_field_that_echoes_its_own_name(setup):
    """The characteristic small-model failure: 'seating': 'Seating'."""
    ont, brief, program, rec = setup
    r = _valid(ont, brief, program, rec)
    broken = r.concept.model_copy(update={
        "program": r.concept.program.model_copy(update={"seating": "Seating"})})
    v = ConceptLLMValidator(ont).validate(
        broken, genotype=rec.concepts[0].genotype, program=program, brief=brief,
        constraints=r.constraints)
    assert "PROGRAM_INCOMPLETE" in [f.code for f in v.errors] or \
           "PROGRAM_ECHOES_NAME" in [f.code for f in v.errors]


def test_validator_rejects_a_changed_capacity(setup):
    ont, brief, program, rec = setup
    r = _valid(ont, brief, program, rec)
    broken = r.concept.model_copy(update={
        "program": r.concept.program.model_copy(update={
            "seating": "Seating for 300 guests arranged in a ring around the mandap."})})
    v = ConceptLLMValidator(ont).validate(
        broken, genotype=rec.concepts[0].genotype, program=program, brief=brief,
        constraints=r.constraints)
    assert "CAPACITY_ALTERED" in [f.code for f in v.errors]


def test_validator_rejects_a_forbidden_token(setup):
    ont, brief, program, rec = setup
    synth = CreativeSynthesizer(ont, MockCreativeProvider(ont))
    r = synth.synthesize(dna=rec.concepts[0], brief=brief, program=program,
                         forbidden_tokens=["zeppelin"], seed=42)
    broken = r.concept.model_copy(update={"atmosphere": "a zeppelin hangar mood"})
    v = ConceptLLMValidator(ont).validate(
        broken, genotype=rec.concepts[0].genotype, program=program, brief=brief,
        constraints=r.constraints)
    assert "FORBIDDEN_TOKEN" in [f.code for f in v.errors]


def test_impossible_architecture_must_be_admitted_not_asserted(setup):
    ont, brief, program, rec = setup
    r = _valid(ont, brief, program, rec)
    broken = r.concept.model_copy(update={
        "structure": r.concept.structure.model_copy(update={
            "structural_system": "A floating canopy suspended by nothing at all."}),
        "construction_character": "Assembled on site in two days."})
    v = ConceptLLMValidator(ont).validate(
        broken, genotype=rec.concepts[0].genotype, program=program, brief=brief,
        constraints=r.constraints)
    codes = [f.code for f in v.errors]
    admitted = broken.model_copy(update={
        "construction_character": "This is speculative and not buildable as drawn."})
    v2 = ConceptLLMValidator(ont).validate(
        admitted, genotype=rec.concepts[0].genotype, program=program, brief=brief,
        constraints=r.constraints)
    assert "IMPOSSIBLE_UNFLAGGED" in codes
    assert "IMPOSSIBLE_UNFLAGGED" not in [f.code for f in v2.errors]


def test_the_engines_own_vocabulary_is_not_called_impossible(container):
    """`floating_on_water` is a pontoon. The validator must not reject the engine."""
    from app.domain.synthesis import ConstraintEnvelope, LockedFacet
    ont = container.ontology
    cons = ConstraintEnvelope(locked_facets=[LockedFacet(
        facet="site_relationship", ref="site_relationship:floating_on_water",
        label="floating on water")])
    c = StructuredArchitecturalConcept(
        design_story="A floating platform moored to the bank.")
    findings = ConceptLLMValidator(ont)._structure_realism(c, cons)
    assert "IMPOSSIBLE_UNFLAGGED" not in [f.code for f in findings]


# ─────────────────── repair is bounded (§20/§22) ───────────────────

class _AlwaysBad:
    name, model = "bad", "stub"

    def __init__(self):
        self.calls = 0
        self.last_prompt, self.last_raw = "", None

    def is_configured(self):
        return True

    def synthesize_concept(self, **kw):
        self.calls += 1
        return StructuredArchitecturalConcept(concept_title="x")


def test_a_failing_provider_is_retried_exactly_once(setup):
    ont, brief, program, rec = setup
    bad = _AlwaysBad()
    r = CreativeSynthesizer(ont, bad, max_repairs=1).synthesize(
        dna=rec.concepts[0], brief=brief, program=program, seed=1)
    assert bad.calls == 2, "one synthesis plus exactly one repair"
    assert not r.validation.passed
    assert r.trace.repaired and r.trace.repair_instruction


def test_a_raising_provider_degrades_the_concept_not_the_run(setup):
    class _Boom(_AlwaysBad):
        def synthesize_concept(self, **kw):
            raise RuntimeError("model is down")

    ont, brief, program, rec = setup
    r = CreativeSynthesizer(ont, _Boom()).synthesize(
        dna=rec.concepts[0], brief=brief, program=program, seed=1)
    assert r.concept is None and not r.validation.passed
    assert "model is down" in r.trace.error


def test_ten_concepts_cost_ten_calls_when_nothing_needs_repair(setup):
    ont, brief, program, rec = setup
    provider = MockCreativeProvider(ont)
    synth = CreativeSynthesizer(ont, provider)
    for dna in rec.concepts:
        synth.synthesize(dna=dna, brief=brief, program=program, seed=42)
    assert provider.calls == len(rec.concepts)


# ─────────────────── the prompt compiler (§14/§15) ───────────────────

def test_the_compiler_emits_every_required_section(setup):
    ont, brief, program, rec = setup
    r = _valid(ont, brief, program, rec)
    p = ArchitecturalPromptCompiler(ont).compile(
        dna=rec.concepts[0], concept=r.concept, brief=brief, program=program,
        constraints=r.constraints)
    names = {s.name for s in p.sections}
    for required in SECTION_ORDER:
        assert required in names, f"missing section {required}"
    assert p.missing_sections == []


def test_the_compiler_does_not_just_echo_the_model(setup):
    """SUBJECT is authoritative: it comes from the brief, never from the model."""
    ont, brief, program, rec = setup
    r = _valid(ont, brief, program, rec)
    p = ArchitecturalPromptCompiler(ont).compile(
        dna=rec.concepts[0], concept=r.concept, brief=brief, program=program,
        constraints=r.constraints)
    subject = next(s for s in p.sections if s.name == "SUBJECT")
    assert subject.source == "brief"
    assert "500" in subject.text and "wedding mandap" in subject.text


def test_a_prompt_is_still_complete_with_no_llm_concept_at_all(setup):
    """§21/§27 — the deterministic engine alone still produces a full prompt."""
    ont, brief, program, rec = setup
    r = _valid(ont, brief, program, rec)
    p = ArchitecturalPromptCompiler(ont).compile(
        dna=rec.concepts[0], concept=None, brief=brief, program=program,
        constraints=r.constraints)
    assert p.degraded is True
    assert {s.name for s in p.sections} >= set(SECTION_ORDER)
    assert {s.source for s in p.sections} <= {"brief", "dna", "compiler"}


def test_negative_prompt_combines_every_source(setup):
    ont, brief, program, rec = setup
    synth = CreativeSynthesizer(ont, MockCreativeProvider(ont))
    r = synth.synthesize(dna=rec.concepts[0], brief=brief, program=program,
                         forbidden_tokens=["zeppelin"], seed=42)
    p = ArchitecturalPromptCompiler(ont).compile(
        dna=rec.concepts[0], concept=r.concept, brief=brief, program=program,
        constraints=r.constraints, extra_negatives=["marzipan"])
    neg = p.negative_prompt
    assert "zeppelin" in neg and "marzipan" in neg
    assert "generic palace" in neg
    assert "applied floral decoration" in neg          # from the concept's anti_cliches


def test_prompts_differ_across_concepts(setup):
    ont, brief, program, rec = setup
    synth = CreativeSynthesizer(ont, MockCreativeProvider(ont))
    comp = ArchitecturalPromptCompiler(ont)
    hashes = set()
    for dna in rec.concepts:
        r = synth.synthesize(dna=dna, brief=brief, program=program, seed=42)
        hashes.add(comp.compile(dna=dna, concept=r.concept, brief=brief,
                                program=program, constraints=r.constraints).prompt_hash)
    assert len(hashes) == len(rec.concepts)


# ─────────────────── regression (§27) ───────────────────

def test_synthesis_is_off_by_default(container):
    assert Settings().synthesis_enabled is False
    assert container.pipeline.synthesizer is None


def test_a_run_without_a_synthesizer_records_no_synthesis_stage(setup):
    _, _, _, rec = setup
    assert "14b" not in [s.stage for s in rec.stage_runs]
    assert rec.structured == {} and rec.arch_prompts == {}
    assert rec.synthesis_calls == 0
