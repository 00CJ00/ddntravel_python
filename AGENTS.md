# AGENTS.md — DDN Travel (Python)

## Quickstart

| Command | Description |
|---|---|
| `python run.py` | Start dev server at http://localhost:3000 |
| `pip install -r requirements.txt` | Install deps (Flask, python-dotenv, google-genai, flask-dance, reportlab) |
| `cp .env.example .env` | Copy env template; edit GEMINI_API_KEY (optional — app works with simulated data) |
| `python -m pytest tests -v` | Run all tests (RN-01 to RN-03, web layer, persistence) |

## Architecture

- **Entry point**: `run.py` — creates Flask app via `create_app()` and starts server on port 3000
- **App factory**: `app/__init__.py` — creates Flask app, registers blueprint `routes.bp`
- **Data store**: `app/store.py` — singleton `DataStore` with in-memory state + persistence to `app/state.json`
- **Entity model**: `app/models.py` — base class `Entity`; subclasses: `Client`, `Booking`, `TourPackage`, `PaymentTransaction`, etc.
- **AI service**: `app/ai_service.py` — Gemini (`google-genai`) with fallback simulated responses if key unavailable
- **Routes**: `app/routes.py` — all Flask endpoints (auth, bookings, AI, billing, documents, audit)
- **Seed data**: `app/seed_data.json` — initial data loaded on `DataStore` init
- **State persistence**: `app/state.json` — survives server restarts; delete to force fresh load

## Developer workflow

1. **Make code changes** — `auto_save` decorator in `store.py` persists to `state.json` after every mutating operation
2. **Test changes** — `python -m pytest tests -v`; tests use `tmp_path` for isolated `state.json`
3. **Reset data** — use "Restablecer Datos Iniciales" in UI, or delete `app/state.json` and restart
4. **AI functions** — set `GEMINI_API_KEY` in `.env` for real Gemini; otherwise fallback simulated data is used

## High-signal facts (don't guess)

- **RN-01**: `TourPackage.has_availability(travelers)` — check `available_slots >= travelers` before booking
- **RN-02**: `create_booking` requires `client_id` and `client_name` — returns error with "RN-02" if missing
- **RN-03**: Payment `initial_payment` vs `total_price` determines `payment_status` (Pagado/Parcial/Pendiente) and `status` (Confirmada/Pendiente)
- **Auto-save**: `DataStore.auto_save` wrapper persists after every mutating method — no manual `persist()` calls needed
- **State file**: `app/state.json` — delete + restart to reset to seed data; data survives normal restarts
- **User roles**: `admin`/`employee` access `/audit`, `/payments`, `/documents`, `/admin/destinations`; `client` accesses `/client-portal` only
- **Google OAuth**: optional — set `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` in `.env`; otherwise button hidden
- **AI fallback**: all 3 AI functions (`get_predictive_analytics`, `get_recommendations`, `get_itinerary`) return high-fidelity simulated data if Gemini not configured
- **Test isolation**: each test fixture replaces `STATE_PATH` with `tmp_path` — never modify the real `state.json` in tests
- **Health endpoint**: `GET /api/health` returns `{"status":"ok","app":"DDN Travel Server (Python)"}`
- **Promo code**: `store.apply_promo_code(code, total_price)` — strips/uppercases code, checks `active` and `current_uses < max_uses`
- **NCF generation**: automatic on payment register if not yet generated; uses `generar_ncf` from `billing.py`
- **OAuth callback URI**: must be `http://localhost:3000/login/google/authorized` if configuring Google Cloud credentials