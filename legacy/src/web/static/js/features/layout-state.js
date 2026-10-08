// src/web/static/js/features/layout-state.js
/** Чистые операции раскладки камер, независимые от DOM и пригодные для regression tests. */

/** Автоматически выбирает столбцы без ограничения четырьмя камерами. */
export function gridColumns(count, grid = 'auto') {
  return grid === 'auto' ? Math.max(1, Math.ceil(Math.sqrt(count))) : Number(grid);
}

/** Перемещает существующий UUID перед другим UUID, сохраняя уникальность и порядок. */
export function reorder(ids, moving, target) {
  if (!ids.includes(moving) || !ids.includes(target) || moving === target) return [...ids];
  const next = ids.filter(id => id !== moving);
  next.splice(next.indexOf(target), 0, moving);
  return next;
}

/** Переводит mouse/touch позицию в ограниченные normalized coordinates snapshot. */
export function normalizedPoint(x, y, rectangle) {
  return { x: Math.max(0, Math.min(1, (x - rectangle.left) / rectangle.width)),
    y: Math.max(0, Math.min(1, (y - rectangle.top) / rectangle.height)) };
}
