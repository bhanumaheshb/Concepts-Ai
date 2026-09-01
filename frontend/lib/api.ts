export const API = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000";

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
  location?: string;
  dimensions?: string;
  budget?: string;
  k?: number;
  inspiration?: string; // trend mode, "OFF" when unused
};

export const TREND_MODES = [
  { value: "CURRENT_INSPIRATION", label: "Current inspiration" },
  { value: "TRENDING_NOW", label: "Trending now" },
  { value: "DESIGN_TRENDS", label: "Design trends" },
  { value: "CULTURAL_MOMENT", label: "Cultural moment" },
  { value: "SURPRISE_ME", label: "Surprise me" },
];

export const PROJECT_TYPES = [
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
    location: input.location || undefined,
    dimensions: input.dimensions || undefined,
    budget: input.budget || undefined,
    k: input.k ?? 3,
  };
  if (input.inspiration && input.inspiration !== "OFF") {
    body.trend = { mode: input.inspiration, influence: 0.55, max_selected: 3 };
  }
  return req<Exploration>("/api/explorations", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function getConcepts(id: string): Promise<{ concepts: Concept[] }> {
  return req(`/api/explorations/${id}/concepts`);
}

export function getExploration(id: string): Promise<{ status?: string } & Record<string, any>> {
  return req(`/api/explorations/${id}`);
}

export function getConcept(id: string): Promise<ConceptDetail> {
  return req(`/api/concepts/${id}`);
}
