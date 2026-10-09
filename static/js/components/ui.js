// static/js/components/ui.js
/** Безопасные DOM helpers, уведомления и обёртка асинхронных UI операций. */
import { api } from '../api.js';

let toastTimer;

/** Создаёт element и назначает свойства; пользовательский текст всегда textContent. */
export function el(tag, props = {}, children = []) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (key === 'text') node.textContent = value;
    else if (key.startsWith('data-') || key.startsWith('aria-')) node.setAttribute(key, value);
    else node[key] = value;
  }
  node.append(...children);
  return node;
}

/** Показывает текст результата через aria-live, включая ошибки API. */
export function toast(message, error = false) {
  const node = document.querySelector('[data-toast]');
  if (!node) return;
  node.textContent = message;
  node.hidden = false;
  node.classList.toggle('toast--error', error);
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { node.hidden = true; }, error ? 15000 : 5000);
}

/** Блокирует кнопку до завершения операции и показывает содержательные validation errors. */
export async function run(operation, button) {
  if (button?.disabled) return;
  if (button) button.disabled = true;
  try { return await operation(); }
  catch (error) {
    let details = '';
    if (error.details && Object.keys(error.details).length) details = ` ${JSON.stringify(error.details)}`;
    toast(`${error.message}${details}`, true);
  } finally { if (button) button.disabled = false; }
}

/** Форматирует timestamp в timezone объекта вместо timezone исполнения сервера. */
export function formatDate(value) {
  if (!value) return 'Нет данных';
  return new Intl.DateTimeFormat('ru-RU', { dateStyle: 'short', timeStyle: 'medium',
    timeZone: document.body.dataset.timezone || 'Europe/Moscow' }).format(new Date(value));
}

/** Формирует status badge канала без смешения SENT и skipped состояний. */
export function badge(channel, status) {
  const labels = { SENT: '✓', FAILED: 'ошибка', DEAD: 'ошибка', SKIPPED_DISABLED: 'отключено',
    QUEUED: 'в очереди', PENDING: 'ожидание', RETRYING: 'повтор' };
  return el('span', { className: `badge ${status === 'SENT' ? 'badge--sent' : ['FAILED', 'DEAD'].includes(status) ? 'badge--failed' : ''}`,
    text: `${channel} ${labels[status] || status || '—'}` });
}

/** Считывает filters формы и преобразует local browser даты в timezone-aware ISO. */
export function filters(form) {
  const data = Object.fromEntries(new FormData(form));
  for (const key of Object.keys(data)) {
    if (!data[key]) delete data[key];
    else if (key === 'date_from' || key === 'date_to') data[key] = new Date(data[key]).toISOString();
  }
  return data;
}

// Все page modules ждут этот module: даты не рендерятся раньше timezone объекта.
if (document.body.dataset.page) {
  await run(async () => {
    const schedule = await api('/api/v1/control-schedule');
    document.body.dataset.timezone = schedule.timezone;
  });
}
