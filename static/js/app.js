// ============================================================
// DDN TRAVEL — lógica de interfaz (modales, precios, IA)
// ============================================================

// ------------------------------------------------------------
// CSRF: Flask-WTF exige el token en toda petición que muta datos.
// Se lee de <meta name="csrf-token"> (inyectado en base.html) y de los
// formularios, de modo que el mismo helper sirve para fetch y para forms.
// ------------------------------------------------------------
function getCsrfToken() {
  const meta = document.querySelector('meta[name="csrf-token"]');
  if (meta && meta.content) return meta.content;
  const input = document.querySelector('input[name="csrf_token"]');
  return input ? input.value : '';
}

function csrfHeaders(extra = {}) {
  const token = getCsrfToken();
  return token ? { ...extra, 'X-CSRFToken': token } : { ...extra };
}

// Wrapper de fetch que aplica CSRF, normaliza errores JSON y avisa al usuario
// cuando la sesión ha caducado (401/403) o el token es inválido (400).
async function csrfFetch(url, options = {}) {
  const config = { credentials: 'same-origin', ...options, headers: csrfHeaders(options.headers || {}) };
  const response = await fetch(url, config);
  if (response.status === 400) {
    const detail = await response.text();
    if (detail.includes('CSRF')) {
      showToast('La sesión expiró. Recarga la página para continuar.', 'error');
    }
    return response;
  }
  return response;
}

function openModal(id) {
  document.getElementById(id).classList.add('open');
  document.body.style.overflow = 'hidden';
  if (id === 'modal-new-booking') refreshBookingQuote();
}
function closeModal(id) {
  document.getElementById(id).classList.remove('open');
  document.body.style.overflow = '';
}
document.querySelectorAll('.modal-overlay').forEach(overlay => {
  overlay.addEventListener('click', e => { if (e.target === overlay) closeModal(overlay.id); });
});
document.addEventListener('keydown', event => {
  if (event.key !== 'Escape') return;
  const activeModal = document.querySelector('.modal-overlay.open');
  if (activeModal) closeModal(activeModal.id);
});

function setCatalogFields(kind) {
  document.querySelectorAll('[data-catalog-fields]').forEach(fieldset => {
    const isActive = fieldset.dataset.catalogFields === kind;
    fieldset.hidden = !isActive;
    fieldset.disabled = !isActive;
  });
}

function openCatalogEditor(kind, item = null, editUrl = '') {
  const form = document.getElementById('catalog-editor-form');
  const title = document.getElementById('catalog-editor-title');
  const error = document.getElementById('catalog-editor-error');
  const createUrls = {
    package: '/admin/packages/new',
    flight: '/admin/flights/new',
    transport: '/admin/transports/new',
    activity: '/admin/activities/new'
  };
  const labels = {
    package: 'paquete turístico',
    flight: 'vuelo',
    transport: 'transporte turístico',
    activity: 'tour o actividad'
  };
  if (!form || !createUrls[kind]) return;
  form.reset();
  error.textContent = '';
  error.classList.add('hidden');
  setCatalogFields(kind);
  form.dataset.mode = item ? 'edit' : 'create';
  form.action = item ? editUrl : createUrls[kind];
  title.textContent = `${item ? 'Editar' : 'Nuevo'} ${labels[kind]}`;
  if (item) {
    const activeFields = form.querySelector(`[data-catalog-fields="${kind}"]`);
    Object.entries(item).forEach(([key, value]) => {
      const field = activeFields.elements.namedItem(key);
      if (!field || value === null || value === undefined) return;
      field.value = Array.isArray(value)
        ? value.join(', ')
        : (typeof value === 'boolean' ? (value ? '1' : '0') : String(value));
    });
    if (kind === 'package' && item.image_url && !item.image) {
      activeFields.elements.namedItem('image').value = item.image_url;
    }
  }
  openModal('catalog-editor-modal');
  const firstField = form.querySelector(`[data-catalog-fields="${kind}"] input:not([type=hidden])`);
  if (firstField) firstField.focus();
}

