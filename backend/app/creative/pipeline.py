"""The staged pipeline.

Fifteen stages, of which nine are fully deterministic. Every stage records a
StageRun, so an exploration can answer "why does concept 7 exist?" and "why was
concept 12 rejected?" from stored data alone.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from app.core import logging as elog
from app.core.hashing import short_hash
from app.core.ids import deterministic_id, new_id
from app.core.seeded import SeededRandom
from app.core.versions import VersionStamp
from app.creative.antibrief import build_antibrief
from app.creative.context import BriefContext
from app.creative.mockgen import make_program_generator  # noqa: F401  (registered in composition)
from app.creative.phenotype import synthesise_phenotype
from app.creative.portfolio import select_portfolio
from app.creative.program import attach_soft_intents, build_program, estimate_capacity
from app.creative.schemas import ProgramProposal
from app.critics.runner import evaluate
from app.diversity.matrix import build_matrix, is_duplicate
from app.diversity.metric import D_MIN, genotype_distance
from app.domain.antibrief import AntiBrief, AntiBriefProposal
from app.domain.brief import DesignBrief, DesignProgram
from app.domain.common import ModelTier, NicheRole, Typology, ViewRole
from app.domain.concept import ConceptDNA, Lineage, RejectionRecord
from app.domain.diversity import DiversityMatrix
from app.domain.genotype import ConceptGenotype
from app.domain.niche import Niche
from app.domain.portfolio import Portfolio
from app.domain.prompt import PromptCompilation
from app.domain.providers.protocols import LLMProvider, PromptBlock, PromptEnvelope
from app.domain.scene import SceneGraph
from app.domain.space import CreativeSearchSpace
from app.domain.trace import RepairRecord, StageRun
from app.critics.originality import run_originality
from app.niche.allocator import allocate, novelty
from app.ontology.index import index_for
from app.ontology.graph import Ontology
from app.prompt.compiler import compile_prompt
from app.repair.engine import repair_concept
from app.scene.build import build_scene_graph
from app.semantics.intelligence import DesignIntelligence, log_reading
from app.semantics.priors import semantic_priors
from app.visual.director import VisualDirector, log_intent
from app.space.instantiate import instantiate_with_relaxation

STAGES = [
    ("01", "Design intelligence"), ("02", "Design programme"), ("03", "Anti-brief"),
    ("04", "Search space"), ("05", "Niche allocation"), ("06", "Genotype solve"),
    ("07", "Principle injection"), ("08", "Phenotype synthesis"), ("09", "Critics"),
    ("10", "Repair"), ("11", "Diversity evaluation"), ("12", "Portfolio selection"),
    ("13", "Scene graph"), ("14", "Prompt compilation"), ("15", "Trace & archive"),
]


class RunCancelled(Exception):
    """Raised at a stage boundary once the run's cancel flag is set."""


@dataclass
class ExplorationRecord:
    exploration_id: str
    status: str
    seed: int
    k: int
    brief: DesignBrief
    versions: VersionStamp
    program: DesignProgram | None = None
    semantic: object | None = None           # SemanticBrief: what the brief means
    llm_trace: list = field(default_factory=list)   # LLMCallRecord per reasoning call
    visual_intents: dict = field(default_factory=dict)   # cid -> list[VisualIntent]
    antibrief: AntiBrief | None = None
    space: CreativeSearchSpace | None = None
    niches: list[Niche] = field(default_factory=list)
    concepts: list[ConceptDNA] = field(default_factory=list)
    rejected: list[ConceptDNA] = field(default_factory=list)
    matrix: DiversityMatrix | None = None
    portfolio: Portfolio | None = None
    scenes: dict[str, SceneGraph] = field(default_factory=dict)
    prompts: dict[str, PromptCompilation] = field(default_factory=dict)
    # LLM creative synthesis — populated only when a synthesizer is configured
    structured: dict = field(default_factory=dict)          # cid -> StructuredArchitecturalConcept
    arch_prompts: dict = field(default_factory=dict)        # cid -> ArchitecturalVisualizationPrompt
    view_prompts: dict = field(default_factory=dict)        # cid -> list[per-area prompt]
    validations: dict = field(default_factory=dict)         # cid -> ConceptValidation
    synthesis_traces: dict = field(default_factory=dict)    # cid -> SynthesisTrace
    synthesis_calls: int = 0
    synthesis_repairs: int = 0
    injection: object | None = None          # CreativePrincipleInjection, or None
    trend_result: object | None = None       # TrendDiscoveryResult, for the trace only
    principle_index: object | None = None
    cognition: object | None = None          # CreativeMemory, when the layer ran
    stage_runs: list[StageRun] = field(default_factory=list)
    repairs: list[RepairRecord] = field(default_factory=list)
    degraded: list[str] = field(default_factory=list)
    llm_calls: int = 0
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    error: str | None = None
    # A threading.Event set by the API to stop the run. Checked at every stage boundary
    # and between concepts; a model call already in flight is allowed to finish.
    cancel: object | None = field(default=None, repr=False)

    def cancelled(self) -> bool:
        return bool(self.cancel is not None and self.cancel.is_set())

    def all_concepts(self) -> list[ConceptDNA]:
        return self.concepts + self.rejected

    def concept(self, cid: str) -> ConceptDNA | None:
        return next((c for c in self.all_concepts() if c.concept_id == cid), None)

    def stage_status(self) -> list[dict]:
        done = {s.stage for s in self.stage_runs}
        out = []
        for code, label in STAGES:
            run = next((s for s in self.stage_runs if s.stage == code), None)
            out.append({
                "stage": code, "label": label,
                "status": run.status if run else ("RUNNING" if self.status == "RUNNING" and
                                                  code not in done else "PENDING"),
                "latency_ms": run.latency_ms if run else 0,
                "detail": run.detail if run else "",
            })
        return out


