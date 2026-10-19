(() => {
  function csrfToken() {
    return document.querySelector('meta[name="csrf-token"]')?.content ||
      document.querySelector('input[name="csrf_token"]')?.value || '';
  }

  async function request(url, options = {}) {
    const headers = new Headers(options.headers || {});
    const token = csrfToken();
    if (token && !['GET', 'HEAD', 'OPTIONS'].includes((options.method || 'GET').toUpperCase())) {
      headers.set('X-CSRFToken', token);
    }
    const response = await fetch(url, {
      credentials: 'same-origin',
      ...options,
      headers
    });
    if (!response.ok) {
      const contentType = response.headers.get('content-type') || '';
      const detail = contentType.includes('application/json')
        ? await response.clone().json().catch(() => ({}))
        : { error: await response.clone().text() };
      response.error = detail.error || detail.message || `Solicitud fallida (${response.status})`;
    }
    return response;
  }

  window.DDNApi = Object.freeze({ request, csrfToken });
})();
