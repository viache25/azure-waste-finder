# Azure Kostencheck: Verschwendungsbericht

> **Demo-Daten:** fiktive Subscriptions und Beispielpreise, keine echte Umgebung.

**Bereich:** `demo (Contoso)`  
**Datum:** 2026-10-05

## Ergebnis

Sie verlieren ca. **509,03 € pro Monat** (≈ 6.108,36 € pro Jahr) durch **15** ungenutzte Ressourcen.

Die Ressourcen kosten zusammen ca. 533,36 € pro Monat; eingespart wird weniger, weil verkleinerte Ressourcen weiter etwas kosten (Spalten „Kosten“ und „Einsparung“).

1 Ressource(n) ignoriert (Tag `waste-finder:ignore=true` oder Ausschluss in der Konfiguration).

Dazu 6 kostenlose Ressource(n) zum Aufräumen, nicht in der Summe enthalten (Abschnitt „Aufräumen (kostenlos)“).

## Entwicklung seit dem letzten Bericht

Letzter Bericht vom 2026-09-04: ca. 519,00 € pro Monat. Jetzt ca. 509,03 €, also **-9,97 € pro Monat**.

2 neu (+77,34 €), 2 behoben (-151,55 €), 13 unverändert, davon 1 mit geändertem Betrag (+64,24 €).

| Status | Ressource | Problem | Subscription | vorher €/Monat | jetzt €/Monat |
|---|---|---|---|---:|---:|
| neu | `sap-test-db-data` | Premium-Disk an deallozierter VM | `11111111-1111-1111-1111-111111111111` | – | 48,43 € |
| neu | `natgw-old-hub` | NAT-Gateway ohne Subnetz | `11111111-1111-1111-1111-111111111111` | – | 28,91 € |
| behoben | `build-agent-01` | VM gestoppt, aber nicht dealloziert | `11111111-1111-1111-1111-111111111111` | 148,19 € | – |
| behoben | `pip-old-vpn` | Ungenutzte öffentliche IP-Adresse | `00000000-0000-0000-0000-000000000000` | 3,36 € | – |
| geändert | `asp-intranet-legacy` | Leerer App-Service-Plan | `11111111-1111-1111-1111-111111111111` | 64,24 € | 128,48 € |

## Gefundene Ressourcen

### Subscription `11111111-1111-1111-1111-111111111111`

Ca. **444,12 € pro Monat** durch 6 Ressource(n).

| # | Ressource | Problem | Priorität | Ressourcengruppe | SKU | Kosten €/Monat | Einsparung €/Monat | Empfehlung |
|---|---|---|---|---|---|---:|---:|---|
| 1 | `build-agent-02` | VM gestoppt, aber nicht dealloziert | hoch | rg-test | Standard_D4s_v5 | 148,19 € | 148,19 € | VM deallozieren (az vm deallocate) oder löschen, wenn sie nicht mehr gebraucht wird. |
| 2 | `asp-intranet-legacy` | Leerer App-Service-Plan | mittel | rg-intranet | S1, 2 Instanz(en) | 128,48 € | 128,48 € | Plan löschen, wenn keine App mehr darauf soll; sonst auf den Free-Tarif (F1) oder eine kleinere Stufe skalieren. |
| 3 | `erp-db-old-data` | Nicht angehängte Managed Disk | mittel | rg-legacy-erp | Premium_LRS (512 GB) | 67,58 € | 67,58 € | Bei Bedarf Snapshot erstellen, dann Disk löschen. |
| 4 | `sap-test-db-data` | Premium-Disk an deallozierter VM | mittel | rg-sap-test | Premium_LRS (512 GB), 75 Tage dealloziert | 67,58 € | 48,43 € | Solange die VM dealloziert bleibt, die Disk auf Standard HDD umstellen (vor dem nächsten Start bei Bedarf zurück auf SSD); wird die VM nicht mehr gebraucht, VM und Disks löschen. |
| 5 | `natgw-old-hub` | NAT-Gateway ohne Subnetz | mittel | rg-network-old | Standard | 28,91 € | 28,91 € | NAT-Gateway löschen, wenn kein Subnetz es mehr braucht; danach die frei gewordenen öffentlichen IPs prüfen. |
| 6 | `erp-db-before-migration` | Alter Disk-Snapshot | niedrig | rg-legacy-erp | Standard_LRS (512 GB), 324 Tage alt | 22,53 € | 22,53 € | Prüfen, ob der Snapshot noch als Backup gebraucht wird; sonst löschen oder durch Azure Backup mit Aufbewahrungsregel ersetzen. |

