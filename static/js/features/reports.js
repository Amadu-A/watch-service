// static/js/features/reports.js
/** Генерация PDF/CSV по filters и персональная история download links. */
import { api } from '../api.js';
import { activate, el, filters, formatDate, run, toast } from '../components/ui.js';

const form = document.querySelector('[data-report-form]');

/** Загружает только отчёты текущего пользователя. */
async function history() {
  const items = await api('/api/v1/reports');
  const root = document.querySelector('[data-report-history]');
  root.replaceChildren(...items.map(item => el('article', { className: 'delivery' }, [el('span', { text: `${formatDate(item.created_at)} · ${item.format} · ${item.status}` }), el('a', { className: 'button', href: item.download_url, text: 'Скачать отчёт' })])));
  if (!items.length) root.append(el('p', { className: 'empty', text: 'Сформированных отчётов пока нет.' }));
}

if (form) {
  form.addEventListener('submit', event => { event.preventDefault(); run(async () => {
    const values = filters(form); const format = values.format; delete values.format;
    await api('/api/v1/reports', { method: 'POST', body: { type: 'VIOLATIONS', format, filters: values }, timeout: 120000 });
    await history(); toast('Отчёт готов.');
  }, event.submitter); });
  await run(async () => {
    const cameras = await api('/api/v1/cameras');
    form.elements.camera_id.append(...cameras.map(camera => el('option', { value: camera.id, text: camera.name })));
    await history();
    activate(form);
  });
}
