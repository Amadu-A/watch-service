// static/js/features/settings.js
/** Изменение несекретных настроек объекта с серверным потолком retention. */
import { api } from '../api.js';
import { activate, run, toast } from '../components/ui.js';

const form = document.querySelector('[data-system-settings]');
if (form) {
  form.inert = true;
  form.addEventListener('submit', event => { event.preventDefault(); run(async () => {
    await api('/api/v1/system-settings', { method: 'PATCH', body: { default_timezone: form.elements.default_timezone.value,
      media_retention_days: Number(form.elements.media_retention_days.value), default_confidence: Number(form.elements.default_confidence.value) } });
    toast('Настройки объекта сохранены.');
  }, event.submitter); });
  await run(async () => {
    const data = await api('/api/v1/system-settings');
    for (const key of ['default_timezone', 'media_retention_days', 'default_confidence']) form.elements[key].value = data[key];
    form.elements.media_retention_days.max = data.retention_limit;
    if (document.body.dataset.canConfigure !== 'true') for (const input of form.elements) input.disabled = true;
    activate(form);
  });
}
