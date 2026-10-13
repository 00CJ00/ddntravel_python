"""
Servicio de Inteligencia Artificial de DDN Travel.

Es el equivalente en Python de la lógica que en el proyecto original vivía en
`server.ts`, usando el SDK oficial de Google (`google-genai`, el mismo que
`@google/genai` en la versión de TypeScript). Genera:

  1. Estadísticas predictivas de comportamiento de compra.
  2. Recomendaciones inteligentes de paquetes según el perfil del cliente.
  3. Itinerarios de viaje personalizados día a día.

Si la API de Gemini no está configurada, se satura, o falla por cualquier
motivo, cada función retorna una respuesta simulada de alta fidelidad (igual
que hacía el código original) para que la demo nunca se quede "rota".
"""
from __future__ import annotations
import concurrent.futures
import os
import json
import time

try:
    from google import genai
    from google.genai import types as genai_types
except ImportError:  # el paquete es opcional hasta que se instale
    genai = None
    genai_types = None

MODELS_TO_TRY = ["gemini-3.8-flash", "gemini-flash-latest", "gemini-3.1-flash-lite"]

# Tiempo máximo por llamada al proveedor y reintentos solo ante fallos
# transitorios (red, timeout, 429/503). Acotado: como máximo 2 intentos por
# modelo y sin espera entre modelos distintos.
AI_TIMEOUT_SECONDS = 20
AI_MAX_ATTEMPTS_PER_MODEL = 2
AI_RETRY_SLEEP_SECONDS = 0.8

# Metadatos de la última llamada (para auditoría sin PII). Se actualizan en
# cada invocación a `generate_gemini_json`.
last_provider: str = "fallback"
last_used_model: str | None = None

_client = None


def _get_client():
    """Inicializa (una sola vez) el cliente de Gemini de forma perezosa."""
    global _client
    if _client is not None:
        return _client
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key or genai is None:
        raise RuntimeError("GEMINI_API_KEY no está configurada o falta el paquete google-genai")
    _client = genai.Client(api_key=api_key)
    return _client


def _transient_failure(message: str) -> bool:
    """Indica si el error parece transitorio (reintentable una vez)."""
    lowered = (message or "").lower()
    return ("timeout" in lowered or "timed out" in lowered
            or any(code in message for code in
                   ["503", "429", "UNAVAILABLE", "quota", "high demand",
                    "temporarily", "try again", "overloaded"]))


def _call_with_timeout(client, model: str, prompt: str, timeout: float):
    """Una llamada al proveedor con límite de tiempo.

    La firma de `generate_content` se conserva intacta (tests y SDK).
    Lanza `TimeoutError` si excede el límite; el hilo huérfano se abandona
    sin bloquear la petición.
    """
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        future = executor.submit(
            client.models.generate_content,
            model=model,
            contents=prompt,
            config=genai_types.GenerateContentConfig(response_mime_type="application/json"),
        )
        return future.result(timeout=timeout)
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


def generate_gemini_json(prompt: str, fallback_fn, *, schema=None,
                         timeout: float = AI_TIMEOUT_SECONDS):
    """
    Llama a Gemini pidiendo una respuesta JSON, con timeout, reintentos
    acotados solo ante fallos transitorios y validación opcional de esquema.
    Si todo falla (o la respuesta no cumple el esquema), devuelve el
    resultado de `fallback_fn()`. Nunca lanza por causas del proveedor.
    """
    global last_provider, last_used_model
    last_provider, last_used_model = "fallback", None
    last_error = None
    try:
        client = _get_client()
        for model in MODELS_TO_TRY:
            for attempt in range(AI_MAX_ATTEMPTS_PER_MODEL):
                try:
                    response = _call_with_timeout(client, model, prompt, timeout)
                    if response.text:
                        parsed = json.loads(response.text)
                        if schema is not None:
                            cleaned = schema(parsed)
                            if cleaned is None:
                                last_error = ValueError("respuesta fuera de esquema")
                                break  # probar con el siguiente modelo
                            parsed = cleaned
                        last_provider, last_used_model = "gemini", model
                        return parsed
                    break
                except Exception as err:  # noqa: BLE001
                    last_error = err
                    if _transient_failure(str(err)) \
                            and attempt + 1 < AI_MAX_ATTEMPTS_PER_MODEL:
                        time.sleep(AI_RETRY_SLEEP_SECONDS)
                        continue
                    break
    except Exception as err:  # noqa: BLE001
        last_error = err

    print(f"[ai_service] Gemini no disponible, usando generador de respaldo: {last_error}")
    return fallback_fn()


