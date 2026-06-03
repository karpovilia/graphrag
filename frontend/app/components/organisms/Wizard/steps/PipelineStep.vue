<script setup lang="ts">
  import { useAsyncData } from "nuxt/app";
  import { computed, reactive, watch } from "vue";
  import { useI18n } from "vue-i18n";

  import { useBuildWizard } from "@/composables/use-build-wizard";
  import { useApi } from "@/lib/api-client";

  const { t } = useI18n();
  const wizard = useBuildWizard();
  const api = useApi();

  // ---- LLM override form ----
  //
  // Lives entirely in the wizard's BuildVariantRequest: empty fields →
  // omit `llm_override` from the payload → backend uses its default LLM.
  // Presets are convenience nudges; the user can edit any field after
  // applying a preset. base_url is the discriminator the backend
  // actually receives — provider name is just a label for the UI.
  type LLMPreset = "openai" | "deepseek" | "ollama" | "custom";
  const LLM_PRESETS: Record<
    LLMPreset,
    { base_url: string; model: string; placeholderKey: string }
  > = {
    openai: {
      base_url: "https://api.openai.com/v1",
      model: "gpt-4o-mini",
      placeholderKey: "sk-…",
    },
    deepseek: {
      base_url: "https://api.deepseek.com",
      model: "deepseek-chat",
      placeholderKey: "sk-…",
    },
    ollama: {
      base_url: "http://localhost:11434/v1",
      model: "qwen2.5:7b",
      placeholderKey: "ollama (можно пусто)",
    },
    custom: { base_url: "", model: "", placeholderKey: "" },
  };
  const llmForm = reactive({
    base_url: wizard.data.value.build_request.llm_override?.base_url ?? "",
    api_key: wizard.data.value.build_request.llm_override?.api_key ?? "",
    model: wizard.data.value.build_request.llm_override?.model ?? "",
  });
  function applyPreset(p: LLMPreset) {
    const preset = LLM_PRESETS[p];
    llmForm.base_url = preset.base_url;
    llmForm.model = preset.model;
    // Don't clear api_key — user may have already pasted it.
  }
  function clearLLM() {
    llmForm.base_url = "";
    llmForm.api_key = "";
    llmForm.model = "";
  }
  function detectPreset(): LLMPreset | null {
    for (const k of ["openai", "deepseek", "ollama"] as LLMPreset[]) {
      if (llmForm.base_url === LLM_PRESETS[k].base_url) return k;
    }
    return llmForm.base_url ? "custom" : null;
  }
  const activePreset = computed<LLMPreset | null>(() => detectPreset());
  const placeholderApiKey = computed<string>(() => {
    const p = activePreset.value;
    return p ? LLM_PRESETS[p].placeholderKey : "sk-…";
  });
  watch(
    llmForm,
    () => {
      const url = llmForm.base_url.trim();
      const model = llmForm.model.trim();
      // Both required to take effect; partial form → null (i.e. fall back
      // to server default). api_key is optional — local servers accept any.
      if (!url || !model) {
        wizard.data.value.build_request.llm_override = null;
      } else {
        wizard.data.value.build_request.llm_override = {
          base_url: url,
          model,
          api_key: llmForm.api_key,
        };
      }
      wizard.invalidateDownstream(3);
    },
    { deep: true },
  );

  const { data: builders } = await useAsyncData("builders", () =>
    api.strategies.listKind("builder"),
  );
  const { data: cleaners } = await useAsyncData("cleaners", () =>
    api.strategies.listKind("cleaner"),
  );
  const { data: clusterers } = await useAsyncData("clusterers", () =>
    api.strategies.listKind("clusterer"),
  );
  const { data: projectors } = await useAsyncData("projectors", () =>
    api.strategies.listKind("projector"),
  );

  const recommendation = computed(() => wizard.data.value.eda?.recommendation);

  function toggleCleaner(name: string) {
    const chain = wizard.data.value.build_request.cleaner_chain ?? [];
    const idx = chain.indexOf(name);
    const next = idx === -1 ? [...chain, name] : chain.filter((c) => c !== name);
    wizard.data.value.build_request.cleaner_chain = next;
    wizard.invalidateDownstream(3);
  }

  function selectBuilder(name: string) {
    wizard.data.value.build_request.builder = name;
    wizard.invalidateDownstream(3);
  }

  function selectClusterer(name: string | null) {
    wizard.data.value.build_request.clusterer = name;
    wizard.invalidateDownstream(3);
  }

  function selectProjector(name: string | null) {
    wizard.data.value.build_request.projector = name;
    wizard.invalidateDownstream(3);
  }

  // Editable scalar/enum params of the currently-selected projector,
  // surfaced as inputs (e.g. multiprojection's `normalization`). Object/
  // array params (e.g. `projections`) are left to their schema defaults.
  type ParamMeta = {
    type?: string;
    default?: unknown;
    enum?: string[];
    description?: string;
  };
  const selectedProjector = computed(() =>
    (projectors.value ?? []).find(
      (p) => p.name === wizard.data.value.build_request.projector,
    ) ?? null,
  );
  const projectorScalarParams = computed(() => {
    const schema = (selectedProjector.value?.params_schema ?? {}) as Record<
      string,
      ParamMeta
    >;
    return Object.entries(schema)
      .filter(([, v]) =>
        ["string", "number", "integer", "boolean"].includes(v?.type ?? ""),
      )
      .map(([key, v]) => ({ key, ...v }));
  });
  function projectorParamValue(key: string, def: unknown): unknown {
    const pp = wizard.data.value.build_request.projector_params ?? {};
    return pp[key] ?? def;
  }
  function setProjectorParam(key: string, raw: unknown, type?: string) {
    let v: unknown = raw;
    if (type === "number" || type === "integer") v = raw === "" ? undefined : Number(raw);
    if (type === "boolean") v = Boolean(raw);
    const pp = { ...(wizard.data.value.build_request.projector_params ?? {}) };
    if (v === undefined || v === "") delete pp[key];
    else pp[key] = v;
    wizard.data.value.build_request.projector_params = pp;
    wizard.invalidateDownstream(3);
  }

  function setOutputLanguage(e: Event) {
    const lang = (e.target as HTMLSelectElement).value === "en" ? "en" : "ru";
    wizard.data.value.build_request.output_language = lang;
    wizard.invalidateDownstream(3);
  }

  function isRecommended(kind: "builder" | "clusterer", name: string): boolean {
    if (!recommendation.value) return false;
    if (kind === "builder") return recommendation.value.builder === name;
    return recommendation.value.clusterer === name;
  }

  function isRecommendedCleaner(name: string): boolean {
    return recommendation.value?.cleaner_chain.includes(name) ?? false;
  }

  // Multi-line native HTML tooltip. Browsers honour \n in title=, so this
  // surfaces description + layers + params + references without pulling
  // in a tooltip lib.
  // Matches the StrategyDescriptor shape from /api/{builders,cleaners,
  // clusterers}: params_schema is Record<string, unknown> upstream, so
  // narrow per-entry inside the loop instead of constraining the type here.
  type StrategyLike = {
    description?: string | null;
    summary?: string;
    produces_layers?: string[];
    requires_layers?: string[];
    params_schema?: Record<string, unknown>;
    references?: string[];
    cost_hint?: string | null;
  };
  function tooltip(d: StrategyLike): string {
    const lines: string[] = [];
    lines.push(d.description ?? d.summary ?? "");
    if (d.cost_hint) lines.push(`\n${t("wizard.pipeline.tooltipCost")} ${d.cost_hint}`);
    if (d.requires_layers?.length) {
      lines.push(`${t("wizard.pipeline.tooltipRequires")} ${d.requires_layers.join(", ")}`);
    }
    if (d.produces_layers?.length) {
      lines.push(`${t("wizard.pipeline.tooltipProduces")} ${d.produces_layers.join(", ")}`);
    }
    const params = Object.entries(d.params_schema ?? {});
    if (params.length) {
      lines.push(`\n${t("wizard.pipeline.tooltipParams")}`);
      for (const [k, v] of params) {
        const meta = (v && typeof v === "object" ? v : {}) as {
          type?: string;
          default?: unknown;
        };
        const ty = meta.type ?? "?";
        const def = meta.default;
        lines.push(
          `  • ${k}: ${ty}${def !== undefined ? ` = ${JSON.stringify(def)}` : ""}`,
        );
      }
    }
    if (d.references?.length) {
      lines.push(`\n${t("wizard.pipeline.tooltipReferences")} ${d.references.join(", ")}`);
    }
    return lines.join("\n");
  }