### Subscription `00000000-0000-0000-0000-000000000000`

Ca. **64,91 € pro Monat** durch 9 Ressource(n).

| # | Ressource | Problem | Priorität | Ressourcengruppe | SKU | Kosten €/Monat | Einsparung €/Monat | Empfehlung |
|---|---|---|---|---|---|---:|---:|---|
| 1 | `web-os-before-upgrade` | Alter Disk-Snapshot | niedrig | rg-web-old | Premium_LRS (128 GB), 124 Tage alt | 16,33 € | 16,33 € | Prüfen, ob der Snapshot noch als Backup gebraucht wird; sonst löschen oder durch Azure Backup mit Aufbewahrungsregel ersetzen. |
| 2 | `lb-web-old` | Load Balancer ohne Backend | niedrig | rg-web-old | Standard, 2 Regel(n) | 16,06 € | 16,06 € | Load Balancer löschen, wenn keine Backends mehr dazukommen; sonst die Regeln entfernen, bis wieder Backends zugeordnet sind. |
| 3 | `awf-empty-plan` | Leerer App-Service-Plan | mittel | awf-waste-demo-rg | B1, 1 Instanz(en) | 11,53 € | 11,53 € | Plan löschen, wenn keine App mehr darauf soll; sonst auf den Free-Tarif (F1) oder eine kleinere Stufe skalieren. |
| 4 | `awf-stopped-vm` | VM gestoppt, aber nicht dealloziert | hoch | awf-waste-demo-rg | Standard_B1s | 8,18 € | 8,18 € | VM deallozieren (az vm deallocate) oder löschen, wenn sie nicht mehr gebraucht wird. |
| 5 | `awf-orphaned-pip` | Ungenutzte öffentliche IP-Adresse | niedrig | awf-waste-demo-rg | Standard | 3,36 € | 3,36 € | Löschen, sofern die Adresse nicht bewusst reserviert bleiben muss. |
| 6 | `pip-old-gateway` | Ungenutzte öffentliche IP-Adresse | niedrig | rg-web-old | Standard | 3,36 € | 3,36 € | Löschen, sofern die Adresse nicht bewusst reserviert bleiben muss. |
| 7 | `web-old-vm-osdisk` | Premium-Disk an deallozierter VM | mittel | rg-web-old | StandardSSD_LRS (128 GB), 40 Tage dealloziert | 8,45 € | 3,27 € | Solange die VM dealloziert bleibt, die Disk auf Standard HDD umstellen (vor dem nächsten Start bei Bedarf zurück auf SSD); wird die VM nicht mehr gebraucht, VM und Disks löschen. |
| 8 | `awf-orphaned-disk` | Nicht angehängte Managed Disk | mittel | awf-waste-demo-rg | Standard_LRS (32 GB) | 1,41 € | 1,41 € | Bei Bedarf Snapshot erstellen, dann Disk löschen. |
| 9 | `awf-old-snapshot` | Alter Disk-Snapshot | niedrig | awf-waste-demo-rg | Standard_LRS (32 GB), 45 Tage alt | 1,41 € | 1,41 € | Prüfen, ob der Snapshot noch als Backup gebraucht wird; sonst löschen oder durch Azure Backup mit Aufbewahrungsregel ersetzen. |

## Aufräumen (kostenlos)

Diese Ressourcen kosten nichts und zählen nicht zur Summe oben. Aufräumen schafft Übersicht und vermeidet Fehler.

| # | Ressource | Problem | Subscription | Ressourcengruppe | Empfehlung |
|---|---|---|---|---|---|
| 1 | `awf-idle-lb` | Load Balancer ohne Backend | `00000000-0000-0000-0000-000000000000` | awf-waste-demo-rg | Load Balancer löschen, wenn keine Backends mehr dazukommen; sonst die Regeln entfernen, bis wieder Backends zugeordnet sind. |
| 2 | `rg-migration-temp` | Leere Ressourcengruppe | `00000000-0000-0000-0000-000000000000` | rg-migration-temp | Löschen, wenn kein neues Projekt darin geplant ist. |
| 3 | `web-old-vm2-nic` | Verwaiste Netzwerkschnittstelle | `00000000-0000-0000-0000-000000000000` | rg-web-old | Löschen, wenn keine VM sie mehr bekommen soll. |
| 4 | `web-old-nsg` | Nicht zugeordnete Netzwerksicherheitsgruppe | `00000000-0000-0000-0000-000000000000` | rg-web-old | Löschen oder bewusst dem vorgesehenen Subnetz zuordnen. |
| 5 | `rg-poc-2024` | Leere Ressourcengruppe | `11111111-1111-1111-1111-111111111111` | rg-poc-2024 | Löschen, wenn kein neues Projekt darin geplant ist. |
| 6 | `build-agent-01-nic` | Verwaiste Netzwerkschnittstelle | `11111111-1111-1111-1111-111111111111` | rg-test | Löschen, wenn keine VM sie mehr bekommen soll. |

