"""The rule registry: every rule is declared once here, as data.

`rules.py` runs the KQL file, `pricing.py` looks up the pricing strategy by name,
the report and the CLI take titles, severity and remediation from here.
How to add a rule: see CLAUDE.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Severity = Literal["high", "medium", "low", "info"]

# Report order and German labels.
SEVERITIES: dict[Severity, str] = {"high": "hoch", "medium": "mittel", "low": "niedrig", "info": "info"}


@dataclass(frozen=True)
class Rule:
    id: str
    title_de: str
    title_en: str
    severity: Severity
    query_file: str  # file in waste_finder/queries
    pricing: str  # key in pricing.STRATEGIES
    why_de: str  # why it costs money (German, for the report)
    action_de: str  # what to do (German, for the report)
    command: str  # az command for the remediation; {id} is replaced by the resource ID
    docs_url: str
    quantity_unit_de: str = ""  # label for Finding.quantity in the report, e.g. "Instanz(en)"; empty = not shown

    def remediation_command(self, resource_id: str) -> str:
        return self.command.format(id=resource_id)


REGISTRY: dict[str, Rule] = {
    rule.id: rule
    for rule in (
        Rule(
            id="unattached_disk",
            title_de="Nicht angehängte Managed Disk",
            title_en="Unattached managed disk",
            severity="medium",
            query_file="unattached_disks.kql",
            pricing="managed_disk",
            why_de="Disks werden nach bereitgestellter Größe abgerechnet, auch wenn keine VM sie nutzt.",
            action_de="Bei Bedarf Snapshot erstellen, dann Disk löschen.",
            command="az disk delete --ids {id}",
            docs_url="https://learn.microsoft.com/azure/virtual-machines/windows/find-unattached-disks",
        ),
        Rule(
            id="stopped_vm",
            title_de="VM gestoppt, aber nicht dealloziert",
            title_en="VM stopped but not deallocated",
            severity="high",
            query_file="stopped_vms.kql",
            pricing="vm_compute",
            why_de=(
                "Im Zustand 'Stopped' bleibt die Hardware reserviert und die Rechenleistung wird weiter verrechnet."
            ),
            action_de="VM deallozieren (az vm deallocate) oder löschen, wenn sie nicht mehr gebraucht wird.",
            command="az vm deallocate --ids {id}",
            docs_url="https://learn.microsoft.com/azure/virtual-machines/states-billing",
        ),
        Rule(
            id="orphaned_public_ip",
            title_de="Ungenutzte öffentliche IP-Adresse",
            title_en="Orphaned public IP",
            severity="low",
            query_file="orphaned_public_ips.kql",
            pricing="public_ip",
            why_de="Standard-IPs werden pro Stunde verrechnet, auch ohne Zuordnung.",
            action_de="Löschen, sofern die Adresse nicht bewusst reserviert bleiben muss.",
            command="az network public-ip delete --ids {id}",
            docs_url="https://learn.microsoft.com/azure/virtual-network/ip-services/public-ip-addresses",
        ),
        Rule(
            id="old_snapshot",
            title_de="Alter Disk-Snapshot",
            title_en="Old disk snapshot",
            severity="low",
            query_file="old_snapshots.kql",
            pricing="snapshot",
            why_de=(
                "Snapshots werden pro GB und Monat verrechnet, solange sie existieren, auch wenn die Quell-Disk "
                "längst gelöscht ist. Geschätzt mit der bereitgestellten Größe (Obergrenze; verrechnet wird die "
                "belegte Größe)."
            ),
            action_de=(
                "Prüfen, ob der Snapshot noch als Backup gebraucht wird; sonst löschen oder durch Azure Backup "
                "mit Aufbewahrungsregel ersetzen."
            ),
            command="az snapshot delete --ids {id}",
            docs_url="https://learn.microsoft.com/azure/virtual-machines/disks-understand-billing",
        ),
        Rule(
            id="empty_app_service_plan",
            title_de="Leerer App-Service-Plan",
            title_en="Empty App Service plan",
            severity="medium",
            query_file="empty_app_service_plans.kql",
            pricing="app_service_plan",
            why_de=("Ein App-Service-Plan wird pro Instanz und Stunde verrechnet, auch wenn keine App darauf läuft."),
            action_de=(
                "Plan löschen, wenn keine App mehr darauf soll; sonst auf den Free-Tarif (F1) oder eine kleinere "
                "Stufe skalieren."
            ),
            command="az appservice plan delete --ids {id}",
            docs_url="https://learn.microsoft.com/azure/app-service/overview-hosting-plans",
            quantity_unit_de="Instanz(en)",
        ),
    )
}
