// Empty by default: requests go to the page's own origin and next.config.mjs
// rewrites /api/* to the engine. That keeps the app working unchanged whether it
// is opened at localhost or through a tunnel. Set NEXT_PUBLIC_API_BASE only to
// point the UI at an engine somewhere else.
export const API = process.env.NEXT_PUBLIC_API_BASE ?? "";

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`${API}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    cache: "no-store",
  });
  if (!r.ok) throw new Error(await friendlyError(r));
  return r.json() as Promise<T>;
}

async function friendlyError(r: Response): Promise<string> {
  const raw = await r.text();
  try {
    const j = JSON.parse(raw);
    if (Array.isArray(j.detail)) return j.detail.map((d: any) => d.msg).join("; ");
    if (typeof j.detail === "string") return j.detail;
  } catch {
    /* fall through to the raw body */
  }
  return raw.slice(0, 200) || `Request failed (${r.status})`;
}

/* ── what the UI actually consumes ──────────────────────────────── */

export type Shot = {
  view_key: string;
  view_label: string;
  positive_prompt: string;
  negative_prompt: string;
  camera: string;
  shared_signature: string;
  prompt_hash: string;
};

export type Step = { step: string; description: string };

/** Present once the writer has been asked for this concept.
 *  `available: false` means the model was asked and failed — never silently treat
 *  that as written, or engine prose gets presented as the model's work. */
export type Synthesis = {
  available: boolean;
  thesis?: string;
  concept_title?: string;
  model?: string;
  source?: string;
  valid?: boolean | null;
  error?: string;
} | null;

export type Concept = {
  concept_id: string;
  index: number;
  title: string;
  one_line: string;
  signature_read: string;
  headline_dna: {
    architectural_language: string;
    geometry: string;
    structural_logic: string;
    material: string;
    spatial_narrative: string;
    emotional_register: string;
  };
  synthesis: Synthesis;
};

/** Written = the model actually produced this concept. */
export const isWritten = (c: Concept) => c.synthesis?.available === true;
/** Failed = the model was asked and could not. */
export const hasFailed = (c: Concept) => c.synthesis?.available === false;
/** Settled = nothing more will happen to this card. */
export const isSettled = (c: Concept) => c.synthesis != null;

export type ConceptDetail = Concept & {
  structured_concept: {
    concept_title: string;
    concept_thesis: string;
    design_story: string;
    architectural_language: string;
    spatial_organization: string;
    arrival_sequence: string;
    circulation: string;
    atmosphere: string;
    landscape: string;
    human_experience: string;
    construction_character: string;
    rationale: string;
    spatial_sequence: Step[];
    anti_cliches: string[];
    distinctive_elements: string[];
    program: Record<string, any>;
    structure: Record<string, string>;
    materials: Record<string, any>;
    lighting: Record<string, any>;
  } | null;
  architectural_prompt: { positive_prompt: string; negative_prompt: string } | null;
  view_prompts: Shot[];
};

export type Exploration = {
  exploration_id: string;
  status: string;
  k: number;
};

export type BriefInput = {
  brief: string;
  project_type?: string;
  event_type?: string; // what is happening — decides the shot list
  tradition?: string; // decides the ceremonial focus: mandap / nikah / altar / palki
  venue_type?: string;
  location?: string;
  dimensions?: string;
  budget?: string;
  k?: number;
  inspiration?: string; // trend mode, "OFF" when unused
  references?: string[]; // curated references to work in, by display name
  influence?: number; // 0..1, how strongly they push
};

export type ReferenceHit = {
  reference_id: string;
  display_name: string;
  kind: string;
  resolved_by: string;
  confidence: number;
  blurb: string;
};

export function searchReferences(q: string): Promise<{ results: ReferenceHit[] }> {
  return req(`/api/references/search?q=${encodeURIComponent(q)}`);
}

/** How literally a reference is taken. The engine transfers principles, never props. */
export const REFERENCE_PRESETS = [
  { value: "INSPIRED_BY", label: "Inspired by", hint: "Takes the underlying idea only." },
  { value: "IN_THE_STYLE_OF", label: "In the style of", hint: "Leans harder on its language." },
  { value: "ECHOES_OF", label: "Echoes of", hint: "A trace, barely legible." },
];

// The ceremonial focus is not a dressing choice — a mandap, a nikah stage, an
// altar and a palki differ in axis, enclosure and what must stay open to the sky.
export const TRADITIONS = [
  { value: "UNSPECIFIED", label: "Not stated" },
  { value: "HINDU", label: "Hindu", focus: "Mandap" },
  { value: "MUSLIM", label: "Muslim", focus: "Nikah stage" },
  { value: "CHRISTIAN", label: "Christian", focus: "Altar" },
  { value: "SIKH", label: "Sikh", focus: "Palki Sahib" },
  { value: "SECULAR", label: "Secular", focus: "Ceremony focus" },
];

export const VENUE_TYPES = [
  { value: "CONVENTION_SPACE", label: "Convention space" },
  { value: "BANQUET_HALL", label: "Banquet hall" },
  { value: "LAWN", label: "Lawn / outdoor" },
  { value: "HERITAGE", label: "Heritage property" },
  { value: "BEACH", label: "Beach" },
];

export const TREND_MODES = [
  { value: "CURRENT_INSPIRATION", label: "Current inspiration" },
  { value: "TRENDING_NOW", label: "Trending now" },
  { value: "DESIGN_TRENDS", label: "Design trends" },
  { value: "CULTURAL_MOMENT", label: "Cultural moment" },
  { value: "SURPRISE_ME", label: "Surprise me" },
];

export const PROJECT_TYPES = [
  { value: "", label: "Detect from the brief" },
  { value: "WEDDING_MANDAP", label: "Wedding / Mandap" },
  { value: "EVENT_STAGE", label: "Event stage" },
  { value: "RESTAURANT", label: "Restaurant" },
  { value: "INTERIOR", label: "Interior" },
  { value: "PAVILION", label: "Pavilion" },
  { value: "EXHIBITION", label: "Exhibition" },
  { value: "GENERIC_SPATIAL", label: "Other space" },
];

export function createExploration(input: BriefInput): Promise<Exploration> {
  const body: Record<string, unknown> = {
    brief: input.brief,
    project_type: input.project_type || undefined,
    event_type: input.event_type?.trim() || undefined,
    tradition: input.tradition && input.tradition !== "UNSPECIFIED" ? input.tradition : undefined,
    venue_type: input.venue_type || undefined,
    location: input.location || undefined,
    dimensions: input.dimensions || undefined,
    budget: input.budget || undefined,
    k: input.k ?? 10,
  };
  if (input.inspiration && input.inspiration !== "OFF") {
    body.trend = { mode: input.inspiration, influence: 0.55, max_selected: 3 };
  }
  if (input.references?.length) {
    body.reference = {
      references: input.references.slice(0, 4), // the API caps at four
      influence: input.influence ?? 0.55,
      preset: "INSPIRED_BY",
      synthesis: true,
    };
  }
  return req<Exploration>("/api/explorations", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

/* ── design intelligence ─────────────────────────────────────────── */

export type SemanticZone = {
  key: string;
  label: string;
  role: string;
  priority: "required" | "recommended" | "optional";
  provenance: string;
  rationale: string;
};

export type SemanticElement = {
  key: string;
  label: string;
  status: "REQUIRED" | "RECOMMENDED" | "OPTIONAL" | "FORBIDDEN" | "CONTEXTUAL";
  provenance: string;
  rationale: string;
  rule: string;
};

/** What the engine understood the brief to be, before any design was explored. */
export type SemanticReading = {
  profile: {
    identity: {
      event_type: string;
      event_type_label: string;
      event_family: string | null;
      tradition: string | null;
      known_type: boolean;
      provenance: string;
    };
    primary_activities: { key: string; label: string; provenance: string }[];
    audience_relationship: string;
    focal_relationship: string;
    elements: SemanticElement[];
  };
  intent: {
    primary_focus: string;
    must_communicate: string[];
    avoid: string[];
    uncertainties: string[];
  };
  programme: SemanticZone[];
  reasoner: { source: string; model: string; error: string | null };
};

export function interpretBrief(input: {
  brief: string;
  event_type?: string;
  tradition?: string;
  project_type?: string;
}): Promise<SemanticReading> {
  return req("/api/semantics/interpret", {
    method: "POST",
    body: JSON.stringify({
      brief: input.brief,
      event_type: input.event_type || undefined,
      tradition: input.tradition || undefined,
      project_type: input.project_type || undefined,
    }),
  });
}

export type KnowledgeCatalogue = {
  version: string;
  event_types: { key: string; label: string; family: string; traditions: string[] }[];
  traditions: Record<string, string>;
};

export function getKnowledge(): Promise<KnowledgeCatalogue> {
  return req("/api/semantics/knowledge");
}

export function getConcepts(id: string): Promise<{ concepts: Concept[] }> {
  return req(`/api/explorations/${id}/concepts`);
}

export function getExploration(id: string): Promise<{ status?: string } & Record<string, any>> {
  return req(`/api/explorations/${id}`);
}

/* ── session history ─────────────────────────────────────────────── */

/** A past run, kept on disk so it survives a backend restart. */
export type Session = {
  exploration_id: string;
  session_no: number;
  saved_at: number;
  started_at: number;
  status: string;
  brief: string;
  concepts: number;
  /** How many the writer has finished. Below `k` while a run is still going. */
  written: number;
  seed: number | null;
  k: number | null;
};

/** A run still in flight. Its row keeps updating instead of waiting for the end. */
export const isRunning = (s: Session) => s.status !== "COMPLETE" && s.status !== "FAILED";

export function listSessions(): Promise<{ sessions: Session[] }> {
  return req("/api/sessions");
}

/** The saved exploration payload — same shape the live endpoint returns. */
export function getSession(id: string): Promise<{ concepts: Concept[] } & Record<string, any>> {
  return req(`/api/sessions/${id}`);
}

export function getSessionConcept(
  explorationId: string,
  conceptId: string
): Promise<ConceptDetail> {
  return req(`/api/sessions/${explorationId}/concepts/${conceptId}`);
}

export function getConcept(id: string): Promise<ConceptDetail> {
  return req(`/api/concepts/${id}`);
}
