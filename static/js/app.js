// ============================================================
// DDN TRAVEL — lógica de interfaz (modales, precios, IA)
// ============================================================

function openModal(id) {
  document.getElementById(id).classList.add('open');
  document.body.style.overflow = 'hidden';
}
function closeModal(id) {
  document.getElementById(id).classList.remove('open');
  document.body.style.overflow = '';
}
document.querySelectorAll('.modal-overlay').forEach(overlay => {
  overlay.addEventListener('click', e => { if (e.target === overlay) closeModal(overlay.id); });
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
// Nueva reserva: pasajeros dinámicos + cálculo de precio en vivo
// ------------------------------------------------------------
function syncPassengers() {
  const count = Math.max(1, Math.min(10, parseInt(document.getElementById('booking-travelers').value) || 1));
  const container = document.getElementById('passenger-rows');
  const existing = container.querySelectorAll('.passenger-row').length;
  if (count > existing) {
    for (let i = existing; i < count; i++) {
      const row = document.createElement('div');
      row.className = 'passenger-row grid grid-cols-3 gap-2';
      row.innerHTML = `
        <input name="passenger_name[]" placeholder="Pasajero ${i + 1}: Nombre completo" class="px-3 py-1.5 rounded-lg bg-black/40 border border-white/10 text-2xs text-white">
        <input name="passenger_document[]" placeholder="Documento" class="px-3 py-1.5 rounded-lg bg-black/40 border border-white/10 text-2xs text-white">
        <input name="passenger_age[]" type="number" placeholder="Edad" value="30" class="px-3 py-1.5 rounded-lg bg-black/40 border border-white/10 text-2xs text-white">`;
      container.appendChild(row);
    }
  } else {
    while (container.querySelectorAll('.passenger-row').length > count) {
      container.removeChild(container.lastElementChild);
    }
  }
}
document.addEventListener('DOMContentLoaded', syncPassengers);

function recalcBookingPrice() {
  const pkgSelect = document.getElementById('booking-package');
  const flightSelect = document.getElementById('booking-flight');
  const travelers = Math.max(1, parseInt(document.getElementById('booking-travelers').value) || 1);
  const pkgOpt = pkgSelect.options[pkgSelect.selectedIndex];
  const flightOpt = flightSelect.options[flightSelect.selectedIndex];
  const basePrice = pkgOpt && pkgOpt.dataset.price ? parseFloat(pkgOpt.dataset.price) : 300;
  const flightAddon = flightOpt && flightOpt.dataset.price ? parseFloat(flightOpt.dataset.price) * travelers : 0;
  const rawTotal = basePrice * travelers + flightAddon;
  document.getElementById('booking-total-display').textContent = `$${Math.round(rawTotal).toLocaleString()} USD`;
  window._rawBookingTotal = rawTotal;
}

function openNewBookingModal(packageId) {
  if (packageId) {
    const select = document.getElementById('booking-package');
    select.value = packageId;
  }
  recalcBookingPrice();
  openModal('modal-new-booking');
}

async function applyPromoPreview() {
  const code = document.getElementById('booking-promo').value;
  const msgEl = document.getElementById('promo-message');
  if (!code.trim()) return;
  recalcBookingPrice();
  const total = window._rawBookingTotal || 0;
  try {
    const res = await fetch('/api/promo/preview', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ code, total })
    });
    const data = await res.json();
    msgEl.textContent = data.message;
    msgEl.className = 'text-2xs mt-1 ' + (data.valid ? 'text-emerald-400' : 'text-rose-400');
    if (data.valid) {
      document.getElementById('booking-total-display').textContent = `$${Math.round(data.final_price).toLocaleString()} USD`;
    }
  } catch (err) {
    msgEl.textContent = 'No se pudo validar el cupón en este momento.';
    msgEl.className = 'text-2xs mt-1 text-rose-400';
  }
}

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
      ${b.payment_status !== 'Pagado' && b.status !== 'Cancelada' ? `<button onclick="closeModal('modal-booking-detail'); document.getElementById('payment-booking-select').value='${b.id}'; openModal('modal-new-payment');" class="px-3 py-1.5 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white text-2xs font-bold">Registrar Pago</button>` : ''}
      <button onclick="closeModal('modal-booking-detail'); openInvoice(window._lastBookingDetail);" class="px-3 py-1.5 rounded-xl bg-white/10 hover:bg-white/15 border border-white/10 text-white text-2xs font-bold">Ver Factura</button>
      ${b.status !== 'Cancelada' && b.status !== 'Completada' ? `<form method="POST" action="/bookings/${b.id}/cancel" onsubmit="return confirm('¿Cancelar esta reserva?');" class="inline">
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
    const res = await fetch('/api/ai/generate-itinerary', {
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
    const res = await fetch('/api/ai/recommendations', {
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
      const res = await fetch('/api/chat/message', {
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