</script>

<template>
  <section :class="$style.step">
    <h2 :class="$style.title">{{ t("wizard.pipeline.title") }}</h2>
    <p :class="$style.hint">{{ t("wizard.pipeline.hint") }}</p>

    <div :class="$style.section">
      <h3 :class="$style.subhead">{{ t("wizard.pipeline.outputLanguage") }}</h3>
      <p :class="$style.note">{{ t("wizard.pipeline.outputLanguageHint") }}</p>
      <select
        :class="$style.langSelect"
        :value="wizard.data.value.build_request.output_language ?? 'ru'"
        @change="setOutputLanguage"
      >
        <option value="ru">{{ t("profile.languageRu") }}</option>
        <option value="en">{{ t("profile.languageEn") }}</option>
      </select>
    </div>

    <div :class="$style.section">
      <h3 :class="$style.subhead">{{ t("wizard.pipeline.builder") }}</h3>
      <ul :class="$style.cards">
        <li
          v-for="b in builders ?? []"
          :key="b.name"
          :class="[
            $style.card,
            wizard.data.value.build_request.builder === b.name ? $style.card_active : '',
            isRecommended('builder', b.name) ? $style.card_recommended : '',
          ]"
          :title="tooltip(b)"
          @click="selectBuilder(b.name)"
        >
          <header :class="$style.cardHeader">
            <strong>{{ b.name }}</strong>
            <span :class="$style.costChip">{{ b.cost_hint ?? "?" }}</span>
          </header>
          <p :class="$style.summary">{{ b.summary }}</p>
        </li>
      </ul>
    </div>

    <div :class="$style.section">
      <h3 :class="$style.subhead">{{ t("wizard.pipeline.cleanerChain") }}</h3>
      <p :class="$style.note">{{ t("wizard.pipeline.cleanerNote") }}</p>
      <div :class="$style.chain">
        <span
          v-for="(name, i) in wizard.data.value.build_request.cleaner_chain ?? []"
          :key="i"
          :class="$style.chainItem"
        >
          {{ i + 1 }}. {{ name }}
          <button
            type="button"
            :class="$style.chainRemove"
            @click="toggleCleaner(name)"
          >
            ×
          </button>
        </span>
        <span
          v-if="!(wizard.data.value.build_request.cleaner_chain ?? []).length"
          :class="$style.chainEmpty"
        >
          {{ t("wizard.pipeline.cleanerEmpty") }}
        </span>
      </div>
      <ul :class="$style.cards">
        <li
          v-for="c in cleaners ?? []"
          :key="c.name"
          :class="[
            $style.card,
            (wizard.data.value.build_request.cleaner_chain ?? []).includes(c.name)
              ? $style.card_active
              : '',
            isRecommendedCleaner(c.name) ? $style.card_recommended : '',
          ]"
          :title="tooltip(c)"
          @click="toggleCleaner(c.name)"
        >
          <header :class="$style.cardHeader">
            <strong>{{ c.name }}</strong>
            <span :class="$style.costChip">{{ c.cost_hint ?? "?" }}</span>
          </header>
          <p :class="$style.summary">{{ c.summary }}</p>
        </li>
      </ul>
    </div>

    <div :class="$style.section">
      <h3 :class="$style.subhead">{{ t("wizard.pipeline.clusterer") }}</h3>
      <ul :class="$style.cards">
        <li
          :class="[
            $style.card,
            wizard.data.value.build_request.clusterer === null ? $style.card_active : '',
          ]"
          @click="selectClusterer(null)"
        >
          <header :class="$style.cardHeader">
            <strong>{{ t("wizard.pipeline.clusterNone") }}</strong>
          </header>
          <p :class="$style.summary">{{ t("wizard.pipeline.clusterNoneHint") }}</p>
        </li>
        <li
          v-for="cl in clusterers ?? []"
          :key="cl.name"
          :class="[
            $style.card,
            wizard.data.value.build_request.clusterer === cl.name ? $style.card_active : '',
            isRecommended('clusterer', cl.name) ? $style.card_recommended : '',
          ]"
          :title="tooltip(cl)"
          @click="selectClusterer(cl.name)"
        >
          <header :class="$style.cardHeader">
            <strong>{{ cl.name }}</strong>
            <span :class="$style.costChip">{{ cl.cost_hint ?? "?" }}</span>
          </header>
          <p :class="$style.summary">{{ cl.summary }}</p>
        </li>
      </ul>
    </div>

    <div :class="$style.section">
      <h3 :class="$style.subhead">{{ t("wizard.pipeline.projector") }}</h3>
      <p :class="$style.note">{{ t("wizard.pipeline.projectorHint") }}</p>
      <ul :class="$style.cards">
        <li
          :class="[
            $style.card,
            !wizard.data.value.build_request.projector ? $style.card_active : '',
          ]"
          @click="selectProjector(null)"
        >
          <header :class="$style.cardHeader">
            <strong>{{ t("wizard.pipeline.projectorNone") }}</strong>
          </header>
          <p :class="$style.summary">{{ t("wizard.pipeline.projectorNoneHint") }}</p>
        </li>
        <li
          v-for="p in projectors ?? []"
          :key="p.name"
          :class="[
            $style.card,
            wizard.data.value.build_request.projector === p.name ? $style.card_active : '',
          ]"
          :title="tooltip(p)"
          @click="selectProjector(p.name)"
        >
          <header :class="$style.cardHeader">
            <strong>{{ p.name }}</strong>
            <span :class="$style.costChip">{{ p.cost_hint ?? "?" }}</span>
          </header>
          <p :class="$style.summary">{{ p.summary }}</p>
        </li>
      </ul>
      <div
        v-if="selectedProjector && projectorScalarParams.length"
        :class="$style.projectorParams"
      >
        <p :class="$style.note">{{ t("wizard.pipeline.projectorParamsHint") }}</p>
        <div
          v-for="p in projectorScalarParams"
          :key="p.key"
          :class="$style.paramRow"
        >
          <label :class="$style.paramLabel" :title="p.description ?? ''">{{ p.key }}</label>
          <select
            v-if="p.enum && p.enum.length"
            :value="projectorParamValue(p.key, p.default)"
            @change="setProjectorParam(p.key, ($event.target as HTMLSelectElement).value, p.type)"
          >
            <option v-for="opt in p.enum" :key="opt" :value="opt">{{ opt }}</option>
          </select>
          <input
            v-else-if="p.type === 'boolean'"
            type="checkbox"
            :checked="Boolean(projectorParamValue(p.key, p.default))"
            @change="setProjectorParam(p.key, ($event.target as HTMLInputElement).checked, p.type)"
          />
          <input
            v-else
            type="number"
            :value="projectorParamValue(p.key, p.default)"
            @input="setProjectorParam(p.key, ($event.target as HTMLInputElement).value, p.type)"
          />
        </div>
      </div>
    </div>

    <div :class="$style.section">
      <h3 :class="$style.subhead">{{ t("wizard.pipeline.llmTitle") }}</h3>
      <p :class="$style.note">{{ t("wizard.pipeline.llmHint") }}</p>
      <div :class="$style.presets">
        <button
          v-for="p in (['openai', 'deepseek', 'ollama', 'custom'] as const)"
          :key="p"
          type="button"
          :class="[
            $style.preset,
            activePreset === p ? $style.preset_active : '',
          ]"
          @click="applyPreset(p)"
        >
          {{ t(`wizard.pipeline.llmPreset${p.charAt(0).toUpperCase() + p.slice(1)}`) }}
        </button>
        <button type="button" :class="$style.presetClear" @click="clearLLM">
          {{ t("wizard.pipeline.llmClear") }}
        </button>
      </div>
      <label :class="$style.llmField">
        <span :class="$style.llmLabel">{{ t("wizard.pipeline.llmBaseUrl") }}</span>
        <input
          v-model="llmForm.base_url"
          type="text"
          :class="$style.llmInput"
          placeholder="https://api.openai.com/v1"
          autocomplete="off"
          spellcheck="false"
        />
      </label>
      <label :class="$style.llmField">
        <span :class="$style.llmLabel">{{ t("wizard.pipeline.llmApiKey") }}</span>
        <input
          v-model="llmForm.api_key"
          type="password"
          :class="$style.llmInput"
          :placeholder="placeholderApiKey"
          autocomplete="off"
          spellcheck="false"
        />
      </label>
      <p :class="$style.note">{{ t("wizard.pipeline.llmApiKeyHint") }}</p>
      <label :class="$style.llmField">
        <span :class="$style.llmLabel">{{ t("wizard.pipeline.llmModel") }}</span>
        <input
          v-model="llmForm.model"
          type="text"
          :class="$style.llmInput"
          placeholder="gpt-4o-mini"
          autocomplete="off"
          spellcheck="false"
        />
      </label>
    </div>
  </section>
