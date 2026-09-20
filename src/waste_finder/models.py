from __future__ import annotations

from dataclasses import dataclass, field

HOURS_PER_MONTH = 730  # Azure's own convention for monthly estimates


@dataclass
class Finding:
    """One wasted resource found in the subscription."""

    rule: str  # unattached_disk | stopped_vm | orphaned_public_ip
    resource_id: str
    name: str
    resource_group: str
    location: str
    sku: str
    size_gb: int | None = None
    os_type: str | None = None
    tags: dict = field(default_factory=dict)
    monthly_cost_eur: float | None = None  # None = price not found
    price_note: str = ""