document.addEventListener('click', event => {
  const createButton = event.target.closest('[data-catalog-new]');
  if (createButton) {
    openCatalogEditor(createButton.dataset.catalogNew);
    return;
  }
  const editButton = event.target.closest('[data-catalog-edit]');
  if (editButton) {
    try {
      openCatalogEditor(
        editButton.dataset.catalogEdit,
        JSON.parse(editButton.dataset.item),
        editButton.dataset.editUrl
      );
    } catch (error) {
      window.alert('No se pudieron cargar los datos para editar este recurso.');
    }
  }
});

document.querySelectorAll('[data-catalog-editor]').forEach(form => {
  form.addEventListener('submit', async event => {
    if (form.dataset.mode !== 'edit') return;
    event.preventDefault();
    const errorBox = document.getElementById('catalog-editor-error');
    errorBox.textContent = '';
    errorBox.classList.add('hidden');
    try {
      const response = await csrfFetch(form.action, {
        method: 'POST',
        headers: { 'X-Requested-With': 'XMLHttpRequest' },
        body: new FormData(form)
      });
      const result = await response.json();
      if (!response.ok || !result.success) {
        const details = result.errors ? result.errors.join(' ') : result.error;
        throw new Error(details || 'No se pudo guardar el recurso.');
      }
      window.alert('Los cambios se guardaron correctamente.');
      window.location.reload();
    } catch (error) {
      errorBox.textContent = error.message || 'No se pudo guardar el recurso.';
      errorBox.classList.remove('hidden');
    }
  });
});

document.querySelectorAll('[data-catalog-delete]').forEach(form => {
  form.addEventListener('submit', async event => {
    event.preventDefault();
    const label = form.dataset.label || 'este recurso';
    if (!window.confirm(`¿Seguro que deseas eliminar «${label}»?`)) return;
    try {
      const response = await csrfFetch(form.action, {
        method: 'POST',
        headers: { 'X-Requested-With': 'XMLHttpRequest' },
        body: new FormData(form)
      });
      const result = await response.json();
      if (!response.ok || !result.success) {
        throw new Error(result.error || 'No se pudo eliminar el recurso.');
      }
      window.alert('El recurso se eliminó correctamente.');
      window.location.reload();
    } catch (error) {
      window.alert(error.message || 'No se pudo eliminar el recurso.');
    }
  });
});

function toggleDropdown(id) {
  const el = document.getElementById(id);
  const isOpen = !el.classList.contains('hidden');
  document.querySelectorAll('[id$="-dropdown"]').forEach(d => d.classList.add('hidden'));
  if (!isOpen) el.classList.remove('hidden');
}
document.addEventListener('click', e => {
  if (!e.target.closest('[onclick^="toggleDropdown"]') && !e.target.closest('[id$="-dropdown"]')) {
    document.querySelectorAll('[id$="-dropdown"]').forEach(d => d.classList.add('hidden'));
  }
});

