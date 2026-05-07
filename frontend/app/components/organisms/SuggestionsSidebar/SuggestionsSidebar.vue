<script setup lang="ts">
  import { useAsyncData } from "nuxt/app";
  import { computed, ref } from "vue";

  import type { GraphVariant, StrategyDescriptor, Suggestion } from "@/entities/api";
  import { useApi } from "@/lib/api-client";
  import { formatRelativeTime } from "@/lib/format";

  type Props = {
    variant: GraphVariant;
    actor?: string;
  };

  const props = withDefaults(defineProps<Props>(), {
    actor: "user:wizard",
  });

  const emit = defineEmits<{
    (e: "applied", journal_entry_id: string): void;
    (e: "variant-changed", variant: GraphVariant): void;
  }>();

  const api = useApi();

  const { data: suggestions, refresh } = await useAsyncData(
    () => `suggestions:${props.variant.id}`,
    () =>
      api.agents.listSuggestions(props.variant.id, { status: "pending" }),
    { watch: [() => props.variant.id, () => props.variant.version] },
  );

  const { data: agents } = await useAsyncData("agent-catalog", () =>
    api.agents.list(),
  );

  const runningAgent = ref<string | null>(null);
  const error = ref<string | null>(null);
  const decideId = ref<string | null>(null);
  const filter = ref<string>("");

  const filtered = computed(() => {
    if (!filter.value) return suggestions.value ?? [];
    return (suggestions.value ?? []).filter((s) => s.agent === filter.value);
  });

  const agentNames = computed(() => {
    const fromSuggestions = new Set(
      (suggestions.value ?? []).map((s) => s.agent),
    );
    return Array.from(fromSuggestions).sort();
  });

  async function runAgent(name: string) {
    runningAgent.value = name;
    error.value = null;
    try {
      await api.agents.run(props.variant.id, name);
      await refresh();
    } catch (e) {
      error.value = e instanceof Error ? e.message : String(e);
    } finally {
      runningAgent.value = null;
    }
  }

  async function accept(s: Suggestion) {
    decideId.value = s.id;
    error.value = null;
    try {
      const result = await api.agents.accept(s.id, {
        expected_variant_version: props.variant.version,
        actor: props.actor,
      });
      emit("applied", result.entry.id);
      emit("variant-changed", result.variant);
      await refresh();
    } catch (e) {
      error.value = e instanceof Error ? e.message : String(e);
    } finally {
      decideId.value = null;
    }
  }

  async function reject(s: Suggestion) {
    decideId.value = s.id;
    error.value = null;
    try {
      await api.agents.reject(s.id, { actor: props.actor });
      await refresh();
    } catch (e) {
      error.value = e instanceof Error ? e.message : String(e);
    } finally {
      decideId.value = null;
    }
  }
</script>

<template>
  <aside :class="$style.sidebar" aria-label="Pending suggestions">
    <header :class="$style.header">
      <h2 :class="$style.title">
        Suggestions
        <span :class="$style.muted">
          {{ (suggestions ?? []).length }} pending
        </span>
      </h2>
    </header>

    <section :class="$style.runner">
      <h3 :class="$style.subhead">Запустить агента</h3>
      <div :class="$style.agentChips">
        <button
          v-for="a in (agents as StrategyDescriptor[] | null) ?? []"
          :key="a.name"
          type="button"
          :class="$style.agentChip"
          :disabled="runningAgent !== null"
          :title="a.description"
          @click="runAgent(a.name)"
        >
          {{ a.name }}
          <span v-if="runningAgent === a.name" :class="$style.muted">…</span>
        </button>
      </div>
    </section>

    <section v-if="error" :class="$style.error">{{ error }}</section>

    <section :class="$style.filterRow" v-if="agentNames.length > 1">
      <label :class="$style.muted" for="agent-filter">Фильтр:</label>
      <select id="agent-filter" v-model="filter" :class="$style.select">
        <option value="">все</option>
        <option v-for="name in agentNames" :key="name" :value="name">
          {{ name }}
        </option>
      </select>
    </section>

    <ul :class="$style.list" v-if="filtered.length">
      <li
        v-for="s in filtered"
        :key="s.id"
        :class="$style.row"
      >
        <header :class="$style.rowHeader">
          <code :class="$style.agentTag">{{ s.agent }}</code>
          <span :class="$style.actionTag">{{ s.action }}</span>
          <span :class="$style.confChip">conf {{ s.confidence.toFixed(2) }}</span>
        </header>
        <p :class="$style.rationale">{{ s.rationale }}</p>
        <footer :class="$style.actions">
          <button
            type="button"
            :class="$style.accept"
            :disabled="decideId !== null"
            @click="accept(s)"
          >
            Accept
          </button>
          <button
            type="button"
            :class="$style.reject"
            :disabled="decideId !== null"
            @click="reject(s)"
          >
            Reject
          </button>
          <span :class="$style.muted">
            {{ formatRelativeTime(s.created_at) }}
          </span>
        </footer>
      </li>
    </ul>

    <p v-else :class="$style.empty">
      Pending suggestions нет — запустите агента выше.
    </p>
  </aside>
