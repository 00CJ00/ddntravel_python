# P1 — Acta de cierre: Seguridad de rutas

> Evidencia de la fase P1 (permisos, CSRF, rate limiting, propiedad de datos).
> Todos los datos de este documento son reproducibles con los comandos de la
> sección final. Fase cerrada el 2026-10-01 sobre `main`.
>
> Commit de cierre: `da9dffd` (merge de `fase-P1`).

## 1. Veredicto

| Comprobación | Resultado |
|---|---|
| Suite automática | **170 passed, 0 skipped** |
| Cobertura de la matriz ruta × rol | 22 pruebas (200/302/403, nunca 500) |
| Prueba de humo end-to-end (servidor real) | **0 fallos** en 102 peticiones |
| Respuestas 5xx en el humo | **0** |
| Tracebacks en el log del servidor | **0** |
| Fugas de datos de otros clientes | ninguna detectada |
| Estado del árbol al cerrar | limpio y sincronizado con `origin/main` |

## 2. Commits que componen la fase

| Commit | Paso |
|---|---|
| `e18d42d` | 0 — Flask-WTF, Flask-Limiter y fixtures de test |
| `5171e92` | 1 — matriz de permisos como fuente única de verdad |
| `c58afbf` | 2 — CSRF, rate limiting, cookies seguras y global `can()` |
| `ef31246` | 3 — permisos en todas las rutas; `/switch-user` eliminado; `/reset` protegido |
| `64df57f` | 4 — propiedad de datos (IDOR), perfil por cliente, 501 explícito en facturación |
| `65f7c69` | 5 — `StoreView` filtra el store por rol y propiedad |
| `16f7a6d` | 6 — token CSRF en todos los formularios y botones con `can()` |
| `df5833a` | 7 — `X-CSRFToken` en `fetch`, `DDN_PERMS` y 400 explícito |
| `6371d60` | 8 — rate limits por endpoint, límites de entrada, chat por palabras |
| `4a8417d` | 9 — matriz HTTP ruta × rol y verificación de permisos declarados |
| `e0c7557` | Fijación de test: la reserva Pendiente se crea en el propio test |
| `fe9f714` | Fijación de test: setups explícitos en facturación |
| `da9dffd` | Merge de `fase-P1` en `main` |

## 3. Pruebas automáticas

```
.\.venv\Scripts\python.exe -m pytest -q     ->  170 passed, 1 warning
```

| Archivo | Pruebas | Cubre |
|---|---:|---|
| `tests/test_permissions.py` | 53 | matriz por rol, `owns`, rutas mutantes sin permiso, endpoints huérfanos |
| `tests/test_matriz_http.py` | 22 | ruta × rol por HTTP, nunca 500, sin sesión, `/api/*` |
| `tests/test_idor.py` | 21 | propiedad de reservas, pagos y documentos |
| `tests/test_ratelimit.py` | 20 | 429 por endpoint, límites de entrada, cookies, anti-enumeración |
| `tests/test_store_view.py` | 13 | fugas en HTML y en `DDN_DATA` |
| `tests/test_templates_csrf.py` | 12 | todo `<form method="post">` con token; botones por `can()` |
| `tests/test_csrf_client.py` | 7 | `X-CSRFToken` en `fetch`; 400 explícito |
| `tests/test_app.py` | 10 | base heredada de P0 |
| `tests/test_store.py` | 8 | base heredada de P0 |
| `tests/test_seed_encoding.py` | 4 | codificación de la semilla (P0) |
| **Total** | **170** | 0 omitidas |

## 4. Matriz de permisos verificada por HTTP

Resultado real del humo (rutas GET, sesión por rol):

| Ruta | admin | employee | client |
|---|:---:|:---:|:---:|
| `/dashboard` | 200 | 200 | 403 |
| `/clients` | 200 | 200 | 403 |
| `/bookings` | 200 | 200 | 403 |
| `/payments` | 200 | 200 | 403 |
| `/promotions` | 200 | 200 | 403 |
| `/documents` | 200 | 200 | 200 |
| `/destinations` | 200 | 200 | 200 |
| `/packages` | 200 | 200 | 200 |
| `/hotels` | 200 | 200 | 403 |
| `/flights` | 200 | 200 | 403 |
| `/transports` | 200 | 200 | 403 |
| `/activities` | 200 | 200 | 200 |
| `/ai-predictive` | 200 | 200 | 200 |
| `/edit-profile` | 200 | 200 | 200 |
| `/client-portal` | 403 | 403 | 200 |

