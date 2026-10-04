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
    age_label_de: str = "Tage alt"  # label for Finding.age_days in the report

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
        Rule(
            id="idle_nat_gateway",
            title_de="NAT-Gateway ohne Subnetz",
            title_en="NAT gateway without subnet",
            severity="medium",
            query_file="idle_nat_gateways.kql",
            pricing="nat_gateway",
            why_de=(
                "Ein NAT-Gateway wird pro Stunde verrechnet, auch wenn kein Subnetz es nutzt und kein Datenverkehr "
                "fließt; die zugeordneten öffentlichen IPs kosten zusätzlich."
            ),
            action_de=(
                "NAT-Gateway löschen, wenn kein Subnetz es mehr braucht; danach die frei gewordenen öffentlichen "
                "IPs prüfen."
            ),
            command="az network nat gateway delete --ids {id}",
            docs_url="https://learn.microsoft.com/azure/nat-gateway/nat-overview",
        ),
        Rule(
            id="idle_load_balancer",
            title_de="Load Balancer ohne Backend",
            title_en="Load balancer without backends",
            severity="low",
            query_file="idle_load_balancers.kql",
            pricing="load_balancer",
            why_de=(
                "Ein Standard Load Balancer wird pro Stunde für seine Lastenausgleichs- und Ausgangsregeln "
                "verrechnet, auch ohne Backend-Mitglieder. Ohne Regeln fällt keine Stundengebühr an; dann ist es "
                "nur ein Hinweis."
            ),
            action_de=(
                "Load Balancer löschen, wenn keine Backends mehr dazukommen; sonst die Regeln entfernen, bis wieder "
                "Backends zugeordnet sind."
            ),
            command="az network lb delete --ids {id}",
            docs_url="https://learn.microsoft.com/azure/load-balancer/load-balancer-overview",
            quantity_unit_de="Regel(n)",
        ),
        Rule(
            id="premium_disk_deallocated_vm",
            title_de="Premium-Disk an deallozierter VM",
            title_en="Premium disk on deallocated VM",
            severity="medium",
            query_file="premium_disks_deallocated_vms.kql",
            pricing="disk_downgrade",
            why_de=(
                "Eine deallozierte VM kostet keine Rechenleistung, ihre Premium- und Standard-SSD-Disks werden aber "
                "weiter zum vollen Tarif verrechnet. Als Standard-HDD kostet dieselbe Größe deutlich weniger; "
                "eingespart wird die Differenz."
            ),
            action_de=(
                "Solange die VM dealloziert bleibt, die Disk auf Standard HDD umstellen (vor dem nächsten Start bei "
                "Bedarf zurück auf SSD); wird die VM nicht mehr gebraucht, VM und Disks löschen."
            ),
            command="az disk update --sku Standard_LRS --ids {id}",
            docs_url="https://learn.microsoft.com/azure/virtual-machines/disks-convert-types",
            age_label_de="Tage dealloziert",
        ),
    )
}