</template>

<style lang="scss" module>
  .sidebar {
    display: flex;
    flex-direction: column;
    gap: var(--gr-space-md);
    width: 320px;
    max-width: 100%;
    height: 100%;
    background: var(--ksd-card-bg-color);
    border-right: 1px solid var(--ksd-border-color);
    padding: var(--gr-space-md);
    overflow-y: auto;
    flex-shrink: 0;
  }

  .header {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
  }

  .title {
    margin: 0;
    font-size: 1rem;
    font-weight: 600;
  }

  .muted {
    color: var(--ksd-text-secondary-color);
    font-weight: 400;
    font-size: 0.875rem;
  }

  .subhead {
    margin: 0 0 var(--gr-space-2xs);
    font-size: 0.875rem;
    font-weight: 600;
    color: var(--ksd-text-secondary-color);
  }

  .runner {
    display: flex;
    flex-direction: column;
    gap: var(--gr-space-2xs);
  }

  .agentChips {
    display: flex;
    flex-wrap: wrap;
    gap: var(--gr-space-2xs);
  }

  .agentChip {
    padding: var(--gr-space-2xs) var(--gr-space-xs);
    border: 1px solid var(--ksd-border-color);
    background: transparent;
    border-radius: var(--gr-radius-sm);
    cursor: pointer;
    color: var(--ksd-text-main-color);
    font-size: 0.75rem;
    font-family: ui-monospace, monospace;

    &:hover:not(:disabled) {
      border-color: var(--ksd-accent-color);
    }

    &:disabled {
      opacity: 0.5;
      cursor: not-allowed;
    }
  }

  .error {
    padding: var(--gr-space-xs);
    border: 1px solid var(--gr-status-failed);
    background: rgba(239, 68, 68, 0.08);
    border-radius: var(--gr-radius-sm);
    font-size: 0.875rem;
  }

  .filterRow {
    display: flex;
    align-items: center;
    gap: var(--gr-space-xs);
  }

  .select {
    padding: 2px var(--gr-space-2xs);
    border: 1px solid var(--ksd-border-color);
    border-radius: var(--gr-radius-sm);
    background: var(--ksd-bg-color);
    color: var(--ksd-text-main-color);
  }

  .list {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: var(--gr-space-xs);
  }

  .row {
    display: flex;
    flex-direction: column;
    gap: var(--gr-space-2xs);
    padding: var(--gr-space-xs);
    border: 1px solid var(--ksd-border-color);
    border-radius: var(--gr-radius-sm);
    background: var(--ksd-bg-color);
  }

  .rowHeader {
    display: flex;
    align-items: center;
    gap: var(--gr-space-2xs);
    flex-wrap: wrap;
  }

  .agentTag {
    font-family: ui-monospace, monospace;
    font-size: 0.75rem;
    background: var(--ksd-card-bg-color);
    padding: 1px var(--gr-space-2xs);
    border-radius: var(--gr-radius-sm);
  }

  .actionTag {
    padding: 1px var(--gr-space-2xs);
    background: var(--ksd-accent-color);
    color: var(--ksd-bg-color);
    font-size: 0.7rem;
    border-radius: var(--gr-radius-sm);
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }

  .confChip {
    margin-left: auto;
    font-size: 0.75rem;
    color: var(--ksd-text-secondary-color);
  }

  .rationale {
    margin: 0;
    font-size: 0.875rem;
    line-height: 1.4;
  }

  .actions {
    display: flex;
    align-items: center;
    gap: var(--gr-space-2xs);
  }

  .accept,
  .reject {
    padding: 2px var(--gr-space-xs);
    font-size: 0.75rem;
    border: 1px solid;
    border-radius: var(--gr-radius-sm);
    background: transparent;
    cursor: pointer;
    font-weight: 600;

    &:disabled {
      opacity: 0.5;
      cursor: not-allowed;
    }
  }

  .accept {
    border-color: var(--gr-status-success);
    color: var(--gr-status-success);

    &:hover:not(:disabled) {
      background: var(--gr-status-success);
      color: white;
    }
  }

  .reject {
    border-color: var(--gr-status-failed);
    color: var(--gr-status-failed);

    &:hover:not(:disabled) {
      background: var(--gr-status-failed);
      color: white;
    }
  }

  .empty {
    padding: var(--gr-space-md);
    text-align: center;
    color: var(--ksd-text-secondary-color);
    font-size: 0.875rem;
  }
</style>
