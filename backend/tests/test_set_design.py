import pytest

from app.api.serializers import concept_detail
from app.creative.synthesis import CreativeSynthesizer
from app.domain.brief import DesignBrief
from app.prompt.design_lock import physical
from app.prompt.set_design import compile_set_design
from app.providers.llm.mock_synthesis import MockCreativeProvider


@pytest.fixture(params=[
    'A Telugu Hindu wedding for 3000 guests in a convention hall in Hyderabad, with a divine temple set.',
    'A technology conference for 300 people with presentation stage and networking lounge.',
    'An automobile exhibition for 500 visitors with product displays and demo areas.',
])
def handoff(request, container):
    brief = DesignBrief(brief_id='bf_set_test', raw_text=request.param,
                        dimensions_text='60 x 40 m', output_mode='SET_3D')
    rec = container.pipeline.run(brief, k=3, seed=42)
    dna = rec.concepts[0]
    result = CreativeSynthesizer(container.ontology, MockCreativeProvider(container.ontology)).synthesize(
        dna=dna, brief=brief, program=rec.program, seed=42)
    rec.structured[dna.concept_id] = result.concept
    return request.param, container.ontology, rec, dna, compile_set_design(container.ontology, rec, dna)


def test_views_are_coordinated_and_people_free(handoff):
    _, _, _, _, data = handoff
    assert data['people'] is False
    assert data['image_generation'] == 'not_connected'
    assert {'hero', 'plan', 'front', 'left', 'right', 'clay', 'assembly', 'axonometric'} <= {v['key'] for v in data['views']}
    assert len({v['prompt_hash'] for v in data['views']}) == len(data['views'])
    for view in data['views']:
        assert view['shared_signature'] == data['shared_signature']
        assert data['design_lock'] in view['positive_prompt']
        assert 'EMPTY, unoccupied' in view['positive_prompt']
        assert 'people' in view['negative_prompt']
        assert view['image_url'] is None


def test_area_programme_and_dimensions(handoff):
    brief, _, _, _, data = handoff
    labels = ' '.join(a['label'] for a in data['areas']).lower()
    assert 'side walls' in labels
    if 'wedding' in brief:
        assert 'mandap' in labels
        assert 'presentation stage' not in labels
    else:
        assert 'mandap' not in labels
    assert data['dimensions']['width_m'] == 60
    assert data['dimensions']['depth_m'] == 40
    assert 'Brief footprint' in data['dimensions']['source']
    assert 'estimate' in data['dimensions']['source']
    assert data['review_required']
    assert data['walkthrough']['stops']


def test_serialized_mode_and_normal_mode(handoff):
    _, ont, rec, dna, _ = handoff
    detail = concept_detail(ont, rec, dna)
    assert detail['output_mode'] == 'SET_3D'
    assert detail['set_design']['status'] == 'prompt_ready'
    # a CONCEPT run gets the same handoff: both tabs are views of one design
    rec.brief = rec.brief.model_copy(update={'output_mode': 'CONCEPT'})
    normal = concept_detail(ont, rec, dna)
    assert normal['output_mode'] == 'CONCEPT'
    assert normal['set_design']['shared_signature'] == detail['set_design']['shared_signature']


def test_narrative_does_not_reintroduce_people():
    assert physical('Guests gather near the columns. Carved panels carry grazing light.') == 'Carved panels carry grazing light'


def test_every_key_is_unique(handoff):
    """Area, view and walkthrough keys become React list keys. A programme that already
    names its side walls once produced two 'side_walls' areas and two views."""
    _, _, _, _, data = handoff
    for field in ("areas", "views"):
        keys = [x["key"] for x in data[field]]
        assert len(keys) == len(set(keys)), f"duplicate {field} keys: {keys}"


def test_a_programme_side_walls_zone_absorbs_the_perimeter(container):
    """The Telugu wedding brief asks for side walls explicitly, so the programme has a
    side_walls zone; the perimeter envelope must merge into it, not repeat it."""
    brief = DesignBrief(brief_id='bf_walls', raw_text=(
        'A Telugu Hindu wedding set for 3000 guests in Hyderabad with a temple-inspired '
        'entrance, long pathway, side walls, ceremony mandap, and empty seating area.'),
        dimensions_text='60 x 40 m', output_mode='SET_3D')
    rec = container.pipeline.run(brief, k=3, seed=42)
    data = compile_set_design(container.ontology, rec, rec.concepts[0])
    walls = [a for a in data["areas"] if a["key"] == "side_walls"]
    assert len(walls) == 1
    assert walls[0]["width_m"] is not None and walls[0]["height_m"] is not None
