<script setup lang="ts">
  import { useAsyncData } from "nuxt/app";
  import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
  import { useRoute } from "vue-router";
  import { useI18n } from "vue-i18n";

  import LayeredGraph from "@/components/organisms/LayeredGraph/LayeredGraph.vue";
  import LayersPanel from "@/components/organisms/LayersPanel/LayersPanel.vue";
  import NodeDrawer from "@/components/organisms/NodeDrawer/NodeDrawer.vue";
  import EdgeDrawer from "@/components/organisms/EdgeDrawer/EdgeDrawer.vue";
  import SuggestionsSidebar from "@/components/organisms/SuggestionsSidebar/SuggestionsSidebar.vue";
  import AssistantChat from "@/components/organisms/AssistantChat/AssistantChat.vue";
  import RagDialog from "@/components/organisms/RagDialog/RagDialog.vue";
  import TimelineScrubber from "@/components/organisms/TimelineScrubber/TimelineScrubber.vue";
  import AxisToggle from "@/components/organisms/TimelineScrubber/AxisToggle.vue";
  import DeltaLegend from "@/components/organisms/DeltaLegend/DeltaLegend.vue";
  import InvalidationPanel from "@/components/organisms/InvalidationPanel/InvalidationPanel.vue";
  import GuidedWalkthrough from "@/components/organisms/GuidedWalkthrough/GuidedWalkthrough.vue";
  import ErrorBanner from "@/components/molecules/ErrorBanner/ErrorBanner.vue";
  import LatencyBadge from "@/components/molecules/LatencyBadge/LatencyBadge.vue";
  import { themeBehaviorSubject } from "@/entities/tech";
  import { useApi } from "@/lib/api-client";
  import { formatNumber } from "@/lib/format";
  import type {
    Edge,
    GraphVariant,
    Node,
    ProjectionImportanceResult,
    ProjectionOption,
    ProjectionResult,
    TimeAxis,
  } from "@/entities/api";
  import { useTemporalWindow } from "@/composables/use-temporal-window";
  import { useQueryDelta } from "@/composables/use-query-delta";
  import { useEditCascade } from "@/composables/use-edit-cascade";
  import { useWalkthrough } from "@/composables/use-walkthrough";
  import type { DeltaSource, DeltaState } from "@/components/organisms/LayeredGraph/lib/delta";

  const route = useRoute();
  const variantId = String(route.params.id);
  const api = useApi();
  const theme = themeBehaviorSubject.useSubscribe();
  const { t } = useI18n();

  const { data: variant, error: variantError } =
    await useAsyncData(`variant:${variantId}`, () => api.graphs.get(variantId));
  const { data: nodes, refresh: refreshNodes, error: nodesError } =
    await useAsyncData(`nodes:${variantId}`, () =>
      api.graphs.listNodes(variantId),
    );
  const { data: edges, refresh: refreshEdges, error: edgesError } =
    await useAsyncData(`edges:${variantId}`, () =>
      api.graphs.listEdges(variantId),
    );

  // §2.1 timeline — best-effort: if the backend doesn't expose the
  // endpoint yet, fall back to an empty axis (scrubber stays hidden).
  const { data: timeline, refresh: refreshTimeline } = await useAsyncData(
    `timeline:${variantId}`,
    () => api.graphs.timeline(variantId, "tx").catch(() => []),
  );

  const selectedNodes = ref<id[]>([]);
  const selectedLink = ref<id | null>(null);
  // Merge-by-click: while the NodeDrawer is in merge-pick mode, the next
  // graph node click selects the *absorbed* node instead of moving the
  // drawer. `mergePickTarget` carries that click down to the drawer, which
  // owns the actual merge call.
  const mergePicking = ref(false);
  const mergePickTarget = ref<Node | null>(null);
  const showSuggestions = ref(false);
  const showLayers = ref(false);
  const showTimeline = ref(false);
  const showAssistant = ref(false);
  const showRag = ref(false);
  // End of the selected period for RAG temporal mode: the scrubber's upper
  // bound (range) or the instant; undefined when no window is set.
  const ragAsOf = computed<string | undefined>(() => {
    const v = scrubModel.value;
    if (Array.isArray(v)) return v[1];
    return v ?? undefined;
  });
  // DERIVED higher-order projection edges are dense → hidden by default.
  const showDerived = ref(false);
  // #1c projection-importance panel (lazy-loaded on first open).
  const showImportance = ref(false);
  const importance = ref<ProjectionImportanceResult | null>(null);
  const loadingImportance = ref(false);
  async function loadImportance() {
    showImportance.value = !showImportance.value;
    if (!showImportance.value || importance.value || loadingImportance.value) return;
    loadingImportance.value = true;
    try {
      importance.value = await api.graphs.projectionImportance(variantId);
    } finally {
      loadingImportance.value = false;
    }
  }
  // #6 — layer-pair projection picker. Two slots (A, B) so two projections
  // can be overlaid at once, each in its own colour.
  const PROJ_COLOR_A = "#e8743b"; // orange
  const PROJ_COLOR_B = "#1f9e89"; // teal
  const showProjection = ref(false);
  const projOptions = ref<ProjectionOption[]>([]);
  const projChoiceKey = ref<string>("");
  const projChoiceKeyB = ref<string>(""); // "" = second projection off
  const projNorm = ref<string>("newman");
  const projResult = ref<ProjectionResult | null>(null);
  const projResultB = ref<ProjectionResult | null>(null);
  const projLoading = ref(false);
  const projectionsOnly = ref(true); // hide base edges while projections shown
  function projKey(o: ProjectionOption) {
    return `${o.target_layer}|${o.via}|${o.neighbor_layer}`;
  }
  async function toggleProjection() {
    showProjection.value = !showProjection.value;
    if (showProjection.value && !projOptions.value.length) {
      projOptions.value = await api.graphs.projectionAvailable(variantId);
      const first = projOptions.value.find((o) => o.target_layer === "entity");
      projChoiceKey.value = projKey(first ?? projOptions.value[0] ?? ({} as ProjectionOption));
    }
  }
  async function _fetchProj(key: string): Promise<ProjectionResult | null> {
    const o = projOptions.value.find((x) => projKey(x) === key);
    if (!o) return null;
    return api.graphs.projection(variantId, {
      target_layer: o.target_layer,
      via: o.via,
      neighbor_layer: o.neighbor_layer,
      normalization: projNorm.value,
    });
  }
  async function applyProjection() {
    projLoading.value = true;
    try {
      projResult.value = await _fetchProj(projChoiceKey.value);
      projResultB.value = projChoiceKeyB.value
        ? await _fetchProj(projChoiceKeyB.value)
        : null;
      showDerived.value = true; // make the overlay visible
    } finally {
      projLoading.value = false;
    }
  }
  function clearProjection() {
    projResult.value = null;
    projResultB.value = null;
  }
  const highlightedNodes = ref<id[]>([]);
  // #2 — entities that exist before the timeline begins (stamp earlier than
  // the first event, or timeless). The scrubber's leading "⋯" cell selects
  // them as the genesis / pre-window population.
  const genesisNodeIds = computed<id[]>(() => {
    const evs = timeline.value ?? [];
    if (!evs.length) return [];
    const valid = tw.axis.value === "valid";
    const firstMs = Math.min(
      ...evs.map((e) => Date.parse(valid ? e.event_time : e.ingested_at)),
    );
    return (nodes.value ?? [])
      .filter((n) => n.layer === "entity")
      .filter((n) => {
        // ≤ first event: the initial population present when the timeline
        // opens (their creation isn't shown), plus timeless entities.
        const stamp = valid ? n.valid_from : n.tx_from;
        return stamp == null || Date.parse(stamp) <= firstMs;
      })
      .map((n) => n.id);
  });
  // Fine-grained graph filters, lifted here so LayersPanel (table) and
  // LayeredGraph (canvas) share the same state — pick "PERSON" in the
  // side panel and the canvas hides everything else, without a round-trip.
  const typeFilter = ref<string>("");
  const hideUnnamedCommunities = ref<boolean>(true);

  // §2.1 temporal window (shared, observable, lifted out of LayeredGraph).
  const tw = useTemporalWindow(variantId);
  // scrubber model: ISO (instant) or [t_a, t_b] (diff).
  const scrubModel = ref<string | [string, string] | null>(null);
  watch(scrubModel, (v) => {
    if (v != null) tw.scrubTo(v);
  });
  function onAxisChange(next: TimeAxis) {
    tw.setAxis(next);
    refreshTimeline();
  }
  // Switching to diff mode auto-fires a full-span diff so the delta
  // grammar + legend render immediately, without requiring a handle drag.
  function onDiffMode() {
    const evs = timeline.value ?? [];
    if (!evs.length) {
      tw.mode.value = "diff";
      return;
    }
    const key = tw.axis.value === "tx" ? "ingested_at" : "event_time";
    const times = evs.map((e) => e[key]).sort();
    scrubModel.value = [times[0], times[times.length - 1]];
  }
  // Opening the timeline shows a full-span period diff immediately (period is
  // the primary interaction) so the activity histogram + delta render at once.
  function onToggleTimeline() {
    showTimeline.value = !showTimeline.value;
    if (showTimeline.value && tw.mode.value === "diff" && !scrubModel.value) {
      onDiffMode();
    }
  }

  // §2.2 query-delta bridge (evidence highlight from the ask wizard).
  const queryDelta = useQueryDelta();
  const queryDeltaActive = computed(() => route.query.queryDelta === "1");

  // §2.3 — ONE edit cascade lifted to the page, bound to the live edge
  // set so its BFS ripple traverses the current adjacency. Passed down to
  // NodeDrawer / SuggestionsSidebar / InvalidationPanel; its transient
  // deltaIndex paints the shared LayeredGraph with deltaSource='edit'.
  const cascade = useEditCascade(variantId, () => edges.value ?? []);

  // §2.6 guided walkthrough — page owns the state; the overlay is mounted
  // at page root (never inside the wizard frame).
  const walkthrough = useWalkthrough();

  // The delta overlay fed to LayeredGraph. Priority: edit-cascade ripple
  // (transient, highest) > time diff > query-delta evidence.
  // #3 — a node that merely *persisted* across the window but gained or lost
  // an incident fact (edge born/dead/invalidated) is "changed", not static.
  // Upgrade those from persisted → changed using the edge endpoints.
  function withChanged(base: Map<string, DeltaState>): Map<string, DeltaState> {
    const out = new Map(base);
    for (const e of edges.value ?? []) {
      const est = base.get(String(e.id));
      if (est === "born" || est === "dead" || est === "invalidated") {
        for (const nid of [e.source_node_id, e.target_node_id]) {
          if (out.get(String(nid)) === "persisted") out.set(String(nid), "changed");
        }
      }
    }
    return out;
  }
  const deltaIndex = computed<Map<string, DeltaState> | null>(() => {
    if (cascade.rippleActive.value && cascade.deltaIndex.value)
      return cascade.deltaIndex.value;
    if (tw.mode.value === "diff" && tw.deltaIndex.value)
      return withChanged(tw.deltaIndex.value);
    if (queryDeltaActive.value) return queryDelta.buildDeltaIndex(variantId);
    return null;
  });
  const deltaSource = computed<DeltaSource>(() => {
    if (cascade.rippleActive.value && cascade.deltaIndex.value) return "edit";
    if (tw.mode.value === "diff" && tw.deltaIndex.value) return "time";
    if (queryDeltaActive.value && queryDelta.entryFor(variantId)) return "query";
    return null;
  });

  // Instant scrub SHRINKS the visible graph to the facts live at t (R1).
  const visibleNodes = computed<Node[]>(() => {
    const all = nodes.value ?? [];
    const ids = tw.visibleNodeIds.value;
    if (tw.mode.value !== "instant" || !ids) return all;
    return all.filter((n) => ids.has(String(n.id)));
  });
  const hasDerived = computed(
    () =>
      (edges.value ?? []).some((e) => e.type === "derived") ||
      projectionEdges.value.length > 0,
  );
  // #6 — on-the-fly layer-pair projection(s) overlaid as synthetic DERIVED
  // edges. Two slots (A orange, B teal) can be shown at once for comparison.
  function _projEdges(p: ProjectionResult | null, color: string, tag: string): Edge[] {
    if (!p || !variant.value) return [];
    return p.edges.map(
      (e) =>
        ({
          id: `proj${tag}:${e.source_node_id}:${e.target_node_id}`,
          graph_variant_id: variant.value!.id,
          type: "derived",
          source_node_id: e.source_node_id,
          target_node_id: e.target_node_id,
          weight: e.weight,
          relation: `${p.target_layer} via ${p.neighbor_layer}`,
          attributes: { color },
        }) as unknown as Edge,
    );
  }
  const projectionEdges = computed<Edge[]>(() => [
    ..._projEdges(projResult.value, PROJ_COLOR_A, "A"),
    ..._projEdges(projResultB.value, PROJ_COLOR_B, "B"),
  ]);
  const visibleEdges = computed<Edge[]>(() => {
    const proj = projectionEdges.value;
    // "Projections only": when a layer-pair projection is loaded and the
    // toggle is on, hide the base edges entirely so the two coloured
    // projection structures read cleanly instead of drowning in 3k+ edges.
    if (proj.length && projectionsOnly.value) return proj;
    let all = edges.value ?? [];
    if (!showDerived.value) all = all.filter((e) => e.type !== "derived");
    const ids = tw.visibleEdgeIds.value;
    if (tw.mode.value === "instant" && ids) {
      all = all.filter((e) => ids.has(String(e.id)));
    }
    return showDerived.value && proj.length ? [...all, ...proj] : all;
  });

  const selectedNode = computed<Node | null>(() => {
    if (selectedNodes.value.length !== 1) return null;
    const id = selectedNodes.value[0];
    return (nodes.value ?? []).find((n) => n.id === id) ?? null;
  });

  // Graph selection sink. In merge-pick mode a single click on a *different*
  // node is the absorbed target — capture it and keep the survivor selected
  // so the drawer stays put; any other selection exits pick mode normally.
  function onSelectNodes(ids: id[]) {
    if (mergePicking.value) {
      const survivor = selectedNodes.value[0];
      if (ids.length === 1 && ids[0] !== survivor) {
        mergePickTarget.value =
          (nodes.value ?? []).find((n) => n.id === ids[0]) ?? null;
        return; // don't move the drawer off the survivor
      }
      // clicked elsewhere / cleared selection → abandon the pick
      mergePicking.value = false;
      mergePickTarget.value = null;
    }
    // clicking empty space (ids = []) also clears the assistant's halos
    if (ids.length === 0) highlightedNodes.value = [];
    selectedNodes.value = ids;
  }

  function clearHighlight() {
    highlightedNodes.value = [];
  }

  function onMergePickCancel() {
    mergePicking.value = false;
    mergePickTarget.value = null;
  }

  // Edge counterpart — drives EdgeDrawer when the user clicks a link
  // (CityGraph already mutex's selectedNodes vs selectedLink).
  const selectedEdge = computed<Edge | null>(() => {
    const id = selectedLink.value;
    if (id == null) return null;
    return (edges.value ?? []).find((e) => e.id === id) ?? null;
  });

  const error = variantError.value || nodesError.value || edgesError.value;

  function onVariantChanged(v: GraphVariant) {
    if (variant.value) variant.value = v;
    refreshNodes();
    refreshEdges();
  }

  // Force-reload graph payloads on every version bump (curation op
  // applied) so the canvas reflects post-edit state.
  watch(
    () => variant.value?.version,
    () => {
      refreshNodes();
      refreshEdges();
      refreshTimeline();
    },
  );

  // §2.6 — auto-start the tour on ?walkthrough=1 (explicit) or on a first
  // visit (localStorage 'gr:walkthrough:seen' unset). Graph page only.
  // Esc cancels an in-flight merge pick (the LayeredGraph's own Esc only
  // clears the active layer, so we add a page-level guard).
  function onPageKeydown(e: KeyboardEvent) {
    if (e.key !== "Escape") return;
    if (mergePicking.value) onMergePickCancel();
    else if (highlightedNodes.value.length) clearHighlight();
  }

  onMounted(() => {
    if (route.query.walkthrough === "1" || !walkthrough.hasSeen()) {
      walkthrough.start();
    }
    window.addEventListener("keydown", onPageKeydown);
  });
  onBeforeUnmount(() => window.removeEventListener("keydown", onPageKeydown));
