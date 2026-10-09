// static/js/features/monitoring.js
/** Dashboard camera selection, persistent ordering, fullscreen и фактическая статистика. */
import { api } from '../api.js';
import { activate, el, formatDate, run, toast } from '../components/ui.js';
import { gridColumns, reorder } from './layout-state.js';

let cameras = [], layout = { camera_ids: [], grid: 'auto' }, dragged;
const grid = document.querySelector('[data-camera-grid]');
const selected = document.querySelector('[data-selected-cameras]');
const selector = document.querySelector('[data-camera-selector]');
let streamTimer;

/** Создаёт защищённую live card; offline никогда не изображается как LIVE. */
function cameraCard(camera) {
  const offline = el('p', { className: 'camera-card__offline', text: 'Камера недоступна · ожидание подключения' });
  const online = camera.status === 'ONLINE' && camera.enabled;
  const photo = el('img', { className: 'camera-card__image', alt: `Видео: ${camera.name}`, hidden: !online });
  const live = el('span', { className: 'camera-card__live', text: '● LIVE', hidden: !online });
  offline.hidden = online;
  const title = el('h2', { className: 'camera-card__title', text: camera.name });
  title.prepend(el('span', { className: `status-dot ${online ? 'status-dot--online' : ''}` }));
  const card = el('article', { className: 'camera-card', 'data-camera-id': camera.id }, [photo, offline, title, live,
    el('time', { className: 'camera-card__time', text: formatDate(camera.last_seen) })]);
  photo.addEventListener('error', () => { photo.hidden = true; offline.hidden = false; live.hidden = true; });
  if (online) photo.src = `/api/v1/cameras/${camera.id}/stream.mjpeg`;
  const fullscreen = el('button', { className: 'button button--icon camera-card__fullscreen', type: 'button',
    text: '⛶', 'aria-label': `Полный экран: ${camera.name}` });
  fullscreen.addEventListener('click', () => run(() => card.requestFullscreen(), fullscreen));
  card.append(fullscreen);
  return card;
}

/** Перерисовывает selection и grid после подтверждённого изменения layout. */
function render() {
  clearInterval(streamTimer);
  grid.style.setProperty('--camera-columns', gridColumns(layout.camera_ids.length, layout.grid));
  const chosen = layout.camera_ids.map(id => cameras.find(camera => camera.id === id)).filter(Boolean);
  grid.replaceChildren(...chosen.map(cameraCard));
  if (!chosen.length) grid.append(el('p', { className: 'empty', text: 'Добавьте зарегистрированную камеру в наблюдение.' }));
  document.querySelector('[data-camera-count]').textContent = `${chosen.length} камер`;
  document.querySelector('[data-grid]').value = layout.grid;
  selector.replaceChildren(el('option', { value: '', text: 'Добавить камеру…' }), ...cameras.filter(camera => !layout.camera_ids.includes(camera.id)).map(camera => el('option', { value: camera.id, text: camera.name })));
  selected.replaceChildren(...chosen.map((camera, index) => {
    const item = el('li', { className: 'camera-list__item', draggable: true, 'data-selected-id': camera.id }, [
      el('span', { className: 'camera-list__handle', text: '⠿', 'aria-hidden': 'true' }),
      el('span', { className: `status-dot ${camera.status === 'ONLINE' ? 'status-dot--online' : ''}` }),
      el('span', { className: 'camera-list__name', text: camera.name })]);
    const up = el('button', { className: 'button button--icon', type: 'button', text: '↑', disabled: index === 0, 'aria-label': `Поднять ${camera.name}` });
    up.addEventListener('click', () => run(() => save({ ...layout, camera_ids: reorder(layout.camera_ids, camera.id, chosen[index - 1].id) }), up));
    const remove = el('button', { className: 'button button--icon', type: 'button', text: '×', 'aria-label': `Убрать ${camera.name}` });
    remove.addEventListener('click', () => run(() => save({ ...layout, camera_ids: layout.camera_ids.filter(id => id !== camera.id) }), remove));
    item.addEventListener('dragstart', event => { dragged = camera.id; event.dataTransfer.setData('text/plain', camera.id); });
    item.addEventListener('dragover', event => event.preventDefault());
    item.addEventListener('drop', event => { event.preventDefault(); run(() => save({ ...layout, camera_ids: reorder(layout.camera_ids, dragged, camera.id) })); });
    item.append(up, remove);
    return item;
  }));
  // Django завершает MJPEG через минуту; browser регулярно открывает новое auth соединение.
  streamTimer = setInterval(() => {
    for (const image of grid.querySelectorAll('img')) if (!image.hidden) image.src = image.src.split('?')[0] + `?t=${Date.now()}`;
  }, 55000);
}

/** Записывает layout через сервер; при ошибке прежний UI остаётся согласованным. */
async function save(next) {
  layout = await api('/api/v1/users/me/monitoring-layout', { method: 'PUT', body: next });
  render();
}

/** Загружает выбранный statistics period, включая пользовательский interval. */
async function loadStatistics(validate = false) {
  const period = document.querySelector('[data-statistics-period]').value;
  const custom = document.querySelector('[data-statistics-custom]');
  custom.hidden = period !== 'custom';
  let query = { period };
  if (period === 'custom') {
    if (!(validate ? custom.reportValidity() : custom.checkValidity())) return;
    query = { period, date_from: new Date(custom.elements.date_from.value).toISOString(), date_to: new Date(custom.elements.date_to.value).toISOString() };
  }
  const data = await api(`/api/v1/statistics/summary?${new URLSearchParams(query)}`);
  document.querySelector('[data-statistics]').replaceChildren(...[
    ['violations', 'Нарушений', ''], ['email_sent', 'Отправлено Email', 'blue'],
    ['telegram_sent', 'Отправлено Telegram', 'green'], ['delivery_errors', 'Ошибок отправки', 'orange'],
  ].map(([key, text, color]) => el('div', { className: `statistics__card ${color ? `statistics__card--${color}` : ''}` }, [el('strong', { className: 'statistics__value', text: data[key] }), el('span', { text })])));
}

if (grid) {
  document.querySelector('[data-add-camera-form]').addEventListener('submit', event => {
    event.preventDefault();
    run(async () => {
      if (!selector.value) return toast('Выберите зарегистрированную камеру.');
      await save({ ...layout, camera_ids: [...layout.camera_ids, selector.value] });
    }, event.submitter);
  });
  document.querySelector('[data-grid]').addEventListener('change', event => run(() => save({ ...layout, grid: event.target.value })));
  document.querySelector('[data-grid-fullscreen]').addEventListener('click', event => run(() => grid.requestFullscreen(), event.currentTarget));
  document.querySelector('[data-statistics-period]').addEventListener('change', () => run(loadStatistics));
  document.querySelector('[data-statistics-custom]').addEventListener('submit', event => { event.preventDefault(); run(() => loadStatistics(true), event.submitter); });
  setInterval(() => run(async () => {
    const next = await api('/api/v1/cameras');
    if (next.map(camera => camera.id + camera.status + camera.name).join() !== cameras.map(camera => camera.id + camera.status + camera.name).join()) { cameras = next; render(); }
    await loadStatistics();
  }), 10000);
  await run(async () => {
    [cameras, layout] = await Promise.all([api('/api/v1/cameras'), api('/api/v1/users/me/monitoring-layout')]);
    render(); await loadStatistics();
    activate(document.querySelector('[data-add-camera-form]'));
  });
}
