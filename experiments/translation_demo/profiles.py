"""Versioned generation profiles; preserve historical native request defaults."""

from typing import Any


LEGACY_PROFILE = "legacy-greedy-v1"
OFFICIAL_PROFILE = "official30b-cached-v1"
PROFILE_NAMES = (LEGACY_PROFILE, OFFICIAL_PROFILE)
APEX_CANDIDATE = "hy-mt2-30b-a3b-apex-i-compact"
GUARD_TOKENS = 64


def resolve_profile(
    name: str, candidate: str, *, n_predict: int | None = None,
    context_size: int | None = None, mapping_only: bool = False,
) -> dict[str, Any]:
    """Resolve defaults before inference and reject ambiguous official overrides."""
    if name not in PROFILE_NAMES:
        raise ValueError(f"Unknown sampling profile: {name}")
    official = name == OFFICIAL_PROFILE
    if official and (candidate != APEX_CANDIDATE or mapping_only):
        raise ValueError("Official cached baseline requires APEX translation, without a mapping phase")
    output = n_predict if n_predict is not None else (4096 if official else 1024)
    context = context_size if context_size is not None else (8192 if official else 4096)
    if type(output) is not int or type(context) is not int or output <= 0 or context <= 0:
        raise ValueError("Token budgets must be positive integers")
    if official and (output != 4096 or context < 8192):
        raise ValueError("Official cached baseline requires --n-predict 4096 and --context-size >= 8192")
    parameters: dict[str, Any] = {
        "n_predict": output, "temperature": 0.0, "seed": 20261006,
        "cache_prompt": False, "stream": False,
    }
    if official:
        # Native /completion uses 0 for disabled top-k, repeat_penalty for
        # repetition_penalty and n_predict for max_tokens. Only temperature
        # participates in the sampler chain; server truncation defaults cannot
        # silently reintroduce top-k, top-p, min-p or adaptive sampling.
        parameters.update(
            temperature=0.7, top_p=1.0, top_k=0, repeat_penalty=1.0,
            min_p=0.0, samplers=["temperature"], dynatemp_range=0.0,
            mirostat=0, frequency_penalty=0.0, presence_penalty=0.0,
            cache_prompt=True,
        )
    result = {
        "sampling_profile": name, "n_predict": output, "context_size": context,
        "generation_parameters": parameters,
    }
    if official:
        result["model_recommendation"] = {
            "temperature": 0.7, "top_p": 1.0, "top_k": -1,
            "repetition_penalty": 1.0, "max_tokens": 4096,
        }
    return result


def generation_parameters(settings: dict[str, Any]) -> dict[str, Any]:
    """Return actual wire settings, including exact historical fallback."""
    parameters = settings.get("generation_parameters")
    if parameters is not None:
        if parameters["n_predict"] != settings["n_predict"]:
            raise ValueError("Generation output budget differs from recorded settings")
        return dict(parameters)
    return {
        "n_predict": settings["n_predict"], "temperature": 0.0,
        "seed": 20261006, "cache_prompt": False, "stream": False,
    }