// ------------------------------------------------------------
// Nueva reserva: pasajeros dinámicos + cotización calculada por el servidor
// ------------------------------------------------------------
function syncPassengers() {
  const count = Math.max(1, Math.min(10, parseInt(document.getElementById('booking-travelers').value) || 1));
  const container = document.getElementById('passenger-rows');
  const existing = container.querySelectorAll('.passenger-row').length;
  if (count > existing) {
    for (let i = existing; i < count; i++) {
      const row = document.createElement('div');
      row.className = 'passenger-row grid grid-cols-1 sm:grid-cols-3 gap-3';
      row.innerHTML = `
        <div>
          <label for="passenger-name-${i}" class="block text-xs font-medium text-slate-300 mb-1">Viajero ${i + 1}: nombre completo</label>
          <input id="passenger-name-${i}" name="passenger_name[]" autocomplete="name" aria-label="Viajero ${i + 1}: nombre completo" class="w-full min-h-11 px-3 py-2 rounded-xl bg-black/40 border border-white/10 text-xs text-white">
        </div>
        <div>
          <label for="passenger-document-${i}" class="block text-xs font-medium text-slate-300 mb-1">Documento de identidad</label>
          <input id="passenger-document-${i}" name="passenger_document[]" aria-label="Viajero ${i + 1}: documento de identidad" class="w-full min-h-11 px-3 py-2 rounded-xl bg-black/40 border border-white/10 text-xs text-white">
        </div>
        <div>
          <label for="passenger-age-${i}" class="block text-xs font-medium text-slate-300 mb-1">Edad</label>
          <input id="passenger-age-${i}" name="passenger_age[]" type="number" min="0" max="120" value="30" aria-label="Viajero ${i + 1}: edad" class="w-full min-h-11 px-3 py-2 rounded-xl bg-black/40 border border-white/10 text-xs text-white">
        </div>`;
      container.appendChild(row);
    }
  } else {
    while (container.querySelectorAll('.passenger-row').length > count) {
      container.removeChild(container.lastElementChild);
    }
  }
}
document.addEventListener('DOMContentLoaded', syncPassengers);

let bookingQuoteRequest = 0;
let bookingQuoteReady = false;

async function refreshBookingQuote() {
  const form = document.getElementById('new-booking-form');
  const totalEl = document.getElementById('booking-total-display');
  if (!form || !totalEl) return;

  const requestId = ++bookingQuoteRequest;
  bookingQuoteReady = false;
  const submitButton = form.querySelector('button[type="submit"]');
  if (submitButton) submitButton.disabled = true;
  const params = new URLSearchParams();
  const fields = new FormData(form);
  ['package_id', 'hotel_id', 'room_type_id', 'flight_id', 'travelers', 'rooms_count',
    'departure_date', 'return_date', 'check_in', 'check_out',
    'promo_code', 'client_id'].forEach(name => {
    const value = fields.get(name);
    if (value !== null && value !== '') params.set(name, value);
  });

  totalEl.textContent = 'Calculando…';
  const promoMessage = document.getElementById('promo-message');
  try {
    const response = await csrfFetch(`/api/bookings/quote?${params.toString()}`);
    const quote = await response.json();
    if (requestId !== bookingQuoteRequest) return;
    if (!response.ok || !quote.success) throw new Error(quote.error || 'Cotización no disponible');

    totalEl.textContent = `$${Number(quote.total).toLocaleString('en-US', {
      minimumFractionDigits: 2, maximumFractionDigits: 2
    })} USD`;
    bookingQuoteReady = true;
    if (submitButton) submitButton.disabled = false;
    if (promoMessage) {
      promoMessage.textContent = quote.promo_message || '';
      promoMessage.className = 'text-2xs mt-1 ' +
        (quote.promo_valid ? 'text-emerald-400' : 'text-rose-400');
    }
  } catch (err) {
    if (requestId !== bookingQuoteRequest) return;
    totalEl.textContent = 'No disponible';
    if (promoMessage) {
      promoMessage.textContent = err.message || 'No se pudo calcular la cotización.';
      promoMessage.className = 'text-2xs mt-1 text-rose-400';
    }
  }
}

function openNewBookingModal(packageId) {
  if (packageId) {
    const select = document.getElementById('booking-package');
    select.value = packageId;
  }
  openModal('modal-new-booking');
}

async function applyPromoPreview() {
  await refreshBookingQuote();
}

