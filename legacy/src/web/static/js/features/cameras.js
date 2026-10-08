// src/web/static/js/features/cameras.js
/** RTSP camera CRUD, server-side test и доступный normalized line editor. */
import { api } from '../api.js';
import { el, run, toast } from '../components/ui.js';
import { normalizedPoint } from './layout-state.js';

const admin = document.body.dataset.canConfigure === 'true';
const cameraId = document.body.dataset.objectId;

/** Строит write-only RTSP command, включая изменение credentials только при новом URL. */
function cameraCommand(form) {
  const data = Object.fromEntries(new FormData(form));
  const command = { name: data.name, location: data.location };
  if (form.elements.enabled) command.enabled = form.elements.enabled.checked;
  if (data.url) command.rtsp = { url: data.url, username: data.username, password: data.password };
  return command;
}

/** Загружает каталог камер без чтения credentials. */
async function catalog() {
  const cameras = await api('/api/v1/cameras');
  document.querySelector('[data-camera-catalog]').replaceChildren(...cameras.map(camera => el('article', { className: 'camera-catalog__item' }, [
    el('div', {}, [el('h3', { text: camera.name }), el('p', { className: 'panel__hint', text: `${camera.location || 'Место не задано'} · ${camera.status}` })]),
    el('a', { className: 'button', href: `/cameras/${camera.id}/`, text: admin ? 'Настроить' : 'Открыть' })])));
  if (!cameras.length) document.querySelector('[data-camera-catalog]').append(el('p', { className: 'empty', text: 'Камеры пока не зарегистрированы.' }));
}

if (document.querySelector('[data-camera-catalog]')) {
  await run(catalog);
  document.querySelector('[data-camera-create]')?.addEventListener('submit', event => {
    event.preventDefault(); run(async () => {
      const camera = await api('/api/v1/cameras', { method: 'POST', body: cameraCommand(event.currentTarget) });
      location.assign(`/cameras/${camera.id}/`);
    }, event.submitter);
  });
}

if (cameraId && document.querySelector('[data-line-form]')) {
  const lineForm = document.querySelector('[data-line-form]');
  const cameraForm = document.querySelector('[data-camera-update]');
  const overlay = document.querySelector('[data-line-overlay]');
  const image = document.querySelector('[data-line-image]');
  let pointIndex = 0;

  /** Рисует line из numeric inputs; позволяет исправлять точки с клавиатуры. */
  function draw() {
    const values = ['start_x', 'start_y', 'end_x', 'end_y'].map(key => Number(lineForm.elements[key].value) * 1000);
    const shape = document.querySelector('[data-line-shape]');
    for (const [index, key] of ['x1', 'y1', 'x2', 'y2'].entries()) shape.setAttribute(key, values[index]);
    for (const [selector, offset] of [['[data-line-start]', 0], ['[data-line-end]', 2]]) {
      const circle = document.querySelector(selector); circle.setAttribute('cx', values[offset]); circle.setAttribute('cy', values[offset + 1]);
    }
  }

  /** Получает реальный размер snapshot и избегает смещения линии из-за letterboxing. */
  image.addEventListener('load', () => {
    image.parentElement.style.aspectRatio = `${image.naturalWidth} / ${image.naturalHeight}`;
    document.querySelector('[data-camera-offline]').hidden = true;
  });
  image.addEventListener('error', () => { document.querySelector('[data-camera-offline]').hidden = false; });
  await run(async () => {
    const [camera, line, system] = await Promise.all([api(`/api/v1/cameras/${cameraId}`), api(`/api/v1/cameras/${cameraId}/guard-line`), api('/api/v1/system-settings')]);
    document.querySelector('[data-camera-name]').textContent = camera.name;
    for (const key of ['name', 'location']) cameraForm.elements[key].value = camera[key];
    cameraForm.elements.enabled.checked = camera.enabled;
    image.src = `/api/v1/cameras/${cameraId}/snapshot`;
    if (line) {
      for (const point of ['start', 'end']) for (const axis of ['x', 'y']) lineForm.elements[`${point}_${axis}`].value = line[point][axis];
      for (const key of ['inside_side', 'direction', 'min_confidence']) lineForm.elements[key].value = line[key];
      lineForm.elements.enabled.checked = line.enabled; draw();
    } else lineForm.elements.min_confidence.value = system.default_confidence;
    if (!admin) for (const input of [...lineForm.elements, ...cameraForm.elements]) input.disabled = true;
  });
  const refreshFrame = el('button', { type: 'button', className: 'button', text: 'Обновить кадр' });
  refreshFrame.addEventListener('click', () => { image.src = `/api/v1/cameras/${cameraId}/snapshot?t=${Date.now()}`; });
  image.parentElement.after(refreshFrame);
  overlay.addEventListener('pointerdown', event => {
    if (!admin || !image.naturalWidth) return;
    const point = normalizedPoint(event.clientX, event.clientY, overlay.getBoundingClientRect());
    const prefix = pointIndex++ % 2 === 0 ? 'start' : 'end';
    lineForm.elements[`${prefix}_x`].value = point.x.toFixed(3); lineForm.elements[`${prefix}_y`].value = point.y.toFixed(3); draw();
  });
  lineForm.addEventListener('input', draw);
  lineForm.addEventListener('submit', event => { event.preventDefault(); run(async () => {
    const values = Object.fromEntries(new FormData(lineForm));
    await api(`/api/v1/cameras/${cameraId}/guard-line`, { method: 'PUT', body: {
      start: { x: Number(values.start_x), y: Number(values.start_y) }, end: { x: Number(values.end_x), y: Number(values.end_y) },
      inside_side: values.inside_side, direction: values.direction, min_confidence: Number(values.min_confidence), enabled: lineForm.elements.enabled.checked } });
    toast('Контрольная линия сохранена.');
  }, event.submitter); });
  cameraForm.addEventListener('submit', event => { event.preventDefault(); run(async () => {
    await api(`/api/v1/cameras/${cameraId}`, { method: 'PATCH', body: cameraCommand(cameraForm) });
    cameraForm.elements.password.value = ''; toast('Камера сохранена.');
  }, event.submitter); });
  document.querySelector('[data-test-connection]')?.addEventListener('click', event => run(async () => {
    const result = await api(`/api/v1/cameras/${cameraId}/test-connection`, { method: 'POST', timeout: 15000 });
    toast(result.connected ? 'RTSP: кадр получен.' : 'RTSP: кадр недоступен.', !result.connected);
  }, event.currentTarget));
  document.querySelector('[data-camera-disable]')?.addEventListener('click', event => run(async () => {
    await api(`/api/v1/cameras/${cameraId}`, { method: 'DELETE' }); cameraForm.elements.enabled.checked = false; toast('Камера отключена.');
  }, event.currentTarget));
}