- **Load Balancer ohne Backend:** Ein Standard Load Balancer wird pro Stunde für seine Lastenausgleichs- und Ausgangsregeln verrechnet, auch ohne Backend-Mitglieder. Ohne Regeln fällt keine Stundengebühr an; dann ist es nur ein Hinweis. ([Doku](https://learn.microsoft.com/azure/load-balancer/load-balancer-overview))
- **Leere Ressourcengruppe:** Kostet nichts, macht aber Zuständigkeiten, Budgets und Berechtigungen unübersichtlich; oft der Rest eines abgeschlossenen Projekts. ([Doku](https://learn.microsoft.com/azure/azure-resource-manager/management/manage-resource-groups-cli))
- **Verwaiste Netzwerkschnittstelle:** Kostet nichts, belegt aber eine private IP-Adresse im Subnetz und bleibt oft nach dem Löschen einer VM zurück. ([Doku](https://learn.microsoft.com/azure/virtual-network/virtual-network-network-interface))
- **Nicht zugeordnete Netzwerksicherheitsgruppe:** Kostet nichts, schützt aber auch nichts: Ihre Regeln wirken erst, wenn sie einem Subnetz oder einer Netzwerkschnittstelle zugeordnet ist. ([Doku](https://learn.microsoft.com/azure/virtual-network/network-security-groups-overview))

```bash
# awf-idle-lb: Load Balancer ohne Backend
az network lb delete --ids /subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/awf-waste-demo-rg/providers/Microsoft.Network/loadBalancers/awf-idle-lb
# rg-migration-temp: Leere Ressourcengruppe
az group delete --name rg-migration-temp --subscription 00000000-0000-0000-0000-000000000000
# web-old-vm2-nic: Verwaiste Netzwerkschnittstelle
az network nic delete --ids /subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-web-old/providers/Microsoft.Network/networkInterfaces/web-old-vm2-nic
# web-old-nsg: Nicht zugeordnete Netzwerksicherheitsgruppe
az network nsg delete --ids /subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-web-old/providers/Microsoft.Network/networkSecurityGroups/web-old-nsg
# rg-poc-2024: Leere Ressourcengruppe
az group delete --name rg-poc-2024 --subscription 11111111-1111-1111-1111-111111111111
# build-agent-01-nic: Verwaiste Netzwerkschnittstelle
az network nic delete --ids /subscriptions/11111111-1111-1111-1111-111111111111/resourceGroups/rg-test/providers/Microsoft.Network/networkInterfaces/build-agent-01-nic
```

## Warum kostet das Geld?

- **Nicht angehängte Managed Disk:** Disks werden nach bereitgestellter Größe abgerechnet, auch wenn keine VM sie nutzt. ([Doku](https://learn.microsoft.com/azure/virtual-machines/windows/find-unattached-disks))
- **VM gestoppt, aber nicht dealloziert:** Im Zustand 'Stopped' bleibt die Hardware reserviert und die Rechenleistung wird weiter verrechnet. ([Doku](https://learn.microsoft.com/azure/virtual-machines/states-billing))
- **Ungenutzte öffentliche IP-Adresse:** Standard-IPs werden pro Stunde verrechnet, auch ohne Zuordnung. ([Doku](https://learn.microsoft.com/azure/virtual-network/ip-services/public-ip-addresses))
- **Alter Disk-Snapshot:** Snapshots werden pro GB und Monat verrechnet, solange sie existieren, auch wenn die Quell-Disk längst gelöscht ist. Geschätzt mit der bereitgestellten Größe (Obergrenze; verrechnet wird die belegte Größe). ([Doku](https://learn.microsoft.com/azure/virtual-machines/disks-understand-billing))
- **Leerer App-Service-Plan:** Ein App-Service-Plan wird pro Instanz und Stunde verrechnet, auch wenn keine App darauf läuft. ([Doku](https://learn.microsoft.com/azure/app-service/overview-hosting-plans))
- **NAT-Gateway ohne Subnetz:** Ein NAT-Gateway wird pro Stunde verrechnet, auch wenn kein Subnetz es nutzt und kein Datenverkehr fließt; die zugeordneten öffentlichen IPs kosten zusätzlich. ([Doku](https://learn.microsoft.com/azure/nat-gateway/nat-overview))
- **Load Balancer ohne Backend:** Ein Standard Load Balancer wird pro Stunde für seine Lastenausgleichs- und Ausgangsregeln verrechnet, auch ohne Backend-Mitglieder. Ohne Regeln fällt keine Stundengebühr an; dann ist es nur ein Hinweis. ([Doku](https://learn.microsoft.com/azure/load-balancer/load-balancer-overview))
- **Premium-Disk an deallozierter VM:** Eine deallozierte VM kostet keine Rechenleistung, ihre Premium- und Standard-SSD-Disks werden aber weiter zum vollen Tarif verrechnet. Als Standard-HDD kostet dieselbe Größe deutlich weniger; eingespart wird die Differenz. ([Doku](https://learn.microsoft.com/azure/virtual-machines/disks-convert-types))

## Befehle

Erst prüfen, dann ausführen. Das Tool selbst ändert nichts in der Subscription.

```bash
# build-agent-02: VM gestoppt, aber nicht dealloziert
az vm deallocate --ids /subscriptions/11111111-1111-1111-1111-111111111111/resourceGroups/rg-test/providers/Microsoft.Compute/virtualMachines/build-agent-02
# asp-intranet-legacy: Leerer App-Service-Plan
az appservice plan delete --ids /subscriptions/11111111-1111-1111-1111-111111111111/resourceGroups/rg-intranet/providers/Microsoft.Web/serverfarms/asp-intranet-legacy
# erp-db-old-data: Nicht angehängte Managed Disk
az disk delete --ids /subscriptions/11111111-1111-1111-1111-111111111111/resourceGroups/rg-legacy-erp/providers/Microsoft.Compute/disks/erp-db-old-data
# sap-test-db-data: Premium-Disk an deallozierter VM
az disk update --sku Standard_LRS --ids /subscriptions/11111111-1111-1111-1111-111111111111/resourceGroups/rg-sap-test/providers/Microsoft.Compute/disks/sap-test-db-data
# natgw-old-hub: NAT-Gateway ohne Subnetz
az network nat gateway delete --ids /subscriptions/11111111-1111-1111-1111-111111111111/resourceGroups/rg-network-old/providers/Microsoft.Network/natGateways/natgw-old-hub
# erp-db-before-migration: Alter Disk-Snapshot
az snapshot delete --ids /subscriptions/11111111-1111-1111-1111-111111111111/resourceGroups/rg-legacy-erp/providers/Microsoft.Compute/snapshots/erp-db-before-migration
# web-os-before-upgrade: Alter Disk-Snapshot
az snapshot delete --ids /subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-web-old/providers/Microsoft.Compute/snapshots/web-os-before-upgrade
# lb-web-old: Load Balancer ohne Backend
az network lb delete --ids /subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-web-old/providers/Microsoft.Network/loadBalancers/lb-web-old
# awf-empty-plan: Leerer App-Service-Plan
az appservice plan delete --ids /subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/awf-waste-demo-rg/providers/Microsoft.Web/serverfarms/awf-empty-plan
# awf-stopped-vm: VM gestoppt, aber nicht dealloziert
az vm deallocate --ids /subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/awf-waste-demo-rg/providers/Microsoft.Compute/virtualMachines/awf-stopped-vm
# awf-orphaned-pip: Ungenutzte öffentliche IP-Adresse
az network public-ip delete --ids /subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/awf-waste-demo-rg/providers/Microsoft.Network/publicIPAddresses/awf-orphaned-pip
# pip-old-gateway: Ungenutzte öffentliche IP-Adresse
az network public-ip delete --ids /subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-web-old/providers/Microsoft.Network/publicIPAddresses/pip-old-gateway
# web-old-vm-osdisk: Premium-Disk an deallozierter VM
az disk update --sku Standard_LRS --ids /subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-web-old/providers/Microsoft.Compute/disks/web-old-vm-osdisk
# awf-orphaned-disk: Nicht angehängte Managed Disk
az disk delete --ids /subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/awf-waste-demo-rg/providers/Microsoft.Compute/disks/awf-orphaned-disk
# awf-old-snapshot: Alter Disk-Snapshot
az snapshot delete --ids /subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/awf-waste-demo-rg/providers/Microsoft.Compute/snapshots/awf-old-snapshot
```

---

*Preise: Azure Retail Prices API (Listenpreise in EUR, 730 h/Monat). Tatsächliche Preise können durch Rabatte (EA/CSP, Reservierungen, Azure Hybrid Benefit) abweichen.*