function refreshBookingRoomTypes() {
  const hotelSelect = document.getElementById('booking-hotel');
  const roomSelect = document.getElementById('booking-room-type');
  if (!hotelSelect || !roomSelect) return;

  const hotelId = hotelSelect.value;
  const options = [...roomSelect.querySelectorAll('option[data-hotel-id]')];
  options.forEach(option => {
    option.hidden = !hotelId || option.dataset.hotelId !== hotelId;
  });
  const availableOptions = options.filter(option => !option.hidden);
  roomSelect.value = availableOptions[0]?.value || '';
  roomSelect.disabled = availableOptions.length === 0;
  if (!availableOptions.length) {
    roomSelect.options[0].textContent = hotelId
      ? 'Este hotel no tiene tipos de habitación'
      : 'Selecciona un hotel primero';
  }
  refreshBookingQuote();
}

function initBookingQuote() {
  const form = document.getElementById('new-booking-form');
  if (!form) return;
  ['package_id', 'room_type_id', 'flight_id', 'travelers', 'rooms_count',
    'departure_date', 'return_date', 'check_in', 'check_out',
    'promo_code', 'client_id'].forEach(name => {
    const field = form.elements.namedItem(name);
    if (field) {
      const eventName = field.tagName === 'SELECT' ? 'change' : 'input';
      field.addEventListener(eventName, refreshBookingQuote);
    }
  });
  const hotelSelect = form.elements.namedItem('hotel_id');
  if (hotelSelect) hotelSelect.addEventListener('change', refreshBookingRoomTypes);
  refreshBookingRoomTypes();
  form.addEventListener('submit', event => {
    if (!bookingQuoteReady) {
      event.preventDefault();
      showToast('Espera a que se complete una cotización válida antes de confirmar.', 'error');
    }
  });
  refreshBookingQuote();
}

document.addEventListener('DOMContentLoaded', initBookingQuote);

// ------------------------------------------------------------
// Detalle de reserva / factura (poblados desde data-json embebido en filas)
// ------------------------------------------------------------
function openBookingDetail(booking) {
  const b = typeof booking === 'string' ? JSON.parse(booking) : booking;
  window._lastBookingDetail = b;
  const body = document.getElementById('booking-detail-body');
  body.innerHTML = `
    <div class="flex items-center justify-between p-4 rounded-2xl bg-white/5 border border-white/10">
      <div><p class="font-mono text-indigo-300 font-bold">${b.booking_code}</p>
        <p class="text-white font-bold text-sm">${b.client_name}</p><p class="text-slate-400">${b.client_email || ''}</p></div>
      <span class="px-3 py-1 rounded-full text-2xs font-bold bg-indigo-500/20 text-indigo-300 border border-indigo-500/30">${b.status}</span>
    </div>
    <div class="grid grid-cols-2 gap-3">
      <div class="p-3 rounded-xl bg-white/5 border border-white/5"><p class="text-slate-400">Destino</p><p class="text-white font-semibold">${b.destination_name || '-'}</p></div>
      <div class="p-3 rounded-xl bg-white/5 border border-white/5"><p class="text-slate-400">Paquete</p><p class="text-white font-semibold">${b.package_name || '-'}</p></div>
      <div class="p-3 rounded-xl bg-white/5 border border-white/5"><p class="text-slate-400">Fechas</p><p class="text-white font-semibold">${b.departure_date} → ${b.return_date}</p></div>
      <div class="p-3 rounded-xl bg-white/5 border border-white/5"><p class="text-slate-400">Viajeros</p><p class="text-white font-semibold">${b.travelers}</p></div>
      <div class="p-3 rounded-xl bg-white/5 border border-white/5"><p class="text-slate-400">Total</p><p class="text-white font-semibold">$${Number(b.total_price).toLocaleString()} USD</p></div>
      <div class="p-3 rounded-xl bg-white/5 border border-white/5"><p class="text-slate-400">Pagado / Estado</p><p class="text-white font-semibold">$${Number(b.amount_paid).toLocaleString()} USD — ${b.payment_status}</p></div>
    </div>
    ${(b.passengers && b.passengers.length) ? `<div class="p-3 rounded-xl bg-white/5 border border-white/5">
      <p class="text-slate-400 mb-2">Pasajeros</p>
      <ul class="space-y-1">${b.passengers.map(p => `<li class="text-white">• ${p.full_name} — ${p.document} (${p.age} años)</li>`).join('')}</ul>
    </div>` : ''}
    ${b.notes ? `<div class="p-3 rounded-xl bg-amber-500/10 border border-amber-500/20 text-amber-200">${b.notes}</div>` : ''}
    <div class="flex flex-wrap gap-2 pt-2">
      ${window.DDN_PERMS && window.DDN_PERMS['payments:create'] && b.payment_status !== 'Pagado' && b.status !== 'Cancelada' ? `<button onclick="closeModal('modal-booking-detail'); document.getElementById('payment-booking-select').value='${b.id}'; openModal('modal-new-payment');" class="px-3 py-1.5 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white text-2xs font-bold">Registrar Pago</button>` : ''}
      <button onclick="closeModal('modal-booking-detail'); openInvoice(window._lastBookingDetail);" class="px-3 py-1.5 rounded-xl bg-white/10 hover:bg-white/15 border border-white/10 text-white text-2xs font-bold">Ver Factura</button>
      ${window.DDN_PERMS && window.DDN_PERMS['bookings:cancel'] && b.status !== 'Cancelada' && b.status !== 'Completada' ? `<form method="POST" action="/bookings/${b.id}/cancel" onsubmit="return confirm('¿Cancelar esta reserva?');" class="inline">
        <input type="hidden" name="csrf_token" value="${getCsrfToken()}">
        <button class="px-3 py-1.5 rounded-xl bg-rose-500/20 hover:bg-rose-500/30 border border-rose-500/30 text-rose-300 text-2xs font-bold">Cancelar Reserva</button></form>` : ''}
    </div>
  `;
  openModal('modal-booking-detail');
}

