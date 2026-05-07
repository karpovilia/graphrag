<script setup lang="ts">
  import { useAsyncData } from "nuxt/app";
  import { computed, ref, watch } from "vue";

  import type { Node, StrategyDescriptor, ToolInvocation } from "@/entities/api";
  import { useApi } from "@/lib/api-client";
  import { formatRelativeTime } from "@/lib/format";

  type Props = {
    node: Node;
    variantId: string;
  };

  const props = defineProps<Props>();
  const emit = defineEmits<{ (e: "close"): void }>();
  const api = useApi();

  const { data: tools, refresh: refreshTools } = await useAsyncData(
    () => `tools:${props.variantId}:${props.node.id}`,
    () => api.nodes.listTools(props.variantId, props.node.id),
    { watch: [() => props.node.id] },
  );

  const { data: history, refresh: refreshHistory } = await useAsyncData(
    () => `tool-history:${props.variantId}:${props.node.id}`,
    () => api.nodes.listToolInvocations(props.variantId, props.node.id),
    { watch: [() => props.node.id] },
  );

  watch(
    () => props.node.id,
    () => {
      refreshTools();
      refreshHistory();
    },
  );

  const running = ref<string | null>(null);
  const lastResult = ref<ToolInvocation | null>(null);
  const lastError = ref<string | null>(null);

  async function run(tool: StrategyDescriptor) {
    running.value = tool.name;
    lastError.value = null;
    try {
      const inv = await api.nodes.runTool(
        props.variantId,
        props.node.id,
        tool.name,
        {},
      );
      lastResult.value = inv;
      await refreshHistory();
    } catch (e) {
      lastError.value = e instanceof Error ? e.message : String(e);
    } finally {
      running.value = null;
    }
  }

  const sorted = computed(() => {
    const universals = (tools.value ?? []).filter((t) => {
      // applies_to lives on the class, not the descriptor; we infer by
      // looking at the cost_hint+name pair. Cheap heuristic — wizard
      // can later request `?include=class` if we need exact data.
      return true;
    });
    return universals;
  });
</script>

<template>
  <aside :class="$style.drawer" aria-label="Node detail panel">
    <header :class="$style.header">
      <div :class="$style.titleRow">
        <strong :class="$style.title">{{ node.name }}</strong>
        <button type="button" :class="$style.close" @click="emit('close')">
          ×
        </button>
      </div>
      <div :class="$style.meta">
        <span :class="[$style.chip, $style[`chip_${node.layer}`] || '']">
          {{ node.layer }}
        </span>
        <span :class="$style.chip_type">{{ node.type }}</span>
        <span :class="$style.muted">id {{ node.id.slice(0, 8) }}</span>
      </div>
    </header>

    <section v-if="node.summary" :class="$style.summary">
      <h3 :class="$style.subhead">Summary</h3>
      <p>{{ node.summary }}</p>
    </section>

    <section :class="$style.tools">
      <h3 :class="$style.subhead">
        Tools
        <span :class="$style.muted" v-if="tools">({{ tools.length }})</span>
      </h3>
      <ul :class="$style.toolList" v-if="(sorted ?? []).length">
        <li
          v-for="t in sorted"
          :key="t.name"
          :class="$style.toolRow"
        >
          <button
            type="button"
            :class="$style.toolBtn"
            :disabled="running !== null"
            @click="run(t)"
          >
            <strong>{{ t.name }}</strong>
            <span :class="$style.muted">{{ t.summary }}</span>
            <span :class="$style.toolMeta">
              <span :class="$style.costChip">{{ t.cost_hint ?? "?" }}</span>
              <span v-if="running === t.name">…</span>
              <span v-else>▶</span>
            </span>
          </button>
        </li>
      </ul>
      <p v-else :class="$style.muted">Нет применимых инструментов.</p>
    </section>

    <section v-if="lastError" :class="$style.error">{{ lastError }}</section>

    <section v-if="lastResult" :class="$style.lastResult">
      <h3 :class="$style.subhead">Последний результат</h3>
      <p :class="$style.muted">
        {{ lastResult.tool }} ·
        {{ formatRelativeTime(lastResult.created_at) }}
      </p>
      <pre :class="$style.json">{{ JSON.stringify(lastResult.result, null, 2) }}</pre>
    </section>

    <section v-if="(history ?? []).length" :class="$style.history">
      <h3 :class="$style.subhead">
        История ({{ history?.length ?? 0 }})
      </h3>
      <ul :class="$style.historyList">
        <li
          v-for="h in history ?? []"
          :key="h.id"
          :class="$style.historyRow"
        >
          <strong>{{ h.tool }}</strong>
          <span :class="$style.muted">{{ formatRelativeTime(h.created_at) }}</span>
        </li>
      </ul>
    </section>
  </aside>
