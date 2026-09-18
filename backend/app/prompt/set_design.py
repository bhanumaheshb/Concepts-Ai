"""A deterministic, people-free 3D handoff derived from one selected concept."""
from __future__ import annotations

import re

from app.core.hashing import sha256_of
from app.creative.program import parse_dimensions

NEGATIVE = ("people, humans, guests, crowds, performers, bride, groom, faces, silhouettes, "
            "human scale figures, mannequins, portraits, characters on screens, "
            "watermarks, logos, poster layout, unreadable text, mismatched geometry, "
            "floating supports, impossible connections")
_PEOPLE = re.compile(r"\b(people|humans?|guests?|crowds?|performers?|bride|groom|visitors?|"
                     r"dancers?|couple|attendees?|figures?|witnesses)\b", re.I)


def _physical(text: str) -> str:
    # Narrative fields can ask an image model to add guests even when a later
    # negative prompt forbids them. Keep only physical-description sentences.
    return " ".join(s.strip() for s in re.split(r"(?<=[.!?;])\s+", text or "")
                    if s.strip() and not _PEOPLE.search(s))


def compile_set_design(ont, rec, dna) -> dict:
    program = rec.program
    if program is None:
        return {}
    concept = rec.structured.get(dna.concept_id)
    scene = rec.scenes.get(dna.concept_id)
    semantic = program.semantic
    identity = semantic.profile.identity if semantic else None
    focal_key = semantic.intent.primary_zone_key if semantic else "main"
    focal_label = semantic.intent.primary_focus if semantic else "Main space"
    nodes = {n.role: n for n in scene.by_type("zone")} if scene else {}
    element = scene.node("element_signature") if scene else None
    width, depth = program.site.width_m, program.site.depth_m
    height = (program.site.height_clear_m or (element.height_m if element else None) or 4.0)
    supplied = parse_dimensions(" ".join(filter(None, [rec.brief.dimensions_text, rec.brief.raw_text])))
    footprint_source = "Brief footprint" if supplied and supplied == (width, depth) else "Proposed footprint"
    dimensions = dict(width_m=width, depth_m=depth, height_m=height,
                      source=f"{footprint_source}; concept height estimate")
    material = _physical('; '.join([concept.materials.primary, concept.materials.material_behaviour,
                         concept.materials.surface_treatment, *concept.materials.secondary,
                         concept.materials.palette_note])) if concept else ont.label(dna.genotype.primary_material().material)
    structure = _physical(concept.structure.structural_system) if concept else ont.label(dna.genotype.structural_logic.value)
    lighting = _physical('; '.join([*concept.lighting.lighting_sources, concept.lighting.colour_temperature,
                         concept.lighting.height_and_distribution, concept.lighting.shadow_behaviour,
                         concept.lighting.interaction_with_materials])) if concept else ont.label(dna.genotype.lighting_philosophy.value)
    language = _physical(concept.architectural_language) if concept else ont.label(dna.genotype.architectural_language.value)
    thesis = _physical(concept.concept_thesis) if concept else _physical(dna.phenotype.design_thesis)
    locked = (f"DESIGN ID: {dna.concept_id}.\nDESIGN: {thesis}\n"
              f"ARCHITECTURAL LANGUAGE: {language}\nGEOMETRY: {ont.label(dna.genotype.geometry.system)}\n"
              f"STRUCTURE: {structure}\nMATERIALS: {material}\nLIGHTING: {lighting}")
    signature = sha256_of(locked)
    areas = []
    for zone in (semantic.programme if semantic else []):
        if zone.priority == "optional" and zone.key not in nodes:
            continue
        n = nodes.get(zone.key)
        areas.append(dict(key=zone.key, label=zone.label, role=zone.role,
                          width_m=n.width_m if n else None, depth_m=n.depth_m if n else None,
                          height_m=(element.height_m if element and zone.key == focal_key else None),
                          x_m=n.x_m if n else None, y_m=n.y_m if n else None,
                          source="Concept layout estimate" if n else "Size to be resolved"))
    if not areas:
        areas = [dict(key=k, label=k.replace('_', ' ').title(), role="space",
                      width_m=n.width_m, depth_m=n.depth_m, height_m=None,
                      x_m=n.x_m, y_m=n.y_m, source="Concept layout estimate") for k, n in nodes.items()]
    # Access and the enclosing set are deliverables even if the programme calls
    # the arrival zone "registration", "orientation", or "foyer".
    if not any(a['role'] == 'arrival' for a in areas):
        areas.insert(0, dict(key="entrance", label="Main entrance", role="arrival", width_m=None,
                             depth_m=None, height_m=None, x_m=None, y_m=None, source="Size to be resolved"))
    if not any(a['role'] == 'circulation' for a in areas):
        areas.append(dict(key="pathway", label="Connecting pathway", role="circulation", width_m=None,
                          depth_m=None, height_m=None, x_m=None, y_m=None, source="Size to be resolved"))
    perimeter = dict(key="side_walls", label="Side walls / perimeter", role="enclosure",
                     width_m=width, depth_m=depth, height_m=height, x_m=0, y_m=0,
                     source="Overall perimeter envelope; concept estimate")
    existing = next((a for a in areas if a['key'] == perimeter['key']), None)
    if existing is None:
        areas.append(perimeter)
    else:
        # The programme already names its side walls: that zone IS the perimeter, so it
        # gains the envelope's dimensions rather than appearing a second time.
        for dim in ("width_m", "depth_m", "height_m", "x_m", "y_m"):
            if existing.get(dim) is None:
                existing[dim] = perimeter[dim]
        if existing.get("source") == "Size to be resolved":
            existing["source"] = perimeter["source"]
    # Area keys become view keys, walkthrough stops and React list keys downstream, so
    # they must be unique. Later duplicates merge into the first instead of repeating.
    unique: dict[str, dict] = {}
    for a in areas:
        kept = unique.setdefault(a['key'], a)
        if kept is not a:
            for dim, value in a.items():
                if kept.get(dim) is None:
                    kept[dim] = value
    areas = list(unique.values())
    views = []

    def add(key, label, kind, camera, scope, dims, instruction):
        size = "; ".join(f"{axis[:-2]} {dims[axis]:g} m" for axis in
                         ('width_m', 'depth_m', 'height_m') if dims.get(axis) is not None)
        positive = (f"DELIVERABLE: {label}. {kind.replace('_', ' ')} of an EMPTY, unoccupied "
                    f"{identity.event_type_label if identity else program.typology.value} set. "
                    "Show only architecture, set dressing, empty furniture and lighting equipment. "
                    "No living people, silhouettes or figures in reflections, screens or artwork.\n"
                    f"{locked}\nSCOPE: {scope}\nDIMENSIONS: {size or 'Unresolved; do not invent dimension labels'}. "
                    f"{dims['source']}. These are concept design values, not surveyed or approved construction sizes.\n"
                    f"CAMERA: {camera}\nVIEW REQUIREMENTS: {instruction}\n"
                    "CONTINUITY: Reuse the same origin, dimensions, modules, materials and fixtures in every view. "
                    "Preserve access routes, reveals, connections and clearances. "
                    "Geometry must be readable at modeling scale. Physically based materials, "
                    "controlled exposure, crisp edges and legible shadows. No poster, montage or crowds.")
        views.append(dict(key=key, label=label, kind=kind, camera=camera, dimensions=dims,
                          positive_prompt=positive, negative_prompt=NEGATIVE,
                          prompt_hash=sha256_of(positive), shared_signature=signature,
                          image_status="not_connected", image_url=None))

    master = f"Entire set; focus on {focal_label}. Include " + ", ".join(a['label'] for a in areas) + "."
    add('hero', 'Overall set render', 'beauty_render', 'Eye level 1.6 m, 28 mm lens, full set in frame', master, dimensions,
        'Finished client presentation, empty set, complete silhouette, no cropped wings or hidden approach.')
    add('axonometric', 'Axonometric model', 'model_view', 'Orthographic isometric, 45 degrees above', master, dimensions,
        'Open roof cutaway; expose circulation, modular assemblies and spatial relationships. No perspective distortion.')
    add('clay', 'Clay model / massing', 'clay_render', 'Same framing as the overall set render', master, dimensions,
        'Neutral grey clay material override, diffuse studio light, ambient occlusion, no textures. Preserve all geometry.')
    for key, label, camera in [
        ('plan', 'Dimensioned top plan', 'True orthographic top-down; no perspective'),
        ('front', 'Front elevation', 'True orthographic front elevation'),
        ('left', 'Left elevation', 'True orthographic left elevation'),
        ('right', 'Right elevation', 'True orthographic right elevation')]:
        add(key, label, 'dimensioned_drawing', camera, master, dimensions,
            'White technical background, clean linework, zone outlines and dimension leaders. '
            'Use only the supplied values; unknown sizes marked TBD. Dimension annotations are a drafting layer, '
            'never baked into beauty renders. Verify image-generated text against the dimension schedule.')
    add('assembly', 'Assembly / exploded model', 'assembly_view', 'Orthographic isometric', master, dimensions,
        'Separate primary frame, decorative skin, decking and lighting layers vertically without changing their positions. '
        'Show conceptual joints and module boundaries; connection sizes and rigging loads remain for engineering.')
    role_cameras = {'arrival': 'Exterior three-quarter view at 1.6 m, 28 mm lens, looking through the entry',
                    'circulation': 'Axial eye-level view at 1.6 m, 35 mm lens, route fully visible',
                    'enclosure': 'Oblique view along the side wall, 35 mm lens, grazing light',
                    'ceremony': 'Centered front view at 1.6 m, 35 mm lens, complete focal set',
                    'performance': 'Centered frontal stage view, 35 mm lens, complete wings and apron'}
    for area in areas:
        add('area_' + area['key'], area['label'], 'area_render',
            role_cameras.get(area['role'], 'Raised three-quarter view at 2.2 m, 28 mm lens'),
            f"{area['label']} within the same set. Spatial role: {area['role']}. "
            f"Origin x={area.get('x_m')} m, y={area.get('y_m')} m where resolved.", area,
            'Show the full local assembly, floor transitions, fixture positions, empty furniture and junction with adjacent areas. '
            'Use fixed furniture and a separate dimension schedule for scale, never human figures.')
    route = sorted([a for a in areas if a['role'] != 'service'],
                   key=lambda a: {'arrival': 0, 'circulation': 1, 'enclosure': 2}.get(a['role'], 3))
    stops = [dict(order=i+1, area_key=a['key'], label=a['label'], camera_height_m=1.6,
                  duration_seconds=5, x_m=a.get('x_m'), y_m=a.get('y_m')) for i, a in enumerate(route)]
    checks = ['Site dimensions and ceiling / rigging limits require confirmation.',
              'Zone dimensions are concept estimates; confirm capacity, exits and accessible routes.',
              'Connection design, spans, fire performance and loads require engineering review.']
    if scene and scene.status != 'COMPLETE':
        checks.append('Source layout is incomplete; resolve its missing geometry before modeling.')
    if any((a.get('x_m') or 0)+(a.get('width_m') or 0) > width+0.1 or
           (a.get('y_m') or 0)+(a.get('depth_m') or 0) > depth+0.1 for a in areas):
        checks.append('Some proposed zones exceed the site envelope; layout coordination is required.')
    return dict(version='1.0', concept_id=dna.concept_id, title=concept.concept_title if concept else dna.phenotype.title,
                status='prompt_ready' if concept else 'awaiting_synthesis', output='3D_CONCEPT_HANDOFF',
                image_generation='not_connected', people=False, units='m', dimensions=dimensions,
                shared_signature=signature, design_lock=locked, areas=areas, views=views,
                walkthrough=dict(stops=stops, prompt='Continuous unoccupied-set architectural walkthrough. '
                                 'Camera at 1.6 m, 28 mm lens, smooth dolly, no cuts or geometry morphing. '
                                 'Follow: ' + ' -> '.join(a['label'] for a in route) + '.\n' + locked),
                modeling_notes=['Model at 1:1 in metres. Origin is the front-left site corner; +X across, +Y inward, +Z up.',
                                'Separate frame, skin, floor, furniture, landscape and luminaires into named collections.',
                                'Keep finish thickness, repeated modules and fixture locations consistent across cameras.'],
                review_required=checks)
