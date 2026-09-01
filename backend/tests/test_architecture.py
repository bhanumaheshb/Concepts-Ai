"""The one structural prohibition in the spec, enforced as a test.

The creative engine must never reach a concrete image provider — that is what makes
the whole system runnable, testable and shippable with no image API in existence.
"""
import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1] / "app"
ENGINE_PACKAGES = [
    "domain", "ontology", "diversity", "space", "niche", "genotype",
    "critics", "repair", "mutation", "scene", "prompt", "creative",
    "references",          # R-REF-18: inherits the isolation contract, is not exempt
]
FORBIDDEN_PREFIXES = ("app.providers.image", "app.providers.llm", "app.providers.embeddings")


def _imports(path: pathlib.Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            out.append(node.module)
    return out


def test_engine_never_imports_a_concrete_provider():
    offenders = []
    for pkg in ENGINE_PACKAGES:
        for path in (ROOT / pkg).rglob("*.py"):
            for mod in _imports(path):
                if mod.startswith(FORBIDDEN_PREFIXES):
                    offenders.append(f"{path.relative_to(ROOT)} imports {mod}")
    assert not offenders, "engine reached a concrete provider:\n" + "\n".join(offenders)


def test_domain_imports_nothing_from_the_application_except_core():
    offenders = []
    for path in (ROOT / "domain").rglob("*.py"):
        for mod in _imports(path):
            if mod.startswith("app.") and not mod.startswith(("app.domain", "app.core")):
                offenders.append(f"{path.relative_to(ROOT)} imports {mod}")
    assert not offenders, "domain layer is not at the bottom:\n" + "\n".join(offenders)


def test_only_composition_constructs_providers():
    allowed = {"composition.py"}
    offenders = []
    for path in ROOT.rglob("*.py"):
        if path.name in allowed or "providers" in path.parts or "tests" in path.parts:
            continue
        for mod in _imports(path):
            if mod.startswith("app.providers.") and not mod.endswith("protocols"):
                offenders.append(f"{path.relative_to(ROOT)} imports {mod}")
    assert not offenders, "provider constructed outside composition.py:\n" + "\n".join(offenders)


def test_app_works_with_the_image_router_removed():
    """R-API-01: deleting the image router leaves every engine endpoint green."""
    from fastapi.testclient import TestClient
    from app.main import create_app
    client = TestClient(create_app(include_images=False))
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/config").status_code == 200
    assert client.post("/api/images/generate", json={"prompt_id": "x"}).status_code == 404


def test_no_sampling_noise_parameter_is_ever_passed():
    """Creativity must not depend on sampling noise (critical rule 3).

    Looks for real usage — a keyword argument, an assignment, or a dict key — rather
    than any mention, so the protocol docstring that explains their absence is fine.
    """
    offenders = []
    for pkg in ENGINE_PACKAGES + ["providers"]:
        for path in (ROOT / pkg).rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                bad = None
                if isinstance(node, ast.keyword) and node.arg in ("temperature", "top_p", "top_k"):
                    bad = node.arg
                elif isinstance(node, ast.Constant) and node.value in ("temperature", "top_p", "top_k"):
                    bad = node.value
                elif isinstance(node, ast.arg) and node.arg in ("temperature", "top_p", "top_k"):
                    bad = node.arg
                if bad:
                    offenders.append(f"{path.relative_to(ROOT)} uses {bad}")
    assert not offenders, "sampling-noise parameter in use:\n" + "\n".join(offenders)