- Visitar `/dashboard` es exclusivo del personal; el portal es exclusivo del cliente.
- El cliente nunca recibe 500: obtiene 403 donde no tiene permiso.

## 5. Controles verificados en el humo

| Control | Evidencia |
|---|---|
| Salud | `/api/health` → 200 con `{"status":"ok","app":"DDN Travel Server (Python)"}` |
| Login | los 3 roles entran con la clave demo; credencial inválida rechazada |
| CSRF | `POST` sin token → **400** (no 302 silencioso) |
| Flujo de reserva | cliente crea reserva → aparece en el portal → cancela → queda **Cancelada** |
| Escritura por rol | cliente no cambia estados (403); employee no elimina documentos (403) |
| Fugas HTML | el cliente no ve ningún email ajeno en sus 7 páginas |
| Fugas `DDN_DATA` | el cliente recibe **solo su propio registro**; `hotels=0` y `flights=0` |
| `DDN_PERMS` | cliente: `clients:create=False`, `clients:delete=False`, `bookings:status=False`, `audit:view=False`, `data:reset=False` |
| Estáticos | `styles.css` (8 417 B) y `app.js` (23 132 B) → 200 |
| Rate limit | 8 intentos de login fallidos → aparece **429** |

## 6. Hallazgos corregidos durante la fase

Bugs reales encontrados y resueltos antes del cierre:

1. **`/contacto` con visitante anónimo devolvía 500.** `templates/base.html` asumía
   sesión. Se añadió un encabezado anónimo y se protegió el layout del sidebar.
2. **Escalada de privilegios por `/switch-user`.** Ruta eliminada por completo;
   `test_matriz_http.py` comprueba que ya no existe.
3. **`/reset` accesible sin control.** Ahora exige rol admin, `ENABLE_RESET=1` y
   confirmación explícita.
4. **El rate limit de login consumía cuota también en `GET`.** El formulario se
   bloqueaba legítimamente; se limitó a `POST`.
5. **Coincidencia por subcadena en el chat.** `"hi"` coincidía dentro de
   `"which"`; ahora se compara por palabras completas.
6. **`POST /contacto` sin `message` lanzaba `TypeError.`** Se valida el campo y
   se aplica longitud máxima.
7. **Facturación rota llamaba a métodos inexistentes** (`store.get_payment`,
   `store.state`, `store.persist`). Se devuelve **501** tras comprobar permiso y
   propiedad, dejando el trabajo real para P4.
8. **CSRF fallaba con 302 hacia el login**, ocultando el ataque; ahora es 400.
9. **Tests dependientes de la semilla.** Se crearon reservas y pagos dentro de
   los propios tests (`e0c7557`, `fe9f714`); hoy no hay ningún `pytest.skip`.

## 7. Deuda trasladada a fases siguientes

| Pendiente | Fase | Detalle |
|---|---|---|
| `store.delete_document` aún acepta empleados (la ruta ya es solo admin) | P3 | coherencia en el store |
| Factura PDF/`ncf` devuelven 501; `app/billing.py` conserva referencias a `state.json` (líneas 64, 239) | P4 | NCF secuencial y PDF reales |
| `app/store.py:24` mantiene `STATE_PATH = state.json` | P2 | migración a SQLAlchemy + Alembic |
| Prompts de IA podrían exponer nombres reales | P6 | anonimizar antes de Gemini |
| `window.DDN_DATA` sigue existiendo (ya filtrado) | P7 | eliminarlo y usar `/api/lookup` |

## 8. Nota sobre ngrok

La verificación por túnel público no pudo realizarse: la cuenta del token tiene
el dominio reservado `citrus-pretzel-comic.ngrok-free.dev` **en uso por otra
sesión activa** (`ERR_NGROK_334`). El plan Free no permite subdominios propios
(`ERR_NGROK_313`) ni libera el dominio con `--pooling-enabled`. La validación
local sustituye a la remota y cubre los mismos flujos por HTTP.

## 9. Cómo reproducir la verificación

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe run.py       # servidor real en http://127.0.0.1:3000
# en otra terminal:
Invoke-WebRequest http://127.0.0.1:3000/api/health
```

Credenciales demo (README): `admin@ddntravel.com`, `sofia.v@ddntravel.com`,
`roberto.gomez@gmail.com` — clave `ddn123`.
