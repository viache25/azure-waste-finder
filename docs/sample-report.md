# Azure Kostencheck: Verschwendungsbericht

> **Demo-Daten:** fiktive Subscriptions und Beispielpreise, keine echte Umgebung.

**Bereich:** `demo (Contoso)`  
**Datum:** 2026-10-04

## Ergebnis

Sie verlieren ca. **412,36 € pro Monat** (≈ 4.948,32 € pro Jahr) durch **11** ungenutzte Ressourcen.

1 Ressource(n) ignoriert (Tag `waste-finder:ignore=true` oder Ausschluss in der Konfiguration).

## Gefundene Ressourcen

### Subscription `11111111-1111-1111-1111-111111111111`

Ca. **366,78 € pro Monat** durch 4 Ressource(n).

| # | Ressource | Problem | Priorität | Ressourcengruppe | SKU | €/Monat | Empfehlung |
|---|---|---|---|---|---|---:|---|
| 1 | `build-agent-02` | VM gestoppt, aber nicht dealloziert | hoch | rg-test | Standard_D4s_v5 | 148,19 € | VM deallozieren (az vm deallocate) oder löschen, wenn sie nicht mehr gebraucht wird. |
| 2 | `asp-intranet-legacy` | Leerer App-Service-Plan | mittel | rg-intranet | S1, 2 Instanz(en) | 128,48 € | Plan löschen, wenn keine App mehr darauf soll; sonst auf den Free-Tarif (F1) oder eine kleinere Stufe skalieren. |
| 3 | `erp-db-old-data` | Nicht angehängte Managed Disk | mittel | rg-legacy-erp | Premium_LRS (512 GB) | 67,58 € | Bei Bedarf Snapshot erstellen, dann Disk löschen. |
| 4 | `erp-db-before-migration` | Alter Disk-Snapshot | niedrig | rg-legacy-erp | Standard_LRS (512 GB), 324 Tage alt | 22,53 € | Prüfen, ob der Snapshot noch als Backup gebraucht wird; sonst löschen oder durch Azure Backup mit Aufbewahrungsregel ersetzen. |

### Subscription `00000000-0000-0000-0000-000000000000`

Ca. **45,58 € pro Monat** durch 7 Ressource(n).

| # | Ressource | Problem | Priorität | Ressourcengruppe | SKU | €/Monat | Empfehlung |
|---|---|---|---|---|---|---:|---|
| 1 | `web-os-before-upgrade` | Alter Disk-Snapshot | niedrig | rg-web-old | Premium_LRS (128 GB), 124 Tage alt | 16,33 € | Prüfen, ob der Snapshot noch als Backup gebraucht wird; sonst löschen oder durch Azure Backup mit Aufbewahrungsregel ersetzen. |
| 2 | `awf-empty-plan` | Leerer App-Service-Plan | mittel | awf-waste-demo-rg | B1, 1 Instanz(en) | 11,53 € | Plan löschen, wenn keine App mehr darauf soll; sonst auf den Free-Tarif (F1) oder eine kleinere Stufe skalieren. |
| 3 | `awf-stopped-vm` | VM gestoppt, aber nicht dealloziert | hoch | awf-waste-demo-rg | Standard_B1s | 8,18 € | VM deallozieren (az vm deallocate) oder löschen, wenn sie nicht mehr gebraucht wird. |
| 4 | `awf-orphaned-pip` | Ungenutzte öffentliche IP-Adresse | niedrig | awf-waste-demo-rg | Standard | 3,36 € | Löschen, sofern die Adresse nicht bewusst reserviert bleiben muss. |
| 5 | `pip-old-gateway` | Ungenutzte öffentliche IP-Adresse | niedrig | rg-web-old | Standard | 3,36 € | Löschen, sofern die Adresse nicht bewusst reserviert bleiben muss. |
| 6 | `awf-orphaned-disk` | Nicht angehängte Managed Disk | mittel | awf-waste-demo-rg | Standard_LRS (32 GB) | 1,41 € | Bei Bedarf Snapshot erstellen, dann Disk löschen. |
| 7 | `awf-old-snapshot` | Alter Disk-Snapshot | niedrig | awf-waste-demo-rg | Standard_LRS (32 GB), 45 Tage alt | 1,41 € | Prüfen, ob der Snapshot noch als Backup gebraucht wird; sonst löschen oder durch Azure Backup mit Aufbewahrungsregel ersetzen. |

