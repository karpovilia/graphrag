# Отчёт: Community Detection в многослойных сетях через единую модулярность

> Дата: 2026-05-03

**Постановка задачи:** дана многослойная сеть, в которой *одни и те же узлы* присутствуют на нескольких слоях (multiplex / node-aligned multilayer). Нужно найти разбиение узлов на сообщества, максимизирующее **единую** модулярностную функцию, агрегирующую вклад всех слоёв (а не оптимизировать каждый слой отдельно с последующим объединением). Принципиально — единая партиция узлов, согласованная между слоями.

В таксономии Magnani & Hanteer (2021) это **flattening-free, joint optimization** подход; в литературе именно для него существует строго определённая *multilayer modularity* и устоявшийся алгоритмический инструментарий.

---

## 1. Фундамент: формализация и каноническая модулярность

### 1.1 Mucha et al., **Science** 2010 — *seminal*
Mucha, Richardson, Macon, Porter, Onnela. *"Community structure in time-dependent, multiscale, and multiplex networks"*. **Science** 328(5980):876–878. **Q1, top-tier.**
[Препринт/обсуждение](https://www.science.org/doi/10.1126/science.1184819) · [GenLouvain ref-импл.](https://github.com/GenLouvain/GenLouvain)

Это базовая работа всей области. Ключевая идея — записать модулярность для multilayer-сети как
$$Q_{ML} = \frac{1}{2\mu}\sum_{ijsr}\!\Big[(A_{ijs} - \gamma_s P_{ijs})\delta_{sr} + \delta_{ij}\,C_{jsr}\Big]\,\delta(g_{is},g_{jr}),$$
где $A_{ijs}$ — связь $i\!-\!j$ на слое $s$, $P_{ijs}$ — null-модель внутри слоя, $\gamma_s$ — resolution, а **$C_{jsr}$ — inter-layer coupling** (один и тот же узел $j$ на слоях $s$ и $r$). Параметр связи $\omega = C_{jsr}$ — главный «рычаг» того, насколько разрешено партиции расходиться между слоями.

Почему важно: впервые корректно соединили слои через тензорное расширение Newman–Girvan, и эта формула стала *де-факто стандартом*.

### 1.2 De Domenico et al., **Phys. Rev. X** 2013
De Domenico, Solé-Ribalta, Cozzo, Kivelä, Moreno, Porter, Gómez, Arenas. *"Mathematical Formulation of Multilayer Networks"*. **PRX** 3:041022. **Q1.**
[PRX](https://link.aps.org/doi/10.1103/PhysRevX.3.041022) · [arXiv:1307.4977](https://arxiv.org/abs/1307.4977)

Дают тензорное представление multilayer-сети (4-tensor $M^{ij}_{\alpha\beta}$) и обобщают модулярность, центральности и другие меры в этом аппарате. Без этой работы не понять последующую литературу про supra-adjacency.

---

## 2. Null-модели и теоретическая обоснованность

### 2.1 Bazzi et al., **Multiscale Modeling & Simulation** (SIAM) 2016
Bazzi, Porter, Williams, McDonald, Fenn, Howison. *"Community Detection in Temporal Multilayer Networks…"*. **MMS** 14(1):1–41. **Q1 (SIAM).**
[SIAM](https://epubs.siam.org/doi/10.1137/15M1009615) · [arXiv:1501.00040](https://arxiv.org/abs/1501.00040)

Систематически разделяют **null networks** vs **null models** для multilayer modularity, обсуждают persistence (диагностика устойчивости сообщества по слоям). Под наш кейс (один узел — много слоёв) это must-read: показывают, что выбор $C_{jsr}$ нетривиален и сильно влияет на результат.

### 2.2 Pamfil, Howison, Lambiotte, Porter, **SIAM J. Math. of Data Science** 2019
*"Relating Modularity Maximization and Stochastic Block Models in Multilayer Networks"*. **SIMODS** 1:667–698. **Q1 (SIAM).**
[SIMODS](https://epubs.siam.org/doi/10.1137/18M1231304) · [arXiv:1804.01964](https://arxiv.org/abs/1804.01964)

Доказывают эквивалентность multilayer-модулярности и MAP-оценки в специальном multilayer-SBM. Важное следствие — *layer-weighted modularity*: когда параметры варьируются между слоями, естественно возникает взвешенная по слоям функция $Q$. Прямо этот кейс «суммирование по всем слоям с весами».

### 2.3 Paul & Chen, **Annals of Statistics** 2020
*"Spectral and matrix factorization methods for consistent community detection in multi-layer networks"*. **AoS** 48(1):230–250. **Q1, top-tier statistics.**
[ProjectEuclid](https://projecteuclid.org/euclid.aos/1581930133)

Показывают **состоятельность** оценщиков сообществ при росте $n$, числа слоёв $L$ и числа сообществ $K$. Сравнивают early/intermediate/late fusion стратегии. Полезно как теоретическая опора для выбора между стратегиями агрегации слоёв.

---

## 3. Алгоритмика: как реально оптимизировать $Q_{ML}$

### 3.1 GenLouvain (Jeub, Bazzi, Jutla, Mucha)
[arXiv:1108.1502](https://arxiv.org/abs/1108.1502) · [GitHub](https://github.com/GenLouvain/GenLouvain)
Это не отдельная статья Q1, но **референс-реализация** для $Q_{ML}$ Mucha. Любая эмпирическая работа с модулярностью на multiplex-сетях, скорее всего, начнётся с GenLouvain (или его портов на Python — `leidenalg.find_partition_multiplex`, `multinetx`).

### 3.2 Wilson, Palowitch, Bhamidi, Nobel, **JMLR** 2017
*"Community Extraction in Multilayer Networks with Heterogeneous Community Structure"*. **JMLR** 18(149):1–49. **Q1, CORE A\*.**
[JMLR](https://jmlr.org/papers/v18/16-645.html) · [arXiv:1610.06511](https://arxiv.org/abs/1610.06511) · [код](https://github.com/jdwilson4/MultilayerExtraction)

Альтернатива модулярности — **Multilayer Extraction**: значимостный score, оптимизируемый по vertex–layer наборам. Разрешает overlapping и фон. Если сообщества могут существовать только на части слоёв — это методологический бенчмарк.

### 3.3 Taylor, Caceres, Mucha, **Phys. Rev. X** 2017
*"Super-Resolution Community Detection for Layer-Aggregated Multilayer Networks"*. **PRX** 7:031056. **Q1.**
[PRX](https://journals.aps.org/prx/abstract/10.1103/PhysRevX.7.031056)

Показывают, что *агрегирование слоёв* (даже корректное) даёт detectability transition хуже, чем joint multilayer detection при одинаковом сигнале. Прямой аргумент в пользу единой $Q_{ML}$ против layer-by-layer + post-hoc consensus.

### 3.4 Stanley, Shai, Taylor, Mucha, **IEEE TNSE** 2016
*"Clustering Network Layers With the Strata Multilayer Stochastic Block Model"*. **IEEE TNSE** 3(2):95–105. **Q1.**
[IEEE/PMC](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC5400296/) · [arXiv:1507.01826](http://arxiv.org/abs/1507.01826) · [код](https://github.com/stanleyn/sMLSBM)

Если есть гипотеза, что *слои гетерогенны* (одни описывают одну структуру сообществ, другие — другую), sMLSBM сначала кластеризует **слои в страты**, потом оценивает SBM в каждой страте. Это естественный «оппонент» single-$Q_{ML}$ подхода и must-discuss в related work.

---

## 4. Информационно-теоретический контрбенчмарк (не модулярность, но обязателен в обзоре)

### 4.1 De Domenico, Lancichinetti, Arenas, Rosvall, **Phys. Rev. X** 2015
*"Identifying Modular Flows on Multilayer Networks Reveals Highly Overlapping Organization in Interconnected Systems"*. **PRX** 5:011027. **Q1.**

Multilayer-Infomap: оптимизируют MDL-описание потока random walker по supra-узлам $(i,\alpha)$, а не модулярность. Главный конкурент Mucha-семейства. Любая статья «модулярность vs Infomap на multilayer» обязана его цитировать.

---

## 5. Обзоры и бенчмарки

### 5.1 Magnani, Hanteer, Interdonato, Rossi, Tagarelli, **ACM Computing Surveys** 2021
*"Community Detection in Multiplex Networks"*. **ACM CSUR** 54(3), 35 pp. **Q1, CORE A\*.**
[ACM](https://dl.acm.org/doi/10.1145/3444688) · [arXiv:1910.07646](https://arxiv.org/abs/1910.07646)

Эталонный systematic review. Таксономия: flattening / aggregation / direct multilayer (включая $Q_{ML}$) / multi-objective. Эмпирическое сравнение на ground-truth датасетах. Без этой ссылки сегодня не пишется ни одна статья по теме.

### 5.2 Huang, Chen, Wang, Wei, Xie, **DMKD** 2021
*"A survey of community detection methods in multilayer networks"*. **Data Mining and Knowledge Discovery**. **Q1, CORE A.**
[Springer](https://link.springer.com/article/10.1007/s10618-020-00716-6)

Дополняет CSUR-обзор — больше внимания multi-objective и feature-based методам.

### 5.3 Tagarelli, Amelio, Gullo, **DMKD** 2017
*"Ensemble-based community detection in multilayer networks"*. **DMKD** 31:1506–1543. **Q1, CORE A.**
[Springer](https://link.springer.com/article/10.1007/s10618-017-0528-8)

Modularity-driven ensemble: идёт «вторым путём» — оптимизируют per-layer, потом агрегируют через консенсус по multilayer modularity. Принципиально отличается от Mucha по схеме оптимизации; полезен как baseline.

---

## 6. Краткая дорожная карта чтения

| Цель | Что читать первым |
|------|-------------------|
| Понять формулу $Q_{ML}$ | Mucha 2010 → De Domenico 2013 |
| Грамотно выбрать null-модель и $\omega$ | Bazzi 2016 → Pamfil 2019 |
| Обосновать joint vs aggregated | Taylor 2017 |
| Получить теоретические гарантии | Paul–Chen 2020 |
| Защититься от reviewer'а «почему не SBM/Infomap» | Pamfil 2019 + De Domenico 2015 + Stanley 2016 |
| Написать related work | Magnani 2021 (CSUR) + Huang 2021 (DMKD) |
| Эмпирический baseline | GenLouvain + Wilson 2017 + Tagarelli 2017 |

---

## 7. Открытые вопросы (deferred)

1. **Inter-layer coupling $\omega$:** в категориальном multiplex-случае Mucha 2010 предлагает однородную связь между всеми парами слоёв; Bazzi 2016 показывает, что это даёт **резкий переход** партиции при изменении $\omega$. Нужна явная политика выбора $\omega$ для корпуса (cross-validation? null-distribution? Pamfil-эквивалент SBM-параметру?).
2. **Resolution-параметры $\gamma_s$:** на разных слоях оптимальные $\gamma$ разные (Pamfil 2019). Нужна стратегия — общий $\gamma$, per-layer $\gamma_s$, или адаптивный?
3. **Persistence vs flexibility:** партиция, *максимально стабильная* по слоям (Bazzi), или допускающая *эволюцию* сообществ (Mucha temporal)?
4. **Overlapping vs hard partition:** $Q_{ML}$ — hard. Если узел может быть в разных сообществах на разных слоях — рассмотреть Wilson 2017.

---

## Источники

- [Mucha et al., Science 2010 — Community structure in time-dependent, multiscale, and multiplex networks](https://www.science.org/doi/10.1126/science.1184819)
- [De Domenico et al., PRX 2013 — Mathematical Formulation of Multilayer Networks](https://link.aps.org/doi/10.1103/PhysRevX.3.041022)
- [De Domenico et al., PRX 2015 — Identifying Modular Flows on Multilayer Networks](https://journals.aps.org/prx/abstract/10.1103/PhysRevX.5.011027)
- [Bazzi et al., MMS 2016 — Community Detection in Temporal Multilayer Networks](https://epubs.siam.org/doi/10.1137/15M1009615)
- [Pamfil et al., SIMODS 2019 — Relating Modularity Maximization and SBMs in Multilayer Networks](https://epubs.siam.org/doi/10.1137/18M1231304)
- [Paul & Chen, Annals of Statistics 2020 — Spectral and matrix factorization methods…](https://projecteuclid.org/euclid.aos/1581930133)
- [Wilson et al., JMLR 2017 — Community Extraction in Multilayer Networks](https://jmlr.org/papers/v18/16-645.html)
- [Taylor, Caceres, Mucha, PRX 2017 — Super-Resolution Community Detection](https://journals.aps.org/prx/abstract/10.1103/PhysRevX.7.031056)
- [Stanley et al., IEEE TNSE 2016 — Strata Multilayer SBM](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC5400296/)
- [Magnani, Hanteer et al., ACM CSUR 2021 — Community Detection in Multiplex Networks](https://dl.acm.org/doi/10.1145/3444688)
- [Huang et al., DMKD 2021 — A survey of community detection methods in multilayer networks](https://link.springer.com/article/10.1007/s10618-020-00716-6)
- [Tagarelli, Amelio, Gullo, DMKD 2017 — Ensemble-based community detection](https://link.springer.com/article/10.1007/s10618-017-0528-8)
- [GenLouvain — reference implementation](https://github.com/GenLouvain/GenLouvain) · [arXiv:1108.1502](https://arxiv.org/abs/1108.1502)
