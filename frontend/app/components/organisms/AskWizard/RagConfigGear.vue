<script setup lang="ts">
  import { onMounted, ref } from "vue";
  import { useI18n } from "vue-i18n";

  import type { ReasonMode } from "@/entities/api";
  import { useAskWizard } from "@/composables/use-ask-wizard";

  // A saved RAG config: the strategy knobs only (not the question or which
  // variants — those are per-session). Persisted in localStorage so the
  // operator can keep a few named setups and switch them right from the
  // question box.
  type RagConfig = {
    name: string;
    mode: ReasonMode;
    reasoner: string;
    aggregator: string;
    reasoner_params: Record<string, unknown>;
    aggregator_params: Record<string, unknown>;
  };

  const STORAGE_KEY = "gr:rag-configs";

  const { t } = useI18n();
  const wizard = useAskWizard();

  const open = ref(false);
  const configs = ref<RagConfig[]>([]);
  const newName = ref("");

  function load() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      configs.value = raw ? (JSON.parse(raw) as RagConfig[]) : [];
    } catch {
      configs.value = [];
    }
  }
  function persist() {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(configs.value));
  }
  onMounted(load);

  function applyConfig(c: RagConfig) {
    const d = wizard.data.value;
    d.mode = c.mode;
    d.reasoner = c.reasoner;
    d.aggregator = c.aggregator;
    d.reasoner_params = { ...c.reasoner_params };
    d.aggregator_params = { ...c.aggregator_params };
    // strategy changed → re-validate strategy step + downstream
    wizard.invalidateDownstream(2);
    open.value = false;
  }

  function saveCurrent() {
    const name = newName.value.trim();
    if (!name) return;
    const d = wizard.data.value;
    const cfg: RagConfig = {
      name,
      mode: d.mode,
      reasoner: d.reasoner,
      aggregator: d.aggregator,
      reasoner_params: { ...d.reasoner_params },
      aggregator_params: { ...d.aggregator_params },
    };
    const idx = configs.value.findIndex((c) => c.name === name);
    if (idx >= 0) configs.value[idx] = cfg;
    else configs.value.push(cfg);
    persist();
    newName.value = "";
  }

  function removeConfig(name: string) {
    configs.value = configs.value.filter((c) => c.name !== name);
    persist();
  }
</script>

<template>
  <div :class="$style.wrap">
    <button
      type="button"
      :class="$style.gear"
      data-testid="rag-config-gear"
      :title="t('wizard.ask.configTitle')"
      :aria-label="t('wizard.ask.configTitle')"
      @click="open = !open"
    >
      ⚙
    </button>

    <div v-if="open" :class="$style.panel" data-testid="rag-config-panel">
      <h4 :class="$style.head">{{ t("wizard.ask.configTitle") }}</h4>

      <ul v-if="configs.length" :class="$style.list">
        <li v-for="c in configs" :key="c.name" :class="$style.item">
          <button
            type="button"
            :class="$style.apply"
            data-testid="rag-config-apply"
            @click="applyConfig(c)"
          >
            <strong>{{ c.name }}</strong>
            <span :class="$style.meta">{{ c.mode }} · {{ c.reasoner }} · {{ c.aggregator }}</span>
          </button>
          <button
            type="button"
            :class="$style.del"
            :aria-label="t('wizard.ask.configDelete')"
            @click="removeConfig(c.name)"
          >
            ×
          </button>
        </li>
      </ul>
      <p v-else :class="$style.empty">{{ t("wizard.ask.configEmpty") }}</p>

      <div :class="$style.saveRow">
        <input
          v-model="newName"
          :class="$style.nameInput"
          :placeholder="t('wizard.ask.configNamePlaceholder')"
          data-testid="rag-config-name"
          @keydown.enter.prevent="saveCurrent"
        />
        <button
          type="button"
          :class="$style.save"
          data-testid="rag-config-save"
          :disabled="!newName.trim()"
          @click="saveCurrent"
        >
          {{ t("wizard.ask.configSave") }}
        </button>
      </div>
    </div>
  </div>
</template>

<style lang="scss" module>
  .wrap {
    position: relative;
    display: inline-block;
  }
  .gear {
    border: 1px solid var(--ksd-border-color);
    border-radius: var(--gr-radius-sm);
    background: transparent;
    color: var(--ksd-text-main-color);
    cursor: pointer;
    font-size: 1.6rem;
    line-height: 1;
    padding: 6px 12px;

    &:hover {
      border-color: var(--ksd-accent-color);
    }
  }
  .panel {
    position: absolute;
    z-index: 30;
    top: calc(100% + 4px);
    left: 0;
    width: 20rem;
    padding: var(--gr-space-sm);
    background: var(--ksd-card-bg-color, var(--ksd-bg-color));
    border: 1px solid var(--ksd-border-color);
    border-radius: var(--gr-radius-md);
    box-shadow: var(--gr-shadow-md, 0 4px 16px rgb(0 0 0 / 25%));
  }
  .head {
    margin: 0 0 var(--gr-space-xs);
    font-size: 0.9rem;
  }
  .list {
    list-style: none;
    margin: 0 0 var(--gr-space-sm);
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: var(--gr-space-2xs);
    max-height: 240px;
    overflow-y: auto;
  }
  .item {
    display: flex;
    gap: var(--gr-space-2xs);
    align-items: stretch;
  }
  .apply {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: 1px;
    text-align: left;
    padding: var(--gr-space-2xs) var(--gr-space-xs);
    border: 1px solid var(--ksd-border-color);
    border-radius: var(--gr-radius-sm);
    background: transparent;
    color: var(--ksd-text-main-color);
    cursor: pointer;

    &:hover {
      border-color: var(--ksd-accent-color);
    }
  }
  .meta {
    font-size: 0.75rem;
    color: var(--ksd-text-secondary-color);
  }
  .del {
    border: 1px solid var(--ksd-border-color);
    border-radius: var(--gr-radius-sm);
    background: transparent;
    color: var(--ksd-text-secondary-color);
    cursor: pointer;
    padding: 0 var(--gr-space-xs);

    &:hover {
      color: #fff;
      background: var(--ksd-danger-color, #c0392b);
      border-color: var(--ksd-danger-color, #c0392b);
    }
  }
  .empty {
    margin: 0 0 var(--gr-space-sm);
    font-size: 0.8125rem;
    color: var(--ksd-text-secondary-color);
  }
  .saveRow {
    display: flex;
    gap: var(--gr-space-2xs);
  }
  .nameInput {
    flex: 1;
    padding: var(--gr-space-2xs) var(--gr-space-xs);
    border: 1px solid var(--ksd-border-color);
    border-radius: var(--gr-radius-sm);
    background: var(--ksd-bg-color);
    color: var(--ksd-text-main-color);
    font-size: 0.8125rem;
  }
  .save {
    padding: var(--gr-space-2xs) var(--gr-space-sm);
    border: none;
    border-radius: var(--gr-radius-sm);
    background: var(--ksd-accent-color);
    color: #fff;
    cursor: pointer;
    font-size: 0.8125rem;

    &:disabled {
      opacity: 0.5;
      cursor: not-allowed;
    }
  }
</style>