## Warum kostet das Geld?

- **Nicht angehängte Managed Disk:** Disks werden nach bereitgestellter Größe abgerechnet, auch wenn keine VM sie nutzt. ([Doku](https://learn.microsoft.com/azure/virtual-machines/windows/find-unattached-disks))
- **VM gestoppt, aber nicht dealloziert:** Im Zustand 'Stopped' bleibt die Hardware reserviert und die Rechenleistung wird weiter verrechnet. ([Doku](https://learn.microsoft.com/azure/virtual-machines/states-billing))
- **Ungenutzte öffentliche IP-Adresse:** Standard-IPs werden pro Stunde verrechnet, auch ohne Zuordnung. ([Doku](https://learn.microsoft.com/azure/virtual-network/ip-services/public-ip-addresses))
- **Alter Disk-Snapshot:** Snapshots werden pro GB und Monat verrechnet, solange sie existieren, auch wenn die Quell-Disk längst gelöscht ist. Geschätzt mit der bereitgestellten Größe (Obergrenze; verrechnet wird die belegte Größe). ([Doku](https://learn.microsoft.com/azure/virtual-machines/disks-understand-billing))
- **Leerer App-Service-Plan:** Ein App-Service-Plan wird pro Instanz und Stunde verrechnet, auch wenn keine App darauf läuft. ([Doku](https://learn.microsoft.com/azure/app-service/overview-hosting-plans))

## Befehle

Erst prüfen, dann ausführen. Das Tool selbst ändert nichts in der Subscription.

```bash
# build-agent-02: VM gestoppt, aber nicht dealloziert
az vm deallocate --ids /subscriptions/11111111-1111-1111-1111-111111111111/resourceGroups/rg-test/providers/Microsoft.Compute/virtualMachines/build-agent-02
# asp-intranet-legacy: Leerer App-Service-Plan
az appservice plan delete --ids /subscriptions/11111111-1111-1111-1111-111111111111/resourceGroups/rg-intranet/providers/Microsoft.Web/serverfarms/asp-intranet-legacy
# erp-db-old-data: Nicht angehängte Managed Disk
az disk delete --ids /subscriptions/11111111-1111-1111-1111-111111111111/resourceGroups/rg-legacy-erp/providers/Microsoft.Compute/disks/erp-db-old-data
# erp-db-before-migration: Alter Disk-Snapshot
az snapshot delete --ids /subscriptions/11111111-1111-1111-1111-111111111111/resourceGroups/rg-legacy-erp/providers/Microsoft.Compute/snapshots/erp-db-before-migration
# web-os-before-upgrade: Alter Disk-Snapshot
az snapshot delete --ids /subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-web-old/providers/Microsoft.Compute/snapshots/web-os-before-upgrade
# awf-empty-plan: Leerer App-Service-Plan
az appservice plan delete --ids /subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/awf-waste-demo-rg/providers/Microsoft.Web/serverfarms/awf-empty-plan
# awf-stopped-vm: VM gestoppt, aber nicht dealloziert
az vm deallocate --ids /subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/awf-waste-demo-rg/providers/Microsoft.Compute/virtualMachines/awf-stopped-vm
# awf-orphaned-pip: Ungenutzte öffentliche IP-Adresse
az network public-ip delete --ids /subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/awf-waste-demo-rg/providers/Microsoft.Network/publicIPAddresses/awf-orphaned-pip
# pip-old-gateway: Ungenutzte öffentliche IP-Adresse
az network public-ip delete --ids /subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-web-old/providers/Microsoft.Network/publicIPAddresses/pip-old-gateway
# awf-orphaned-disk: Nicht angehängte Managed Disk
az disk delete --ids /subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/awf-waste-demo-rg/providers/Microsoft.Compute/disks/awf-orphaned-disk
# awf-old-snapshot: Alter Disk-Snapshot
az snapshot delete --ids /subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/awf-waste-demo-rg/providers/Microsoft.Compute/snapshots/awf-old-snapshot
```

---

*Preise: Azure Retail Prices API (Listenpreise in EUR, 730 h/Monat). Tatsächliche Preise können durch Rabatte (EA/CSP, Reservierungen, Azure Hybrid Benefit) abweichen.*