"""Image adapter routes — a SEPARATELY MOUNTED router.

Removing this module entirely must leave the application fully functional
(spec R-API-01), which `tests/test_architecture.py` asserts.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.composition import get_container
from app.core.ids import new_id
from app.domain.images import ImageGenerationRequest

router = APIRouter(prefix="/api/images", tags=["images"])


class GenerateRequest(BaseModel):
    prompt_id: str


@router.get("/providers")
def providers() -> dict:
    c = get_container()
    caps = c.images.capabilities()
    return {"providers": [{"name": c.images.name, "configured": c.images.is_configured(),
                           "capabilities": caps.model_dump(mode="json")}]}


@router.post("/providers/test")
def test_provider() -> dict:
    c = get_container()
    if not c.images.is_configured():
        return {"status": "not_configured",
                "message": "No image provider configured. The engine does not require one."}
    return {"status": "ok", "provider": c.images.name}


@router.post("/generate")
def generate(req: GenerateRequest) -> dict:
    """Accepts only a prompt_id and resolves the prompt server-side, so every image
    is traceable to a compiled prompt, an ontology version and a concept."""
    c = get_container()
    store = c.store
    for eid in store.list_ids():
        rec = store.get(eid)
        for cid, pc in rec.prompts.items():
            if pc.prompt_id == req.prompt_id:
                result = c.images.generate(ImageGenerationRequest(
                    request_id=new_id("ir"), prompt_id=pc.prompt_id,
                    positive_prompt=pc.positive_prompt, negative_prompt=pc.negative_prompt,
                    aspect_ratio=pc.aspect_ratio, seed=pc.seed,
                ))
                return result.model_dump(mode="json")
    raise HTTPException(404, f"prompt {req.prompt_id} not found")