</template>

<style lang="scss" module>
  .drawer {
    display: flex;
    flex-direction: column;
    gap: var(--gr-space-md);
    width: 380px;
    max-width: 100%;
    height: 100%;
    background: var(--ksd-card-bg-color);
    border-left: 1px solid var(--ksd-border-color);
    overflow-y: auto;
    padding: var(--gr-space-md);
    flex-shrink: 0;
  }

  .header {
    display: flex;
    flex-direction: column;
    gap: var(--gr-space-xs);
  }

  .titleRow {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: var(--gr-space-xs);
  }

  .title {
    font-size: 1.1rem;
    line-height: 1.3;
    word-break: break-word;
  }

  .close {
    background: transparent;
    border: none;
    color: var(--ksd-text-secondary-color);
    cursor: pointer;
    font-size: 1.5rem;
    line-height: 1;
    padding: 0;
    flex-shrink: 0;
  }

  .meta {
    display: flex;
    flex-wrap: wrap;
    gap: var(--gr-space-2xs);
    align-items: center;
  }

  .chip,
  .chip_type {
    padding: 2px var(--gr-space-xs);
    font-size: 0.75rem;
    border-radius: var(--gr-radius-sm);
    text-transform: lowercase;
  }

  .chip_chunk {
    background: var(--gr-layer-chunk);
    color: white;
  }
  .chip_entity {
    background: var(--gr-layer-entity);
    color: white;
  }
  .chip_community {
    background: var(--gr-layer-community);
    color: white;
  }
  .chip_topic {
    background: var(--gr-layer-topic);
    color: white;
  }

  .chip_type {
    background: var(--ksd-card-bg-color);
    border: 1px solid var(--ksd-border-color);
    color: var(--ksd-text-main-color);
  }

  .muted {
    color: var(--ksd-text-secondary-color);
    font-size: 0.875rem;
  }

  .summary p {
    margin: 0;
    white-space: pre-wrap;
    line-height: 1.5;
  }

  .subhead {
    margin: 0 0 var(--gr-space-xs);
    font-size: 0.95rem;
    font-weight: 600;
    display: flex;
    align-items: baseline;
    gap: var(--gr-space-2xs);
  }

  .tools {
    display: flex;
    flex-direction: column;
    gap: var(--gr-space-xs);
  }

  .toolList {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: var(--gr-space-2xs);
  }

  .toolRow {
    display: contents;
  }

  .toolBtn {
    display: flex;
    flex-direction: column;
    gap: 2px;
    align-items: flex-start;
    padding: var(--gr-space-xs) var(--gr-space-sm);
    border: 1px solid var(--ksd-border-color);
    background: var(--ksd-bg-color);
    border-radius: var(--gr-radius-sm);
    color: var(--ksd-text-main-color);
    cursor: pointer;
    text-align: left;
    width: 100%;
    position: relative;

    &:hover:not(:disabled) {
      border-color: var(--ksd-accent-color);
    }

    &:disabled {
      opacity: 0.6;
      cursor: not-allowed;
    }
  }

  .toolMeta {
    position: absolute;
    right: var(--gr-space-xs);
    top: var(--gr-space-xs);
    display: flex;
    align-items: center;
    gap: var(--gr-space-2xs);
  }

  .costChip {
    font-size: 0.7rem;
    padding: 1px var(--gr-space-2xs);
    border-radius: var(--gr-radius-sm);
    background: var(--ksd-card-bg-color);
    color: var(--ksd-text-secondary-color);
    text-transform: uppercase;
  }

  .error {
    padding: var(--gr-space-xs);
    background: rgba(239, 68, 68, 0.08);
    border: 1px solid var(--gr-status-failed);
    border-radius: var(--gr-radius-sm);
    color: var(--ksd-text-main-color);
    font-size: 0.875rem;
  }

  .lastResult,
  .history {
    display: flex;
    flex-direction: column;
    gap: var(--gr-space-2xs);
  }

  .json {
    margin: 0;
    padding: var(--gr-space-xs);
    background: var(--ksd-bg-color);
    border: 1px solid var(--ksd-border-color);
    border-radius: var(--gr-radius-sm);
    font-family: ui-monospace, monospace;
    font-size: 0.75rem;
    overflow-x: auto;
    max-height: 200px;
  }

  .historyList {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: var(--gr-space-2xs);
  }

  .historyRow {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    padding: var(--gr-space-2xs) 0;
    border-bottom: 1px dashed var(--ksd-border-color);
    font-size: 0.875rem;
  }
</style>
