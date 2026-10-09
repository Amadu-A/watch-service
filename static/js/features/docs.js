// static/js/features/docs.js
/** Локальная читаемая OpenAPI справка, все endpoint schemas доступны без CDN. */
import { api } from '../api.js';
import { el, run } from '../components/ui.js';

await run(async () => {
  const schema = await api('/api/schema/?format=json');
  document.querySelector('[data-api-docs]').replaceChildren(...Object.entries(schema.paths).map(([path, methods]) => {
    const detail = el('details', { className: 'delivery' }, [el('summary', { text: path })]);
    for (const [method, operation] of Object.entries(methods)) detail.append(el('section', {}, [el('h2', { className: 'panel__title', text: method.toUpperCase() }), el('pre', { text: JSON.stringify(operation, null, 2) })]));
    return detail;
  }));
});