# ----------------------------------------------------------------------
# Privacidad y esquemas de salida (fase P6, RF-20)
# ----------------------------------------------------------------------
def anonymize_clients(clients: list, limit: int = 10) -> list:
    """Resume clientes con alias (`Cliente A`) en vez de datos personales.

    Nunca incluye nombres, emails, documentos, teléfonos ni pasaportes: solo
    alias, categoría, presupuesto y conteos agregados.
    """
    summary = []
    for i, client in enumerate(clients[:limit]):
        alias = f"Cliente {chr(ord('A') + (i % 26))}"
        summary.append({
            "alias": alias,
            "category": getattr(client, "category", "") or "",
            "budget": getattr(client, "budget_preference", "") or "",
            "tripsCount": int(getattr(client, "trips_count", 0) or 0),
            "preferredDestinations":
                list(getattr(client, "preferred_destinations", []) or []),
        })
    return summary


def sanitize_profile(profile: dict) -> dict:
    """Perfil mínimo para recomendaciones: alias + categoría + presupuesto.

    Descarta nombres, emails, documentos, teléfonos y cualquier otra clave
    identificativa que envíe el frontend.
    """
    profile = profile if isinstance(profile, dict) else {}
    return {
        "alias": "Cliente interesado",
        "category": str(profile.get("category", "") or ""),
        "budget_preference": str(profile.get("budget_preference", "")
                                 or profile.get("budget", "") or ""),
    }


def aggregate_signals(clients: list, bookings: list) -> dict:
    """Agregados no identificativos para enriquecer recomendaciones.

    Vive aquí (y no en `app/analytics.py`, de P5) para no invadir esa fase:
    clientes frecuentes (≥ 3 viajes), top destinos y meses de temporada alta.
    """
    from collections import Counter
    frequent = sum(1 for c in clients if (getattr(c, "trips_count", 0) or 0) >= 3)
    top_destinations = [name for name, _ in Counter(
        (getattr(b, "destination_name", "") or "") for b in bookings
        if getattr(b, "destination_name", "")).most_common(5)]
    months = Counter()
    for booking in bookings:
        created = getattr(booking, "created_at", None)
        month = getattr(created, "month", None)
        if month:
            months[month] += 1
    average = (sum(months.values()) / 12) if months else 0
    high_season = sorted(m for m, n in months.items() if average and n > 1.25 * average)
    return {"frequent_clients": frequent, "top_destinations": top_destinations,
            "high_season_months": high_season}


def _clamp_number(value, minimum=None, maximum=None, default=0):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if minimum is not None:
        number = max(minimum, number)
    if maximum is not None:
        number = min(maximum, number)
    return number


def validate_predictive(data) -> dict | None:
    """Esquema del análisis predictivo. `None` = usar respaldo."""
    if not isinstance(data, dict):
        return None
    summary = data.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        return None
    if not isinstance(data.get("purchasePropensityIndex"), (int, float)):
        return None
    if not isinstance(data.get("nextQuarterForecastRevenue"), (int, float)):
        return None
    cleaned = {
        "summary": summary.strip(),
        "purchasePropensityIndex": int(_clamp_number(
            data.get("purchasePropensityIndex"), 0, 100, 0)),
        "nextQuarterForecastRevenue": _clamp_number(
            data.get("nextQuarterForecastRevenue"), 0, None, 0),
        "growthRateProjected": _clamp_number(data.get("growthRateProjected"), None, None, 0),
        "customerSegmentsBehavior": data.get("customerSegmentsBehavior", []) or [],
        "topPredictedDestinations": data.get("topPredictedDestinations", []) or [],
        "seasonalityAlerts": data.get("seasonalityAlerts", []) or [],
        "churnPreventionInsights": data.get("churnPreventionInsights", []) or [],
        "strategicRecommendations": data.get("strategicRecommendations", []) or [],
    }
    for key in ("customerSegmentsBehavior", "topPredictedDestinations",
                "seasonalityAlerts", "churnPreventionInsights",
                "strategicRecommendations"):
        if not isinstance(cleaned[key], list):
            cleaned[key] = []
    return cleaned


