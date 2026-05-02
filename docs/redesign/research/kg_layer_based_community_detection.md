# Отчёт: Layer-based community detection для графов знаний

> Дата: 2026-05-03

## TL;DR
Интуиция «эту задачу нельзя решать в общем случае» подкреплена литературой формально:
1. **Нерешаема единым алгоритмом** — есть строгая теорема No-Free-Lunch для community detection (Peel-Larremore-Clauset, *Science Advances* 2017; McCarthy & Procaccia, 2019).
2. **Плохо определена в KG** — в графе знаний «слой» = тип отношения, а каждый тип несёт *семантически разные* сообщества. То, что является сообществом по `написал_статью`, не обязано быть сообществом по `работает_в`.
3. **Зависит от выбора метапутей** — в HIN community detection (см. Sun & Han, VLDB 2022) сообщество вообще *определяется* схемой обхода, а не топологией.

Поэтому в литературе нет «layer-based CD для KG» как закрытого класса — есть **HIN community detection**, **multi-relational SBM**, **meta-path-based clustering**, и каждый делает явные семантические допущения.

---

## 1. Терминология: KG = типизированный HIN

Для multilayer/multiplex CD узлы и связи однотипны (Mucha 2010 framework). В KG это не так:

- **Узлы типизированы**: `Person`, `Paper`, `Organization`.
- **Рёбра типизированы**: `cites`, `affiliated_with`, `coauthored`.
- **Слой ≈ тип ребра** (или «вид» в multi-view-формализме), но узлы переходят между слоями только через схему.

В литературе эта задача обычно называется **community detection in heterogeneous information networks (HIN)**. Просто «layer-based CD для KG» — нестандартный термин; формально это либо HIN-CD, либо **multi-relational network clustering**, либо **multi-view clustering on knowledge graphs**.

---

## 2. Топовые статьи по теме

