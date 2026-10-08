
 // tests/frontend/layout.test.mjs
 /**
  * Регрессионные проверки раскладки камер.
  *
  * Контролируют количество столбцов, перестановку камер
  * и нормализованные координаты контрольной линии.
  */

 import test from 'node:test';
 import assert from 'node:assert/strict';

 import {
   gridColumns,
   normalizedPoint,
   reorder,
 } from '../../src/static/static/js/features/layout-state.js';

 test('Сетка автоматически растёт после четырёх камер', () => {
   assert.equal(gridColumns(1), 1);
   assert.equal(gridColumns(2), 2);
   assert.equal(gridColumns(4), 2);
   assert.equal(gridColumns(6), 3);
   assert.equal(gridColumns(16), 4);
   assert.equal(gridColumns(6, '2'), 2);
 });

 test('Перетаскивание сохраняет UUID без потерь и дубликатов', () => {
   assert.deepEqual(
     reorder(['a', 'b', 'c'], 'c', 'a'),
     ['c', 'a', 'b'],
   );

   assert.deepEqual(
     reorder(['a', 'b', 'c'], 'a', 'c'),
     ['b', 'a', 'c'],
   );

   assert.deepEqual(
     reorder(['a'], 'unknown', 'a'),
     ['a'],
   );
 });

 test('Линия сохраняет координаты в долях реального snapshot', () => {
   const rectangle = {
     left: 100,
     top: 100,
     width: 400,
     height: 200,
   };

   assert.deepEqual(
     normalizedPoint(300, 200, rectangle),
     { x: 0.5, y: 0.5 },
   );

   assert.deepEqual(
     normalizedPoint(0, 900, rectangle),
     { x: 0, y: 1 },
   );
 });
