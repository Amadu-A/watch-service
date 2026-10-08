// src/web/static/js/api.js
/** Единый session/CSRF API client с timeout и безопасной обработкой ошибок. */

/** Возвращает CSRF cookie только для same-origin запросов. */
function csrfToken() {
  const cookie = document.cookie.split('; ').find(value => value.startsWith('csrftoken='));
  return cookie ? decodeURIComponent(cookie.slice('csrftoken='.length)) : '';
}

/** Выполняет JSON запрос и возвращает envelope либо data при отсутствии pagination. */
export async function api(path, { method = 'GET', body, timeout = 30000 } = {}) {
  const response = await fetch(path, {
    method, credentials: 'same-origin', signal: AbortSignal.timeout(timeout),
    headers: { Accept: 'application/json', ...(body === undefined ? {} : { 'Content-Type': 'application/json' }),
      ...(method === 'GET' ? {} : { 'X-CSRFToken': csrfToken() }) },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
  const payload = await response.json().catch(() => ({ error: { message: 'Ответ сервера недоступен. Обновите страницу или войдите снова.' } }));
  if (!response.ok) {
    const error = new Error(payload.error?.message || 'Не удалось выполнить запрос.');
    error.details = payload.error?.details;
    error.code = payload.error?.code;
    throw error;
  }
  return payload.meta ? payload : Object.hasOwn(payload, 'data') ? payload.data : payload;
}
