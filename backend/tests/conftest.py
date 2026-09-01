import os

# The suite must not depend on whichever provider a developer happens to have in
# `.env`. Settings reads the file with `setdefault`, so pinning here first wins —
# and it must happen BEFORE app.composition is imported and the container is built.
# Tests that care about another provider construct Settings(...) directly or use
# monkeypatch; nothing here should ever reach a real model or a local server.
os.environ["LLM_PROVIDER"] = "mock"

import pytest  # noqa: E402

from app.composition import get_container  # noqa: E402
from app.creative.program import build_program
from app.domain.brief import DesignBrief
from app.ontology.graph import load_ontology
from app.space.instantiate import instantiate_with_relaxation


@pytest.fixture(scope="session")
def ont():
    return load_ontology("v1")


@pytest.fixture(scope="session")
def container():
    return get_container()


@pytest.fixture()
def brief():
    return DesignBrief(brief_id="bf_fixture",
                       raw_text="Create a luxury Indian wedding mandap for 500 guests.",
                       location="Jaipur, May")


@pytest.fixture()
def program(ont, brief):
    return build_program(ont, brief)


@pytest.fixture()
def space(ont, program):
    return instantiate_with_relaxation(ont, program)


# ─────────────────────── reference fixtures ───────────────────────

@pytest.fixture(scope="session")
def analyzer(ont):
    from app.providers.reference.curated import CuratedReferenceAnalyzer
    return CuratedReferenceAnalyzer(ont)


@pytest.fixture(scope="session")
def ref_service(ont, analyzer):
    from app.references.service import ReferenceService
    return ReferenceService(ont, analyzer)


@pytest.fixture(scope="session")
def fixtures(ont):
    from app.references.fixtures import all_fixtures
    return all_fixtures(ont)


@pytest.fixture()
def sangeeth_brief():
    return DesignBrief(brief_id="bf_sangeeth",
                       raw_text="Luxury high-energy Sangeeth for 500 guests",
                       location="Jaipur, May")


# ─────────────────────── trend fixtures ───────────────────────

@pytest.fixture(scope="session")
def trend_provider():
    from app.providers.trend.mock import MockTrendProvider
    return MockTrendProvider()


@pytest.fixture()
def trend_service(ont, trend_provider):
    from app.trends.service import TrendService
    return TrendService(ont, trend_provider)      # fresh cache per test


@pytest.fixture(scope="session")
def today():
    from datetime import date
    return date(2026, 8, 24)
