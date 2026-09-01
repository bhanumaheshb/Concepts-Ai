"""The compiled ontology: an in-memory typed graph.

At ~200 nodes a graph database would be the wrong tool. The YAML is the source of
truth, this object is the runtime, and its checksum is the `ontology_version`
carried on every artefact.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Iterable

import yaml

DATA_ROOT = Path(__file__).parent / "data"


@dataclass(frozen=True)
class Facet:
    id: str
    type: str          # TREE | ORDERED | WEIGHTED_SET | ORDERED_SEQ | SET
    weight: float
    active: bool
    cardinality: str


@dataclass(frozen=True)
class Node:
    id: str
    label: str
    facet: str
    parent: str | None = None
    abstract: bool = False
    desc: str = ""
    phrase: str = ""
    neg: tuple[str, ...] = ()
    cost: int = 3
    span: float | None = None
    climate_bad: tuple[str, ...] = ()
    typ_low: tuple[str, ...] = ()
    sensitivity: str = "none"
    min_abstraction: float = 0.0
    primitive: str | None = None

    @property
    def value(self) -> str:
        return self.id.split(":", 1)[1]


@dataclass(frozen=True)
class Edge:
    src: str
    dst: str
    type: str
    weight: float = 1.0


@dataclass
class PrincipleProvenance:
    """Where a principle came from. ONTOLOGY is the default so YAML-authored
    principles keep their existing behaviour without being touched."""
    source: str = "ONTOLOGY"              # ONTOLOGY | REFERENCE | SYNTHESIS | USER
    reference_ids: tuple[str, ...] = ()
    derived_from_traits: tuple[str, ...] = ()
    abstraction: float = 1.0
    dimension: str | None = None          # the reference dimension it came from (R-REF-20)


@dataclass
class Principle:
    id: str
    source_domain: str
    domain_class: str
    statements: list[str]
    mappable_to: list[str]
    biases: dict[str, list[str]]
    forbidden_surface_tokens: list[str]
    cost_band_shift: int = 0
    provenance: PrincipleProvenance = field(default_factory=PrincipleProvenance)
    role_eligibility: tuple[str, ...] | None = None
    requires_reconciliation: bool = False
    salience: float = 1.0


@dataclass
class ClicheSeed:
    label: str
    prevalence: float
    facet_values: list[str]
    surface_tokens: list[str]


class OntologyError(RuntimeError):
    pass


class Ontology:
    def __init__(self, version: str) -> None:
        self.version_label = version
        root = DATA_ROOT / version
        if not root.exists():
            raise OntologyError(f"ontology version {version} not found at {root}")
        self._root = root
        raw_facets = _read(root / "facets.yaml")
        raw_nodes = _read(root / "nodes.yaml")
        raw_edges = _read(root / "edges.yaml")
        self._rules_raw = _read(root / "rules.yaml")
        raw_principles = _read(root / "principles.yaml")
        raw_cliches = _read(root / "cliches.yaml")
        self.typology_defaults: dict = _read(root / "typology_defaults.yaml")["typologies"]

        self.facets: dict[str, Facet] = {
            f["id"]: Facet(f["id"], f["type"], float(f["weight"]), bool(f["active"]), f["cardinality"])
            for f in raw_facets["facets"]
        }
        self.orders: dict[str, list[str]] = raw_facets.get("orders", {})

        self.nodes: dict[str, Node] = {}
        for n in raw_nodes["nodes"]:
            nid = n["id"]
            self.nodes[nid] = Node(
                id=nid, label=n.get("label", nid), facet=nid.split(":", 1)[0],
                parent=n.get("parent"), abstract=bool(n.get("abstract", False)),
                desc=n.get("desc", ""), phrase=n.get("phrase", ""),
                neg=tuple(n.get("neg", [])), cost=int(n.get("cost", 3)),
                span=(float(n["span"]) if n.get("span") is not None else None),
                climate_bad=tuple(n.get("climate_bad", [])), typ_low=tuple(n.get("typ_low", [])),
                sensitivity=n.get("sensitivity", "none"),
                min_abstraction=float(n.get("min_abstraction", 0.0)),
                primitive=n.get("primitive"),
            )

        self.edges: list[Edge] = [
            Edge(e["src"], e["dst"], e["type"], float(e.get("weight", 1.0))) for e in raw_edges["edges"]
        ]
        self._out: dict[tuple[str, str], list[Edge]] = {}
        self._sym: dict[tuple[str, str], list[str]] = {}
        for e in self.edges:
            self._out.setdefault((e.src, e.type), []).append(e)
            if e.type in ("inverse_of", "tensions_with", "excludes"):
                self._sym.setdefault((e.src, e.type), []).append(e.dst)
                self._sym.setdefault((e.dst, e.type), []).append(e.src)

        self.domain_distance: dict[str, dict[str, float]] = raw_principles.get("domain_distance", {})
        self.principles: dict[str, Principle] = {
            p["id"]: Principle(
                id=p["id"], source_domain=p["source_domain"], domain_class=p["domain_class"],
                statements=list(p["statements"]), mappable_to=list(p["mappable_to"]),
                biases={k: list(v) for k, v in p.get("biases", {}).items()},
                forbidden_surface_tokens=list(p.get("forbidden_surface_tokens", [])),
                cost_band_shift=int(p.get("cost_band_shift", 0)),
            )
            for p in raw_principles["principles"]
        }
        self.cliches: dict[str, list[ClicheSeed]] = {
            typ: [
                ClicheSeed(c["label"], float(c["prevalence"]), list(c["facet_values"]),
                           list(c.get("surface_tokens", [])))
                for c in seeds
            ]
            for typ, seeds in raw_cliches["typologies"].items()
        }

        self._depth_cache: dict[str, int] = {}
        self._validate()
        self.version = f"{version}+sha256:{self.checksum()[:12]}"

    # ---------- compile-time validation (spec R-ONT-02) ----------
    def _validate(self) -> None:
        for n in self.nodes.values():
            if n.parent and n.parent not in self.nodes:
                raise OntologyError(f"{n.id}: unknown parent {n.parent}")
            if n.facet not in self.facets and n.facet != "technology":
                raise OntologyError(f"{n.id}: unknown facet {n.facet}")
            # cycle check
            seen, cur = {n.id}, n.parent
            while cur:
                if cur in seen:
                    raise OntologyError(f"cycle in is_a at {n.id}")
                seen.add(cur)
                cur = self.nodes[cur].parent
        for e in self.edges:
            if e.src not in self.nodes:
                raise OntologyError(f"edge src not found: {e.src}")
            if e.dst not in self.nodes and not e.dst.startswith("technology:"):
                raise OntologyError(f"edge dst not found: {e.dst}")
        for fid, f in self.facets.items():
            if not f.active:
                continue
            vals = self.values(fid)
            if len(vals) < 5:
                raise OntologyError(f"active facet {fid} has only {len(vals)} values (min 5)")
            for v in vals:
                if not self.nodes[v].phrase:
                    raise OntologyError(f"active-facet leaf {v} has no prompt_phrase")
        # every geometry value must map to a scene primitive (spec R-SCENE-02)
        for v in self.values("geometry_system"):
            if not self.nodes[v].primitive:
                raise OntologyError(f"geometry_system value {v} has no scene primitive mapping")

    def checksum(self) -> str:
        h = hashlib.sha256()
        for p in sorted(self._root.glob("*.yaml")):
            h.update(p.read_bytes())
        return h.hexdigest()

    # ---------- accessors ----------
    def values(self, facet: str) -> list[str]:
        """Concrete (sampleable) node ids for a facet, in stable order."""
        return sorted(n.id for n in self.nodes.values() if n.facet == facet and not n.abstract)

    def node(self, ref: str) -> Node:
        try:
            return self.nodes[ref]
        except KeyError as exc:
            raise OntologyError(f"unknown ontology ref: {ref}") from exc

    def label(self, ref: str) -> str:
        return self.nodes[ref].label if ref in self.nodes else ref

    def phrase(self, ref: str) -> str:
        n = self.nodes.get(ref)
        if n is None:
            return ref.split(":", 1)[-1].replace("_", " ")
        return n.phrase or n.label.lower()

    def depth(self, ref: str) -> int:
        """Depth with the *facet* as a virtual root at depth 0.

        A top-level group sits at 1 and a leaf at 2, so two leaves sharing a group
        are correctly nearer than two leaves that share only the facet.
        """
        if ref in self._depth_cache:
            return self._depth_cache[ref]
        d, cur = 1, self.nodes.get(ref)
        while cur is not None and cur.parent:
            d += 1
            cur = self.nodes.get(cur.parent)
        self._depth_cache[ref] = d
        return d

    def ancestors(self, ref: str) -> list[str]:
        out, cur = [ref], self.nodes.get(ref)
        while cur is not None and cur.parent:
            out.append(cur.parent)
            cur = self.nodes.get(cur.parent)
        return out

    def lca_depth(self, a: str, b: str) -> int:
        """Depth of the lowest common ancestor.

        Returns 0 (the virtual facet root) when two values share no real ancestor,
        which yields Wu-Palmer similarity 0 and therefore distance 1.0.
        """
        if a == b:
            return self.depth(a)
        anc_b = set(self.ancestors(b))
        for node in self.ancestors(a):
            if node in anc_b:
                return self.depth(node)
        return 0

    def targets(self, ref: str, edge_type: str) -> list[str]:
        return [e.dst for e in self._out.get((ref, edge_type), [])]

    def symmetric(self, ref: str, edge_type: str) -> list[str]:
        return list(dict.fromkeys(self._sym.get((ref, edge_type), [])))

    def inverse_of(self, ref: str) -> list[str]:
        return self.symmetric(ref, "inverse_of")

    def excludes(self, ref: str) -> set[str]:
        return set(self.symmetric(ref, "excludes"))

    def tensions(self, ref: str) -> list[tuple[str, float]]:
        out = []
        for e in self.edges:
            if e.type != "tensions_with":
                continue
            if e.src == ref:
                out.append((e.dst, e.weight))
            elif e.dst == ref:
                out.append((e.src, e.weight))
        return out

    def requires(self, ref: str) -> list[str]:
        return self.targets(ref, "requires")

    def implies(self, ref: str) -> list[tuple[str, float]]:
        return [(e.dst, e.weight) for e in self._out.get((ref, "implies"), [])]

    def rank(self, facet: str, ref: str) -> int:
        order = self.orders.get(facet, [])
        v = ref.split(":", 1)[-1]
        return order.index(v) if v in order else 0

    def order_len(self, facet: str) -> int:
        return max(2, len(self.orders.get(facet, [])))

    def active_facets(self) -> list[str]:
        return [f.id for f in self.facets.values() if f.active]

    def weight(self, facet: str) -> float:
        f = self.facets.get(facet)
        return f.weight if f else 0.0

    def rules(self) -> list[dict]:
        return self._rules_raw["rules"]

    def relaxation_order(self) -> list[str]:
        return self._rules_raw.get("relaxation_order", [])

    def principle_domain_distance(self, a_class: str, b_class: str) -> float:
        return self.domain_distance.get(a_class, {}).get(b_class, 0.5)

    def stats(self) -> dict[str, int]:
        return {
            "nodes": len(self.nodes),
            "sampleable": sum(1 for n in self.nodes.values() if not n.abstract),
            "edges": len(self.edges),
            "facets": len(self.facets),
            "active_facets": len(self.active_facets()),
            "principles": len(self.principles),
        }


def _read(path: Path) -> dict:
    if not path.exists():
        raise OntologyError(f"missing ontology file: {path}")
    return yaml.safe_load(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=4)
def load_ontology(version: str = "v1") -> Ontology:
    return Ontology(version)
