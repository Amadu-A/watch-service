// src/web/static/js/features/violations.js
/** История событий, filters, pagination, доказательства и notification retry. */
import { api } from '../api.js';
import { badge, el, filters, formatDate, run, toast } from '../components/ui.js';

const canRetry = document.body.dataset.canRetry === 'true';
let page = 1, query = {};

/** Добавляет зарегистрированные камеры в общий filter select. */
export async function cameraOptions() {
  const select = document.querySelector('[data-filter-camera]');
  if (!select) return;
  const cameras = await api('/api/v1/cameras');
  select.append(...cameras.map(camera => el('option', { value: camera.id, text: camera.name })));
}

/** Создаёт действия события: просмотр, PDF и permitted failed resend. */
function eventActions(event) {
  const actions = el('div', { className: 'table__actions' }, [
    el('a', { className: 'button button--icon', href: `/violations/${event.id}/`, text: '◎', 'aria-label': 'Открыть нарушение' }),
    el('a', { className: 'button button--icon', href: `/api/v1/violations/${event.id}/report.pdf`, text: '↓', 'aria-label': 'Скачать PDF отчёт' })]);
  if (canRetry && event.deliveries.some(item => ['FAILED', 'DEAD', 'SKIPPED_DISABLED'].includes(item.status))) {
    const retry = el('button', { className: 'button button--icon', type: 'button', text: '↻', 'aria-label': 'Повторить неуспешные отправки' });
    retry.addEventListener('click', () => run(async () => {
      const result = await api(`/api/v1/violations/${event.id}/resend`, { method: 'POST' });
      toast(`Поставлено отправок: ${result.queued}`);
    }, retry)); actions.append(retry);
  }
  return actions;
}

/** Рендерит строку истории без raw HTML и без вымышленных status badges. */
function eventRow(event) {
  const photo = event.media.annotated_url ? el('a', { href: `/violations/${event.id}/` }, [el('img', { className: 'table__photo', src: event.media.annotated_url, alt: `Фото: ${event.camera.name}`, loading: 'lazy' })]) : el('span', { text: '—' });
  const states = el('div', {}, event.deliveries.map(item => badge(item.channel, item.status)));
  if (!event.deliveries.length) states.append(el('span', { text: 'Нет получателей' }));
  return el('tr', {}, [el('td', { text: formatDate(event.detected_at) }), el('td', { text: event.camera.name }),
    el('td', { className: `table__direction ${event.direction === 'EXIT' ? 'table__direction--exit' : ''}`, text: event.direction === 'ENTRY' ? '→ Вход на территорию' : '↗ Выход с территории' }),
    el('td', {}, [photo]), el('td', {}, [states]), el('td', {}, [eventActions(event)])]);
}

/** Загружает страницу latest/history и показывает пустое состояние при отсутствии событий. */
async function loadHistory() {
  const monitoring = document.body.dataset.page === 'monitoring';
  const result = await api(`/api/v1/violations?${new URLSearchParams({ ...query, page, page_size: monitoring ? 5 : 25 })}`);
  const body = document.querySelector('[data-violation-rows]');
  body.replaceChildren(...result.data.map(eventRow));
  if (!result.data.length) body.append(el('tr', {}, [el('td', { colSpan: 6, className: 'table__empty', text: 'Нарушений за выбранный период нет.' })]));
  if (!monitoring) {
    document.querySelector('[data-page-label]').textContent = `Страница ${page} из ${Math.max(1, result.meta.pages)} · ${result.meta.total} событий`;
    document.querySelector('[data-page-prev]').disabled = page === 1;
    document.querySelector('[data-page-next]').disabled = page >= result.meta.pages;
  }
}

/** Загружает подробности и protected media одного события. */
async function detail() {
  const id = document.body.dataset.objectId;
  const event = await api(`/api/v1/violations/${id}`);
  const values = { 'ID события': event.id, 'Камера': event.camera.name, 'Местоположение': event.camera.location,
    'Дата и время': formatDate(event.detected_at), 'Направление': event.direction === 'ENTRY' ? 'Вход' : 'Выход',
    'Confidence': event.confidence.toFixed(2), 'Track ID': event.track_id };
  document.querySelector('[data-event-details]').replaceChildren(...Object.entries(values).flatMap(([key, value]) => [el('dt', { text: key }), el('dd', { text: value })]));
  const photos = document.querySelector('[data-event-photos]');
  for (const [kind, title] of [['original', 'Оригинальный кадр'], ['annotated', 'Размеченный кадр']]) {
    if (event.media[`${kind}_url`]) photos.append(el('article', {}, [el('h2', { className: 'panel__title', text: title }),
      el('img', { className: 'evidence', src: event.media[`${kind}_url`], alt: title }),
      el('a', { className: 'button', href: event.media[`${kind}_url`], download: `${kind}.jpg`, text: 'Скачать фотографию' })]));
  }
  if (event.media.clip_url) photos.append(el('video', { className: 'evidence', src: event.media.clip_url, controls: true }));
  document.querySelector('[data-event-actions]').append(eventActions(event));
  const history = document.querySelector('[data-event-deliveries]');
  if (!event.deliveries.length) history.append(el('p', { className: 'panel__hint', text: 'На момент события получателей не было.' }));
  for (const item of event.deliveries) {
    const delivery = await api(`/api/v1/notification-deliveries/${item.id}`);
    history.append(el('article', { className: 'delivery' }, [el('span', { text: delivery.target }), badge(item.channel, item.status),
      el('p', { className: 'delivery__attempts', text: delivery.attempts.map(attempt => `${formatDate(attempt.created_at)} · ${attempt.status} ${attempt.error_code}`).join('\n') || 'Попыток отправки нет.' })]));
  }
}

if (document.querySelector('[data-violation-rows]')) {
  await run(async () => { await cameraOptions(); await loadHistory(); });
  document.querySelector('[data-violation-filter]')?.addEventListener('submit', event => { event.preventDefault(); query = filters(event.currentTarget); page = 1; run(loadHistory, event.submitter); });
  document.querySelector('[data-page-prev]')?.addEventListener('click', () => { page--; run(loadHistory); });
  document.querySelector('[data-page-next]')?.addEventListener('click', () => { page++; run(loadHistory); });
  setInterval(() => run(loadHistory), 10000);
}
if (document.querySelector('[data-event-details]')) await run(detail);