function openInvoice(bookingJson) {
  const b = typeof bookingJson === 'string' ? JSON.parse(bookingJson) : bookingJson;
  const body = document.getElementById('invoice-body');
  body.innerHTML = `
    <div class="flex items-center justify-between border-b border-slate-200 pb-3">
      <div><p class="font-black text-lg text-indigo-700">DDN TRAVEL</p><p class="text-slate-500">Agencia de Viajes Turísticos</p></div>
      <div class="text-right"><p class="font-bold">Factura</p><p class="font-mono text-slate-500">${b.booking_code}</p></div>
    </div>
    <div><p class="text-slate-500">Cliente</p><p class="font-semibold">${b.client_name}</p><p class="text-slate-500">${b.client_email || ''}</p></div>
    <table class="w-full text-left mt-2">
      <tbody>
        <tr class="border-t border-slate-100"><td class="py-1.5 text-slate-500">Paquete / Servicio</td><td class="py-1.5 text-right font-medium">${b.package_name || 'Itinerario Personalizado'}</td></tr>
        <tr class="border-t border-slate-100"><td class="py-1.5 text-slate-500">Destino</td><td class="py-1.5 text-right font-medium">${b.destination_name || '-'}</td></tr>
        <tr class="border-t border-slate-100"><td class="py-1.5 text-slate-500">Viajeros</td><td class="py-1.5 text-right font-medium">${b.travelers}</td></tr>
        <tr class="border-t border-slate-200"><td class="py-1.5 font-bold">Total</td><td class="py-1.5 text-right font-bold">$${Number(b.total_price).toLocaleString()} USD</td></tr>
        <tr><td class="py-1.5 text-slate-500">Pagado</td><td class="py-1.5 text-right">$${Number(b.amount_paid).toLocaleString()} USD</td></tr>
        <tr><td class="py-1.5 text-slate-500">Saldo Pendiente</td><td class="py-1.5 text-right font-semibold ${(b.total_price - b.amount_paid) > 0 ? 'text-rose-600' : 'text-emerald-600'}">$${Number(b.total_price - b.amount_paid).toLocaleString()} USD</td></tr>
      </tbody>
    </table>
    <p class="text-slate-400 text-center pt-2 border-t border-slate-100">Gracias por viajar con DDN Travel — Documento generado automáticamente.</p>
  `;
  openModal('modal-invoice');
}

