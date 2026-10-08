// src/web/static/js/features/schedule.js
/** Weekly schedule editor с midnight intervals, IANA timezone и явным сохранением. */
import { api } from '../api.js';
import { el, run, toast } from '../components/ui.js';

const days = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'];
const labels = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'];
const form = document.querySelector('[data-schedule-form]');
const admin = document.body.dataset.canConfigure === 'true';

/** Добавляет независимую строку interval; 24:00 поддерживается text input. */
function addInterval(day = 'monday', start = '19:00', end = '08:00') {
  const weekday = el('select', { name: 'weekday', disabled: !admin, 'aria-label': 'День недели' }, days.map((value, index) => el('option', { value, text: labels[index] })));
  weekday.value = day;
  const row = el('div', { className: 'schedule__row', 'data-interval': '' }, [weekday,
    el('input', { name: 'start', value: start, required: true, pattern: '(?:[01][0-9]|2[0-3]):[0-5][0-9]', disabled: !admin, 'aria-label': 'Начало HH:MM' }),
    el('span', { className: 'schedule__arrow', text: '→' }),
    el('input', { name: 'end', value: end, required: true, pattern: '(?:[01][0-9]|2[0-3]):[0-5][0-9]|24:00', disabled: !admin, 'aria-label': 'Конец HH:MM' })]);
  if (admin) {
    const remove = el('button', { type: 'button', className: 'button button--icon', text: '×', 'aria-label': 'Удалить интервал' });
    remove.addEventListener('click', () => row.remove()); row.append(remove);
  }
  form.querySelector('[data-schedule-intervals]').append(row);
}

if (form) {
  await run(async () => {
    const [schedule, zones] = await Promise.all([api('/api/v1/control-schedule'), api('/api/v1/timezones')]);
    form.elements.timezone.replaceChildren(...zones.map(zone => el('option', { value: zone, text: zone })));
    form.elements.timezone.value = schedule.timezone;
    form.elements.enabled.checked = schedule.enabled;
    for (const day of days) for (const interval of schedule.week[day] || []) addInterval(day, interval.start, interval.end);
  });
  form.querySelector('[data-interval-add]')?.addEventListener('click', () => addInterval());
  form.addEventListener('submit', event => {
    event.preventDefault();
    run(async () => {
      const week = Object.fromEntries(days.map(day => [day, []]));
      for (const row of form.querySelectorAll('[data-interval]')) week[row.querySelector('[name=weekday]').value].push({ start: row.querySelector('[name=start]').value, end: row.querySelector('[name=end]').value });
      const saved = await api('/api/v1/control-schedule', { method: 'PUT', body: { timezone: form.elements.timezone.value, enabled: form.elements.enabled.checked, week } });
      document.body.dataset.timezone = saved.timezone; toast('Расписание сохранено.');
    }, event.submitter);
  });
}
