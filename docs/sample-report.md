# Azure Kostencheck: Verschwendungsbericht

> **Demo-Daten:** fiktive Subscriptions und Beispielpreise, keine echte Umgebung.

**Bereich:** `demo (Contoso)`  
**Datum:** 2026-10-02

## Ergebnis

Sie verlieren ca. **232,08 € pro Monat** (≈ 2.784,96 € pro Jahr) durch **6** ungenutzte Ressourcen.

1 Ressource(n) ignoriert (Tag `waste-finder:ignore=true` oder Ausschluss in der Konfiguration).

## Gefundene Ressourcen

### Subscription `11111111-1111-1111-1111-111111111111`

Ca. **215,77 € pro Monat** durch 2 Ressource(n).

| # | Ressource | Problem | Priorität | Ressourcengruppe | SKU | €/Monat | Empfehlung |
|---|---|---|---|---|---|---:|---|
| 1 | `build-agent-02` | VM gestoppt, aber nicht dealloziert | hoch | rg-test | Standard_D4s_v5 | 148,19 € | VM deallozieren (az vm deallocate) oder löschen, wenn sie nicht mehr gebraucht wird. |
| 2 | `erp-db-old-data` | Nicht angehängte Managed Disk | mittel | rg-legacy-erp | Premium_LRS (512 GB) | 67,58 € | Bei Bedarf Snapshot erstellen, dann Disk löschen. |

### Subscription `00000000-0000-0000-0000-000000000000`

Ca. **16,31 € pro Monat** durch 4 Ressource(n).

| # | Ressource | Problem | Priorität | Ressourcengruppe | SKU | €/Monat | Empfehlung |
|---|---|---|---|---|---|---:|---|
| 1 | `awf-stopped-vm` | VM gestoppt, aber nicht dealloziert | hoch | awf-waste-demo-rg | Standard_B1s | 8,18 € | VM deallozieren (az vm deallocate) oder löschen, wenn sie nicht mehr gebraucht wird. |
| 2 | `awf-orphaned-pip` | Ungenutzte öffentliche IP-Adresse | niedrig | awf-waste-demo-rg | Standard | 3,36 € | Löschen, sofern die Adresse nicht bewusst reserviert bleiben muss. |
| 3 | `pip-old-gateway` | Ungenutzte öffentliche IP-Adresse | niedrig | rg-web-old | Standard | 3,36 € | Löschen, sofern die Adresse nicht bewusst reserviert bleiben muss. |
| 4 | `awf-orphaned-disk` | Nicht angehängte Managed Disk | mittel | awf-waste-demo-rg | Standard_LRS (32 GB) | 1,41 € | Bei Bedarf Snapshot erstellen, dann Disk löschen. |

## Warum kostet das Geld?

- **Nicht angehängte Managed Disk:** Disks werden nach bereitgestellter Größe abgerechnet, auch wenn keine VM sie nutzt. ([Doku](https://learn.microsoft.com/azure/virtual-machines/windows/find-unattached-disks))
- **VM gestoppt, aber nicht dealloziert:** Im Zustand 'Stopped' bleibt die Hardware reserviert und die Rechenleistung wird weiter verrechnet. ([Doku](https://learn.microsoft.com/azure/virtual-machines/states-billing))
- **Ungenutzte öffentliche IP-Adresse:** Standard-IPs werden pro Stunde verrechnet, auch ohne Zuordnung. ([Doku](https://learn.microsoft.com/azure/virtual-network/ip-services/public-ip-addresses))

## Befehle

Erst prüfen, dann ausführen. Das Tool selbst ändert nichts in der Subscription.

```bash
# build-agent-02: VM gestoppt, aber nicht dealloziert
az vm deallocate --ids /subscriptions/11111111-1111-1111-1111-111111111111/resourceGroups/rg-test/providers/Microsoft.Compute/virtualMachines/build-agent-02
# erp-db-old-data: Nicht angehängte Managed Disk
az disk delete --ids /subscriptions/11111111-1111-1111-1111-111111111111/resourceGroups/rg-legacy-erp/providers/Microsoft.Compute/disks/erp-db-old-data
# awf-stopped-vm: VM gestoppt, aber nicht dealloziert
az vm deallocate --ids /subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/awf-waste-demo-rg/providers/Microsoft.Compute/virtualMachines/awf-stopped-vm
# awf-orphaned-pip: Ungenutzte öffentliche IP-Adresse
az network public-ip delete --ids /subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/awf-waste-demo-rg/providers/Microsoft.Network/publicIPAddresses/awf-orphaned-pip
# pip-old-gateway: Ungenutzte öffentliche IP-Adresse
az network public-ip delete --ids /subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-web-old/providers/Microsoft.Network/publicIPAddresses/pip-old-gateway
# awf-orphaned-disk: Nicht angehängte Managed Disk
az disk delete --ids /subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/awf-waste-demo-rg/providers/Microsoft.Compute/disks/awf-orphaned-disk
```

---

*Preise: Azure Retail Prices API (Listenpreise in EUR, 730 h/Monat). Tatsächliche Preise können durch Rabatte (EA/CSP, Reservierungen, Azure Hybrid Benefit) abweichen.*