def validate_recommendations(data) -> dict | None:
    """Esquema de recomendaciones. `None` = usar respaldo."""
    if not isinstance(data, dict):
        return None
    packages = data.get("recommendedPackages", [])
    if not isinstance(packages, list) or not packages:
        return None
    clean_packages = []
    for package in packages:
        if not isinstance(package, dict):
            continue
        title = package.get("title")
        if not isinstance(title, str) or not title.strip():
            continue
        clean_packages.append({
            "title": title.strip(),
            "destination": str(package.get("destination", "") or ""),
            "estimatedPricePerPerson": _clamp_number(
                package.get("estimatedPricePerPerson", 0), 0, None, 0),
            "matchReason": str(package.get("matchReason", "") or ""),
            "highlights": [h for h in (package.get("highlights", []) or [])
                           if isinstance(h, str)],
            "recommendedDuration": str(package.get("recommendedDuration", "") or ""),
            "bestSeason": str(package.get("bestSeason", "") or ""),
        })
    if not clean_packages:
        return None
    tips = data.get("smartTips", [])
    return {
        "affinityScore": int(_clamp_number(data.get("affinityScore", 0), 0, 100, 0)),
        "profileSummary": str(data.get("profileSummary", "") or ""),
        "recommendedPackages": clean_packages,
        "smartTips": [t for t in tips if isinstance(t, str)] if isinstance(tips, list) else [],
    }


def validate_itinerary_result(data) -> dict | None:
    """Esquema del itinerario generado (reutiliza el validador RF-10)."""
    from .validators import validate_itinerary_content
    cleaned, errors = validate_itinerary_content(data)
    return cleaned if not errors else None


