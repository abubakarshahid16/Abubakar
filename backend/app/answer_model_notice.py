"""Order 238.2: the 35B model is the default answer model, and when it cannot run the app says so.

The default `answer_model` is `hf.co/unsloth/Qwen3.6-35B-A3B-GGUF:UD-Q4_K_XL` (a 22 GB file, about
24 GB resident; the owner's decision of 27 Oct 2026). A machine that has not pulled it yet used to
meet the first Explain or chat answer as a failed model call. This module turns that state into a
warning on the dashboard's list: it says the model is not installed, how to install it, and which
earlier model to set instead. It never switches model by itself, and it never edits `backend/.env`
(that file is the owner's: when it pins `ANSWER_MODEL`, the owner changes it).

The low-memory warning for the same model lives in `metrics.warnings` and reads
`answer_model_ram_bytes` (about 24 GB for the 35B). Read only; no network of its own: it is handed
what `metrics.models()` already probed.
"""

from __future__ import annotations

from .config import settings

#: The model that was the default before the 35B. Named in the warning, never switched to.
EARLIER_DEFAULT = "qwen3.5:4b"

CODE = "answer_model_not_installed"


def warnings(models_info: dict, host: bool) -> list[dict]:
    """The one warning when the engine answered and does not hold the answer model.

    Nothing when the engine is unreachable (its own error is already reported) or the model is
    there. The model's name is shown to an operator (`host`); everyone else gets the consequence
    and the remedy without it."""
    if not models_info.get("answer_model_reachable") or models_info.get(
        "answer_model_installed"
    ):
        return []
    message = (
        f"The answer model {settings.answer_model} is not installed on this machine's model "
        f"engine, so Explain and chat answers cannot run. Install it with "
        f"'ollama pull {settings.answer_model}', or set ANSWER_MODEL to the earlier default "
        f"{EARLIER_DEFAULT} (and ANSWER_MODEL_RAM_BYTES to its size). Quoted answers are "
        f"unaffected."
        if host
        else "The answer model is not installed on this machine, so Explain and chat answers "
        "cannot run. Quoted answers are unaffected. Ask an administrator to install it or to "
        "switch to the earlier, smaller model."
    )
    return [
        {"severity": "warning", "code": CODE, "document_id": None, "message": message}
    ]
