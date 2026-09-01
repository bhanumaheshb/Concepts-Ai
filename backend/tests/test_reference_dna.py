"""Schema validators fire where the spec says they must."""
import pytest
from pydantic import ValidationError

from app.domain.common import NicheRole
from app.domain.reference import (
    LiteralReading, ReferenceDimension, ReferenceDNA, ReferenceIdentity, ReferenceInfluence,
    ReferenceTrait, ReferenceType, SurfaceLexicon, SurfaceToken, detect_proper_nouns,
)


def _identity():
    return ReferenceIdentity(reference_id="ref_x", kind=ReferenceType.TV_SERIES,
                             display_name="Testshow")


def _traits(n=6, statement="a society performs itself in public and is looked at"):
    return [ReferenceTrait(trait_id=f"t{i}", dimension=ReferenceDimension.ATMOSPHERE,
                           statement=statement, abstraction=0.8, salience=0.8)
            for i in range(n)]


def _dna(**over):
    base = dict(
        dna_id="d1", identity=_identity(), traits=_traits(),
        literal_reading=LiteralReading(label="l", facet_values=["a:b", "c:d"]),
        surface_lexicon=SurfaceLexicon(),
    )
    base.update(over)
    return ReferenceDNA(**base)


def test_valid_dna_constructs():
    assert len(_dna().traits) == 6


def test_display_name_in_a_statement_is_rejected():
    with pytest.raises(ValidationError, match="names the reference"):
        _dna(traits=_traits(statement="the Testshow room is looked at by everyone"))


def test_blocked_token_in_a_statement_is_rejected():
    with pytest.raises(ValidationError, match="blocked token"):
        _dna(traits=_traits(statement="a room whose purpose is collective display"),
             surface_lexicon=SurfaceLexicon(tokens=[
                 SurfaceToken(token="display", category="SET_ELEMENT", transformed_to="x")]))


def test_proper_noun_in_a_statement_is_rejected():
    with pytest.raises(ValidationError, match="proper noun"):
        _dna(traits=_traits(statement="the room is organised as a Versailles gallery"))


def test_fewer_than_six_traits_is_rejected():
    with pytest.raises(ValidationError):
        _dna(traits=_traits(4))


def test_context_dimension_may_not_map_to_a_facet():
    with pytest.raises(ValidationError, match="CONTEXT dimension"):
        ReferenceTrait(trait_id="t", dimension=ReferenceDimension.ERA,
                       statement="craft is made visible at scale", abstraction=0.8,
                       salience=0.8, maps_to=["geometry_system"])


def test_trait_may_not_contain_its_own_surface_token():
    with pytest.raises(ValidationError, match="own surface token"):
        ReferenceTrait(trait_id="t", dimension=ReferenceDimension.ATMOSPHERE,
                       statement="the ballroom is where everyone is seen",
                       abstraction=0.8, salience=0.8, surface_tokens=["ballroom"])


def test_literal_reading_requires_two_facet_values():
    with pytest.raises(ValidationError):
        LiteralReading(label="l", facet_values=["a:b"])


def test_influence_may_never_reach_the_wildcard():
    with pytest.raises(ValidationError, match="R-REF-03"):
        ReferenceInfluence(level=1.0, max_biased_facets=3, max_principles=5,
                           prior_multiplier=4.0, role_coverage=[NicheRole.WILDCARD],
                           literal_quota=2)


def test_influence_may_never_bias_more_than_three_facets():
    with pytest.raises(ValidationError):
        ReferenceInfluence(level=1.0, max_biased_facets=4, max_principles=5,
                           prior_multiplier=4.0, role_coverage=[], literal_quota=2)


def test_proper_noun_detector_ignores_sentence_start_and_common_words():
    assert detect_proper_nouns("The room is a clearing") == []
    assert "Versailles" in detect_proper_nouns("a room like Versailles")
