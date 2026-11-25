"""Resolve the same local provider budget used at the final generation boundary."""

import json
from typing import Any

from hub.config import Settings
from hub.project_models import check, provider_arguments
from hub.provider_settings import runtime_provider
from hub.providers import Providers


def context_budget(
    factory: Any, cfg: Settings, providers: Any, project_model: dict[str, Any] | None,
    provider_binding: dict[str, Any] | None = None,
) -> tuple[int, int | None]:
    # Injected test adapters have no managed provider configuration. Real requests
    # use exactly the project selection/default resolver used by execute_run.
    if not isinstance(providers, Providers):
        return cfg.context_limit, None
    with factory() as db:
        check(db, cfg, project_model)
    arguments: dict[str, Any] = dict(provider_arguments(project_model))
    if provider_binding:
        pinned = {"provider_id": provider_binding["id"], "model": provider_binding["model"]}
        if arguments and arguments != pinned:
            raise PermissionError("Project model differs from bound provider")
        arguments = pinned
    selected, _, rows = runtime_provider(
        factory, cfg, local_only=True, seed_defaults=False, **arguments
    )
    row = rows.get("local")
    if provider_binding and (row is None or row.revision != provider_binding["revision"]):
        raise PermissionError("Bound local provider changed")
    if row is None:
        return min(cfg.context_limit, selected.context_limit), None
    limits = json.loads(row.config)
    # Same two-message envelope, grammar reserve and minimum answer allowance
    # as execution's final-boundary check. Bytes conservatively bound tokens.
    byte_limit = max(0, limits["context_tokens"] - 4096 - 2 * 64
                     - min(1024, limits["output_tokens"]))
    return min(cfg.context_limit, selected.context_limit), byte_limit


def context_limit(
    factory: Any, cfg: Settings, providers: Any, project_model: dict[str, Any] | None,
    provider_binding: dict[str, Any] | None = None,
) -> int:
    return context_budget(factory, cfg, providers, project_model, provider_binding)[0]
