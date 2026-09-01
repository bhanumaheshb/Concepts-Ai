"""HTTP transport for hosted chat models.

Everything vendor-specific about the *wire* lives here and nowhere else: the engine,
the domain, the pipeline, the critics and the compiler never learn which API answered.

Two dialects are supported, because hosted inference splits roughly in half:

  * `cloudflare` -- POST /accounts/{id}/ai/run/{model}, Workers AI's native endpoint.
                    The envelope carries its own success flag (see below).
  * `openai`     -- POST /v1/chat/completions with `response_format`, which covers
                    LM Studio, llama.cpp, vLLM, OpenAI, Together and Groq.

Why the native Cloudflare endpoint rather than its OpenAI-compatible one:
**Workers AI answers HTTP 200 with `success: false` for authentication and quota
failures.** Trusting the status code would surface an expired token as an
unparseable-JSON error three layers away from the cause. The native envelope states
the failure explicitly, so this transport reads it and raises something a human can
act on. `tests/test_cloudflare_provider.py` pins that behaviour.

Selecting a different model -- or a different vendor entirely -- is configuration,
not a code change.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable

# (method, url, payload_or_None, headers, timeout) -> decoded JSON body.
# Injectable so the whole adapter can be tested without a socket.
Transport = Callable[[str, str, "dict | None", dict, float], dict]


class LLMTransportError(RuntimeError):
    """The model could not be reached, refused the call, or answered unusably."""


@dataclass
class HttpLLM:
    base_url: str
    model: str
    dialect: str = "cloudflare"          # cloudflare | openai
    account_id: str = ""
    api_key: str = ""
    timeout_s: float = 120.0
    retries: int = 1
    strict_schema: bool = False          # ask the server to CONSTRAIN, not just request
    transport: Transport | None = None
    calls: int = 0
    last_error: str | None = None
    last_status: dict[str, Any] = field(default_factory=dict)
    _resolved_model: str = field(default="", repr=False)

    # ---- availability -------------------------------------------------------
    def is_configured(self) -> bool:
        """Configuration presence only -- deliberately no network call.

        Probing here would make container construction depend on an external service,
        which would in turn make `/api/config` slow and the test suite non-hermetic.
        A wrong key, or a local server that is not running, is not detectable without
        spending a request, so it is reported at call time by `chat_json`, loudly,
        per concept.
        """
        if self.dialect == "cloudflare":
            return bool(self.model and self.account_id and self.api_key)
        # A local server names its own loaded model, so a blank model is resolvable
        # rather than missing.
        return bool(self.base_url)

    def missing_settings(self) -> list[str]:
        """What a human must supply. Drives the message shown by `/api/config`."""
        if self.dialect != "cloudflare":
            return [] if self.base_url else ["LLM_BASE_URL"]
        missing = []
        if not self.account_id:
            missing.append("CF_ACCOUNT_ID")
        if not self.api_key:
            missing.append("CF_API_TOKEN")
        if not self.model:
            missing.append("CF_MODEL")
        return missing

    # ---- model identity ------------------------------------------------------
    @property
    def model_id(self) -> str:
        """The configured model, or whichever one the server turned out to be serving."""
        return self.model or self._resolved_model

    def available_models(self) -> list[str]:
        try:
            out = self._get(f"{self.base_url}/v1/models", timeout=5.0)
            return [m.get("id", "") for m in (out.get("data") or []) if m.get("id")]
        except Exception:                             # noqa: BLE001
            return []

    def _require_model(self) -> str:
        """Resolve the model id lazily so a local server can name it for us.

        LM Studio ids are long and easy to mistype (`google/gemma-4-e4b`), and the
        server already knows which one is loaded. Asking beats making a human match
        a string by hand.

        Embedding models are skipped: LM Studio commonly has one loaded alongside a
        chat model, and it may well be listed first. Sending a concept prompt to an
        embedding endpoint fails in a way that looks like a model problem rather
        than a selection mistake.
        """
        if self.model_id:
            return self.model_id
        loaded = self.available_models()
        chat_capable = [m for m in loaded if not _is_embedding_model(m)]
        if not chat_capable:
            detail = (f" (only embedding models are loaded: {', '.join(loaded)})"
                      if loaded else "")
            raise LLMTransportError(
                f"no chat model is loaded at {self.base_url}{detail} — load one in "
                "the local server, or set LLM_MODEL to its id")
        self._resolved_model = chat_capable[0]
        return self._resolved_model

    # ---- generation ---------------------------------------------------------
    def chat_json(self, *, system: str, user: str, schema: dict[str, Any] | None = None,
                  seed: int = 0, max_tokens: int = 3072) -> tuple[dict, int]:
        """Returns (parsed JSON object, duration_ms). Raises LLMTransportError."""
        if not self.is_configured():
            missing = ", ".join(self.missing_settings()) or "provider settings"
            raise LLMTransportError(
                f"{self.dialect} provider is not configured: set {missing}")
        started = time.time()
        last: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                text = (self._run_cloudflare(system, user, schema, seed, max_tokens)
                        if self.dialect == "cloudflare"
                        else self._run_openai(system, user, schema, seed, max_tokens))
                self.calls += 1
                return parse_json_object(text), int((time.time() - started) * 1000)
            except Exception as exc:                  # noqa: BLE001
                last = exc
                self.last_error = (str(exc) if isinstance(exc, LLMTransportError)
                                   else f"{type(exc).__name__}: {exc}")
                if attempt >= self.retries or not _is_retryable(exc):
                    break
                time.sleep(0.6 * (attempt + 1))
        raise LLMTransportError(f"model call failed: {self.last_error}") from last

    # ---- cloudflare workers ai ----------------------------------------------
    def _run_cloudflare(self, system: str, user: str, schema: dict | None,
                        seed: int, max_tokens: int) -> str:
        payload: dict[str, Any] = {
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            # No sampling-noise parameter is sent, here or anywhere (critical rule 3):
            # divergence is produced by the allocator before this call, so turning it
            # up at the sampler would only blur a concept the engine already chose.
            "max_tokens": max_tokens,
            "seed": seed,
        }
        if schema:
            payload["response_format"] = {"type": "json_schema", "json_schema": schema}
        url = f"{self.base_url}/accounts/{self.account_id}/ai/run/{self.model}"
        return _cloudflare_result(self._post(url, payload))

    # ---- openai-compatible ---------------------------------------------------
    def _run_openai(self, system: str, user: str, schema: dict | None,
                    seed: int, max_tokens: int) -> str:
        schema_block: dict[str, Any] = {"name": "concept", "schema": schema}
        if self.strict_schema:
            # For a small local model this is the difference between a grammar
            # constraint and a polite suggestion.
            schema_block["strict"] = True
        payload: dict[str, Any] = {
            "model": self._require_model(),
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "response_format": ({"type": "json_schema", "json_schema": schema_block}
                                if schema else {"type": "json_object"}),
            # No sampling-noise parameter is sent here either (critical rule 3).
            "max_tokens": max_tokens,
            "seed": seed,
        }
        out = self._post(f"{self.base_url}/v1/chat/completions", payload)
        try:
            choice = out["choices"][0]
            content = choice["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMTransportError(
                f"unexpected chat-completions envelope: {json.dumps(out)[:200]}") from exc
        # Truncation produces well-formed JSON that simply stops. Without this check
        # it surfaces as "model output was not JSON", which sends you looking at the
        # model's competence instead of at max_tokens.
        if choice.get("finish_reason") == "length":
            raise LLMTransportError(
                f"model output was truncated at max_tokens={max_tokens} "
                "(finish_reason=length) — raise LLM_MAX_OUTPUT_TOKENS")
        return content

    # ---- http ---------------------------------------------------------------
    def _headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    def _get(self, url: str, timeout: float) -> dict:
        send = self.transport or _urllib_transport
        return send("GET", url, None, self._headers(), timeout)

    def _post(self, url: str, payload: dict) -> dict:
        send = self.transport or _urllib_transport
        try:
            return send("POST", url, payload, self._headers(), self.timeout_s)
        except LLMTransportError:
            raise
        except urllib.error.URLError as exc:
            # The commonest local failure by far: the server simply isn't up.
            raise LLMTransportError(
                f"could not reach {self.base_url} ({exc.reason}) — is the local "
                "server running?") from exc
        except Exception as exc:                      # noqa: BLE001
            raise LLMTransportError(f"{type(exc).__name__}: {exc}") from exc


# ---- envelopes --------------------------------------------------------------
def _cloudflare_result(out: dict) -> str:
    """Read Workers AI's envelope rather than the HTTP status.

    A 200 with `success: false` is how Workers AI reports an invalid token, a token
    lacking the Workers AI permission, and an exhausted neuron quota. Those must not
    look like a malformed model reply.
    """
    if not isinstance(out, dict):
        raise LLMTransportError(
            f"Workers AI returned {type(out).__name__}, not an object")
    if not out.get("success", False):
        raise LLMTransportError(
            "Workers AI rejected the request: " + _describe_errors(out))
    result = out.get("result")
    if isinstance(result, str):
        return result
    if not isinstance(result, dict):
        raise LLMTransportError(
            f"Workers AI returned no result: {json.dumps(out)[:200]}")
    response = result.get("response")
    if isinstance(response, (dict, list)):
        # JSON mode can hand back an already-decoded object.
        return json.dumps(response)
    if isinstance(response, str) and response.strip():
        return response
    raise LLMTransportError(
        f"Workers AI returned an empty response: {json.dumps(out)[:200]}")


def _describe_errors(out: dict) -> str:
    parts = []
    for err in out.get("errors") or []:
        if isinstance(err, dict):
            code, message = err.get("code", ""), err.get("message", "")
            parts.append(f"[{code}] {message}".strip() if code else str(message))
        elif err:
            parts.append(str(err))
    return "; ".join(p for p in parts if p) or json.dumps(out)[:200]


def _is_embedding_model(model_id: str) -> bool:
    """Name-based, because the OpenAI /v1/models payload does not state capability."""
    lowered = model_id.lower()
    return any(t in lowered for t in ("embed", "rerank"))


def _is_retryable(exc: Exception) -> bool:
    """An expired token will not fix itself; a rate limit or a 5xx might."""
    text = str(exc).lower()
    return not any(t in text for t in (
        "authentication", "unauthorized", "invalid token", "not configured",
        "permission", "10000",
        # Retrying a truncation just spends the same tokens to hit the same wall.
        "truncated", "no chat model is loaded",
    ))


def _urllib_transport(method: str, url: str, payload: dict | None,
                      headers: dict, timeout: float) -> dict:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")[:400]
        # A JSON error body is more useful than the status line; keep both.
        raise LLMTransportError(f"HTTP {exc.code} from {url}: {body}") from exc


def parse_json_object(text: str) -> dict:
    """Models fence their JSON or prepend a sentence. Recover, don't fail."""
    if not text or not text.strip():
        raise LLMTransportError("model returned empty output")
    s = text.strip()
    if s.startswith("```"):
        s = s.split("```", 2)[1] if s.count("```") >= 2 else s.strip("`")
        s = s[4:].lstrip() if s.lower().startswith("json") else s
    try:
        parsed = json.loads(s)
    except json.JSONDecodeError:
        start, end = s.find("{"), s.rfind("}")
        if start < 0 or end <= start:
            raise LLMTransportError(f"model output was not JSON: {text[:180]!r}") from None
        try:
            parsed = json.loads(s[start:end + 1])
        except json.JSONDecodeError:
            raise LLMTransportError(f"model output was not JSON: {text[:180]!r}") from None
    if not isinstance(parsed, dict):
        raise LLMTransportError("model returned JSON that is not an object")
    return parsed