// ------------------------------------------------------------
// IA: Itinerario personalizado
// ------------------------------------------------------------
async function submitItineraryForm(e) {
  e.preventDefault();
  const form = e.target;
  const btn = document.getElementById('itinerary-submit-btn');
  btn.disabled = true;
  btn.textContent = 'Generando itinerario con IA...';
  const data = Object.fromEntries(new FormData(form).entries());
  try {
    const res = await csrfFetch('/api/ai/generate-itinerary', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data)
    });
    const json = await res.json();
    renderItineraryResult(json.data);
  } finally {
    btn.disabled = false;
    btn.innerHTML = '✨ Generar Itinerario con IA';
  }
  return false;
}

function renderItineraryResult(data) {
  document.getElementById('itinerary-form').classList.add('hidden');
  const el = document.getElementById('itinerary-result');
  el.classList.remove('hidden');
  el.innerHTML = `
    <div class="p-4 rounded-2xl bg-indigo-500/10 border border-indigo-500/20 text-xs space-y-1.5">
      <p class="font-bold text-white text-sm">${data.destination}</p>
      <p class="text-slate-300">${data.overview}</p>
      <p class="text-indigo-300 bg-black/30 p-2 rounded-xl">🌤️ ${data.weatherAdvice}</p>
    </div>
    <div class="space-y-2">
      ${(data.days || []).map(d => `
        <div class="p-3 rounded-2xl bg-white/5 border border-white/10 text-xs space-y-1">
          <p class="font-bold text-white">Día ${d.dayNumber}: ${d.title}</p>
          <p><strong class="text-indigo-300">Mañana:</strong> ${d.morning}</p>
          <p><strong class="text-indigo-300">Tarde:</strong> ${d.afternoon}</p>
          <p><strong class="text-indigo-300">Noche:</strong> ${d.evening}</p>
          <p class="text-slate-400 text-2xs">${d.transportIncluded} • ${d.mealPlan}</p>
        </div>`).join('')}
    </div>
    <div class="p-3 rounded-2xl bg-emerald-500/10 border border-emerald-500/20 text-xs">
      <p class="font-bold text-emerald-300">Incluye:</p>
      <ul class="list-disc list-inside">${(data.includedPerks || []).map(p => `<li>${p}</li>`).join('')}</ul>
      <p class="mt-2 font-bold text-white">Presupuesto estimado: $${Number(data.estimatedBudgetUSD || 0).toLocaleString()} USD</p>
    </div>
    <div class="flex justify-end gap-2 pt-2">
      <button onclick="document.getElementById('itinerary-form').classList.remove('hidden'); document.getElementById('itinerary-result').classList.add('hidden');" class="px-4 py-2 rounded-xl border border-white/10 text-slate-300 hover:bg-white/5 text-xs font-semibold">← Recalcular</button>
      <button onclick="closeModal('modal-ai-itinerary')" class="px-5 py-2.5 rounded-2xl bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-bold">Cerrar</button>
    </div>`;
}

// ------------------------------------------------------------
// IA: Recomendador inteligente
// ------------------------------------------------------------
async function submitRecommendForm(e) {
  e.preventDefault();
  const form = e.target;
  const btn = document.getElementById('recommend-submit-btn');
  btn.disabled = true;
  btn.textContent = 'Analizando afinidad con IA...';
  const formData = Object.fromEntries(new FormData(form).entries());
  const client = (window.DDN_DATA.clients || []).find(c => c.id === formData.clientId) || { name: 'Cliente Potencial' };
  const payload = {
    clientProfile: client, budget: parseFloat(formData.budget), travelStyle: formData.travelStyle,
    travelersCount: parseInt(formData.travelersCount), interests: formData.interests
  };
  try {
    const res = await csrfFetch('/api/ai/recommendations', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload)
    });
    const json = await res.json();
    renderRecommendResult(json.data);
  } finally {
    btn.disabled = false;
    btn.innerHTML = '✨ Calcular Recomendaciones';
  }
  return false;
}