# ----------------------------------------------------------------------
# 1. Estadísticas predictivas de comportamiento de compra (RF-20)
# ----------------------------------------------------------------------
def get_predictive_analytics(clients: list, bookings: list, packages: list, timeframe: str) -> dict:
    # Privacidad P6: al proveedor solo viajan alias y agregados, nunca
    # nombres, emails, documentos ni pasaportes.
    clients_summary = anonymize_clients(clients)
    bookings_summary = [
        {"destination": b.destination_name, "total": float(b.total_price or 0), "status": b.status,
         "travelerCount": b.travelers}
        for b in bookings[:12]
    ]

    prompt = f"""
Eres el motor de Inteligencia Artificial Predictiva de "DDN TRAVEL", una agencia de viajes turísticos de alta gama.
Analiza la siguiente data real de clientes, reservas, destinos y ventas para generar estadísticas predictivas sobre el comportamiento de compra de los usuarios.

Data disponible:
- Cantidad de clientes registrados: {len(clients)}
- Cantidad de reservas históricas y actuales: {len(bookings)}
- Catálogo de paquetes: {len(packages)}
- Periodo seleccionado: {timeframe}
- Resumen de clientes: {json.dumps(clients_summary, ensure_ascii=False)}
- Resumen de reservas: {json.dumps(bookings_summary, ensure_ascii=False)}

Tu respuesta debe ser un análisis estadístico predictivo exhaustivo y accionable en formato JSON con la siguiente estructura:
{{
  "summary": "Resumen ejecutivo del comportamiento y tendencias de compra proyectadas",
  "purchasePropensityIndex": 84,
  "nextQuarterForecastRevenue": 142500,
  "growthRateProjected": 18.5,
  "customerSegmentsBehavior": [
    {{"segment": "Viajeros de Lujo / VIP", "propensityScore": 92, "avgTicketProjected": 4200,
      "preferredSeason": "Julio - Agosto / Diciembre", "expectedLeadTimeDays": 45,
      "riskOfChurn": "Bajo (8%)", "recommendedAction": "Campaña de venta cruzada con resorts 5 estrellas"}}
  ],
  "topPredictedDestinations": [
    {{"destination": "Cancún & Riviera Maya", "demandProbability": 94, "estimatedBookings": 38,
      "recommendedPricingStrategy": "Incrementar tarifa 8% en temporada alta", "keyDrivers": "Playas y hoteles all-inclusive"}}
  ],
  "seasonalityAlerts": [
    {{"period": "Próximas 4 a 8 semanas", "impact": "Alta", "description": "Pico de búsquedas de playa",
      "tacticalAdvice": "Asegurar bloqueos de asientos con antelación"}}
  ],
  "churnPreventionInsights": ["Insight de retención 1", "Insight de retención 2"],
  "strategicRecommendations": ["Recomendación estratégica 1", "Recomendación estratégica 2"]
}}
"""

    total_booked_value = float(sum((b.total_price or 0) for b in bookings))

    def fallback():
        return {
            "summary": (f"Basado en el análisis de {len(clients)} clientes y {len(bookings)} reservas registradas, "
                        "la propensión de compra global se sitúa en un rango muy alto (86/100). Se proyecta un "
                        "repunte del 24% en destinos de sol y playa (Punta Cana y Cancún) impulsado por viajeros "
                        "VIP y turismo familiar."),
            "purchasePropensityIndex": 86,
            "nextQuarterForecastRevenue": 135000 + total_booked_value * 1.5,
            "growthRateProjected": 21.4,
            "customerSegmentsBehavior": [
                {"segment": "Viajeros de Lujo / VIP", "propensityScore": 94, "avgTicketProjected": 4150,
                 "preferredSeason": "Diciembre a Marzo / Julio a Agosto", "expectedLeadTimeDays": 45,
                 "riskOfChurn": "Bajo (6%)",
                 "recommendedAction": "Campañas de preventa con upgrades a suites presidenciales y traslados privados."},
                {"segment": "Familias Vacacionales", "propensityScore": 82, "avgTicketProjected": 2850,
                 "preferredSeason": "Vacaciones de verano (Junio a Agosto)", "expectedLeadTimeDays": 55,
                 "riskOfChurn": "Medio (18%)",
                 "recommendedAction": "Paquetes todo incluido con actividades infantiles y facilidades de pago diferido."},
                {"segment": "Aventureros & Ecoturismo", "propensityScore": 88, "avgTicketProjected": 1650,
                 "preferredSeason": "Temporada Seca (Mayo a Octubre)", "expectedLeadTimeDays": 22,
                 "riskOfChurn": "Bajo (10%)",
                 "recommendedAction": "Lanzar promociones de aventura en Cusco, senderismo y ecoparques."},
            ],
            "topPredictedDestinations": [
                {"destination": "Punta Cana & Bávaro", "demandProbability": 95, "estimatedBookings": 42,
                 "recommendedPricingStrategy": "Aumentar tarifa base en fines de semana largos (+8%)",
                 "keyDrivers": "Alta fidelidad de clientes VIP y paquetes All-Inclusive de lujo."},
                {"destination": "Cancún & Riviera Maya", "demandProbability": 92, "estimatedBookings": 37,
                 "recommendedPricingStrategy": "Mantener tarifa con tours de cortesía a cenotes y parques",
                 "keyDrivers": "Atracciones arqueológicas mayas y conectividad aérea frecuente."},
                {"destination": "Cusco & Machu Picchu", "demandProbability": 85, "estimatedBookings": 28,
                 "recommendedPricingStrategy": "Preventa con cupos limitados en trenes panorámicos",
                 "keyDrivers": "Alta demanda en turismo cultural y de aventura de alto ticket."},
                {"destination": "Madrid & París Clásico", "demandProbability": 79, "estimatedBookings": 21,
                 "recommendedPricingStrategy": "Paquetes multidestino con seguro internacional incluido",
                 "keyDrivers": "Interés sostenido en circuitos de primavera y verano en Europa."},
            ],
            "seasonalityAlerts": [
                {"period": "Próximas 4 a 8 semanas", "impact": "Alta",
                 "description": "Pico de búsquedas para paquetes de playa y escapadas caribeñas.",
                 "tacticalAdvice": "Asegurar bloqueos de habitaciones y asientos aéreos con 30 días de antelación."},
                {"period": "Trimestre posterior", "impact": "Media",
                 "description": "Apertura de preventa para rutas europeas y ecoturismo.",
                 "tacticalAdvice": "Activar código promocional preventa con 10% de descuento."},
            ],
            "churnPreventionInsights": [
                "Clientes sin compras en más de 75 días responden positivamente (42% conversión) a cupones "
                "personalizados del 15%.",
                "El 72% de los clientes VIP recomiendan la agencia tras recibir asistencia 24/7 y chofer privado.",
            ],
            "strategicRecommendations": [
                "Automatizar recordatorios de fecha límite de pago para incrementar tasa de conversión en un 14%.",
                "Ofrecer seguros de viaje integrados en el checkout para aumentar el ticket promedio en $120 por pasajero.",
                "Desplegar campañas directas por WhatsApp a clientes VIP con destinos exclusivos antes de abrir cupos generales.",
            ],
        }

    return generate_gemini_json(prompt, fallback, schema=validate_predictive)


