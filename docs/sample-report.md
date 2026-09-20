# Azure Kostencheck: Verschwendungsbericht

> **Demo-Daten:** fiktive Subscription und Beispielpreise, keine echte Umgebung.

**Subscription:** `demo (Contoso)`  
**Datum:** 2026-09-20

## Ergebnis

Sie verlieren ca. **232,08 € pro Monat** (≈ 2.784,96 € pro Jahr) durch **6** ungenutzte Ressourcen.

## Gefundene Ressourcen

| # | Ressource | Problem | Ressourcengruppe | SKU | €/Monat | Empfehlung |
|---|---|---|---|---|---:|---|
| 1 | `build-agent-02` | VM gestoppt, aber nicht dealloziert | rg-test | Standard_D4s_v5 | 148,19 € | VM deallozieren (az vm deallocate) oder löschen, wenn sie nicht mehr gebraucht wird. |
| 2 | `erp-db-old-data` | Nicht angehängte Managed Disk | rg-legacy-erp | Premium_LRS (512 GB) | 67,58 € | Bei Bedarf Snapshot erstellen, dann Disk löschen. |
| 3 | `awf-stopped-vm` | VM gestoppt, aber nicht dealloziert | awf-waste-demo-rg | Standard_B1s | 8,18 € | VM deallozieren (az vm deallocate) oder löschen, wenn sie nicht mehr gebraucht wird. |
| 4 | `awf-orphaned-pip` | Ungenutzte öffentliche IP-Adresse | awf-waste-demo-rg | Standard | 3,36 € | Löschen, sofern die Adresse nicht bewusst reserviert bleiben muss. |
| 5 | `pip-old-gateway` | Ungenutzte öffentliche IP-Adresse | rg-web-old | Standard | 3,36 € | Löschen, sofern die Adresse nicht bewusst reserviert bleiben muss. |
| 6 | `awf-orphaned-disk` | Nicht angehängte Managed Disk | awf-waste-demo-rg | Standard_LRS (32 GB) | 1,41 € | Bei Bedarf Snapshot erstellen, dann Disk löschen. |

## Warum kostet das Geld?

- **Nicht angehängte Managed Disk:** Disks werden nach bereitgestellter Größe abgerechnet, auch wenn keine VM sie nutzt.
- **VM gestoppt, aber nicht dealloziert:** Im Zustand 'Stopped' bleibt die Hardware reserviert und die Rechenleistung wird weiter verrechnet.
- **Ungenutzte öffentliche IP-Adresse:** Standard-IPs werden pro Stunde verrechnet, auch ohne Zuordnung.

---

*Preise: Azure Retail Prices API (Listenpreise in EUR, 730 h/Monat). Tatsächliche Preise können durch Rabatte (EA/CSP, Reservierungen, Azure Hybrid Benefit) abweichen.*