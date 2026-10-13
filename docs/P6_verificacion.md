# Acta de verificación — Fase P6

## Estado

- Rama: `fase-P6`.
- No se ha fusionado con `main`; queda pendiente de revisión manual.
- Los siete commits de alcance P6 están completados. Se añadió además un commit
  de seguimiento para corregir la configuración global de logging detectada por
  la suite completa.
- Los cambios locales ajenos a P6 se conservaron y no se incluyeron en esos
  commits.

## Commits P6

| Commit | Alcance |
| --- | --- |
| `3bc125a` | Privacidad de IA: no enviar nombres reales a Gemini. |
| `2044df3` | CRUD de itinerarios (RF-10). |
| `db4905c` | Subida y descarga de documentos (RF-17), con validación de extensión y firma, almacenamiento fuera de `static/` y control de propiedad. |
| `f1d2a2b` | Generación de vouchers PDF y estado de vencimiento documental. Si falla el PDF, la reserva no se bloquea y el voucher queda pendiente. |
| `5d0ad3e` | Notificaciones leídas por usuario y envío de correo configurable. |
| `390bc79` | Alertas automáticas, deduplicadas por entidad, tipo y fecha de ejecución; comando `flask alerts run` y scheduler desactivado por defecto. |
| `b2ebfe8` | Robustez de IA: timeout, reintentos, normalización de respuestas y auditoría de llamadas. |

## Seguimiento de logging

La ejecución completa de tests encontraba fallos solo en las aserciones de logs
de correo y voucher; las verificaciones de negocio pasaban. La causa era
`fileConfig()` en `migrations/env.py`, que por defecto desactivaba loggers
existentes. La ejecución de migraciones durante la suite ocurría antes de esas
pruebas y dejaba deshabilitado el logger Flask. Se corrigió pasando
`disable_existing_loggers=False`.

- Commit: `7eae424` — `fix: preserve application loggers during migrations`.
- Las pruebas de notificaciones y vouchers afectadas pasan juntas tras el fix.

## Verificación

Comando ejecutado:

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q
```

Resultado: **321 passed**, 5 warnings, en 107.01 s.

Los warnings corresponden a una deprecación de `google-genai` y al uso heredado
de `Query.get()` en pruebas preexistentes de P3; no impidieron la ejecución y
no se modificaron como parte de P6.

## Pendiente bloqueado

El enriquecimiento de IA con `app/analytics.py` queda fuera del cierre de estos
siete commits. No se implementó porque depende de que P5 se integre primero en
`main`. Reabrir ese trabajo después de integrar P5.
