"use client";
import { useState } from "react";
import { Box, Camera, Copy, Download, Ruler, Route } from "lucide-react";
import { SetDesign, SetDimensions } from "../lib/api";

/** First entry per key. Sessions saved before the backend fix can hold two areas and
 *  two views with the same key; rendering both breaks React's list identity. */
function uniqueByKey<T extends { key: string }>(items: T[]): T[] {
  const seen = new Set<string>();
  return items.filter((item) => (seen.has(item.key) ? false : (seen.add(item.key), true)));
}

export function SetDesignPanel({ data: raw, onToast }: { data: SetDesign; onToast: (message: string) => void }) {
  const data = { ...raw, views: uniqueByKey(raw.views), areas: uniqueByKey(raw.areas) };
  const [tab, setTab] = useState("views");
  const [viewKey, setViewKey] = useState(data.views[0]?.key);
  const [unit, setUnit] = useState("m");
  const view = data.views.find(v => v.key === viewKey) || data.views[0];
  const size = (value: number | null) => value == null ? "TBD" : `${(value * (unit === "ft" ? 3.28084 : 1)).toFixed(2)} ${unit}`;
  const dimensions = (d: SetDimensions) => `${size(d.width_m)} W / ${size(d.depth_m)} D / ${size(d.height_m)} H`;
  async function copy(text: string) {
    try { await navigator.clipboard.writeText(text); onToast("Copied"); }
    catch { onToast("Clipboard unavailable. The prompt text is selectable."); }
  }
  function download() {
    const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }));
    const a = document.createElement("a"); a.href = url; a.download = `${data.concept_id}-3d-handoff.json`;
    a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  return <div className="set-handoff">
    <div className="handoff-toolbar">
      <div><h3><Box size={22} />3D Concepts</h3><span className="handoff-status">{data.status === "prompt_ready" ? "Prompts ready" : "Awaiting synthesis"} · Unoccupied set · Images not connected</span></div>
      <div className="handoff-tools">
        <button title="Copy all render prompts" aria-label="Copy all render prompts" onClick={() => copy(data.views.map(v => `${v.label}\n${v.positive_prompt}\nNEGATIVE: ${v.negative_prompt}`).join("\n\n"))}><Copy size={18} /></button>
        <button title="Download 3D handoff JSON" aria-label="Download 3D handoff JSON" onClick={download}><Download size={18} /></button>
      </div>
    </div>
    <div className="handoff-tabs" role="group" aria-label="Handoff sections">
      {[{ key: "views", label: "Views", icon: Camera }, { key: "dimensions", label: "Dimensions", icon: Ruler }, { key: "walkthrough", label: "Walkthrough", icon: Route }].map(t => <button key={t.key} aria-pressed={tab === t.key} onClick={() => setTab(t.key)}><t.icon size={17} />{t.label}</button>)}
    </div>
    {tab === "views" && view && <div className="handoff-layout">
      <nav className="view-list" aria-label="Set views">{data.views.map((v, i) => <button key={v.key} aria-current={view.key === v.key ? "true" : undefined} onClick={() => setViewKey(v.key)}><span>{String(i + 1).padStart(2, "0")}</span>{v.label}</button>)}</nav>
      <section className="view-content">
        <div className="handoff-toolbar"><h3>{view.label}</h3><div className="handoff-tools"><button title="Copy this view and negative prompt" aria-label="Copy this view and negative prompt" onClick={() => copy(`${view.positive_prompt}\nNEGATIVE: ${view.negative_prompt}`)}><Copy size={18} /></button></div></div>
        <p className="shot-cam">{view.camera}</p>
        <p className="dimension-readout">{dimensions(view.dimensions)}</p>
        <p className="handoff-status">{view.dimensions.source}</p>
        <h4>Render prompt</h4><pre className="prompt">{view.positive_prompt}</pre>
        <h4>Negative prompt</h4><pre className="prompt">{view.negative_prompt}</pre>
      </section>
    </div>}
    {tab === "dimensions" && <section>
      <div className="handoff-toolbar"><h3>Dimension schedule</h3><div className="handoff-tabs" role="group" aria-label="Dimension units">{["m", "ft"].map(u => <button key={u} aria-pressed={unit === u} onClick={() => setUnit(u)}>{u}</button>)}</div></div>
      <div className="dimension-table"><table><thead><tr><th>Area</th><th>Width</th><th>Depth</th><th>Height</th><th>Source</th></tr></thead><tbody>
        {[{ ...data.dimensions, key: "site", label: "Overall set" }, ...data.areas].map(a => <tr key={a.key}><th>{a.label}</th><td>{size(a.width_m)}</td><td>{size(a.depth_m)}</td><td>{size(a.height_m)}</td><td>{a.source}</td></tr>)}
      </tbody></table></div>
      <h4>Modeling notes</h4><ul className="bullets">{data.modeling_notes.map((n, i) => <li key={`${i}-${n}`}>{n}</li>)}</ul>
      <h4>Required review</h4><ul className="bullets">{data.review_required.map((n, i) => <li key={`${i}-${n}`}>{n}</li>)}</ul>
    </section>}
    {tab === "walkthrough" && <section>
      <div className="handoff-toolbar"><h3>Camera route</h3><div className="handoff-tools"><button title="Copy walkthrough prompt" aria-label="Copy walkthrough prompt" onClick={() => copy(data.walkthrough.prompt)}><Copy size={18} /></button></div></div>
      <ol className="walkthrough-stops">{data.walkthrough.stops.map((s, i) => <li key={`${s.order}-${i}`}><strong>{s.label}</strong><span>{s.duration_seconds}s / camera {s.camera_height_m} m</span></li>)}</ol>
      <pre className="prompt">{data.walkthrough.prompt}</pre>
    </section>}
  </div>;
}
