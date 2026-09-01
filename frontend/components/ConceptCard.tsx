"use client";
import { Concept, hasFailed, isWritten } from "../lib/api";

/** A card the client can read. No niche, no scores, no provenance. */
export function ConceptCard({
  concept,
  n,
  onOpen,
}: {
  concept: Concept;
  n: number;
  onOpen: () => void;
}) {
  const dna = concept.headline_dna;
  const delay = { animationDelay: `${n * 40}ms` };

  // Still being written.
  if (!concept.synthesis) {
    return (
      <article className="card pending" aria-busy="true" style={delay}>
        <div className="card-num">{String(concept.index).padStart(2, "0")}</div>
        <div className="skel t" />
        <div className="skel s" />
        <div className="skel s2" />
        <div className="card-foot">
          <span>Writing this concept…</span>
        </div>
      </article>
    );
  }

  // Asked for, and the model could not deliver. Say so — never quietly show the
  // engine's own text as though the model had written it.
  if (hasFailed(concept)) {
    return (
      <article className="card failed" style={delay}>
        <div className="card-num">{String(concept.index).padStart(2, "0")}</div>
        <h3 className="card-title muted-title">Not written</h3>
        <p className="card-line">
          The model could not complete this concept.
        </p>
        {concept.synthesis?.error && (
          <p className="fail-why" title={concept.synthesis.error}>
            {concept.synthesis.error}
          </p>
        )}
        <div className="card-foot">
          <span>{dna.architectural_language}</span>
        </div>
      </article>
    );
  }

  const written = isWritten(concept);
  return (
    <article
      className="card"
      style={delay}
      onClick={onOpen}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && onOpen()}
    >
      <div className="card-num">{String(concept.index).padStart(2, "0")}</div>
      <h3 className="card-title">{concept.title}</h3>
      <p className="card-line">{concept.synthesis?.thesis || concept.one_line}</p>
      <div className="tags">
        <span className="tag">{dna.architectural_language}</span>
        <span className="tag">{dna.geometry}</span>
        <span className="tag">{dna.material}</span>
      </div>
      <div className="card-foot">
        <span>{dna.spatial_narrative}</span>
        {concept.synthesis?.valid === false ? (
          <span className="review" title="Some details did not pass the design checks">
            Needs review
          </span>
        ) : (
          <span className="card-shots">View →</span>
        )}
      </div>
    </article>
  );
}
