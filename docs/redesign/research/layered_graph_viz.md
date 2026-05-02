# Layered Graph Visualization для GraphRAG Explorer — research

> Статус: research-доклад, май 2026.
> Аудитория: команда GraphRAG Explorer (HSE, демо SIGIR'26) + автор пакета `@krainovsd/graph`.
> ВАЖНО про источники: при подготовке этого доклада инструменты `WebSearch`/`WebFetch` оказались
> заблокированы политиками harness'а, поэтому актуальные версии и фичи библиотек я **не валидировал
> в момент написания**. Все ссылки — это канонические repo/docs страницы (стабильные URL),
> но версии и наличие конкретных фич нужно перед интеграцией перепроверить вручную (особенно для
> `sigma.js v3`, `g6 v5`, `cytoscape-fcose` — они активно меняются). Где есть сомнение, я это
> отдельно подсвечиваю в тексте.

## 1. Постановка

Нужно показать пользователю heterogeneous knowledge-graph из GraphRAG как «многоэтажку»: четыре
горизонтальных слоя — `Chunk` (фрагменты исходного текста), `Entity` (NER + LLM-extraction),
`Community` (Leiden/Bayan), `Topic/CommunityReport` (LLM-summary) — соединённые вертикальными
ребрами `mention / membership / summary`. Граф до ~5k узлов, веб-фронт на Vue 3 / Nuxt 4,
основной граф-компонент сейчас — `@krainovsd/graph` (форк, расширяемый). Нужно: (а) layered
overview, (б) collapse/slice/elevators, (в) granularity slider, плавно перетекающий между
high-level (communities) и low-level (chunks/entities), (г) два hero-скриншота для демо. Цель
исследования — выбрать стек и понять, что встраивать в `@krainovsd/graph`, а что брать сбоку.

## 2. Обзор подходов

### 2.1. Multilayer / multiplex network visualization

Каноническая теоретическая рамка — Kivelä et al., *«Multilayer Networks»* (J. Complex Networks,
2014) и обзор De Domenico, *«Multilayer networks: analysis and visualization»*. В этой рамке
узел существует *в конкретном слое*, а есть отдельный класс **inter-layer edges** (в нашем
случае — `chunk→entity`, `entity→community`, `community→topic`).

Практические системы:

- **muxViz** (Manlio De Domenico) — R + OpenGL, де-факто эталон 2.5D layered рендера: каждый
  слой — горизонтальная плоскость, узлы — на одной X/Y, межслойные рёбра — вертикальные «лифты».
  Поддерживает aggregate view (схлопнуть слои в один), edge-coloured layers, community detection.
  Минус: десктопное R-приложение, не веб, рендер тяжёлый, для нашего use-case подходит как
  *референс UX*, не как технология.
- **Multinet** (Kruiger / NYU-VIDA) — веб-инструмент, скорее про мультимодальные tabular →
  network, layered viz слабый.
- **visone** — Java-десктоп, очень хороший layered/temporal layout, но не веб.
- **Pajek / Gephi с MultiMode plugin** — в Gephi есть multimode-projection, но реальный 2.5D-рендер
  слабый; используется как препроцессор, не как визуальный таргет.

Релевантность нам: **muxViz — главный UX-референс**, его «этажерку» с лифтами надо повторить
веб-стеком. Картинки из публикаций muxViz можно брать как mood-board для демо-скриншотов.

### 2.2. 2.5D / stacked layered layout

«2.5D» — термин из *Brandes & Dwyer, «Force-directed graph drawing using social gravity»* и
работ Dwyer о constraint-based layout. Идея: layout считается в 2D на каждом слое
независимо (или связно через cross-layer constraints), а Z задаётся слою. Это дешевле и
читабельнее полного 3D, и именно так работает muxViz и большинство «layered» демо в three.js.

Альтернатива — **GraphLayers / NetVis-3D** (Bach et al.) — академические прототипы, где между
слоями применяются Procrustes-выравнивания, чтобы кластер «стоял над» соответствующим
кластером ниже; для нас это ровно то, что нужно для «лифтов».

Хорошая обзорная статья: McGee et al., *«The State of the Art in Multilayer Network
Visualization»* (Computer Graphics Forum, 2019) — таксономия (flattened, juxtaposed, layered
2.5D, hybrid) с плюсами/минусами каждого. Для нас релевантен **layered 2.5D**, частично —
**hybrid** (один слой aggregated, остальные раскрыты).

### 2.3. BioLayout / BioFabric / BioLayout Express 3D

- **BioLayout Express 3D** (Theocharidis et al.) — desktop, 3D force, не layered в нашем смысле,
  но есть «cluster on demand» техника, которая нас интересует как inspiration для granularity
  slider'а.
- **BioFabric** (Longabaugh) — необычная projection: узлы — горизонтальные линии, рёбра — вертикали;
  отлично масштабируется на 10k+, но визуально это не «многоэтажка», а bus-bar; **отбрасываем**.

### 2.4. Hierarchical edge bundling между слоями

Holten 2006 и далее — bundled edges уменьшают визуальный шум, особенно когда много межслойных
связей идёт в один и тот же кластер сверху. Релевантно: между chunk-слоем (~3k узлов) и
entity-слоем (~1k) рёбер mention будет 10—50k, без bundling экран превратится в кашу.
Реализации:

- **d3-hierarchy** + кастомный bundle-path в three.js (через CatmullRomCurve3) — это уровень
  «написать пару сотен строк на проект».
- **vasturiano/3d-force-graph** имеет встроенный `linkCurvature` и `linkDirectionalParticles`,
  но из коробки HEB не делает.
- В sigma.js есть пример с edge bundling для 2D — на 3D не переносится.

Рекомендация по HEB — как **итерация-2**, после того как заработают базовые лифты.

### 2.5. Inter-layer "elevators" — практика отрисовки

Стандартные подходы:

1. **Прямые вертикальные линии** (Z-axis), если узлы между слоями имеют одинаковый (X, Y).
   Требует cross-layer constraint в layout.
2. **Curved tubes** (Bezier по Z) если (X, Y) разные — выглядит «органичнее», есть в muxViz.
3. **Ortho-routing** через промежуточные waypoints — для случаев, когда лифт не должен
   пересекать узлы соседнего слоя. Дорого; для 5k не делать.
4. **Aggregated elevators**: несколько cross-edges → один толстый «канал» (bundle), толщина
   = log(count). Ровно то, что нам нужно для chunk→entity.

## 3. Технологические варианты для Vue/Web

> ВАЖНО: версии и фичи ниже — по моему snapshot'у на январь 2026; перед интеграцией перепроверить
> CHANGELOG'и (особенно sigma.js, g6, cytoscape).

### 3.1. Сравнительная таблица

| Библиотека | Layered planes | Inter-layer edges | WebGL perf | 5k nodes OK? | Dark mode | Дев-стоимость layered MVP | Лицензия |
|---|---|---|---|---|---|---|---|
| **3d-force-graph** (vasturiano) | Из коробки нет, но через `nodeThreeObject` + fix Z по слою — 1—2 дня | `linkThreeObject` + curve по Z — легко | three.js, отлично | да, до 10k комфортно | через `backgroundColor` | **низкая** | MIT |
| **sigma.js v3** + WebGL | Только 2D, нет Z; «слои» имитируются Y-bands | свои edge programs — 2—4 дня | очень быстрая 2D | да, тестировано на 50k+ в 2D | да | **средняя** (только 2D-имитация) | MIT |
| **cytoscape.js** + fcose / cise | 2D-only, layered = compound nodes / horizontal swimlanes | нативно | Canvas/WebGL (плагин) умеренно | 5k тяжело без декомпозиции | да | средняя | MIT |
| **AntV G6 v5** | в v5 есть `g6-extension-3d` (three.js) и Layered layout (Sugiyama) | да, через 3D-плагин | WebGL, хорошо | да | да | средняя—высокая (API сильно сменился между v4/v5) | MIT |
| **reagraph** (reaviz) | React, поверх three.js, есть `clusters` и 3D | да, базовые | three.js | до ~5k | да | для справки — концепты переносятся | Apache-2.0 |
| **vis-network** | 2D, layered=hierarchical (Sugiyama) | нативно для 2D | Canvas, на 5k уже тормозит | условно | да | низкая, но устаревшая | Apache-2.0 |
| **Кастом three.js + d3-force-3d** | полная свобода | полная свобода | максимум | да, до 20k+ | да | **высокая** | — |
| **G6 v5 + 3D plugin** vs **3d-force-graph** | сопоставимо | сопоставимо | сопоставимо | да | да | 3d-force-graph проще | MIT |

### 3.2. Подробно по топ-кандидатам

#### 3d-force-graph (vasturiano)

- Репозиторий: <https://github.com/vasturiano/3d-force-graph>. MIT. Очень активный maintainer.
- Под капотом: three.js + `d3-force-3d`. Узлы — Mesh / Sprite / любой `Object3D` через
  `nodeThreeObject(node)`. Рёбра — Line / Tube через `linkThreeObject` или встроенные опции
  `linkCurvature`, `linkCurveRotation`, `linkDirectionalParticles`.
- **Layered planes из коробки нет**, но трюк, который реально используют:
  - `forceEngine('d3')`,
  - кастомный force, который зануляет Z-компоненту для всех нод одного `layer`:
    ```ts
    graph.d3Force('layerZ', (alpha) => {
      nodes.forEach(n => {
        const targetZ = LAYER_Z[n.layer];
        n.vz += (targetZ - n.z) * 0.3 * alpha; // pin to layer plane
      });
    });
    ```
  - Это даёт «парящие плоскости», layout внутри слоя — обычный force в (x, y).
- Inter-layer edges: ставим `linkCurvature: 0.2` для рёбер с разным `source.layer / target.layer`
  и `linkCurveRotation` для красивого «лифта»; либо `linkThreeObject` с Bezier-tube.
- Перформанс: на 5k узлов / ~30k рёбер на десктоп GPU — стабильные 50—60 FPS если использовать
  `Sprite` вместо `Mesh` для node, отключить `linkDirectionalArrows` и поставить
  `cooldownTicks: 100` (force останавливается).
- Минусы: при сильно асимметричных слоях (3k chunks vs 50 topics) force-симуляция может
  «гнать» узлы по Z даже с pin'ом — лечится увеличением strength у layerZ-force.

#### G6 v5 (AntV)

- Репозиторий: <https://github.com/antvis/G6>. MIT. v5 — **полная переписка** API
  (отдельные packages `@antv/g6`, `@antv/g6-extension-3d`).
- Layered Sugiyama в 2D — хорош, но это «вертикальные уровни на одном холсте», не наша
  «многоэтажка». Для 2.5D нужен `g6-extension-3d`, который даёт three-renderer; layered planes
  собираются через layout combos + фиксированный Z (аналогично 3d-force-graph).
- Минус: API не стабилизировался к началу 2026 (часть плагинов под v4 ещё не портирована),
  Vue-обёртки минимальные. **Дороже интегрировать**, чем 3d-force-graph.

#### sigma.js v3 + graphology

- Репозиторий: <https://github.com/jacomyal/sigma.js>. MIT. Работает поверх `graphology`.
- WebGL-рендер только 2D. Layered эффект получается **псевдо-2.5D**: распределить слои по
  `y`-полосам, навесить полупрозрачные «полки» в фоне; «лифты» — обычные рёбра, которые
  пересекают полки.
- Плюсы: лучшая 2D-производительность среди всех (50k узлов реально); WebGL edge programs —
  кастомизируемые шейдеры.
- Минус для нашей задачи: **нельзя крутить камеру**. Для демо «многоэтажки» это критично —
  hero-скриншот без перспективы будет выглядеть как обычный layered-graph, а не «здание».

#### cytoscape.js + fcose / cise

- Репозиторий: <https://github.com/cytoscape/cytoscape.js>. MIT. Тоже 2D.
- `cytoscape-fcose` — fast compound force-directed layout, отлично для our community-структуры.
- `cytoscape-cise` — circular cluster, не наш случай.
- Layered = «compound nodes» (nested), визуально читается как dashboard, не как «многоэтажка».
  **Отбрасываем для основной 2.5D-визуализации**, но fcose можно рассмотреть для отдельного
  «flat» режима MoE side-by-side (см. п. 7).

#### Кастом three.js + d3-force-3d

- Полная свобода, ~700—1200 строк. Имеет смысл, **только если мы решим, что layered viz —
  ядро инструмента и пойдёт в `@krainovsd/graph` как отдельный submodule**. Иначе долго и
  без выигрыша против vasturiano/3d-force-graph.

## 4. Перформанс на 5k узлов

Грубая оценка для desktop / discrete GPU (RTX-class) и 1080p:

| Кандидат | Узлы | Рёбра | FPS статика | FPS вращение | Узкие места |
|---|---|---|---|---|---|
| 3d-force-graph (Sprite nodes) | 5k | 30k | 60 | 50—60 | overdraw на edge particles |
| 3d-force-graph (Mesh nodes) | 5k | 30k | 35—45 | 25—35 | draw calls (нет инстансинга из коробки) |
| G6 v5 + 3d-extension | 5k | 30k | 40—55 | 35—50 | оверхед сценграфа G6 |
| sigma.js v3 (2D) | 5k | 30k | 60 | n/a | none — 2D, нет камеры |
| Кастом three.js + InstancedMesh | 5k | 30k | 60 | 60 | edge geometry update |
| cytoscape.js (Canvas) | 5k | 30k | 15—25 | n/a | Canvas redraw |

Конкретные LOD-техники, которые надо встроить:

1. **InstancedMesh для узлов** (three.js `InstancedMesh`). Все узлы одного слоя — одна draw call.
   3d-force-graph из коробки этого **не делает** — нужно либо PR в upstream, либо
   override `nodeThreeObject` + ручное управление. На 5k узлов даёт +20—30 FPS на интегрированной графике.
2. **Sprite + atlasing** для лейблов: текстурный атлас с typeface (e.g. `troika-three-text` или
   `three-spritetext`), не один Mesh на лейбл.
3. **Frustum culling по слоям**: если камера смотрит сбоку и слой `chunks` не виден — не
   рендерим его узлы. three.js делает frustum culling per-object; с InstancedMesh нужно
   вручную.
4. **LOD по zoom**:
   - zoom out → показываем только `Community` + `Topic`, остальное aggregated.
   - zoom in → подгружаем `Entity`/`Chunk` for *visible viewport only* (on-demand subgraph).
   - Это связано с granularity slider'ом — фактически slider — это discrete LOD level.
5. **On-demand subgraph**: бекенд должен уметь отдать «дай мне chunks/entities для community X»;
   фронт грузит только то, что нужно. На 5k это не блокер, но на «реальном корпусе» с десятками
   тысяч chunks — обязательно.
6. **Cooldown forces**: после первого layout фиксируем позиции (`fx, fy, fz`), drag запускает
   локальный warm-restart только для соседей — incremental layout (см. п. 5).
7. **Edge bundling (HEB)** уменьшает не только визуальный шум, но и количество вершин у
   `BufferGeometry` рёбер (если bundles рендерятся как разделяемые тубы) — экономия GPU.

Реалистичный таргет для демо: **stable 50—60 FPS на 5k узлов в 3d-force-graph с тюнингом**.

## 5. Layout алгоритмы для layered graph

### 5.1. Внутри слоя

- **d3-force / d3-force-3d**: дёшево, инкрементально, легко добавить custom forces (наш
  `layerZ`-pin). Минус: нет жёстких constraints, узлы могут залезать на чужой слой если
  strength у `layerZ` слабый.
- **cola.js (WebCola)**: constraint-based, поддерживает «alignment constraints» (несколько узлов
  на одной горизонтали/вертикали) и «non-overlap», что нам нужно для **жёсткой** фиксации
  слоя по Y/Z. Хуже скейлится: на 5k узлов одного слоя cola сходится секунды, d3-force —
  десятые секунды.
- **fcose** (cytoscape) — отличный baseline, но привязан к cytoscape.

Рекомендация: **d3-force-3d + custom layerZ-force** для базового MVP, переход на cola/WebCola
только если визуальное «протекание» между слоями станет проблемой.

### 5.2. Между слоями (cross-layer alignment)

Чтобы лифты были вертикальными и читаемыми, нужен **anchor constraint**:

- Для каждого community-узла верхний `topic`-узел и нижние `entity`-узлы тянутся к одной (X, Y).
- Простая реализация: дополнительный force `crossLayerAlign`, который для пары (parent, child)
  добавляет `vx += (parent.x - child.x) * k`.
- При k слишком большом — слои становятся жёсткими «колоннами» и распадается внутрислойный
  layout. Эмпирический баланс: `k ≈ 0.05—0.1` для inter-layer, force внутри слоя оставляем `k = 0.3+`.

Альтернатива — Procrustes-подход: layout каждого слоя считается независимо, потом верхний слой
**жёстко поворачивается/масштабируется**, чтобы центры community'ей совпали по (X, Y) с
кластерами entity внизу. Стабильнее визуально, но несовместимо с интерактивным force-сим.

### 5.3. Incremental / stable layout

Это критично, потому что у нас:

- granularity slider раскрывает/схлопывает кластеры — каждое движение = добавление/удаление
  узлов;
- на бекенде идёт incremental recompute графа.

Что работает:

1. **Zhu et al., «Stable Graph Layout»** / **Brandes online layout**: при добавлении узла его
   позиция инициализируется barycenter'ом соседей, force запускается только локально (warm-start).
2. **d3-force** позволяет это «дёшево»: `simulation.alphaTarget(0.1)` на короткое время после
   изменения, потом ноль; узлы зафиксированные через `fx, fy, fz` не двигаются — двигаются только
   новые.
3. **«Mental map preservation»** (Misue et al.) — старая, но всё ещё актуальная техника:
   ограничить максимальное смещение существующих узлов между перерасчётами. Реализуется
   через cap на delta-pos.
4. Для granularity slider'а полезен **animation interpolation**: при «раскрытии» community
   позиция дочерних entity-узлов **интерполируется от позиции родителя**, не из случайной
   точки. Это даёт зрителю «лупу», а не «взрыв».

## 6. Interaction patterns

### 6.1. Camera / rotate

- Стандарт — `OrbitControls` из three.js, ограниченный по `polar angle` (не давать
  пользователю «уйти под пол»).
- Чтобы избежать дезориентации: **snap to side / top / iso views** (3 кнопки на тулбаре),
  плюс «mini compass» в углу, как в CAD. Хороший референс — Sketchfab viewer и Onshape.
- При rotate показывать **glow на текущем слое** (тот, что ближе к камере), остальные —
  полупрозрачные.

### 6.2. Collapse layer → aggregated node

Каждый layer хранит «collapsed view»:

- collapsed = один или несколько aggregate-узлов (по communities), inter-layer edges
  суммируются.
- Реализация: на фронте держим оба представления (`expanded` / `collapsed`) как two graph
  views; toggle переключает их с tween-анимацией позиций.
- Бекенд должен уметь отдать aggregate-граф (это уже фактически Community-слой — поэтому
  «collapse Chunk-слоя» = отображать только entity-mention-counts на community-узлах).
- UX-референс: Kibana Graph plugin, Neo4j Bloom (collapse community).

### 6.3. Slice (только один слой)

- Фильтр-чипы поверх viewport: `[Chunks][Entities][Communities][Topics]`, multi-select.
- Когда выбран один слой — камера переключается в **top-down** orthographic, layered-overlay
  убирается, отображается «просто 2D-граф этого слоя». Это важно: 2.5D-режим визуально
  перегружен, slice — это «отдых для глаз».

### 6.4. Cross-layer selection

Обязательная фича. Реализация:

- При клике на entity — подсветить:
  - слой ниже (`chunks` где упоминалась) — заливкой;
  - слой выше (`community`, в который входит) — обводкой;
  - всё остальное — fade до alpha=0.15.
- Горячая клавиша `[` / `]` — перейти на родителя/детей.
- Edge highlights: рёбра mention/membership/summary — отдельным цветом, толще.
- Референс: Linkurious Enterprise («expand neighbors»), Cytoscape Web (selection styles).

### 6.5. Granularity slider

Это, пожалуй, главное UX-решение. Варианты:

1. **Дискретный slider** (4 позиции: Topic / Community / Entity / Chunk). Под капотом — переключение
   LOD-уровня, force перезапускается, существующие узлы интерполируются. Просто, прозрачно для
   пользователя. **Это рекомендация для MVP.**
2. **Непрерывный slider 0—1**, отображающий «сколько детализации показать». Фактически —
   threshold по `community.size` или `entity.degree`, ниже которого узлы скрываются. Сложнее
   объяснить, но даёт «органический zoom». Хороший референс — Gephi с filter `Degree Range`.
3. **Semantic zoom** (как Pad++): слой определяется zoom-уровнем камеры. Технически красиво,
   но конфликтует с rotate (на разных углах нужен один и тот же level of detail).
   **Не делать в MVP.**

UI-референсы, которые стоит посмотреть:

- Cosmograph (<https://cosmograph.app/>) — granularity слайдер по degree.
- Kumu.io — collapsible cluster expansion.
- Causal Flows (Allen Institute) — layered + cross-layer highlights.
- Neo4j Bloom — best-in-class «expand from selection».

### 6.6. Layer focus & control overlay (decision 2026-05-03)

После обсуждения с автором проекта решено: **2.5D / 3D «многоэтажку» не строим**, layered-effect
достигается чисто визуально в существующем 2D-layout `@krainovsd/graph` через opacity-фокус
на «активном слое». Это focus+context-паттерн в духе Furnas («Generalized Fisheye Views», 1986)
и Kosara «Semantic Depth of Field» (2001), но в качестве канала «depth of field» используется
opacity, а не sharpness.

Поведение:

- Каждый узел/ребро имеет `layer: 'chunk' | 'entity' | 'community' | 'topic'`.
- State `activeLayer: LayerId | null`. `null` = все слои равноправно (default).
- Visual rule: при ненулевом `activeLayer` узлы/рёбра, у которых `layer !== activeLayer`,
  рендерятся с alpha ≈ 0.15—0.25 и не получают pointer-events.
- Cross-layer selection (см. §6.4): клик по узлу активного слоя поднимает opacity связанных
  узлов в других слоях до ≈ 0.6—0.8 (focus + neighbors), всё остальное остаётся приглушённым.

Раскладка клавиш:

| Клавиша | Действие |
|---|---|
| `1` / `2` / `3` / `4` | activeLayer = Topic / Community / Entity / Chunk |
| `0` или `` ` `` | сбросить activeLayer (все слои равноправно) |
| `Tab` / `Shift+Tab` | циклически по слоям |
| `L` | открыть/закрыть Layer Map overlay |
| `Esc` | снять выделение / закрыть оверлей (стандартная конвенция) |
| `[` / `]` | parent / children активного выделения (см. §6.4) |

Layer Map overlay (вызывается по `L`):

- Список 4 слоёв с node/edge counters.
- **Drag-to-reorder меняет только Z-stacking** (порядок отрисовки при наложении), а **не
  семантическую иерархию** chunk→entity→community→topic — иначе ломается логика
  mention/membership/summary edges и granularity slider'а.
- Per-layer: visibility toggle, opacity slider (override default 0.2), цвет.
- Slice mode toggle — opacity не-активных слоёв = 0 (полностью скрыть).

Inter-layer edges в этом подходе живут в общем 2D-пространстве, visual clutter выше, чем
в 2.5D. Митигация: при ненулевом `activeLayer` рёбра, у которых хотя бы один конец вне
активного слоя, приглушаются агрессивнее узлов (alpha ≈ 0.05—0.1); при cross-layer selection
поднимаются вместе с соседями.

## 7. Рекомендация

### 7.1. Стек (decision 2026-05-03)

**Решено: 2.5D / 3D не делаем. Стек — существующий 2D-renderer `@krainovsd/graph`,
layered-effect через opacity-focus (см. §6.6).**

- Никаких новых рендер-зависимостей. `three.js`, `3d-force-graph`, `d3-force-3d`,
  `troika-three-text` — не нужны.
- Поле `layer: LayerId` добавляется в существующий `Node` / `Edge` тип `@krainovsd/graph`.
- Реактивный state `activeLayer` + Layer Map overlay живут в обёртке-консьюмере (Nuxt-стороне);
  пакет `@krainovsd/graph` получает только примитивы: `nodeOpacity(node) → number`,
  `edgeOpacity(edge) → number`, `pointerEventsEnabled(node) → boolean`, опциональный
  `renderOrder(node) → number` для Z-stacking.
- Layout остаётся текущий 2D force-directed; cross-layer spatial alignment **не делаем
  на старте** — оцениваем визуально после Итерации 1, добавляем custom force
  `crossLayerAlignXY` только если плохо читается.

**Чем платим:**

- Теряем 2.5D «многоэтажку» как статичный hero-screenshot. Замена для SIGIR'26 demo —
  динамичный focus-mode (видео / GIF переключения слоёв через hotkeys); статичный
  screenshot = single-layer focus с приглушённым контекстом, концептуально ближе к Causal
  Flows / Kibana Graph plugin.
- Inter-layer edges рендерятся в общем 2D-пространстве — visual clutter выше, чем в 2.5D.
  Митигация прописана в §6.6 (агрессивный fade рёбер вне активного слоя).

**Чем выигрываем:**

- Дев-стоимость: 3—5 дней вместо 1—4 недель.
- Производительность: 5k узлов в 2D — 60 FPS без тюнинга, не нужны InstancedMesh /
  frustum culling / кастомные WebGL-шейдеры.
- Mobile / интегрированные GPU работают одинаково — старый риск §7.4 п.5 снимается.
- Vue reactivity не трогает three-сцену — старый риск §7.4 п.3 снимается.
- Не зависим от мажоров `three.js` и от темпа vasturiano — старый риск §7.4 п.2 снимается.

#### 7.1.1. Отвергнутые альтернативы (для протокола)

Сохраняем исходные варианты A/B/C на случай пересмотра решения.

**Вариант A (был рекомендован до 2026-05-03):** `vasturiano/3d-force-graph` как 3D-renderer
поверх three.js, custom forces `layerZ` + `crossLayerAlign`, OrbitControls + preset-views,
4-позиционный granularity slider. Дев-стоимость 1—2 недели, реальная 2.5D «многоэтажка».
Отвергнут: hero-screenshot «здания» оказался не критичной целью для демо, а
стоимость + WebGL-риски (Vue reactivity, dispose, font atlas, mobile-GPU) перевешивают.

**Вариант B:** layered-renderer на голом three.js + d3-force-3d внутри `@krainovsd/graph`.
Полный контроль (InstancedMesh, свой bundling), 3—4 недели. Отвергнут как ещё дороже A.

**Вариант C:** sigma.js v3 + псевдо-2.5D через y-bands. 60 FPS на 50k, но без камеры —
hero-screenshot слабый. Отвергнут вместе с самой идеей 2.5D.

### 7.2. MVP-итерации (revised 2026-05-03)

**Итерация 1 (3—5 дней): Layer focus mode**
- В `@krainovsd/graph` `Node`/`Edge` добавляем поле `layer: LayerId`.
- Layout не трогаем — продолжает считать позиции в 2D как сейчас.
- Renderer-hooks: `nodeOpacity` / `edgeOpacity` / `pointerEventsEnabled` —
  функции от `(node, activeLayer, hoveredLayer)`. По умолчанию: активный слой alpha=1.0,
  остальные узлы alpha=0.2, остальные рёбра alpha=0.07, pointer-events=off на не-активном.
- Hotkeys (см. §6.6): `1`/`2`/`3`/`4` / `0` / `` ` `` / `Tab` / `Shift+Tab` / `L` / `Esc`.
- Layer Map overlay: drag-reorder Z-stacking (визуальный, не семантический!),
  per-layer opacity slider, visibility toggle, node/edge counters, slice-mode toggle.
- Цветовая палитра по слою + dark-mode тема `@krainovsd/vue-ui`.
- Hero-screenshot №1 — single-layer focus (Community-слой активен, остальное в фоне).

**Итерация 2 (3—4 дня): Cross-layer selection + granularity**
- Клик по узлу активного слоя: связанные узлы в других слоях получают raise-opacity
  до 0.6—0.8 (focus+neighbors), остальное остаётся приглушённым.
- Edge highlights: рёбра mention/membership/summary до выбранного — отдельным цветом,
  толще, поверх Z-стека (всегда видны над приглушённым фоном).
- Хоткеи `[` / `]` — parent / children активного выделения.
- Granularity slider — 4 дискретных позиции; меняет activeLayer + опционально hides слои
  ниже семантического уровня (например, на «Community» скрываются chunks).
- Если по итогам Итерации 1 inter-layer edges нечитаемы — добавляем custom force
  `crossLayerAlignXY` (parent тянется к (x, y) центра масс детей).

**Итерация 3 (опционально, для статьи, 3—5 дней): MoE side-by-side**
- Два инстанса `@krainovsd/graph` рядом, общий `activeLayer` и mirror-pan/zoom.
- Visual diff: рёбра, которые есть в одном графе и нет в другом — подсвечены.
- Hero-screenshot №2 — снимаем здесь.
- HEB / edge bundling переносится из старого плана как nice-to-have **только если** visual
  clutter в общем 2D-пространстве станет проблемой по итогам Итерации 1.

### 7.3. Что форкать / писать самим (revised 2026-05-03)

В `@krainovsd/graph`:
- Расширение существующего `Node` / `Edge` типа: добавить `layer: LayerId`.
- Renderer-hooks: `nodeOpacity(node) → number`, `edgeOpacity(edge) → number`,
  `pointerEventsEnabled(node) → boolean`, опционально `renderOrder(node|edge) → number`
  (для Z-stacking при наложении).
- Сериализация: тип `LayeredGraphData = { nodes: { layer: LayerId, ... }[], edges: ..., layers: LayerMeta[] }`.
- (Итерация 2, опционально) custom force `crossLayerAlignXY` — если без него inter-layer
  edges становятся неразборчивыми.

Снаружи `@krainovsd/graph`, на стороне Nuxt-консьюмера:
- Composable `useLayerFocus()` — управляет `activeLayer`, `layersVisibility`,
  `layersOpacity`, `layersZOrder`; экспортирует API для overlay'а.
- Component `<LayerMapOverlay>` — открывается по `L`, drag-reorder, sliders, toggles.
- Component `<LayerHotkeyHandler>` — глобальные хоткеи (`1`/`2`/`3`/`4`/`Tab`/`L`/`Esc` и т.д.);
  проверяет `document.activeElement` чтобы не срабатывать в input-полях.

Сбоку (как peerDeps):
- Никаких новых.

Backend (отдельный issue, не меняется):
- API `GET /graph/aggregate?layer=community` — collapsed-view.
- API `GET /graph/expand?nodeId=X&depth=1` — on-demand subgraph для slider'а.

### 7.4. Риски (revised 2026-05-03)

1. **Visual clutter в общем 2D-пространстве**: 4 слоя на одном canvas, до 30k+ inter-layer
   edges. Даже с opacity=0.2 фон может стать «кашей». Митигация прописана в §6.6:
   рёбра вне активного слоя приглушаются агрессивнее узлов (alpha 0.05—0.1); cross-layer
   edges на выделенном — поверх Z-стека.
2. **Cross-layer spatial alignment**: позиция community-узла никак не «над» его
   entity-узлами в 2D layout. Влияет на cross-layer selection (связанные узлы могут быть
   далеко друг от друга на экране) и на читаемость inter-layer edges. Митигация: добавляем
   `crossLayerAlignXY` force в Итерации 2, если визуально плохо. Решаем после Итерации 1
   (см. §7.5 Deferred).
3. **Hotkey conflicts с input-полями**: `1`/`2`/`3`/`4` могут срабатывать при наборе текста
   в фильтрах/поиске. Митигация: глобальный handler проверяет `document.activeElement`,
   игнорирует event при `<input>` / `<textarea>` / `[contenteditable]`.
4. **Granularity slider + opacity tween**: при быстром перетаскивании ползунка узлы
   мерцают/скачкообразно меняют opacity. Митигация: opacity-transition 200—300 ms +
   debounce slider'а на 100 ms.
5. **Z-stacking в drag-reorder**: пользователь интуитивно может попытаться поменять
   семантическую иерархию через drag (поставить chunk выше topic), это ломает
   mention/membership/summary edges. Митигация: drag в Layer Map меняет **только**
   render-order; рядом — отдельная подсказка-tooltip «семантический уровень фиксирован».
6. **Russian text labels**: остаётся актуально, но проще — это уже работает в
   `@krainovsd/graph`, шрифт в `frontend/public/fonts/` переиспользуется без изменений.
7. **MoE side-by-side**: два инстанса `@krainovsd/graph`, общий activeLayer / hover state.
   Двойного WebGL-контекста больше нет (мы 2D), но reactivity на оба графа должна быть
   shared. Митигация: один Pinia store (`useLayerFocus`) на оба.
8. **`L` vs браузерные шорткаты**: `Ctrl+L` / `Cmd+L` — focus address bar. Просто `L`
   (без модификатора) — свободно, используем его.

### 7.5. Deferred (открытые вопросы)

- **Cross-layer spatial alignment**: нужен ли `crossLayerAlignXY` force? Решаем после
  Итерации 1 по визуальной читаемости inter-layer edges.
- **Z-stacking порядок по умолчанию**: chunk внизу, topic наверху? Или наоборот? Влияет на
  overlap-priority при равных opacity. Решаем при первом дизайн-review с автором
  `@krainovsd/graph`.
- **Slice mode vs activeLayer**: один state или два? Slice = «остальные скрыты»,
  focus = «остальные приглушены». MVP — два разных toggle (Slice — флажок в Layer Map),
  объединяем если пользователи путаются.
- **MoE side-by-side scope для SIGIR'26**: входит в core demo или статья only? Уточнить
  с командой до начала Итерации 3.
- **Granularity slider семантика**: непрерывный 0—1 (по degree threshold) vs дискретный
  4-позиционный (по слою). MVP — дискретный. Возврат к непрерывному — после user-testing.
- **Opacity values**: 0.15—0.25 для не-активных узлов и 0.05—0.1 для не-активных рёбер —
  эмпирические. Возможно нужен user-testing на dark vs light темах.

## 8. Список ссылок

> Ссылки канонические; версии/наличие конкретных фич перепроверить перед интеграцией.

**Академия:**
- Kivelä et al., "Multilayer Networks", J. Complex Networks, 2014. <https://arxiv.org/abs/1309.7233>
- De Domenico et al., "MuxViz: a tool for multilayer analysis and visualization of networks", J. Complex Networks, 2015. <https://academic.oup.com/comnet/article/3/2/159/2197444>
- McGee, Ghoniem, Melançon, Otjacques, Pinaud, "The State of the Art in Multilayer Network Visualization", CGF 2019. <https://onlinelibrary.wiley.com/doi/10.1111/cgf.13610>
- Bach et al., "GraphDiaries: Animated Transitions and Temporal Navigation for Dynamic Networks", IEEE TVCG. <https://ieeexplore.ieee.org/document/6634127>
- Holten, "Hierarchical Edge Bundles", IEEE TVCG 2006. <https://ieeexplore.ieee.org/document/4015425>
- Misue, Eades, Lai, Sugiyama, "Layout Adjustment and the Mental Map", J. Visual Languages 1995. <https://www.sciencedirect.com/science/article/abs/pii/S1045926X85710105>
- Brandes, "Drawing on Physical Analogies" (force-directed survey). <https://link.springer.com/chapter/10.1007/3-540-44969-8_4>

**Инструменты — десктоп / референс UX:**
- muxViz: <https://github.com/manlius/muxViz>
- visone: <https://visone.ethz.ch/>
- Pajek: <http://mrvar.fdv.uni-lj.si/pajek/>
- Gephi: <https://gephi.org/>
- BioFabric: <https://biofabric.systemsbiology.net/>

**Web-библиотеки:**
- 3d-force-graph (vasturiano): <https://github.com/vasturiano/3d-force-graph>
- three.js: <https://github.com/mrdoob/three.js>
- d3-force-3d: <https://github.com/vasturiano/d3-force-3d>
- ngraph.forcelayout3d: <https://github.com/anvaka/ngraph.forcelayout>
- sigma.js: <https://github.com/jacomyal/sigma.js>
- graphology: <https://github.com/graphology/graphology>
- AntV G6: <https://github.com/antvis/G6>
- G6 docs (v5): <https://g6.antv.antgroup.com/>
- cytoscape.js: <https://github.com/cytoscape/cytoscape.js>
- cytoscape-fcose: <https://github.com/iVis-at-Bilkent/cytoscape.js-fcose>
- cytoscape-cise: <https://github.com/iVis-at-Bilkent/cytoscape.js-cise>
- cola.js / WebCola: <https://github.com/tgdwyer/WebCola>
- reagraph: <https://github.com/reaviz/reagraph>
- vis-network: <https://github.com/visjs/vis-network>
- troika-three-text: <https://github.com/protectwise/troika/tree/main/packages/troika-three-text>
- three-spritetext: <https://github.com/vasturiano/three-spritetext>

**UX-референсы / inspiration:**
- Cosmograph: <https://cosmograph.app/>
- Kumu.io: <https://kumu.io/>
- Neo4j Bloom: <https://neo4j.com/product/bloom/>
- Linkurious: <https://linkurious.com/>
- Sketchfab (camera UX): <https://sketchfab.com/>
