import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

from app.creative.pipeline import Pipeline
from app.creative.synthesis import CreativeSynthesizer
from app.domain.brief import DesignBrief
from app.persistence.repository import InMemoryStore
from app.providers.llm import cloudflare
from app.providers.llm.mock_synthesis import MockCreativeProvider


def test_five_workers_publish_before_slowest_finishes(container):
    provider = MockCreativeProvider(container.ontology)
    synth = CreativeSynthesizer(container.ontology, provider, max_repairs=0, max_workers=5)
    original = synth.synthesize
    release = threading.Event()
    lock = threading.Lock()
    active = peak = calls = 0

    def delayed(**kwargs):
        nonlocal active, peak, calls
        with lock:
            calls += 1
            position = calls
            active += 1
            peak = max(peak, active)
        try:
            if position != 1:
                assert release.wait(10), 'Test did not release waiting writers'
            return original(**kwargs)
        finally:
            with lock:
                active -= 1

    synth.synthesize = delayed
    store = InMemoryStore()
    pipeline = Pipeline(container.ontology, container.llm, store,
                        use_llm_critics=False, synthesizer=synth)
    brief = DesignBrief(brief_id='bf_parallel', raw_text='Create a luxury Indian wedding mandap for 500 guests.')
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(pipeline.run, brief, 10, 42)
        try:
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                records = [store.get(key) for key in store.list_ids()]
                if records and records[0].synthesis_traces and peak == 5:
                    break
                if future.done():
                    raise AssertionError(f'Run finished prematurely: {future.result().error}')
                time.sleep(0.02)
            rec = records[0]
            assert peak == 5
            assert len(rec.synthesis_traces) == 1
            assert len(rec.structured) == 1
            assert rec.status == 'RUNNING'
            assert not future.done()
        finally:
            release.set()
        rec = future.result(timeout=10)
    assert rec.status == 'COMPLETE', rec.error
    assert len(rec.structured) == len(rec.concepts) == calls == 10
    assert rec.synthesis_calls == 10
    assert [c.niche_index for c in rec.concepts] == sorted(c.niche_index for c in rec.concepts)


def test_http_traces_are_isolated_between_workers(monkeypatch):
    import app.providers.llm.synthesis_provider as module
    barrier = threading.Barrier(5)
    monkeypatch.setattr(module, 'build_user_prompt', lambda **kw: kw['brief'].raw_text)

    def transport(method, url, payload, headers, timeout):
        barrier.wait(timeout=5)
        return {'success': True, 'result': {'response': {
            'concept_title': payload['messages'][1]['content']}}}

    provider = cloudflare.build_provider(account_id='test', api_token='test',
                                         transport=transport, max_output_tokens=4096)

    def write(i):
        marker = f'concept-{i}'
        result = provider.synthesize_concept(
            concept_dna=SimpleNamespace(genotype=None),
            brief=SimpleNamespace(raw_text=marker), program=None, constraints=None)
        return marker, result.concept_title, provider.last_raw['concept_title'], provider.last_prompt

    with ThreadPoolExecutor(max_workers=5) as executor:
        results = list(executor.map(write, range(5)))
    assert all(len(set(row)) == 1 for row in results)
    assert provider.calls == 5


def test_cloudflare_zero_seed_is_normalized_without_retry():
    seen = []

    def transport(method, url, payload, headers, timeout):
        seen.append(payload['seed'])
        return {'success': True, 'result': {'response': {'ok': True}}}

    client = cloudflare.build_client(account_id='test', api_token='test', transport=transport)
    assert client.chat_json(system='s', user='u', seed=0)[0]['ok']
    assert seen == [1]
    assert client.retries == 0
