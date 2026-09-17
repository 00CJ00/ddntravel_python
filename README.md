# DDN Travel — Versión Python (Flask)

Conversión a Python de la app generada originalmente en Google AI Studio
(React + TypeScript) para el proyecto académico **"Aplicación Inteligente
para la Gestión de Agencia de Viajes Turísticos"**.

Se buscó reproducir la app original lo más fielmente posible: mismo diseño
visual (tema oscuro "Deep Space" + tema claro), misma navegación, mismos
datos de demostración, mismas reglas de negocio (RN-01 a RN-05) y las
mismas 3 funciones de Inteligencia Artificial con Gemini (estadísticas
predictivas, recomendador inteligente y generador de itinerarios), ahora
usando **Python** en el backend en vez de TypeScript/Node.

## Arquitectura y estructura de la app

```
run.py                  # Punto de entrada: crea la app Flask y la inicia en el puerto 3000

app/
  __init__.py           # Fábrica create_app(): configura Flask, filtros Jinja2,
                        # carga blueprint routes.bp y carga datos de semilla
  models.py              # Clase base Entity y subclasses: Client, Booking,
                        # TourPackage, Hotel, Flight, PaymentTransaction,
                        # Promotion, AuditLog, TravelDocument, etc.
                        # - Entities carry id, to_dict(), update(), describe()
                        # - RN-01: TourPackage.has_availability(travelers) valida slots
                        # - RN-03: Booking usa initial_payment vs total_price para status
  store.py               # Singleton DataStore: estado en memoria + persistencia a
                        # app/state.json. Todas las mutaciones van por auto_save()
                        # que grava state.json después de cada operación.
                        # - Métodos clave: create_booking(), register_payment(),
                        #   apply_promo_code(), add_client(), update_client(), etc.
  ai_service.py          # Gemini (google-genai) con fallback de datos simulados
                        # si no hay GEMINI_API_KEY. 3 funciones:
                        #   get_predictive_analytics(), get_recommendations(),
                        #   get_itinerary()
  routes.py              # Todas las rutas Flask (auth, bookings, AI, billing,
                        # documents, audit, OAuth). Define blueprint "main".
  seed_data.json          # Datos iniciales de demo (portados del original).
  state.json              # Estado persistente del servidor: sobrevive reinicios.
                        # Borrar + reiniciar fuerza carga fresca de seed_data.json

templates/               # Plantillas Jinja2 HTML (dashboard, login, bookings,
                        # ai_predictive, client_portal, audit, payments, etc.)
static/
  css/styles.css         # Estilos complementarios (temas, tamaños de texto)
  js/app.js               # Modales, cálculo de precios en vivo, llamadas a API IA

## Instalación

```bash
cd ddn_python
pip install -r requirements.txt        # Flask, python-dotenv, google-genai,
                                         # flask-dance, reportlab
cp .env.example .env                     # Edita y coloca GEMINI_API_KEY (opcional)
# Opcional: configura GOOGLE_CLIENT_ID/SECRET en .env para login con Google
```

## Ejecutar

```bash
python run.py
```

La app estará disponible en **http://localhost:3000**.

## Configuración de IA (Gemini)

- **Sin GEMINI_API_KEY**: la app funciona completamente con datos simulados de
  alta fidelidad. Las 3 funciones IA (predicción, recomendaciones, itinerarios)
  retornan respuestas pre-definidas idénticas a la versión original cuando la IA
  no está disponible.

- **Con GEMINI_API_KEY**: coloca una clave válida en el archivo `.env` y la app
  usará Gemini real mediante el paquete `google-genai`.

Ejemplo `.env.example`:
```
GEMINI_API_KEY=pega_aqui_tu_clave
SECRET_KEY=genera_una_clave_aleatoria_larga
GOOGLE_CLIENT_ID=tu_client_id_de_google.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=tu_client_secret_de_google
```

## Usuarios de demostración

La app muestra una pantalla de login. La contraseña de las 3 cuentas demo es `ddn123`:

- **admin@ddntravel.com** — **Administrador**: acceso total, incluido módulo
  Auditoría (`/audit`), pagos (`/payments`), documentos (`/documents`),
  administración de destinos (`/admin/destinations`).

- **sofia.v@ddntravel.com** — **Agente / Empleado**: gestión del sistema sin
  acceso a auditoría. Puede ver/gestionar la mayoría de módulos pero no audit.

- **roberto.gomez@gmail.com** — **Cliente Viajero**: acceso al portal
  cliente-portal con catálogo, sus reservas propias y generación de itinerarios.

**Notas de rol:**
- El selector de perfil (cambiar de usuario) solo aparece para el Administrador
  y permite alternar entre Admin y Empleado.
- Clientes y empleados solo ven el botón de Cerrar Sesión.
- Permisos por ruta (`role_required` decorator en routes.py):
  - `admin`/`employee`: `/audit`, `/payments`, `/documents`, `/admin/destinations`,
    `/bookings`, `/clients`, `/hotels`, `/flights`, `/transports`, `/promotions`
  - `client`: `/client-portal` solo

## Inicio de sesión con Google (OAuth)

Opcional. Configurar en `.env`:
1. Crear OAuth Client ID (tipo "Web app") en Google Cloud Console.
2. URI de redirección autorizada: `http://localhost:3000/login/google/authorized`.
3. Agregar `GOOGLE_CLIENT_ID` y `GOOGLE_CLIENT_SECRET` al `.env`.
4. Reiniciar servidor (`python run.py`).

