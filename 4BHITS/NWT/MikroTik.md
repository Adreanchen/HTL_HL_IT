# MikroTik

## Zusammenfassung der verwendeten Befehle

| Befehl                                        | Zweck / Erklärung                                            |
| --------------------------------------------- | ------------------------------------------------------------ |
| `/system/reset-configuration no-defaults=yes` | **Router zurücksetzen:** Löscht die gesamte Konfiguration vollständig ohne Standard-Einstellungen. |
| `/export`                                     | **Konfiguration anzeigen:** Gibt die aktuell aktive Konfiguration im Terminal aus. |
| `/system reboot`                              | **Neustart:** Startet den Router neu (erforderlich nach Installation von Paketen oder Firmware-Updates). |
| `/system/routerboard/print`                   | **Firmware-Status:** Zeigt Details zum Routerboard sowie die aktuell installierte und verfügbare Bootloader-Firmware an. |
| `/system/routerboard/upgrade`                 | **Firmware aktualisieren:** Führt das Upgrade der Hardware-Firmware (Bootloader) durch. |
| `/system/package/update/check-for-updates`    | **Online-Update prüfen:** Prüft direkt online nach neuen Updates und lädt diese herunter *(setzt eine aktive Internetverbindung des Routers voraus)*. |