"""Local LLM adapter — optional natural-language fluency upgrade.

Activates ONLY when both of these are true:
  • `llama_cpp_python` package is installed
  • `LOCAL_LLM_MODEL_PATH` env var points to a valid GGUF model file

Otherwise this module is a complete no-op: callers get None back from
`generate()` and fall back to the template-based explainer.

Why optional, not required:
  • A 7B-param model in Q4 quantization is ~4-5GB on disk and ~5-6GB in RAM.
    Forcing that footprint onto every deployment is too heavy.
  • CPU inference is slow (~5-15 tok/sec on a typical EC2 t3-class
    instance). Not all users will tolerate it.
  • The template explainer produces 95% of the value with 0% of the cost.

Recommended model:
  • Phi-3-mini-4k-instruct-q4.gguf (~2.3GB, ~3 tok/sec on t3.small)
    → https://huggingface.co/microsoft/Phi-3-mini-4k-instruct-gguf
  • Or for more fluency: Llama-3-8B-Instruct.Q4_K_M.gguf (~5GB)
    → https://huggingface.co/QuantFactory/Meta-Llama-3-8B-Instruct-GGUF

How to enable:
  1. pip install llama-cpp-python                # adds the inference engine
  2. Download a quantized GGUF model file        # one-time
  3. Set in backend/.env:
       LOCAL_LLM_MODEL_PATH=/abs/path/to/phi-3-mini-4k-instruct-q4.gguf
       LOCAL_LLM_MAX_TOKENS=200                  # output cap
       LOCAL_LLM_CONTEXT=4096                    # context window
  4. Restart the backend. On startup the module logs whether it loaded.

API contract:
  • `is_available()` → True if model is loaded and ready
  • `generate(prompt, max_tokens)` → str | None (None on any failure)
  • `enhance_explanation(struct_data, lang)` → optional LLM-fluent version
    of the signal explanation; falls back to None when unavailable so
    callers can use the template version.

Concurrency:
  llama-cpp-python single Llama instance is NOT thread-safe for
  simultaneous generate() calls. We wrap inference in a process-wide
  lock. For higher throughput, run multiple uvicorn workers (each gets
  its own model instance).
"""
from __future__ import annotations

import os
import threading
from typing import Optional

from loguru import logger


# ----- Config -----
_MODEL_PATH    = os.getenv("LOCAL_LLM_MODEL_PATH", "").strip()
_MAX_TOKENS    = int(os.getenv("LOCAL_LLM_MAX_TOKENS", "200"))
_CONTEXT       = int(os.getenv("LOCAL_LLM_CONTEXT", "4096"))
_N_THREADS     = int(os.getenv("LOCAL_LLM_N_THREADS", "0"))   # 0 = auto-detect
_TEMPERATURE   = float(os.getenv("LOCAL_LLM_TEMPERATURE", "0.4"))

# ----- Module-level state -----
_llm = None
_load_lock = threading.Lock()
_inference_lock = threading.Lock()
_load_attempted = False
_load_error: Optional[str] = None


def _try_load() -> None:
    """One-time lazy load. Idempotent and safe to call repeatedly —
    after the first attempt, sets _load_attempted=True so subsequent calls
    skip the import even when LLM is unavailable."""
    global _llm, _load_attempted, _load_error

    if _load_attempted:
        return
    with _load_lock:
        if _load_attempted:
            return
        _load_attempted = True

        if not _MODEL_PATH:
            _load_error = "LOCAL_LLM_MODEL_PATH not set"
            return
        if not os.path.isfile(_MODEL_PATH):
            _load_error = f"GGUF file not found at {_MODEL_PATH}"
            logger.warning("Local LLM: {}", _load_error)
            return

        try:
            from llama_cpp import Llama   # type: ignore
        except ImportError:
            _load_error = ("llama-cpp-python not installed — "
                            "`pip install llama-cpp-python` to enable local LLM")
            logger.warning(_load_error)
            return

        try:
            kwargs = {
                "model_path": _MODEL_PATH,
                "n_ctx":      _CONTEXT,
                "verbose":    False,
            }
            if _N_THREADS > 0:
                kwargs["n_threads"] = _N_THREADS
            _llm = Llama(**kwargs)
            logger.success("Local LLM loaded: {} (ctx={}, max_tokens={})",
                             os.path.basename(_MODEL_PATH), _CONTEXT, _MAX_TOKENS)
        except Exception as e:
            _load_error = f"Llama init failed: {e}"
            logger.warning("Local LLM load failed: {}", e)