Cuando un usuario entra por primera vez con Google, se registra automáticamente
como **Cliente Viajero** (creando su perfil en el CRM). Sin credenciales, el
botón simplemente no se muestra y todo funciona con login/contraseña.

## Editar información de la cuenta

Los usuarios pueden actualizar su perfil (nombre, foto, teléfono, documento,
nacionalidad, etc.) a través de la interfaz de la aplicación. Los campos
disponibles para edición incluyen:

- **Nombre**: identificador principal del usuario
- **Teléfono**: número de contacto
- **Documento de identidad**: número de documento (RFC, pasaporte, etc.)
- **Nacionalidad**: país de origen
- **Categoría**: nivel de cliente (Estándar, Premium, etc.)
- **Presupuesto preferido**: límite de gasto aproximado
- **Fecha de vencimiento de pasaporte**: para viajes internacionales
- **Destinos preferidos**: lista de destinos favoritos
- **Notas**: información adicional sobre el cliente

### Para administradores:

Puede actualizar la información de cualquier cliente desde el panel de
administración (`/clients`), utilizando el método `update_client` del DataStore,
que persiste los cambios automáticamente en `app/state.json`.

### Para clientes (portal):

Los clientes pueden modificar sus datos personales desde la sección de
configuración de su portal (`/client-portal`). Los cambios se guardan y
quedan registrados en el historial de la agencia.

Los cambios en la información de perfil se reflejan al instante en todos
los módulos de la aplicación y quedan auditados en el módulo de Auditoría
(RN-05) para el rol de administrador.

## Inicio de sesión con Google (OAuth)

Opcional. Configurar en `.env`:
1. Crear OAuth Client ID (tipo "Web app") en Google Cloud Console.
2. URI de redirección autorizada: `http://localhost:3000/login/google/authorized`.
3. Agregar `GOOGLE_CLIENT_ID` y `GOOGLE_CLIENT_SECRET` al `.env`.
4. Reiniciar servidor (`python run.py`).

Cuando un usuario entra por primera vez con Google, se registra automáticamente
como **Cliente Viajero** (creando su perfil en el CRM). Sin credenciales, el
botón simplemente no se muestra y todo funciona con login/contraseña.

## Persistencia de datos

- `app/state.json`: se actualiza después de cada operación significativa. Los
  datos **sobreviven al reinicio del servidor**.
- Para volver al estado inicial: usar "Restablecer Datos Iniciales" en la UI,
  o borrar `app/state.json` y reiniciar.
- Las reservas validan disponibilidad (RN-01), exigen cliente asociado (RN-02)
  y calculan estado de pago (RN-03) igual que la versión original.
- El módulo de Auditoría (RN-05) registra todas las acciones relevantes; visible
  solo para el rol Administrador.

## Ejecutar los tests

```bash
python -m pytest tests -v
```

Cubren:
- Reglas de negocio RN-01 a RN-03 (disponibilidad, cliente obligatorio, cálculo de pago)
- Persistencia de datos
- Flujo de login y permisos por rol
- Pruebas de aislamiento: cada test fixture reemplaza `STATE_PATH` con `tmp_path`,
  nunca se modifica el `state.json` real