</script>

<template>
  <div :class="$style.page">
    <header :class="$style.header" v-if="variant">
      <div :class="$style.headerMain">
        <NuxtLink to="/corpora" :class="$style.back">{{ t("graph.backToCorpora") }}</NuxtLink>
        <h1 :class="$style.title">{{ variant.name }}</h1>
        <p :class="$style.muted">
          builder: <code>{{ variant.builder }}</code> · cleaners:
          <code>{{ variant.cleaner_chain.join(" → ") || "—" }}</code> · clusterer:
          <code>{{ variant.clusterer ?? "—" }}</code>
        </p>
      </div>

      <div :class="$style.headerActions">
        <button
          type="button"
          data-testid="ask-rag-toggle"
          :class="[$style.toggle, showRag ? $style.toggle_active : '']"
          @click="showRag = !showRag"
        >
          {{ t("graph.askRag") }}
        </button>
        <button
          type="button"
          data-testid="assistant-toggle"
          :class="[$style.toggle, showAssistant ? $style.toggle_active : '']"
          @click="showAssistant = !showAssistant"
        >
          {{ t("assistantChat.toggle") }}
        </button>
        <button
          type="button"
          :class="[$style.toggle, showSuggestions ? $style.toggle_active : '']"
          @click="showSuggestions = !showSuggestions"
        >
          {{ showSuggestions ? t("graph.hideSuggestions") : t("graph.showSuggestions") }}
        </button>
        <button
          type="button"
          :class="[$style.toggle, showLayers ? $style.toggle_active : '']"
          @click="showLayers = !showLayers"
        >
          {{ t("layersPanel.open") }}
        </button>
        <button
          type="button"
          data-testid="projection-toggle"
          :class="[$style.toggle, showProjection ? $style.toggle_active : '']"
          @click="toggleProjection"
        >
          {{ t("graph.layerProjection") }}
        </button>
        <button
          v-if="timeline && timeline.length"
          type="button"
          data-testid="timeline-toggle"
          :class="[$style.toggle, showTimeline ? $style.toggle_active : '']"
          @click="onToggleTimeline"
        >
          {{ t("timeline.toggle") }}
        </button>
        <button
          v-if="hasDerived"
          type="button"
          :class="[$style.toggle, showDerived ? $style.toggle_active : '']"
          @click="showDerived = !showDerived"
        >
          {{ showDerived ? t("graph.hideDerived") : t("graph.showDerived") }}
        </button>
        <button
          v-if="hasDerived"
          type="button"
          :class="[$style.toggle, showImportance ? $style.toggle_active : '']"
          @click="loadImportance"
        >
          {{ t("graph.projectionImportance") }}
        </button>
        <a
          :href="api.graphs.exportJournalUrl(variant.id, 'json')"
          target="_blank"
          rel="noopener"
          :class="$style.exportBtn"
        >
          {{ t("graph.exportJournal") }}
        </a>
      </div>

      <dl :class="$style.metrics">
        <div>
          <dt>Узлов</dt>
          <dd>{{ formatNumber(variant.node_count) }}</dd>
        </div>
        <div>
          <dt>Рёбер</dt>
          <dd>{{ formatNumber(variant.edge_count) }}</dd>
        </div>
        <div>
          <dt>Версия</dt>
          <dd>v{{ variant.version }}</dd>
        </div>
      </dl>
    </header>

    <div v-if="showImportance" :class="$style.importancePanel">
      <header :class="$style.importanceHead">
        <strong>{{ t("graph.projectionImportance") }}</strong>
        <button
          type="button"
          :class="$style.importanceClose"
          @click="showImportance = false"
        >
          ×
        </button>
      </header>
      <p v-if="loadingImportance" :class="$style.importanceNote">{{ t("common.loading") }}</p>
      <template v-else-if="importance">
        <p
          v-if="importance.most_redundant_pair"
          :class="$style.importanceNote"
        >
          {{ t("graph.mostRedundant") }}:
          {{ importance.most_redundant_pair.join(" ↔ ") }}
        </p>
        <ol :class="$style.importanceList">
          <li v-for="p in importance.projections" :key="p.name">
            <span :class="$style.importanceName">{{ p.name }}</span>
            <span :class="$style.importanceScore">{{
              (p.distinctiveness_jsd ?? p.distinctiveness_overlap).toFixed(3)
            }}</span>
            <span :class="$style.importanceMeta">{{ p.n_pairs }}</span>
          </li>
        </ol>
        <p v-if="importance.note" :class="$style.importanceNote">{{ importance.note }}</p>
      </template>
    </div>

    <div v-if="showProjection" :class="$style.importancePanel" data-testid="projection-panel">
      <header :class="$style.importanceHead">
        <strong>{{ t("graph.layerProjection") }}</strong>
        <button type="button" :class="$style.importanceClose" @click="showProjection = false">
          ×
        </button>
      </header>
      <label :class="$style.projRow">
        <span :class="$style.projLabel">
          <span :class="$style.projDot" :style="{ background: '#e8743b' }" /> {{ t("graph.projPair") }} A
        </span>
        <select v-model="projChoiceKey" :class="$style.projSelect" data-testid="projection-pair">
          <option v-for="o in projOptions" :key="projKey(o)" :value="projKey(o)">
            {{ o.label }}
          </option>
        </select>
      </label>
      <label :class="$style.projRow">
        <span :class="$style.projLabel">
          <span :class="$style.projDot" :style="{ background: '#1f9e89' }" /> {{ t("graph.projPair") }} B
        </span>
        <select v-model="projChoiceKeyB" :class="$style.projSelect" data-testid="projection-pair-b">
          <option value="">{{ t("graph.projNone") }}</option>
          <option v-for="o in projOptions" :key="projKey(o)" :value="projKey(o)">
            {{ o.label }}
          </option>
        </select>
      </label>
      <label :class="$style.cfgCheck" style="display:flex;gap:6px;align-items:center;margin-top:6px">
        <input v-model="projectionsOnly" type="checkbox" />
        {{ t("graph.projOnly") }}
      </label>
      <label :class="$style.projRow">
        <span :class="$style.projLabel">{{ t("graph.projNorm") }}</span>
        <select v-model="projNorm" :class="$style.projSelect">
          <option value="newman">newman</option>
          <option value="cosine">cosine</option>
          <option value="jaccard">jaccard</option>
          <option value="min">min</option>
          <option value="raw">raw</option>
        </select>
      </label>
      <div :class="$style.projActions">
        <button
          type="button"
          :class="$style.toggle"
          :disabled="projLoading || !projChoiceKey"
          data-testid="projection-apply"
          @click="applyProjection"
        >
          {{ projLoading ? t("common.loading") : t("graph.projApply") }}
        </button>
        <button
          v-if="projResult"
          type="button"
          :class="$style.toggle"
          @click="clearProjection"
        >
          {{ t("graph.projClear") }}
        </button>
      </div>
      <p v-if="projResult" :class="$style.importanceNote" data-testid="projection-count">
        <span :class="$style.projDot" :style="{ background: '#e8743b' }" />
        {{ t("graph.projEdges", { n: projResult.edges.length, norm: projResult.normalization }) }}
      </p>
      <p v-if="projResultB" :class="$style.importanceNote">
        <span :class="$style.projDot" :style="{ background: '#1f9e89' }" />
        {{ t("graph.projEdges", { n: projResultB.edges.length, norm: projResultB.normalization }) }}
      </p>
    </div>

    <div v-if="error" :class="$style.error">
      <ErrorBanner :error="error" />
    </div>

    <div v-else-if="variant && nodes && edges" :class="$style.body">
      <SuggestionsSidebar
        v-if="showSuggestions"
        :variant="variant"
        :cascade="cascade"
        @variant-changed="onVariantChanged"
        @highlight="(ids) => (highlightedNodes = ids)"
      />

      <AssistantChat
        v-if="showAssistant"
        :variant="variant"
        :selected-node-ids="selectedNodes.map(String)"
        :slice-node-ids="visibleNodes.map((n) => String(n.id))"
        @close="showAssistant = false"
        @variant-changed="onVariantChanged"
        @highlight="(ids) => (highlightedNodes = ids)"
      />

      <RagDialog
        v-if="showRag"
        :variant="variant"
        :as-of="ragAsOf"
        @close="showRag = false"
        @highlight="(ids) => (highlightedNodes = ids)"
      />

      <div :class="$style.canvasWrap">
        <ErrorBanner
          v-if="tw.error.value"
          :error="tw.error.value"
          :class="$style.temporalError"
        />

        <div
          data-testid="graph-canvas"
          :class="[$style.canvas, mergePicking ? $style.canvas_picking : '']"
        >
          <div
            v-if="mergePicking"
            data-testid="merge-pick-banner"
            :class="$style.mergePickBanner"
          >
            {{ t("graph.mergePickBanner") }}
          </div>
          <button
            v-if="highlightedNodes.length && !mergePicking"
            type="button"
            data-testid="clear-highlight"
            :class="$style.clearHighlight"
            @click="clearHighlight"
          >
            {{ t("graph.clearHighlight", { n: highlightedNodes.length }) }}
          </button>
          <!-- §2.3 transient ripple marker — lets e2e detect the ~600ms
               edit cascade is running and which source painted it. -->
          <span
            v-if="cascade.rippleActive.value"
            data-testid="edit-cascade"
            data-source="edit"
            :class="$style.cascadeMarker"
            aria-hidden="true"
          />
          <LayeredGraph
            :nodes="visibleNodes"
            :edges="visibleEdges"
            :theme="theme"
            :variant-id="variant.id"
            :highlighted-node-ids="highlightedNodes"
            :delta-index="deltaIndex"
            :delta-source="deltaSource"
            :selectedNodes="selectedNodes"
            @update:selectedNodes="onSelectNodes"
            v-model:selectedLink="selectedLink"
            v-model:typeFilter="typeFilter"
            v-model:hideUnnamedCommunities="hideUnnamedCommunities"
          />
          <LayersPanel
            v-if="showLayers"
            :nodes="nodes"
            :edges="edges"
            v-model:typeFilter="typeFilter"
            v-model:hideUnnamedCommunities="hideUnnamedCommunities"
            @close="showLayers = false"
            @select-node="(id) => (selectedNodes = [id])"
          />
        </div>

        <InvalidationPanel
          v-if="tw.mode.value === 'diff' && tw.lastDiff.value && tw.lastDiff.value.invalidated.length"
          :variant="variant"
          :diff="tw.lastDiff.value"
          :cascade="cascade"
          @variant-changed="onVariantChanged"
          @reverted="() => { refreshTimeline(); tw.refresh(); }"
        />

        <!-- §2.4 — page-level latency feedback for journal writes whose
             surface (e.g. the invalidation panel) collapses on success, so
             the badge isn't lost when the row it lived on drops out. -->
        <LatencyBadge
          v-if="cascade.lastTiming.value"
          :ms="cascade.lastTiming.value.recompute_ms"
          :node-count="cascade.lastTiming.value.node_count_after"
          :edge-count="cascade.lastTiming.value.edge_count_after"
          :class="$style.pageLatency"
        />

        <DeltaLegend
          v-if="deltaSource"
          data-testid="delta-legend"
          :source="deltaSource"
          :diff="tw.lastDiff.value"
        />

        <div v-if="showTimeline && timeline && timeline.length" :class="$style.timeline">
          <div :class="$style.timelineHead">
            <AxisToggle :model-value="tw.axis.value" @update:model-value="onAxisChange" />
            <div :class="$style.timelineModes">
              <button
                type="button"
                :class="[$style.modeBtn, tw.mode.value === 'instant' ? $style.modeBtn_active : '']"
                @click="tw.mode.value = 'instant'; tw.reset()"
              >
                {{ t("timeline.modeInstant") }}
              </button>
              <button
                type="button"
                :class="[$style.modeBtn, tw.mode.value === 'diff' ? $style.modeBtn_active : '']"
                @click="onDiffMode()"
              >
                {{ t("timeline.modeDiff") }}
              </button>
              <button type="button" :class="$style.modeBtn" @click="tw.reset()">
                {{ t("timeline.clear") }}
              </button>
            </div>
          </div>
          <TimelineScrubber
            v-model="scrubModel"
            :events="timeline"
            :axis="tw.axis.value"
            :mode="tw.mode.value"
            :playing="tw.playing.value"
            :genesis-count="genesisNodeIds.length"
            @update:playing="(p) => (tw.playing.value = p)"
            @select-genesis="highlightedNodes = genesisNodeIds"
          />
        </div>
      </div>

      <NodeDrawer
        v-if="selectedNode"
        :node="selectedNode"
        :variant="variant"
        :cascade="cascade"
        :all-nodes="nodes ?? []"
        :all-edges="edges ?? []"
        :visible-node-ids="visibleNodes.map((n) => n.id)"
        :merge-pick-target="mergePickTarget"
        @close="selectedNodes = []"
        @variant-changed="onVariantChanged"
        @merge-pick-start="mergePicking = true"
        @merge-pick-cancel="onMergePickCancel"
      />
      <EdgeDrawer
        v-else-if="selectedEdge"
        :edge="selectedEdge"
        :variant="variant"
        :cascade="cascade"
        :all-nodes="nodes ?? []"
        @close="selectedLink = null"
        @variant-changed="onVariantChanged"
        @select-node="(id) => (selectedNodes = [id])"
      />
    </div>

    <GuidedWalkthrough :walkthrough="walkthrough" />
  </div>