def is_available() -> bool:
    """True iff the model is loaded and ready to serve completions."""
    _try_load()
    return _llm is not None


def get_status() -> dict:
    """Diagnostic info for the /api/health endpoint."""
    _try_load()
    return {
        "available":    _llm is not None,
        "model_path":   _MODEL_PATH or None,
        "context":      _CONTEXT,
        "max_tokens":   _MAX_TOKENS,
        "load_error":   _load_error,
    }


def generate(prompt: str, max_tokens: Optional[int] = None,
              temperature: Optional[float] = None,
              stop: Optional[list[str]] = None) -> Optional[str]:
    """Run inference. Returns the model's text completion, or None on any
    failure (model unavailable, inference exception, empty output).

    `prompt` should be pre-formatted with the model's instruction template.
    For Phi-3 / Llama-3 use chat-style markup; for base Llama, plain prompt.
    """
    if not is_available():
        return None
    with _inference_lock:
        try:
            result = _llm(
                prompt,
                max_tokens=max_tokens or _MAX_TOKENS,
                temperature=temperature if temperature is not None else _TEMPERATURE,
                stop=stop or ["</s>", "<|end|>", "<|eot_id|>"],
            )
            text = result.get("choices", [{}])[0].get("text", "").strip()
            return text or None
        except Exception as e:
            logger.warning("LLM generate failed: {}", e)
            return None


# ----------------------------------------------------------------------------
# Convenience: LLM-fluent enhancement of the template explanation
# ----------------------------------------------------------------------------

_EXPLAIN_PROMPT = """<|system|>
You are a concise trading-signal explainer. Given structured analysis data,
write a 3-5 sentence explanation of the recommendation in clear, professional
prose. Use only facts present in the data — do not invent numbers, indicators,
or events. If the data is contradictory, say so. Output language: {lang_name}.<|end|>
<|user|>
Symbol: {symbol}
Direction: {direction}
Confidence: {confidence:.0f}%

Engine summary:
{engine_summary}

Key facts:
{facts}

Write the explanation now.<|end|>
<|assistant|>
"""

_LANG_NAME = {
    "en": "English",
    "hi": "Hindi (Devanagari script)",
}


def enhance_explanation(data: dict, lang: str = "en") -> Optional[str]:
    """Take the structured symbol-detail payload and produce an LLM-fluent
    explanation. Returns None if LLM is unavailable — caller should fall
    back to the template explainer.

    Faithfulness: the prompt explicitly instructs the model to use ONLY
    facts present in the data. We don't fully prevent hallucination, but
    the prompt + low temperature (0.4) reduces it materially.
    """
    if not is_available():
        return None

    symbol = data.get("symbol", "?")
    direction = data.get("direction", "NEUTRAL")
    confidence = data.get("confidence", 50) or 50

    # Build a compact engine summary
    analyzers = data.get("analyzers", {}) or {}
    eng_lines = []
    for name in ("technical", "smc", "gann", "fibonacci"):
        a = analyzers.get(name) or {}
        if a.get("bias"):
            eng_lines.append(f"  - {name}: {a['bias']} (score {a.get('score', '?')})")
    engine_summary = "\n".join(eng_lines) or "  (no engine output)"

    # Pull standout facts
    facts = []
    ata = data.get("advanced_ta") or {}
    if ata.get("confluence_count", 0) >= 2:
        facts.append(f"  - Advanced TA confluence: {ata['confluence_count']}/3 agree")
    ha = data.get("historical_analog") or {}
    if ha.get("has_enough_data"):
        outcomes = ha.get("outcomes") or {}
        facts.append(f"  - Historical analogs: {outcomes.get('n', 0)} similar past setups, "
                       f"win rate {(outcomes.get('win_rate', 0) * 100):.0f}%")
    sl = data.get("stop_loss_analysis") or {}
    if sl.get("recommended_method") == "CONFLUENCE":
        facts.append(f"  - Stop-loss confluence: {sl.get('confluence_count')} methods agree")
    facts_str = "\n".join(facts) or "  (no standout facts)"

    prompt = _EXPLAIN_PROMPT.format(
        lang_name=_LANG_NAME.get(lang, "English"),
        symbol=symbol, direction=direction, confidence=confidence,
        engine_summary=engine_summary, facts=facts_str,
    )
    return generate(prompt)