function renderRecommendResult(data) {
  document.getElementById('recommend-form').classList.add('hidden');
  const el = document.getElementById('recommend-result');
  el.classList.remove('hidden');
  el.innerHTML = `
    <div class="p-5 rounded-3xl bg-emerald-500/15 border border-emerald-500/30 text-xs space-y-2">
      <p class="font-bold text-white text-sm">Índice de Afinidad IA: ${data.affinityScore}%</p>
      <p class="text-slate-200">${data.profileSummary}</p>
    </div>
    <div class="space-y-3">
      ${(data.recommendedPackages || []).map((pkg, idx) => `
        <div class="p-4 rounded-2xl bg-white/5 border border-white/10 space-y-2 text-xs">
          <div class="flex items-start justify-between">
            <div><span class="text-2xs font-bold text-emerald-300">Opción #${idx + 1} • ${pkg.recommendedDuration}</span>
              <p class="font-bold text-white text-sm">${pkg.title}</p>
              <p class="text-slate-400">${pkg.destination} • ${pkg.bestSeason}</p></div>
            <div class="text-right"><p class="font-bold text-emerald-400">$${pkg.estimatedPricePerPerson}</p><p class="text-2xs text-slate-400">USD / persona</p></div>
          </div>
          <p class="bg-black/30 p-2 rounded-xl">${pkg.matchReason}</p>
          <div class="flex flex-wrap gap-1.5">${(pkg.highlights || []).map(h => `<span class="px-2 py-0.5 rounded-lg bg-white/5 border border-white/5 text-2xs">✓ ${h}</span>`).join('')}</div>
        </div>`).join('')}
    </div>
    ${(data.smartTips || []).length ? `<div class="p-4 rounded-2xl bg-amber-500/10 border border-amber-500/30 text-xs text-amber-200">
      <p class="font-bold text-amber-300">Consejos Inteligentes:</p>
      <ul class="list-disc list-inside">${data.smartTips.map(t => `<li>${t}</li>`).join('')}</ul></div>` : ''}
    <div class="flex justify-end gap-2 pt-2">
      <button onclick="document.getElementById('recommend-form').classList.remove('hidden'); document.getElementById('recommend-result').classList.add('hidden');" class="px-4 py-2 rounded-xl border border-white/10 text-slate-300 hover:bg-white/5 text-xs font-semibold">← Recalcular</button>
      <button onclick="closeModal('modal-ai-recommend')" class="px-5 py-2.5 rounded-2xl bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-bold">Cerrar</button>
    </div>`;
}

// ------------------------------------------------------------
// Búsqueda global simple: filtra filas de tabla / tarjetas en la vista actual
// ------------------------------------------------------------
const searchInput = document.getElementById('global-search');
if (searchInput) {
  searchInput.addEventListener('input', () => {
    const q = searchInput.value.trim().toLowerCase();
    document.querySelectorAll('[data-searchable]').forEach(row => {
      row.style.display = !q || row.textContent.toLowerCase().includes(q) ? '' : 'none';
    });
});
}
// ------------------------------------------------------------
// Chat en vivo widget
// ------------------------------------------------------------
const FAQ_SUGGESTIONS = [
  "¿Cómo hago una reserva?",
  "¿Puedo modificar mi reserva?",
  "¿Qué métodos de pago aceptan?",
  "¿Cómo recibo mis documentos?",
  "¿Ofrecen seguros de viaje?",
  "¿Hay atención 24/7?",
  "¿Puedo cancelar mi reserva?",
  "¿Cómo uso el itinerario IA?",
  "Hablar con agente"
];

