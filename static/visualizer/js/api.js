const API_BASE = '/api/visualizer';

async function traceCode(code, fileContent) {
  const csrfToken = document.querySelector('meta[name="csrf-token"]').content;
  const formData = new FormData();
  formData.append('code', code);
  if (fileContent) {
    formData.append('file', fileContent);
  }
  const resp = await fetch(`${API_BASE}/trace`, {
    method: 'POST',
    // Content-Type не указываем намеренно — браузер сам проставит multipart
    // boundary для FormData; ручной заголовок его сломает.
    headers: { 'X-CSRFToken': csrfToken },
    body: formData,
  });
  if (!resp.ok) {
    throw new Error(`Сервер вернул ошибку: ${resp.status}`);
  }
  return resp.json();
}
