"""Conservative reservations; missing usage remains unknown rather than free."""

import json
import time
from datetime import UTC, datetime
from decimal import ROUND_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from hub.db import BudgetReservation, ProviderConfig
from hub.policy import ContextPart, Privacy


class ExecutionLimitError(ValueError, PermissionError):
    """Trusted user-facing limits; never includes provider response content."""


def month() -> str:
    return datetime.now(UTC).strftime("%Y-%m")


def reserve(
    db: Session, provider: ProviderConfig, request_id: str, parts: list[ContextPart]
) -> float:
    # Lock the provider, serializing API test calls and worker budget reservations.
    current = db.scalar(
        select(ProviderConfig).where(ProviderConfig.id == provider.id).with_for_update()
    )
    if not current or not current.enabled or current.revision != provider.revision:
        raise ExecutionLimitError("Provider geändert oder deaktiviert")
    if any(p.label != Privacy.CLOUD_ALLOWED for p in parts):
        raise ExecutionLimitError("Privater Kontext ist nicht für Cloud freigegeben")
    data = json.loads(current.config)
    if "text" not in data["capabilities"] or "CLOUD_ALLOWED" not in data["allowed_labels"]:
        raise ExecutionLimitError("Modellfähigkeit oder Datenschutzklasse nicht freigegeben")
    pricing = data.get("pricing")
    if not pricing or (
        pricing.get("expires_at", 0) < time.time()
        if current.kind in ("openai", "anthropic")
        else time.time() - pricing["verified_at"] > 3600
    ):
        raise ExecutionLimitError("Frische Modellpreise fehlen; Verbindungstest ausführen")
    # Conservative estimate, not an exact tokenizer or a provider billing guarantee.
    input_bound = sum(len(p.content.encode()) + 64 for p in parts) + 256
    context_tokens = min(
        data["context_tokens"], pricing.get("context_tokens") or data["context_tokens"]
    )
    if (
        input_bound + data["output_tokens"] > context_tokens
        or sum(len(p.content) for p in parts) > data["context_chars"]
    ):
        raise ExecutionLimitError("Kontextgrenze des Modells erreicht")
    ceiling = (
        Decimal(str(pricing["input"])) * input_bound
        + Decimal(str(pricing["output"])) * data["output_tokens"]
    ).quantize(Decimal("0.00000001"), rounding=ROUND_UP)
    if not data["max_run_cost"] or ceiling > Decimal(str(data["max_run_cost"])):
        raise ExecutionLimitError("Kostenlimit je Lauf erreicht oder deaktiviert")
    existing = db.get(BudgetReservation, request_id)
    if existing:
        return existing.ceiling
    used = (
        db.scalar(
            select(
                func.coalesce(
                    func.sum(func.coalesce(BudgetReservation.measured, BudgetReservation.ceiling)),
                    0,
                )
            ).where(BudgetReservation.provider_id == current.id, BudgetReservation.month == month())
        )
        or 0
    )
    if not data["monthly_budget"] or Decimal(str(used)) + ceiling > Decimal(
        str(data["monthly_budget"])
    ):
        raise ExecutionLimitError("Monatsbudget erreicht oder deaktiviert")
    db.add(
        BudgetReservation(
            id=request_id, provider_id=current.id, month=month(), ceiling=float(ceiling)
        )
    )
    db.flush()
    return float(ceiling)


def settle(db: Session, request_id: str, measured: float | None) -> None:
    row = db.get(BudgetReservation, request_id)
    if row and measured is not None:
        row.measured = measured