# ----------------------------------------------------------------------
# 2. Recomendaciones inteligentes de paquetes (RF-20)
# ----------------------------------------------------------------------
def get_recommendations(client_profile: dict, budget: float, travel_style: str,
                         travelers_count: int, interests: str, context: dict | None = None) -> dict:
    # Privacidad P6: el perfil se reduce a alias/categoría/presupuesto antes
    # de construir el prompt; el dict original nunca sale del servidor.
    profile = sanitize_profile(client_profile)
    signals = context or {}
    prompt = f"""
Actúa como el motor de recomendación inteligente de DDN TRAVEL.
Recomienda los mejores paquetes y destinos personalizados para el siguiente perfil de viajero:

Perfil:
- Viajero: {profile['alias']} (categoría {profile['category'] or 'general'})
- Presupuesto aproximado: ${budget or 2000} USD
- Estilo de viaje: {travel_style or 'Playa y Relajación'}
- Número de viajeros: {travelers_count or 2}
- Intereses específicos: {interests or 'Gastronomía, tours culturales, descanso, hoteles de 4 o 5 estrellas'}
- Señales agregadas de la agencia: {json.dumps(signals, ensure_ascii=False) or 'sin datos suficientes'}

Devuelve un JSON estructurado con:
{{
  "affinityScore": 96,
  "profileSummary": "Análisis rápido del perfil y qué busca",
  "recommendedPackages": [
    {{"title": "Nombre del Paquete Recomendado", "destination": "Ciudad, País", "estimatedPricePerPerson": 1250,
      "matchReason": "Por qué se adapta exactamente a su presupuesto y estilo",
      "highlights": ["Punto 1", "Punto 2", "Punto 3"], "recommendedDuration": "5 Días / 4 Noches",
      "bestSeason": "Noviembre a Abril"}}
  ],
  "smartTips": ["Consejo inteligente 1", "Consejo inteligente 2"]
}}
"""

    def fallback():
        b = budget or 2500
        tips = [
            "Reservar con al menos 3 semanas de antelación permite asegurar habitaciones con vista directa al "
            "mar sin costo adicional.",
            "Incluir traslados privados desde el momento de la cotización optimiza el tiempo y evita esperas "
            "en terminales aéreas.",
        ]
        if signals.get("top_destinations"):
            tips.append("Destinos con más demanda ahora mismo: "
                        + ", ".join(signals["top_destinations"][:3]) + ".")
        return {
            "affinityScore": 96,
            "profileSummary": (f"Perfil de alto valor ({profile['alias']}). "
                                f"Con un presupuesto de ${b} USD y estilo enfocado en "
                                f"{travel_style or 'Playa y Relajación'}, la selección prioriza experiencias de "
                                "lujo y servicio exclusivo."),
            "recommendedPackages": [
                {"title": "Punta Cana Royal Luxury All-Inclusive", "destination": "Punta Cana, República Dominicana",
                 "estimatedPricePerPerson": round(b * 0.48),
                 "matchReason": "Se adapta perfectamente al estilo de relax en resort 5 estrellas con mayordomo y "
                                "catamarán privado a Isla Saona.",
                 "highlights": ["Resort All-Inclusive frente al mar", "Excursión privada en catamarán",
                                "Traslado VIP Aeropuerto"],
                 "recommendedDuration": "5 Días / 4 Noches", "bestSeason": "Diciembre a Mayo"},
                {"title": "Cancún & Joyas Mayas Inolvidable", "destination": "Cancún & Riviera Maya, México",
                 "estimatedPricePerPerson": round(b * 0.52),
                 "matchReason": "Combina hermosas playas turquesa con gastronomía mexicana de autor y accesos VIP a "
                                "parques temáticos.",
                 "highlights": ["Entradas preferenciales", "Cenotes sagrados y Chichén Itzá", "Hotelería 5 estrellas"],
                 "recommendedDuration": "6 Días / 5 Noches", "bestSeason": "Noviembre a Abril"},
            ],
            "smartTips": tips,
        }

    return generate_gemini_json(prompt, fallback, schema=validate_recommendations)


