from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from waste_finder.registry import Severity

HOURS_PER_MONTH = 730  # Azure's own convention for monthly estimates

# Where a finding's amounts come from: list price (Retail Prices API) or actual cost (Cost Management).
CostSource = Literal["retail", "actual"]


@dataclass
class Finding:
    """One wasted resource found in the subscription."""

    rule: str  # key in registry.REGISTRY
    resource_id: str
    name: str
    resource_group: str
    location: str
    sku: str
    size_gb: int | None = None
    os_type: str | None = None
    age_days: int | None = None  # days since a reference time (e.g. snapshot creation), for age-based rules
    quantity: int | None = None  # billed units where the price depends on them, e.g. App Service plan instances
    tags: dict[str, str] = field(default_factory=dict)
    severity: Severity = "medium"
    # Amounts are in the configured currency (EUR unless `currency` is set in waste-finder.toml).
    monthly_cost_eur: float | None = None  # what the resource costs now; None = price not found
    monthly_savings_eur: float | None = None  # what acting saves, if less than the full cost (e.g. a downgrade)
    price_note: str = ""
    cost_source: CostSource | None = None  # None while unpriced

    @property
    def subscription_id(self) -> str:
        """'/subscriptions/<id>/resourceGroups/...' -> '<id>'; empty if the ID has no subscription."""
        parts = self.resource_id.split("/")
        return parts[2] if len(parts) > 2 and parts[1].lower() == "subscriptions" else ""

    @property
    def is_free(self) -> bool:
        """Priced at exactly 0: nothing to save, only to clean up (report section "Aufräumen (kostenlos)")."""
        return self.monthly_cost_eur == 0

    @property
    def savings_eur(self) -> float | None:
        """Monthly savings; defaults to the full cost when no separate savings are known."""
        return self.monthly_savings_eur if self.monthly_savings_eur is not None else self.monthly_cost_eur