</template>

<style lang="scss" module>
  .page {
    display: flex;
    flex-direction: column;
    flex: 1;
    overflow: hidden;
  }

  .header {
    display: grid;
    grid-template-columns: 1fr auto auto;
    align-items: flex-start;
    gap: var(--gr-space-md);
    padding: var(--gr-space-md) var(--gr-space-xl);
    border-bottom: 1px solid var(--ksd-border-color);
    flex-shrink: 0;
  }

  .headerMain {
    min-width: 0;
  }

  .back {
    display: inline-block;
    margin-bottom: var(--gr-space-2xs);
    font-size: 0.875rem;
    color: var(--ksd-text-secondary-color);
    text-decoration: none;

    &:hover {
      color: var(--ksd-accent-color);
    }
  }

  .title {
    margin: 0 0 var(--gr-space-2xs);
    font-size: 1.5rem;
    font-weight: 700;
  }

  .muted {
    margin: 0;
    color: var(--ksd-text-secondary-color);
    font-size: 0.875rem;

    code {
      font-family: ui-monospace, monospace;
      background: var(--ksd-card-bg-color);
      padding: 0 var(--gr-space-2xs);
      border-radius: 3px;
    }
  }

  .headerActions {
    display: flex;
    align-items: center;
    gap: var(--gr-space-xs);
  }

  .toggle,
  .exportBtn {
    padding: var(--gr-space-2xs) var(--gr-space-sm);
    border: 1px solid var(--ksd-border-color);
    background: transparent;
    border-radius: var(--gr-radius-sm);
    cursor: pointer;
    color: var(--ksd-text-main-color);
    font-size: 0.875rem;
    text-decoration: none;

    &:hover {
      border-color: var(--ksd-accent-color);
      color: var(--ksd-accent-color);
    }
  }

  .toggle_active {
    background: var(--ksd-accent-color);
    color: var(--ksd-bg-color);
    border-color: var(--ksd-accent-color);

    &:hover {
      color: var(--ksd-bg-color);
    }
  }

  .metrics {
    display: flex;
    gap: var(--gr-space-lg);
    margin: 0;

    dt {
      font-size: 0.7rem;
      color: var(--ksd-text-secondary-color);
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }

    dd {
      margin: 0;
      font-size: 1.25rem;
      font-weight: 600;
    }
  }

  .body {
    flex: 1;
    display: flex;
    overflow: hidden;
  }

  .canvasWrap {
    flex: 1;
    display: flex;
    flex-direction: column;
    overflow: hidden;
    position: relative;
  }

  .canvas {
    flex: 1;
    overflow: hidden;
    position: relative;
  }

  .canvas_picking {
    cursor: crosshair;
    box-shadow: inset 0 0 0 2px var(--ksd-accent-color);
  }

  .mergePickBanner {
    position: absolute;
    top: var(--gr-space-sm);
    left: 50%;
    transform: translateX(-50%);
    z-index: 5;
    padding: var(--gr-space-2xs) var(--gr-space-sm);
    border-radius: var(--gr-radius-sm);
    background: var(--ksd-accent-color);
    color: #fff;
    font-size: 0.8125rem;
    box-shadow: var(--gr-shadow-sm, 0 1px 4px rgb(0 0 0 / 30%));
    pointer-events: none;
  }

  .clearHighlight {
    position: absolute;
    top: var(--gr-space-sm);
    right: var(--gr-space-sm);
    z-index: 7;
    padding: var(--gr-space-2xs) var(--gr-space-sm);
    border: 1px solid var(--ksd-accent-color);
    border-radius: var(--gr-radius-sm);
    background: var(--ksd-card-bg-color, var(--ksd-bg-color));
    color: var(--ksd-accent-color);
    font-size: 0.8125rem;
    cursor: pointer;
    box-shadow: var(--gr-shadow-sm, 0 1px 4px rgb(0 0 0 / 30%));

    &:hover {
      background: var(--ksd-accent-color);
      color: #fff;
    }
  }

  .cascadeMarker {
    position: absolute;
    top: 0;
    left: 0;
    width: 1px;
    height: 1px;
    pointer-events: none;
    opacity: 0;
  }

  .temporalError {
    margin: var(--gr-space-xs) var(--gr-space-md) 0;
  }

  .pageLatency {
    position: absolute;
    top: var(--gr-space-sm);
    right: var(--gr-space-sm);
    z-index: 5;
  }

  .timeline {
    flex-shrink: 0;
    border-top: 1px solid var(--ksd-border-color);
    background: var(--ksd-bg-color);
  }

  .timelineHead {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--gr-space-sm);
    padding: var(--gr-space-2xs) var(--gr-space-md) 0;
  }

  .timelineModes {
    display: flex;
    gap: var(--gr-space-2xs);
  }

  .modeBtn {
    padding: var(--gr-space-2xs) var(--gr-space-sm);
    border: 1px solid var(--ksd-border-color);
    background: transparent;
    border-radius: var(--gr-radius-sm);
    cursor: pointer;
    color: var(--ksd-text-main-color);
    font-size: 0.8rem;

    &:hover {
      border-color: var(--ksd-accent-color);
    }
  }

  .modeBtn_active {
    background: var(--ksd-accent-color);
    color: var(--ksd-bg-color);
    border-color: var(--ksd-accent-color);
  }

  .error {
    padding: var(--gr-space-xl);
    color: var(--gr-status-failed);
  }

  .importancePanel {
    position: absolute;
    right: var(--gr-space-md);
    top: 4rem;
    z-index: 20;
    width: 22rem;
    max-height: 60vh;
    overflow: auto;
    padding: var(--gr-space-md);
    background: var(--ksd-card-bg-color);
    border: 1px solid var(--ksd-border-color);
    border-radius: var(--gr-radius-md);
    box-shadow: var(--gr-shadow-md);
  }

  .projRow {
    display: flex;
    align-items: center;
    gap: var(--gr-space-xs);
    margin-top: var(--gr-space-xs);
  }
  .projLabel {
    flex: 0 0 5rem;
    font-size: 0.8125rem;
    color: var(--ksd-text-secondary-color, var(--ksd-text-main-color));
  }
  .projSelect {
    flex: 1;
    padding: var(--gr-space-2xs) var(--gr-space-xs);
    border: 1px solid var(--ksd-border-color);
    border-radius: var(--gr-radius-sm);
    background: var(--ksd-bg-color);
    color: var(--ksd-text-main-color);
    font-size: 0.8125rem;
  }
  .projActions {
    display: flex;
    gap: var(--gr-space-xs);
    margin-top: var(--gr-space-sm);
  }
  .projDot {
    display: inline-block;
    width: 9px;
    height: 9px;
    border-radius: 50%;
    vertical-align: middle;
  }

  .importanceHead {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: var(--gr-space-sm);
  }

  .importanceClose {
    border: none;
    background: transparent;
    cursor: pointer;
    font-size: 1.1rem;
    color: var(--ksd-text-secondary-color);
  }

  .importanceNote {
    margin: var(--gr-space-xs) 0;
    font-size: 0.8125rem;
    color: var(--ksd-text-secondary-color);
  }

  .importanceList {
    margin: var(--gr-space-xs) 0 0;
    padding-left: 1.2rem;

    li {
      display: flex;
      align-items: baseline;
      gap: var(--gr-space-sm);
      margin: 0.15rem 0;
    }
  }

  .importanceName {
    flex: 1;
    font-family: var(--gr-font-mono, monospace);
    font-size: 0.8125rem;
  }

  .importanceScore {
    font-variant-numeric: tabular-nums;
    font-weight: 600;
  }

  .importanceMeta {
    font-size: 0.75rem;
    color: var(--ksd-text-secondary-color);
  }
</style>
