// static/js/features/notifications.js
/** Business settings, runtime gate, recipient CRUD и delivery history с attempts. */
import { api } from '../api.js';
import { activate, badge, el, formatDate, run, toast } from '../components/ui.js';

const settingsForm = document.querySelector('[data-notification-settings]');
const recipientForm = document.querySelector('[data-recipient-form]');
let recipients = [], historyPage = 1;

/** Показывает deployment hard flags независимо от сохранённых UI switches. */
async function settings() {
  const data = await api('/api/v1/notification-settings');
  for (const key of ['global_enabled', 'email_enabled', 'telegram_enabled']) settingsForm.elements[key].checked = data[key];
  const allowed = data.runtime_enabled && data.global_enabled && ((data.email_runtime_enabled && data.email_enabled) || (data.telegram_runtime_enabled && data.telegram_enabled));
  const notice = document.querySelector('[data-runtime-notice]');
  notice.textContent = !data.runtime_enabled ? 'Отключено конфигурацией: внешняя отправка заблокирована.' : `Разрешённые сервером каналы: ${data.email_runtime_enabled ? 'Email' : ''} ${data.telegram_runtime_enabled ? 'Telegram' : ''}.`;
  document.querySelector('[data-notification-test]')?.toggleAttribute('disabled', !allowed);
}

/** Загружает адресаты и даёт edit/delete действия только administrator UI. */
async function loadRecipients() {
  if (!recipientForm) return;
  recipients = await api('/api/v1/notification-recipients');
  document.querySelector('[data-recipients]').replaceChildren(...recipients.map(recipient => {
    const edit = el('button', { className: 'button', type: 'button', text: 'Изменить' });
    edit.addEventListener('click', () => {
      for (const key of ['id', 'channel', 'target', 'display_name']) recipientForm.elements[key].value = recipient[key];
      recipientForm.elements.enabled.checked = recipient.enabled; recipientForm.elements.target.focus();
    });
    const remove = el('button', { className: 'button button--danger', type: 'button', text: 'Удалить' });
    remove.addEventListener('click', () => run(async () => {
      await api(`/api/v1/notification-recipients/${recipient.id}`, { method: 'DELETE' });
      await loadRecipients(); toast('Получатель удалён.');
    }, remove));
    return el('li', { className: 'camera-list__item' }, [el('span', { className: 'camera-list__name', text: `${recipient.channel}: ${recipient.target}${recipient.enabled ? '' : ' (выключен)'}` }), edit, remove]);
  }));
}

/** Показывает пагинированные доставки и запрашивает подробности attempts по требованию. */
async function history() {
  const root = document.querySelector('[data-delivery-history]');
  if (!root) return;
  const result = await api(`/api/v1/notification-deliveries?page=${historyPage}&page_size=25`);
  root.replaceChildren(...result.data.map(item => {
    const details = el('details', { className: 'delivery__attempts' }, [el('summary', { text: `История попыток (${item.attempt_count})` })]);
    details.addEventListener('toggle', () => {
      if (details.open && details.childElementCount === 1) run(async () => {
        const data = await api(`/api/v1/notification-deliveries/${item.id}`);
        details.append(el('p', { text: data.attempts.map(attempt => `${formatDate(attempt.created_at)} · ${attempt.status} ${attempt.error_code}`).join(' | ') || 'Попыток нет.' }));
      });
    });
    const row = el('article', { className: 'delivery' }, [el('span', { text: `${formatDate(item.created_at)} · ${item.target}` }), badge(item.channel, item.status), details]);
    if (item.violation_id) row.prepend(el('a', { href: `/violations/${item.violation_id}/`, text: 'Нарушение' }));
    if (document.body.dataset.canRetry === 'true' && ['FAILED', 'DEAD', 'SKIPPED_DISABLED'].includes(item.status)) {
      const retry = el('button', { className: 'button', type: 'button', text: 'Повторить' });
      retry.addEventListener('click', () => run(async () => { await api(`/api/v1/notification-deliveries/${item.id}/retry`, { method: 'POST' }); await history(); toast('Отправка поставлена в очередь.'); }, retry));
      row.append(retry);
    }
    return row;
  }));
  if (!result.data.length) root.append(el('p', { className: 'empty', text: 'Отправок пока нет.' }));
  document.querySelector('[data-delivery-page]').textContent = `${historyPage} / ${Math.max(1, result.meta.pages)}`;
  document.querySelector('[data-delivery-prev]').disabled = historyPage === 1;
  document.querySelector('[data-delivery-next]').disabled = historyPage >= result.meta.pages;
}

if (settingsForm) {
  settingsForm.inert = true;
  settingsForm.addEventListener('submit', event => { event.preventDefault(); run(async () => {
    await api('/api/v1/notification-settings', { method: 'PATCH', body: Object.fromEntries(['global_enabled', 'email_enabled', 'telegram_enabled'].map(key => [key, settingsForm.elements[key].checked])) });
    await settings(); toast('Настройки уведомлений сохранены.');
  }, event.submitter); });
  document.querySelector('[data-notification-test]')?.addEventListener('click', event => run(async () => {
    const result = await api('/api/v1/notifications/test', { method: 'POST' }); toast(`Тестовых отправок в очереди: ${result.queued}`); await history();
  }, event.currentTarget));
  recipientForm?.addEventListener('submit', event => { event.preventDefault(); run(async () => {
    const data = Object.fromEntries(new FormData(recipientForm));
    await api(`/api/v1/notification-recipients${data.id ? `/${data.id}` : ''}`, { method: data.id ? 'PATCH' : 'POST', body: { channel: data.channel, target: data.target, display_name: data.display_name, enabled: recipientForm.elements.enabled.checked } });
    recipientForm.reset(); await loadRecipients(); toast('Получатель сохранён.');
  }, event.submitter); });
  document.querySelector('[data-delivery-prev]')?.addEventListener('click', () => { historyPage--; run(history); });
  document.querySelector('[data-delivery-next]')?.addEventListener('click', () => { historyPage++; run(history); });
  if (document.querySelector('[data-delivery-history]')) setInterval(() => run(history), 10000);
  await run(async () => {
    await settings(); await loadRecipients(); await history();
    activate(settingsForm);
    activate(recipientForm);
  });
}