function initChatWidget() {
  const widget = document.getElementById('chat-widget');
  if (!widget) return;

  const toggle = document.getElementById('chat-toggle');
  const windowEl = document.getElementById('chat-window');
  const closeBtn = document.getElementById('chat-close');
  const messagesEl = document.getElementById('chat-messages');
  const form = document.getElementById('chat-form');
  const input = document.getElementById('chat-input');
  const suggestionsEl = document.getElementById('chat-suggestions');
  const badge = document.getElementById('chat-badge');

  let isOpen = false;
  let unreadCount = 0;

  function renderSuggestions() {
    suggestionsEl.innerHTML = FAQ_SUGGESTIONS.map(q =>
      `<button type="button" class="px-3 py-1.5 rounded-full bg-white/10 hover:bg-white/20 border border-white/10 text-2xs text-slate-300 hover:text-white transition-all" data-suggestion="${q}">${q}</button>`
    ).join('');
    suggestionsEl.querySelectorAll('[data-suggestion]').forEach(btn => {
      btn.addEventListener('click', () => {
        input.value = btn.dataset.suggestion;
        sendChatMessage({ preventDefault: () => {} });
      });
    });
  }

  function addMessage(text, isUser = false, isFAQ = false) {
    const div = document.createElement('div');
    div.className = `flex ${isUser ? 'justify-end' : 'justify-start'}`;
    const bubble = document.createElement('div');
    bubble.className = `max-w-[80%] px-4 py-2.5 rounded-2xl text-sm ${isUser ? 'bg-indigo-600 text-white rounded-br-md' : 'bg-slate-100 dark:bg-slate-800 text-slate-900 dark:text-white rounded-bl-md'}`;
    if (isFAQ) {
      bubble.classList.add('border', 'border-emerald-500/30', 'bg-emerald-500/5', 'dark:bg-emerald-900/10');
      bubble.innerHTML = `<span class="text-2xs font-bold text-emerald-400 mr-1">✓ FAQ: </span>${text}`;
    } else {
      bubble.textContent = text;
    }
    div.appendChild(bubble);
    messagesEl.appendChild(div);
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  async function sendChatMessage(e) {
    e.preventDefault();
    const msg = input.value.trim();
    if (!msg) return false;
    input.value = '';
    addMessage(msg, true);
    try {
      const res = await csrfFetch('/api/chat/message', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: msg })
      });
      const data = await res.json();
      addMessage(data.reply, false, data.faq);
    } catch (err) {
      addMessage('Error de conexión. Intenta de nuevo más tarde.', false);
    }
    return false;
  }

  function openChat() {
    windowEl.classList.remove('hidden');
    windowEl.classList.add('flex');
    isOpen = true;
    toggle.setAttribute('aria-expanded', 'true');
    if (unreadCount > 0) {
      unreadCount = 0;
      badge.classList.add('hidden');
      badge.textContent = '0';
    }
    input.focus();
  }

  function closeChat() {
    windowEl.classList.add('hidden');
    windowEl.classList.remove('flex');
    isOpen = false;
    toggle.setAttribute('aria-expanded', 'false');
  }

  toggle.addEventListener('click', () => isOpen ? closeChat() : openChat());
  closeBtn.addEventListener('click', closeChat);
  form.addEventListener('submit', sendChatMessage);

  // Initial welcome message
  addMessage('¡Hola! 👋 Soy el asistente virtual de DDN Travel. ¿En qué puedo ayudarte hoy? Puedes preguntarme sobre reservas, pagos, documentos, seguros, itinerarios...');
  renderSuggestions();

  // Expose for potential external use
  window.DDNChat = { open: openChat, close: closeChat, addMessage };
}

document.addEventListener('DOMContentLoaded', initChatWidget);
