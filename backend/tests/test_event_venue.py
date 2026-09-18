import pytest

from app.creative.program import estimate_capacity
from app.domain.brief import DesignBrief
from app.domain.common import Tradition
from app.semantics.intelligence import DesignIntelligence


EXACT_BRIEF = ('a Telugu south Indian wedding for 3000 ppl guests theme like a '
               'divine temple set in a convention hall hyderabad')


@pytest.mark.parametrize('text,event', [
    (EXACT_BRIEF, 'wedding_ceremony'),
    ('A wedding in a conference room', 'wedding_ceremony'),
    ('A wedding in a convention centre', 'wedding_ceremony'),
    ('A wedding in a CONVENTION-HALL', 'wedding_ceremony'),
    ('A conference hall in Hyderabad hosting our wedding', 'wedding_ceremony'),
    ('A Sangeet for my wedding in a convention hall', 'sangeet'),
    ('A wedding reception in a convention hall', 'wedding_reception'),
    ('A tech conference in a convention hall', 'conference'),
    ('An annual convention for 300 delegates', 'conference'),
])
def test_event_identity_is_not_taken_from_venue(text, event):
    brief = DesignBrief(brief_id='bf_venue', raw_text=text, tradition=Tradition.HINDU)
    semantic = DesignIntelligence().understand(brief, capacity=estimate_capacity(brief))
    assert semantic.profile.identity.event_type == event


def test_exact_wedding_brief_keeps_capacity_and_ceremony():
    brief = DesignBrief(brief_id='bf_exact', raw_text=EXACT_BRIEF, tradition=Tradition.HINDU)
    semantic = DesignIntelligence().understand(brief, capacity=estimate_capacity(brief))
    assert semantic.capacity == 3000
    assert semantic.profile.identity.event_family == 'wedding_celebration'
    assert semantic.profile.identity.tradition == 'hindu'
    assert semantic.space_typology == 'WEDDING_MANDAP'
    assert any(a.key == 'ceremony' for a in semantic.profile.primary_activities)