def _archive_key(program: DesignProgram) -> str:
    """Novelty is measured against past concepts for the same EVENT. A Sangeet is not
    made "novel" by differing from last week's mandaps."""
    sem = program.semantic
    return f"event:{sem.profile.identity.event_type}" if sem else program.typology.value


class Pipeline:
    def __init__(self, ont: Ontology, llm: LLMProvider, store, use_llm_critics: bool = True,
                 synthesizer=None, arch_compiler=None, view_compiler=None,
                 embeddings=None, cognition=None, intelligence=None,
                 visual_director=None) -> None:
        self.ont = ont
        self.llm = llm
        self.store = store
        self.use_llm_critics = use_llm_critics
        # All optional. With synthesizer=None the pipeline is byte-for-byte the one
        # that existed before this layer (§27) — the stages below are simply not run.
        self.synthesizer = synthesizer
        self.arch_compiler = arch_compiler
        self.view_compiler = view_compiler
        # Channel 2 of duplicate detection. None => genotype distance alone, which is
        # the behaviour every existing baseline was recorded against.
        self.embeddings = embeddings
        # Creative Cognition. None => no conceptual expansion, no extra candidates,
        # no extra provider calls, no extra randomness drawn.
        self.cognition = cognition
        # Design Intelligence always runs. Without a reasoning model it is the
        # deterministic reading, and the trace says so.
        self.intelligence = intelligence or DesignIntelligence()
        # Visual Director. Always present: deterministic direction from the semantics,
        # the concept and the scene; a reasoning model may refine the hero view.
        self.visual_director = visual_director or VisualDirector(ont)

    def _drop_duplicates(self, ont: Ontology, pool: list[ConceptDNA]):
        """Two concepts that are the same idea in different words are one concept.

        Channel 1 (genotype distance) always runs. Channel 2 (thesis embedding) runs
        only when an embedding provider is configured, and per spec R-DIV-02 it may
        only ADD rejections, never remove one — so a run without embeddings is a
        strict behavioural subset of a run with them, and existing baselines hold.

        Deterministic: the pool is already ordered by niche_index, and of any duplicate
        pair the LATER concept is the one dropped.
        """
        if len(pool) < 2:
            return pool, []
        vecs: list[list[float]] | list[None] = [None] * len(pool)
        if self.embeddings is not None and self.embeddings.is_configured():
            vecs = self.embeddings.embed_text([c.phenotype.design_thesis for c in pool])

        keep: list[ConceptDNA] = []
        kept_idx: list[int] = []
        dropped: list[ConceptDNA] = []
        for i, cand in enumerate(pool):
            dup_reason = None
            for j in kept_idx:
                is_dup, reason = is_duplicate(ont, pool[j], cand, vecs[j], vecs[i])
                if is_dup:
                    dup_reason = reason
                    break
            if dup_reason:
                dropped.append(cand.model_copy(update={
                    "status": "REJECTED",
                    "rejection": RejectionRecord(
                        stage="11", reason_code=dup_reason,
                        detail="duplicate of an already-selected concept"),
                }))
            else:
                keep.append(cand)
                kept_idx.append(i)
        return keep, dropped

    @staticmethod
    def _reference_statements(rec: "ExplorationRecord", dna) -> list[str]:
        """The transferred PRINCIPLE only.

        The reference's name never reaches the model: an injected principle is already
        the abstracted reading, and passing the source would reintroduce exactly the
        literal copying the whole reference layer exists to prevent.
        """
        index = rec.principle_index
        if index is None or not getattr(dna, "principle_id", None):
            return []
        principle = index.get(dna.principle_id)
        if principle is None:
            return []
        return [s for s in (getattr(principle, "statements", None) or []) if s]

    # ---------- helpers ----------
    def _stage(self, rec: ExplorationRecord, code: str, label: str):
        class _Ctx:
            def __init__(self, outer, rec, code, label):
                self.outer, self.rec, self.code, self.label = outer, rec, code, label
                self.calls_before = rec.llm_calls
                self.detail = ""
            def __enter__(self):
                if self.rec.cancelled():
                    raise RunCancelled(self.code)
                self.t0 = time.perf_counter()
                return self
            def __exit__(self, exc_type, exc, tb):
                ms = int((time.perf_counter() - self.t0) * 1000)
                calls = self.rec.llm_calls - self.calls_before
                status = "FAILED" if exc_type else "OK"
                detail = self.detail if not exc_type else f"{exc_type.__name__}: {exc}"
                self.rec.stage_runs.append(StageRun(
                    stage=self.code, label=self.label, status=status,
                    llm_calls=calls, latency_ms=ms, detail=detail,
                ))
                # The live trace mirrors the recorded StageRun exactly, so what you
                # watch and what you later read back from the API cannot disagree.
                elog.stage(self.code, self.label, status, ms, detail, calls)
                return False
        return _Ctx(self, rec, code, label)

    def _resynth(self, program, niche_principles, sibling_titles, seed):
        def fn(genotype, preserve_title=None, preserve_signature=None, fix_notes=None):
            ph, fail, calls = synthesise_phenotype(
                self.llm, self.ont, program, genotype, role=NicheRole.EXPLORATORY, seed=seed,
                principle_statements=niche_principles, sibling_titles=sibling_titles,
                preserve_title=preserve_title, preserve_signature=preserve_signature,
                fix_notes=fix_notes,
            )
            return ph, fail, calls
        return fn

    # ---------- the run ----------
    def run(self, brief: DesignBrief, k: int, seed: int,
            injection=None, trend_result=None, cancel=None) -> ExplorationRecord:
        """`injection` is the ONLY channel Reference Intelligence has (R-REF-01).
        With injection=None the pipeline is byte-identical to the pre-reference
        implementation for a given seed (R-REF-15)."""
        ont = self.ont
        versions = VersionStamp(ontology_version=ont.version)
        rec = ExplorationRecord(
            exploration_id=deterministic_id("ex", brief.brief_id, str(seed), str(k),
                                            *( [injection.injection_id] if injection else [] )),
            status="RUNNING", seed=seed, k=k, brief=brief, versions=versions,
            injection=injection, trend_result=trend_result, cancel=cancel,
        )
        elog.note("=" * 78)
        elog.note(f"RUN {rec.exploration_id}  k={k} seed={seed} "
                  f"ontology={ont.version}")
        elog.note(f"     brief: {brief.raw_text[:70]!r}")
        elog.note(f"     form: event={brief.event_type_text or brief.event_type.value} "
                  f"tradition={brief.tradition.value} venue={brief.venue_type.value} "
                  f"typology={brief.typology.value}")
        # State the optional layers UP FRONT, present or absent. Reading "why did
        # nothing happen" out of an absence is the slowest kind of debugging.
        elog.note(f"     layers: reference={'on' if injection else 'off'} "
                  f"trend={'on' if trend_result else 'off'} "
                  f"cognition={'on' if self.cognition else 'off'} "
                  f"synthesis={'on' if self.synthesizer else 'off'} "
                  f"dedupe_ch2={'on' if self.embeddings else 'off'}")
        elog.note("=" * 78)
        ref_dnas = list(injection.reference_dnas) if injection else []
        ref_blocked = injection.blocked_tokens() if injection else []
        rec.principle_index = index_for(ont, injection.principles if injection else [])
        self.store.put(rec)
        rng = SeededRandom(seed, "pipeline", rec.exploration_id)
        try:
            # 01 design intelligence — understand the brief BEFORE any creative search.
            # Everything downstream reads the programme it produces; nothing downstream
            # re-reads the brief prose to decide what the event is.
            with self._stage(rec, "01", "Design intelligence") as st:
                calls_before = len(self.intelligence.calls)
                semantic = self.intelligence.understand(
                    brief, capacity=estimate_capacity(brief))
                new_calls = self.intelligence.calls[calls_before:]
                rec.llm_trace += list(new_calls)
                rec.llm_calls += len(new_calls)
                rec.semantic = semantic
                ident = semantic.profile.identity
                if semantic.reasoner.error:
                    rec.degraded.append(f"01: reasoning model failed ({semantic.reasoner.error[:80]}); "
                                        "deterministic reading used")
                st.detail = (f"{ident.event_type_label} [{ident.event_type}"
                             f"{'' if ident.known_type else ', inferred'}] via "
                             f"{semantic.reasoner.source.lower()}: {len(semantic.programme)} zones, "
                             f"{len(semantic.profile.forbidden_keys())} forbidden, "
                             f"{len(semantic.invariants)} invariants")
            log_reading(semantic)
            with self._stage(rec, "02", "Design programme") as st:
                program = build_program(ont, brief, semantic)
                proposal = self._program_proposal(program, brief)
                rec.llm_calls += 1
                program = attach_soft_intents(program, proposal.soft_intents)
                rec.program = program
                st.detail = f"{len(program.invariants)} invariants, {len(program.soft_intents)} soft intents"

            # 04 search space (before anti-brief: the canonical seed must be legal)
            with self._stage(rec, "04", "Search space") as st:
                priors = semantic_priors(semantic)
                space = instantiate_with_relaxation(
                    ont, program, list(injection.prior_bias) if injection else None,
                    semantic_priors=priors)
                rec.space = space
                scoped = sum(1 for d in space.domains for e in d.excluded
                             if e.rule_id == "semantic_scope")
                st.detail = (f"dim={space.effective_dimensionality:.1f}, "
                             f"{sum(len(d.excluded) for d in space.domains)} values pruned "
                             f"({scoped} out of semantic scope), {len(priors)} semantic priors")

            # 03 anti-brief
            with self._stage(rec, "03", "Anti-brief") as st:
                ab_proposal = self._antibrief_proposal(program)
                rec.llm_calls += 1
                antibrief = build_antibrief(
                    ont, program, space, ab_proposal, seed,
                    extra_clusters=injection.cliche_clusters if injection else None)
                rec.antibrief = antibrief
                st.detail = f"{len(antibrief.cliche_clusters)} clusters, seed={antibrief.canonical_seed_source}"

            # 05 + 06 + 07 allocation (solves candidate genotypes, picks the spread)
            with self._stage(rec, "05", "Niche allocation") as st:
                archive = self.store.archive_genotypes(
                    _archive_key(program), exclude_exploration_id=rec.exploration_id)
                alloc = allocate(ont, space, antibrief, rec.exploration_id, k, seed, archive,
                                 injection=injection)
                rec.niches = alloc.niches
                rec.degraded += alloc.degraded
                st.detail = f"{len(alloc.niches)} niches: " + "/".join(
                    n.role.value[:4] for n in alloc.niches)
            with self._stage(rec, "06", "Genotype solve") as st:
                st.detail = f"{len(alloc.genotypes)} genotypes solved inside their niches"
            with self._stage(rec, "07", "Principle injection") as st:
                used = [p.id for p in alloc.principles if p]
                st.detail = f"{len(used)} principles injected: " + ", ".join(
                    sorted({u.split(':')[-1] for u in used})) if used else "none eligible"

            # 08 phenotype synthesis
            candidates: list[ConceptDNA] = []
            fidelity_by_concept: dict[str, list[str]] = {}
            titles: list[str] = []
            with self._stage(rec, "08", "Phenotype synthesis") as st:
                for i, (niche, genotype) in enumerate(zip(alloc.niches, alloc.genotypes)):
                    principle = alloc.principles[i]
                    statements = principle.statements if principle else []
                    # every niche carries the reference lexicon, including those with no
                    # reference principle — the wildcard may not name the source either
                    forbidden_tokens = sorted(set(
                        (principle.forbidden_surface_tokens if principle else []) + ref_blocked))
                    ph, fidelity, calls = synthesise_phenotype(
                        self.llm, ont, program, genotype, role=niche.role,
                        seed=seed + i, principle_statements=statements,
                        forbidden_tokens=forbidden_tokens, sibling_titles=titles,
                    )
                    rec.llm_calls += calls
                    titles.append(ph.title)
                    dna = ConceptDNA(
                        concept_id=deterministic_id("cn", rec.exploration_id, str(i)),
                        exploration_id=rec.exploration_id, niche_id=niche.niche_id,
                        niche_index=niche.index, role=niche.role,
                        lineage=Lineage(origin="ALLOCATED"), genotype=genotype, phenotype=ph,
                        principle_id=principle.id if principle else None,
                        versions=versions, status="DRAFT",
                    )
                    candidates.append(dna)
                    fidelity_by_concept[dna.concept_id] = fidelity
                st.detail = f"{len(candidates)} phenotypes"

            # 08c creative cognition — conceptual expansion of the candidate set.
            # Runs AFTER phenotype because each operation reads the concept's actual
            # thesis, and BEFORE the scene graph and critics so every child faces the
            # same deterministic verification as an allocated concept. With
            # cognition=None nothing below executes and the run is unchanged.
            if self.cognition is None:
                elog.skip("08c", "Creative cognition",
                          "disabled (CREATIVE_COGNITION_ENABLED=false)")
            else:
                with self._stage(rec, "08c", "Creative cognition") as st:
                    before = len(candidates)
                    expanded = self.cognition.expand(
                        concepts=candidates, program=program, antibrief=antibrief,
                        space=space, exploration_id=rec.exploration_id, seed=seed,
                        principle_statements=tuple(
                            s for p in alloc.principles if p for s in p.statements)[:4],
                    )
                    for j, dna in enumerate(expanded[before:], start=before):
                        ph, fidelity, calls = synthesise_phenotype(
                            self.llm, ont, program, dna.genotype, role=dna.role,
                            seed=seed + j, principle_statements=[],
                            forbidden_tokens=sorted(set(ref_blocked)), sibling_titles=titles,
                        )
                        rec.llm_calls += calls
                        titles.append(ph.title)
                        child = dna.model_copy(update={"phenotype": ph})
                        candidates.append(child)
                        fidelity_by_concept[child.concept_id] = fidelity
                    rec.cognition = self.cognition.memory
                    st.detail = (f"+{len(candidates) - before} concepts from "
                                 f"{len(self.cognition.memory.records)} operations")

            # 13 scene graph (before critics: alignment + feasibility read it)
            with self._stage(rec, "13", "Scene graph") as st:
                for dna in candidates:
                    scene, calls = build_scene_graph(
                        self.llm, ont, dna.concept_id, dna.genotype, program, seed)
                    rec.llm_calls += calls
                    rec.scenes[dna.concept_id] = scene
                ok = sum(1 for s in rec.scenes.values() if s.status == "COMPLETE")
                st.detail = f"{ok}/{len(rec.scenes)} COMPLETE"

            # 09 critics
            with self._stage(rec, "09", "Critics") as st:
                evaluated: list[ConceptDNA] = []
                for dna in candidates:
                    nov = novelty(ont, dna.genotype, archive)
                    ref_ctx = None
                    orig = None
                    if injection is not None:
                        ref_ctx = self._reference_context(
                            dna, injection, ref_dnas, space, alloc, is_canonical=(
                                dna.role == NicheRole.CANONICAL))
                        orig = run_originality(ref_ctx, dna.role)
                    ev, calls = evaluate(
                        self.llm, ont, dna, program, rec.scenes.get(dna.concept_id),
                        fidelity_by_concept.get(dna.concept_id, []), seed, novelty=nov,
                        use_llm=self.use_llm_critics, originality=orig,
                    )
                    rec.llm_calls += calls
                    evaluated.append(dna.model_copy(update={
                        "evaluation": ev, "status": "EVALUATED",
                        "reference_context": ref_ctx,
                        "scene_graph_id": rec.scenes[dna.concept_id].scene_graph_id,
                    }))
                passed = sum(1 for c in evaluated if c.evaluation.gate_passed)
                st.detail = f"{passed}/{len(evaluated)} passed all four gates"

            # 09c creative evolution — a failing concept may come back as a DIFFERENT
            # answer rather than a patched one. Repair still runs below and still fixes
            # defects while holding identity exactly; evolution is allowed to move a
            # conceptual variable instead, which repair by design is not.
            if self.cognition is None:
                elog.skip("09c", "Creative evolution", "cognition layer disabled")
            else:
                with self._stage(rec, "09c", "Creative evolution") as st:
                    before = len(evaluated)
                    grown = self.cognition.evolve(
                        concepts=evaluated, program=program, antibrief=antibrief,
                        space=space, exploration_id=rec.exploration_id, seed=seed)
                    for j, dna in enumerate(grown[before:], start=1000):
                        ph, fidelity, calls = synthesise_phenotype(
                            self.llm, ont, program, dna.genotype, role=dna.role,
                            seed=seed + j, principle_statements=[],
                            forbidden_tokens=sorted(set(ref_blocked)), sibling_titles=titles)
                        rec.llm_calls += calls
                        titles.append(ph.title)
                        child = dna.model_copy(update={"phenotype": ph})
                        scene, scalls = build_scene_graph(
                            self.llm, ont, child.concept_id, child.genotype, program, seed)
                        rec.llm_calls += scalls
                        rec.scenes[child.concept_id] = scene
                        ev, ecalls = evaluate(
                            self.llm, ont, child, program, scene, fidelity, seed,
                            novelty=novelty(ont, child.genotype, archive),
                            use_llm=self.use_llm_critics)
                        rec.llm_calls += ecalls
                        evaluated.append(child.model_copy(update={
                            "evaluation": ev, "status": "EVALUATED",
                            "scene_graph_id": scene.scene_graph_id}))
                        fidelity_by_concept[child.concept_id] = fidelity
                    st.detail = f"+{len(evaluated) - before} evolved from critic findings"

            # 10 repair
            with self._stage(rec, "10", "Repair") as st:
                repaired: list[ConceptDNA] = []
                budget = 8
                # repair scarce mandatory roles FIRST: a failed RADICAL costs the
                # curriculum, a failed ADJACENT has three siblings to fall back on
                # CANONICAL first: it is the designer's safe option and the single
                # slot whose absence is most visible in front of a client.
                ROLE_PRIORITY = {NicheRole.CANONICAL: 0, NicheRole.RADICAL: 1,
                                 NicheRole.WILDCARD: 2, NicheRole.EXPLORATORY: 3,
                                 NicheRole.ADJACENT: 4}
                for dna in sorted(evaluated, key=lambda c: ROLE_PRIORITY.get(c.role, 5)):
                    if dna.evaluation.gate_passed or budget <= 0:
                        repaired.append(dna)
                        continue
                    siblings = [
                        c.genotype for c in evaluated
                        if c.concept_id != dna.concept_id
                        and genotype_distance(ont, c.genotype, dna.genotype) >= D_MIN
                    ]  # a near-clone is a competitor, not a sibling to preserve distance from
                    out = repair_concept(
                        self.llm, ont, space, program, dna, siblings,
                        rec.scenes.get(dna.concept_id),
                        self._resynth(program, [], titles, seed), rng.substream("repair", dna.concept_id),
                        seed, use_llm=self.use_llm_critics,
                    )
                    rec.llm_calls += out.llm_calls
                    budget -= 1
                    rec.repairs.append(RepairRecord(
                        concept_id=dna.concept_id, attempt=1,
                        finding_code=out.finding_code or "-", operator=out.operator or "-",
                        outcome=out.status, detail=out.note,
                        before_summary=dna.genotype.primary_material().material,
                        after_summary=(out.dna.genotype.primary_material().material if out.dna else "-"),
                    ))
                    repaired.append(out.dna if out.dna else dna)
                repaired.sort(key=lambda c: c.niche_index)
                st.detail = f"{len(rec.repairs)} repairs attempted, " \
                            f"{sum(1 for r in rec.repairs if r.outcome == 'REPAIRED')} succeeded"

            accepted = [c for c in repaired if c.evaluation and c.evaluation.gate_passed]
            rejected = [c.model_copy(update={
                "status": "REJECTED",
                "rejection": RejectionRecord(
                    stage="09/10", reason_code=(c.evaluation.blockers()[0].code
                                                if c.evaluation and c.evaluation.blockers()
                                                else "GATE_FAILED"),
                    detail="; ".join(f.statement for f in (c.evaluation.all_findings() if c.evaluation else [])[:3]),
                )}) for c in repaired if not (c.evaluation and c.evaluation.gate_passed)]
            rec.rejected = rejected

            # 11 diversity
            with self._stage(rec, "11", "Diversity evaluation") as st:
                pool = accepted or repaired
                pool, dupes = self._drop_duplicates(ont, pool)
                if dupes:
                    rec.rejected = rec.rejected + dupes
                matrix = build_matrix(ont, rec.exploration_id, pool)
                rec.matrix = matrix
                st.detail = (f"vendi={matrix.vendi_score:.2f} mean={matrix.mean_pairwise:.2f} "
                             f"min={matrix.min_pairwise:.2f}")

            # 12 portfolio selection
            with self._stage(rec, "12", "Portfolio selection") as st:
                portfolio = select_portfolio(ont, rec.exploration_id, pool, matrix, k)
                rec.portfolio = portfolio
                member_ids = {m.concept_id for m in portfolio.members}
                rec.concepts = [c.model_copy(update={"status": "ACCEPTED"})
                                for c in pool if c.concept_id in member_ids]
                rec.matrix = build_matrix(ont, rec.exploration_id, rec.concepts)
                rec.portfolio = portfolio.model_copy(update={"diversity": rec.matrix})
                if self.cognition is not None:
                    # close the provenance loop: which proposed ideas survived
                    self.cognition.memory.mark_selected(member_ids)
                st.detail = (f"{len(rec.concepts)} selected, curriculum "
                             f"{'satisfied' if portfolio.curriculum_satisfied else 'DEGRADED'}")

            # 14 prompt compilation
            with self._stage(rec, "14", "Prompt compilation") as st:
                for dna in rec.concepts:
                    pc = compile_prompt(ont, dna, program, rec.scenes.get(dna.concept_id),
                                        antibrief, ViewRole.HERO, "GENERIC", seed,
                                        principles=rec.principle_index)
                    rec.prompts[dna.concept_id] = pc
                rec.concepts = [c.model_copy(update={
                    "prompt_compilation_ids": [rec.prompts[c.concept_id].prompt_id]})
                    for c in rec.concepts]
                degraded_n = sum(1 for p in rec.prompts.values() if p.degraded)
                st.detail = f"{len(rec.prompts)} prompts compiled ({degraded_n} degraded)"


            # 14b LLM creative synthesis + architectural prompt compilation.
            # Runs AFTER portfolio selection so exactly k concepts are synthesised:
            # one bounded call each, never a call for a concept that was rejected.
            constraints_by_concept = {}
            forbidden = []
            if self.synthesizer is None:
                elog.skip("14b", "Creative synthesis",
                          "no writer configured (LLM_PROVIDER=mock) — the 21-section "
                          "prompts are still complete, marked degraded")
            else:
                forbidden = sorted(antibrief.surface_tokens_excluding(set()))
                with self._stage(rec, "14b", "Creative synthesis") as st:
                    for dna in rec.concepts:
                        if rec.cancelled():
                            # stop between concepts: what is written is kept
                            raise RunCancelled("14b")
                        refs = self._reference_statements(rec, dna)
                        result = self.synthesizer.synthesize(
                            dna=dna, brief=brief, program=program,
                            forbidden_tokens=forbidden,
                            reference_statements=refs, seed=seed)
                        rec.synthesis_calls += result.trace.attempts
                        rec.synthesis_repairs += 1 if result.trace.repaired else 0
                        rec.synthesis_traces[dna.concept_id] = result.trace
                        rec.validations[dna.concept_id] = result.validation
                        constraints_by_concept[dna.concept_id] = result.constraints
                        if result.concept is not None:
                            rec.structured[dna.concept_id] = result.concept
                    ok = sum(1 for v in rec.validations.values() if v.passed)
                    st.detail = (f"{len(rec.structured)}/{len(rec.concepts)} synthesised, "
                                 f"{ok} valid, {rec.synthesis_repairs} repaired, "
                                 f"{rec.synthesis_calls} model calls")

            # 14c visual direction, THEN prompt compilation. The director decides what
            # each image must communicate; the compilers only put that into words.
            with self._stage(rec, "14c", "Visual direction") as st:
                calls_before = len(self.visual_director.calls)
                views_total = 0
                for dna in rec.concepts:
                    concept = rec.structured.get(dna.concept_id)
                    scene = rec.scenes.get(dna.concept_id)
                    intents = self.visual_director.direct(
                        dna=dna, program=program, concept=concept, scene=scene)
                    rec.visual_intents[dna.concept_id] = intents
                    views_total += len(intents)
                    if self.synthesizer is None or self.arch_compiler is None:
                        continue
                    hero_intent = next((i for i in intents if i.view_key == "hero"), None)
                    hero = self.arch_compiler.compile(
                        dna=dna, concept=concept, brief=brief, program=program,
                        constraints=constraints_by_concept.get(dna.concept_id),
                        scene=scene, reference_statements=self._reference_statements(rec, dna),
                        extra_negatives=forbidden, visual=hero_intent)
                    rec.arch_prompts[dna.concept_id] = hero
                    if self.view_compiler is not None:
                        rec.view_prompts[dna.concept_id] = self.view_compiler.compile_views(
                            hero=hero, dna=dna, concept=concept, program=program,
                            brief_text=brief.raw_text, scene=scene, visual_intents=intents)
                new_calls = self.visual_director.calls[calls_before:]
                rec.llm_trace += list(new_calls)
                rec.llm_calls += len(new_calls)
                leaks = sum(len(p.semantic_leaks) for p in rec.arch_prompts.values())
                st.detail = (f"{views_total} visual intents for {len(rec.concepts)} concepts"
                             + (f", {len(new_calls)} model refinements" if new_calls else "")
                             + (f", {leaks} leaked sections removed" if leaks else ""))
            try:
                elog.note("")
                elog.note("VISUAL INTENT (hero)")
                for dna in rec.concepts:
                    hero_i = next((i for i in rec.visual_intents.get(dna.concept_id, [])
                                   if i.view_key == "hero"), None)
                    if hero_i is not None:
                        log_intent(hero_i, dna.phenotype.title)
            except Exception:                              # pragma: no cover
                pass

            # 15 archive
            # The prompt IS the product, so print it. Logged here rather than at
            # stage 14 because the 21-section architectural prompt is built in 14b.
            self._log_prompts(rec)

            with self._stage(rec, "15", "Trace & archive") as st:
                self.store.add_to_archive(
                    _archive_key(program), rec.exploration_id,
                    [c.genotype for c in rec.concepts + rec.rejected])
                st.detail = f"{len(rec.concepts)} accepted + {len(rec.rejected)} rejected archived"

            rec.status = "COMPLETE"
        except RunCancelled as where:
            rec.status = "CANCELLED"
            elog.warn(f"RUN CANCELLED {rec.exploration_id} at stage {where}: "
                      f"{len(rec.concepts)} concepts, {len(rec.structured)} written")
        except Exception as exc:                      # pragma: no cover - surfaced to the API
            rec.status = "FAILED"
            rec.error = f"{type(exc).__name__}: {exc}"
            elog.error(f"RUN FAILED {rec.exploration_id}: {rec.error}")
        finally:
            rec.finished_at = time.time()
            self.store.put(rec)
            self._log_summary(rec)
        return rec

    def _log_prompts(self, rec: ExplorationRecord) -> None:
        """The compiled image prompt for each selected concept.

        Prefers the 21-section architectural prompt when a writer ran; falls back to
        the deterministic compilation, whose segments are typed by `kind` rather than
        named — so the two shapes are normalised here.

        Wrapped: observability must never be able to fail a run. A logging defect
        that turns a COMPLETE exploration into a FAILED one is worse than no log.
        """
        try:
            elog.note("")
            elog.note("PROMPTS")
            for i, c in enumerate(rec.concepts, 1):
                arch = rec.arch_prompts.get(c.concept_id)
                if arch is not None:
                    elog.prompt(i, c.phenotype.title,
                                [(x.name, x.text) for x in arch.sections],
                                arch.prompt_hash, arch.positive_prompt)
                    continue
                pc = rec.prompts.get(c.concept_id)
                if pc is None:
                    continue
                elog.prompt(i, c.phenotype.title,
                            [(str(seg.kind).upper(), seg.text) for seg in pc.segments],
                            pc.prompt_hash, pc.positive_prompt)
        except Exception as exc:                       # pragma: no cover
            elog.warn(f"prompt logging failed ({type(exc).__name__}) — run unaffected")

    def _log_summary(self, rec: ExplorationRecord) -> None:
        """Closing block. Everything that was LOST is named with its reason —
        rejected concepts, unmet role quotas, degraded stages — so a short
        portfolio never has to be explained by re-reading the whole trace."""
        total = int(((rec.finished_at or time.time()) - rec.started_at) * 1000)
        elog.note("-" * 78)
        elog.note(f"{rec.status} {rec.exploration_id}  {total}ms  "
                  f"{len(rec.concepts)}/{rec.k} concepts  {rec.llm_calls} llm calls")
        if rec.matrix:
            elog.note(f"     diversity: vendi={rec.matrix.vendi_score} "
                      f"mean={rec.matrix.mean_pairwise} min={rec.matrix.min_pairwise}")
        if rec.rejected:
            by_reason: dict[str, int] = {}
            for c in rec.rejected:
                code = c.rejection.reason_code if c.rejection else "UNKNOWN"
                by_reason[code] = by_reason.get(code, 0) + 1
            elog.warn(f"     rejected {len(rec.rejected)}: "
                      + ", ".join(f"{k}={v}" for k, v in sorted(by_reason.items())))
        if rec.portfolio is not None and rec.portfolio.curriculum_gap:
            elog.warn(f"     curriculum GAP: {rec.portfolio.curriculum_gap} "
                      "(a role quota went unmet and was backfilled)")
        if rec.degraded:
            elog.warn(f"     degraded: {', '.join(rec.degraded[:5])}")
        if rec.cognition is not None:
            elog.note(f"     cognition: {rec.cognition.summary()}")
        if rec.validations:
            bad = [cid for cid, v in rec.validations.items() if not v.passed]
            if bad:
                elog.warn(f"     synthesis validation FAILED for {len(bad)}/"
                          f"{len(rec.validations)} concepts")
        elog.note("-" * 78)

    # ---------- reference scoring ----------
    def _reference_context(self, dna, injection, ref_dnas, space, alloc, is_canonical: bool):
        """T and I are computed deterministically here (R-REF-09). The LLM is not asked."""
        from app.references.transformation import score_concept
        niche = next((n for n in alloc.niches if n.niche_id == dna.niche_id), None)
        pids = set(niche.injected_principles) if niche else set()
        used = [p for p in injection.principles if p.id in pids] if pids else []
        thesis = " ".join([
            dna.phenotype.title, dna.phenotype.one_line, dna.phenotype.design_thesis,
            dna.phenotype.spatial_explanation, dna.phenotype.material_explanation,
            dna.phenotype.experience_narrative, dna.phenotype.what_it_is_not,
            " ".join(dna.phenotype.visual_direction.palette_words),
            dna.phenotype.visual_direction.atmosphere,
        ])
        return score_concept(self.ont, dna.genotype, thesis, "", used, ref_dnas, space,
                             is_literal_slot=is_canonical,
                             blocked=injection.blocked_tokens())

    # ---------- small LLM stages ----------
    def _program_proposal(self, program: DesignProgram, brief: DesignBrief) -> ProgramProposal:
        env = PromptEnvelope(
            prompt_id="program.extract", version="1.0.0",
            blocks=[PromptBlock(role="system", cacheable=True,
                                text="Extract only the soft intents implied by the brief."),
                    PromptBlock(role="user", cacheable=False, text=brief.raw_text)],
            schema_ref="ProgramProposal", tier=ModelTier.EXTRACTION, max_output_tokens=1024,
        )
        return self.llm.complete_structured(
            envelope=env, schema=ProgramProposal, seed=0,
            context=BriefContext(raw_text=brief.raw_text, typology=program.typology.value),
        ).value

    def _antibrief_proposal(self, program: DesignProgram) -> AntiBriefProposal | None:
        env = PromptEnvelope(
            prompt_id="antibrief.extract", version="1.0.0",
            blocks=[PromptBlock(role="system", cacheable=True,
                                text="Name the most predictable answers to this brief, and the "
                                     "assumptions a good designer would question."),
                    PromptBlock(role="user", cacheable=False, text=program.summary)],
            schema_ref="AntiBriefProposal", tier=ModelTier.CHEAP, max_output_tokens=1024,
        )
        try:
            return self.llm.complete_structured(
                envelope=env, schema=AntiBriefProposal, seed=0).value
        except Exception:
            return None       # non-fatal: curated cliches.yaml carries the floor