### 2.1 Sun, Han et al., **VLDB / TKDE** — фундамент HIN
- Sun, Han. *"Heterogeneous Information Networks: the Past, the Present, and the Future"*. **PVLDB** 15(12), 2022. **Q1, CORE A\*.**
  [PVLDB](https://www.vldb.org/pvldb/vol15/p3807-sun.pdf)
- Sun, Han, Yan, Yu, Wu. *"PathSim: Meta path-based top-k similarity search in heterogeneous information networks"*. **PVLDB** 4(11), 2011.
- Sun, Norick, Han, Yan, Yu, Wu. *"PathSelClus: integrating meta-path selection with user-guided clustering in HIN"*. **ACM TKDD** 7(3), 2013. **Q1, CORE A\*.**
- Shi, Li, Zhang, Sun, Yu. *"A Survey of Heterogeneous Information Network Analysis"*. **IEEE TKDE** 29(1):17–37, 2017. **Q1, CORE A\*.**
  [TKDE](https://ieeexplore.ieee.org/document/7536145)

**Главный тезис всей серии:** в HIN сообщества *не существуют независимо от метапути*. PathSelClus прямо требует от пользователя задать набор метапутей, и кластеризация — это функция этого выбора. Это формально подтверждает «нельзя в общем случае»: задача параметризована схемой обхода.

### 2.2 Liu, Yang et al., **PACM MOD** 2025 — без материализации метапутей
*"Community Detection in Heterogeneous Information Networks Without Materialization"*. **PACM on Management of Data** (Q1, CORE A\*).
[ACM](https://dl.acm.org/doi/10.1145/3725276)

Современный подход: пытаются обойтись без явного выбора метапутей. Но — выбирают «meta-structure» (схему фрагмента), что лишь смещает проблему: сообщество всё равно зависит от семантического выбора.

### 2.3 Dong, Chawla, Swami, **KDD** 2017 — metapath2vec
*"metapath2vec: Scalable Representation Learning for Heterogeneous Networks"*. **KDD 2017**. **CORE A\*.**
[PDF](https://ericdongyx.github.io/papers/KDD17-dong-chawla-swami-metapath2vec.pdf)

Эмбеддинги, обученные через random walks по метапутям → потом стандартная кластеризация. Доминирующий baseline для KG-кластеризации последние ~7 лет. Классы сообществ напрямую определяются набором метапутей в random walk.

### 2.4 Li, Wu et al., **CIKM** 2021
*"Detecting Communities from Heterogeneous Graphs"*. **CIKM 2021**. **CORE A.**
[ACM](https://dl.acm.org/doi/abs/10.1145/3459637.3482250)

Прямая постановка community detection (а не embedding+kmeans) для гетерогенных графов с метапутями. Полезно как baseline.

### 2.5 Banda, Motik (Oxford), 2020 — RDF-specific
*"Community-Based RDF Graph Partitioning"*.
[Oxford CS](https://www.cs.ox.ac.uk/people/boris.motik/pubs/bm20community-partitioning.pdf)

Чисто инженерный угол: партиционирование RDF под query-engine. Интересен наблюдением: они *удаляют* `rdf:type` рёбра перед кластеризацией, потому что type-rich узлы «искажают модулярность». Это эмпирическое подтверждение: модулярность по сырому RDF плохо себя ведёт без schema-aware preprocessing.

### 2.6 Pham, Aggarwal et al. — KG-Enhanced CD (WSDM 2019)
*"Knowledge Graph Enhanced Community Detection and Characterization"*. **WSDM 2019**. **CORE A\*.**
[ACM](https://dl.acm.org/doi/10.1145/3289600.3291031) · [PDF](https://cs.mu.edu/~keke/papers/wsdm19.pdf)

Здесь обратная постановка: KG используется *как источник признаков* для CD на отдельной (homogeneous) сети. Иллюстрирует, что в индустрии «CD на KG» часто решается через *проекцию*, а не joint optimization.

---

## 3. Формальные основания «нельзя в общем случае»

Это самая важная часть отчёта — здесь есть прямые теоретические аргументы.

### 3.1 Peel, Larremore, Clauset, **Science Advances** 2017 ⭐
*"The ground truth about metadata and community detection in networks"*. **Sci. Adv.** 3(5):e1602548. **Q1, top-tier.**
[Sci Adv](https://www.science.org/doi/10.1126/sciadv.1602548) · [arXiv:1608.05878](https://arxiv.org/abs/1608.05878)

Два центральных результата:
1. **No-Free-Lunch для CD**: для любого алгоритма $A$ существует распределение входов, на котором $A$ не лучше случайного. Формально доказано.
2. **Метаданные ≠ ground truth**: атрибуты узлов (типы в KG — это *именно* метаданные) не являются истинными сообществами. Несовпадение разбиения с метаданными может означать не плохой алгоритм, а *присутствие сразу нескольких валидных структур*.

Для KG это критично: если «слои» — это типы отношений (метаданные ребра), то ожидать, что есть *одно* истинное разбиение, согласованное со всеми типами, — теоретически необоснованно.

### 3.2 McCarthy, Procaccia, 2019 — точная NFL
*"An Exact No Free Lunch Theorem for Community Detection"*. Springer LNCS 2019.
[arXiv:1903.10092](https://arxiv.org/pdf/1903.10092) · [Springer](https://link.springer.com/chapter/10.1007/978-3-030-36687-2_15)

Усиление Peel et al.: дают точную (не асимптотическую) формулировку NFL. На равномерном распределении задач все алгоритмы CD имеют *одинаковую* среднюю ошибку.

### 3.3 Peixoto, инверсия NFL
[Блог Peixoto](https://skewed.de/tiago/posts/free-lunch/)

Прагматическая контрнота от автора `graph-tool`: NFL применима *по равномерному распределению* задач, но реальные сети не равномерно распределены — поэтому NFL не означает «всё бесполезно». Однако это работает только если есть *явная модель того, какие сообщества вы ищете* — что для KG означает: задайте метапути / тип отношения / семантическое ограничение.

**Сухой остаток:** NFL формально подтверждает «в общем случае нельзя», но не говорит «никогда нельзя». Можно при условии явного семантического сужения класса задач.

---

## 4. Почему KG-специфика делает задачу хуже, чем обычный multilayer

Три структурных аргумента для будущей публикации:

1. **Семантическая несоизмеримость слоёв.** На multiplex (например, Twitter follow / mention / retweet) все слои — социальные взаимодействия одного типа, и единая модулярность интерпретируема. В KG слой `был_рождён_в` (1-к-1, sparse) и слой `цитирует` (many-to-many, dense) имеют принципиально разные null-distributions; единая $Q_{ML}$ суммирует *несоизмеримые величины*.

2. **Зависимость от метапути.** В HIN-формализме (Sun-Han) сообщество $C$ определяется относительно метапути $\mathcal{P}$. Без $\mathcal{P}$ задача не определена. Pamfil et al. 2019 показывают, что layer-weighted modularity в multilayer-SBM требует layer-specific параметров — для KG это выливается в подбор параметров для каждого типа отношения, что эквивалентно выбору метапути.

3. **Schema-induced bias.** Banda & Motik 2020 эмпирически показывают, что type-узлы (классы в RDF) ломают модулярность. Это означает, что сама схема KG влияет на «правильное» разбиение — нельзя думать о структуре отдельно от схемы.

---

## 5. Что это значит для GraphRAG Explorer

Формулировка для related work / discussion:

> Layer-based community detection в общем случае ill-posed для KG: NFL-теорема (Peel et al., 2017) формально исключает существование универсально-оптимального алгоритма, а HIN-формализм (Sun & Han, 2022) показывает, что сообщество определено только относительно явно выбранных метапутей. Поэтому практический вывод — *не* искать единое разбиение, а:
> 1. либо **зафиксировать семантическое допущение** (выбор метапути, типа отношения, view), и тогда задача корректна;
> 2. либо **выдавать множество разбиений** под разные семантические контексты (что ближе к multi-view / multifaceted communities, см. *Sci. Reports 2024*);
> 3. либо **проецировать в homogeneous граф** (как делают практически все production GraphRAG-системы — что *технически решаемо*, но теряет половину семантики KG).

Для SIGIR'26-демо это сильный аргумент в пользу *интерактивного* выбора метапути / типа отношения как первоклассного UX-элемента (ложится на существующее требование wizard back-navigation — пользователь должен иметь возможность *менять* семантический контекст кластеризации и видеть, как меняется граф).

---

## 6. Открытые вопросы (deferred)

1. **Какой набор метапутей по умолчанию** в GraphRAG Explorer? Авто-вывод из EDA по типам отношений или ручной выбор пользователя?
2. **Как визуализировать множество разбиений** под разные метапути без перегрузки UI?
3. **Бенчмарк:** есть ли датасет KG с ground-truth сообществами на разных метапутях? (DBLP, Yelp HIN — частично, но без multi-metapath ground-truth.)
4. **Соотношение с MoE-планом для статьи:** можно ли позиционировать «выбор метапути» как expert routing в MoE-формулировке?

---

## Источники

- [Peel, Larremore, Clauset — The ground truth about metadata and community detection (Sci Adv 2017)](https://www.science.org/doi/10.1126/sciadv.1602548)
- [McCarthy, Procaccia — An Exact No Free Lunch Theorem for Community Detection (arXiv 2019)](https://arxiv.org/pdf/1903.10092)
- [Peixoto — No free lunch in community detection? (blog/critique)](https://skewed.de/tiago/posts/free-lunch/)
- [Sun, Han — Heterogeneous Information Networks: Past, Present, and Future (PVLDB 2022)](https://www.vldb.org/pvldb/vol15/p3807-sun.pdf)
- [Sun et al. — PathSelClus (TKDD 2013)](https://web.cs.ucla.edu/~yzsun/papers/TJ13_meta_path.pdf)
- [Shi et al. — A Survey of HIN Analysis (IEEE TKDE 2017)](https://ieeexplore.ieee.org/document/7536145)
- [Liu et al. — Community Detection in HIN Without Materialization (PACM MOD 2025)](https://dl.acm.org/doi/10.1145/3725276)
- [Dong, Chawla, Swami — metapath2vec (KDD 2017)](https://ericdongyx.github.io/papers/KDD17-dong-chawla-swami-metapath2vec.pdf)
- [Li et al. — Detecting Communities from Heterogeneous Graphs (CIKM 2021)](https://dl.acm.org/doi/abs/10.1145/3459637.3482250)
- [Pham et al. — KG-Enhanced Community Detection (WSDM 2019)](https://dl.acm.org/doi/10.1145/3289600.3291031)
- [Banda, Motik — Community-Based RDF Graph Partitioning (Oxford 2020)](https://www.cs.ox.ac.uk/people/boris.motik/pubs/bm20community-partitioning.pdf)