# ----------------------------------------------------------------------
# 3. Generador de itinerarios personalizados (RF-20)
# ----------------------------------------------------------------------
def get_itinerary(destination: str, days: int, travelers: int, travel_type: str,
                   pace: str, notes: str) -> dict:
    prompt = f"""
Genera un itinerario turístico detallado, profesional y optimizado para la agencia DDN TRAVEL.

Parámetros:
- Destino: {destination or 'Punta Cana'}
- Duración: {days or 4} días
- Viajeros: {travelers or 2}
- Tipo de viaje: {travel_type or 'Pareja / Vacaciones'}
- Ritmo deseado: {pace or 'Equilibrado (cultura + descanso)'}
- Notas extra: {notes or 'Ninguna'}

Devuelve un JSON con:
{{
  "destination": "{destination or 'Punta Cana'}",
  "overview": "Introducción atractiva del itinerario",
  "weatherAdvice": "Consejo sobre el clima y qué empacar",
  "days": [
    {{"dayNumber": 1, "title": "Llegada y bienvenida al paraíso",
      "morning": "Recepción en el aeropuerto...", "afternoon": "Tarde libre...",
      "evening": "Cena de bienvenida...", "transportIncluded": "Traslado privado Aeropuerto - Hotel",
      "mealPlan": "Cena incluida"}}
  ],
  "includedPerks": ["Asistencia 24/7 DDN Travel", "Seguro de viaje básico", "Guía local certificado"],
  "estimatedBudgetUSD": 1400
}}
"""

    def fallback():
        day_count = int(days) if days else 4
        titles = ["Llegada y Bienvenida VIP", "Excursión en Catamarán & Arrecifes",
                  "Cultura Local & Cena Gourmet", "Despedida & Mañana de Compras"]
        days_list = []
        for i in range(day_count):
            days_list.append({
                "dayNumber": i + 1,
                "title": titles[i] if i < len(titles) else titles[-1],
                "morning": ("Recepción en el aeropuerto por chofer de DDN Travel y traslado privado al hotel con "
                            "check-in express.") if i == 0 else
                           ("Desayuno buffet con vista al mar y salida hacia la actividad principal del día con "
                            "guía bilingüe."),
                "afternoon": "Tiempo libre para disfrutar de la playa, spa, piscina y almuerzo con sabores caribeños.",
                "evening": "Cena reservada en restaurante de especialidades y velada nocturna bajo las estrellas.",
                "transportIncluded": "Traslado privado DDN Travel",
                "mealPlan": "Desayuno buffet y Almuerzo Gourmet",
            })
        return {
            "destination": destination or "Punta Cana & Bávaro",
            "overview": (f"Itinerario exclusivo de {day_count} días diseñado a medida por la IA de DDN Travel para "
                         f"{travelers or 2} viajero(s). Una experiencia inolvidable que equilibra relax y "
                         "descubrimientos locales de primer nivel."),
            "weatherAdvice": ("Clima cálido tropical con brisa marina. Se recomienda llevar protector solar "
                               "biodegradable, ropa ligera de lino y calzado cómodo para excursiones."),
            "days": days_list,
            "includedPerks": [
                "Asistencia 24/7 por concierge de DDN Travel",
                "Seguro de viaje internacional con cobertura médica integral",
                "Traslados privados puerta a puerta en vehículos ejecutivos",
                "Acceso preferencial en tours y atracciones",
            ],
            "estimatedBudgetUSD": (int(travelers) if travelers else 2) * (day_count * 175),
        }

    return generate_gemini_json(prompt, fallback, schema=validate_itinerary_result)
