const API_BASE = '/api/visualizer';

async function traceCode(code) {
  const csrfToken = document.querySelector('meta[name="csrf-token"]').content;
  const resp = await fetch(`${API_BASE}/trace`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken },
    body: JSON.stringify({ code }),
  });
  if (!resp.ok) {
    throw new Error(`Сервер вернул ошибку: ${resp.status}`);
  }
  return resp.json();
}