</template>

<style lang="scss" module>
  .step {
    display: flex;
    flex-direction: column;
    gap: var(--gr-space-lg);
  }

  .title {
    margin: 0;
    font-size: 1.25rem;
    font-weight: 600;
  }

  .hint {
    margin: 0;
    color: var(--ksd-text-secondary-color);
  }

  .section {
    display: flex;
    flex-direction: column;
    gap: var(--gr-space-sm);
  }

  .subhead {
    margin: 0;
    font-size: 1rem;
    font-weight: 600;
  }

  .note {
    margin: 0;
    font-size: 0.875rem;
    color: var(--ksd-text-secondary-color);
  }

  .projectorParams {
    margin-top: var(--gr-space-sm);
    display: flex;
    flex-direction: column;
    gap: var(--gr-space-xs);
  }

  .paramRow {
    display: flex;
    align-items: center;
    gap: var(--gr-space-sm);

    select,
    input {
      flex: 0 0 auto;
    }
  }

  .paramLabel {
    min-width: 9rem;
    font-size: 0.8125rem;
    font-family: var(--gr-font-mono, monospace);
    color: var(--ksd-text-main-color);
  }

  .chain {
    display: flex;
    flex-wrap: wrap;
    gap: var(--gr-space-2xs);
    align-items: center;
    padding: var(--gr-space-xs);
    border: 1px dashed var(--ksd-border-color);
    border-radius: var(--gr-radius-sm);
  }

  .chainItem {
    padding: var(--gr-space-2xs) var(--gr-space-sm);
    background: var(--ksd-accent-color);
    color: var(--ksd-bg-color);
    border-radius: var(--gr-radius-sm);
    display: inline-flex;
    align-items: center;
    gap: var(--gr-space-2xs);
  }

  .chainRemove {
    background: transparent;
    border: none;
    color: var(--ksd-bg-color);
    cursor: pointer;
    font-weight: 700;
  }

  .chainEmpty {
    color: var(--ksd-text-secondary-color);
    font-size: 0.875rem;
  }

  .cards {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
    gap: var(--gr-space-sm);
  }

  .card {
    padding: var(--gr-space-sm);
    border: 1px solid var(--ksd-border-color);
    border-radius: var(--gr-radius-sm);
    cursor: pointer;
    transition: all 0.15s ease;
    background: var(--ksd-bg-color);

    &:hover {
      border-color: var(--ksd-accent-color);
    }
  }

  .card_active {
    border-color: var(--ksd-accent-color);
    background: rgba(31, 119, 180, 0.08);
  }

  .card_recommended {
    box-shadow: 0 0 0 2px var(--gr-status-success);
  }

  .cardHeader {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: var(--gr-space-2xs);
  }

  .costChip {
    font-size: 0.7rem;
    padding: 1px var(--gr-space-2xs);
    border-radius: var(--gr-radius-sm);
    background: var(--ksd-card-bg-color);
    color: var(--ksd-text-secondary-color);
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }

  .summary {
    margin: 0;
    font-size: 0.875rem;
    color: var(--ksd-text-secondary-color);
  }

  .langSelect {
    width: fit-content;
    min-width: 200px;
    padding: var(--gr-space-xs) var(--gr-space-sm);
    border: 1px solid var(--ksd-border-color);
    border-radius: var(--gr-radius-sm);
    background: var(--ksd-bg-color);
    color: var(--ksd-text-main-color);
  }

  .presets {
    display: flex;
    flex-wrap: wrap;
    gap: var(--gr-space-2xs);
    align-items: center;
  }

  .preset,
  .presetClear {
    padding: var(--gr-space-2xs) var(--gr-space-sm);
    border: 1px solid var(--ksd-border-color);
    border-radius: var(--gr-radius-sm);
    background: transparent;
    color: var(--ksd-text-main-color);
    cursor: pointer;
    font-size: 0.85rem;

    &:hover {
      border-color: var(--ksd-accent-color);
      color: var(--ksd-accent-color);
    }
  }

  .preset_active {
    background: var(--ksd-accent-color);
    border-color: var(--ksd-accent-color);
    color: var(--ksd-bg-color);

    &:hover {
      color: var(--ksd-bg-color);
    }
  }

  .presetClear {
    margin-left: auto;
    color: var(--ksd-text-secondary-color);
  }

  .llmField {
    display: grid;
    grid-template-columns: 140px 1fr;
    gap: var(--gr-space-sm);
    align-items: center;
  }

  .llmLabel {
    font-size: 0.875rem;
    color: var(--ksd-text-secondary-color);
  }

  .llmInput {
    padding: var(--gr-space-xs) var(--gr-space-sm);
    border: 1px solid var(--ksd-border-color);
    border-radius: var(--gr-radius-sm);
    background: var(--ksd-bg-color);
    color: var(--ksd-text-main-color);
    font-family: ui-monospace, monospace;
    font-size: 0.875rem;
  }
</style>
