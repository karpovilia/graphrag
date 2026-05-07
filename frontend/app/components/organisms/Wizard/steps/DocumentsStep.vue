<script setup lang="ts">
  import { computed } from "vue";

  import { useBuildWizard } from "@/composables/use-build-wizard";

  const wizard = useBuildWizard();

  const totalChars = computed(() =>
    wizard.data.value.documents.reduce((s, d) => s + d.text.length, 0),
  );

  function addEmpty() {
    wizard.data.value.documents.push({ title: `Документ ${wizard.data.value.documents.length + 1}`, text: "" });
    wizard.invalidateDownstream(1);
  }

  function remove(index: number) {
    wizard.data.value.documents.splice(index, 1);
    wizard.invalidateDownstream(1);
  }

  async function loadFile(event: Event, index: number) {
    const target = event.target as HTMLInputElement;
    const file = target.files?.[0];
    if (!file) return;
    const text = await file.text();
    const doc = wizard.data.value.documents[index];
    if (!doc) return;
    doc.text = text;
    if (!doc.title || doc.title.startsWith("Документ ")) {
      doc.title = file.name;
    }
    wizard.invalidateDownstream(1);
  }
</script>

<template>
  <section :class="$style.step">
    <h2 :class="$style.title">Документы</h2>
    <p :class="$style.hint">
      Загрузите файлы или вставьте текст. EDA-шаг анализирует именно их —
      пустые документы будут отброшены.
    </p>

    <div :class="$style.summary">
      <span><strong>{{ wizard.data.value.documents.length }}</strong> документов</span>
      <span><strong>{{ totalChars.toLocaleString("ru-RU") }}</strong> символов всего</span>
    </div>

    <ul :class="$style.list">
      <li
        v-for="(doc, index) in wizard.data.value.documents"
        :key="index"
        :class="$style.row"
      >
        <input
          v-model="doc.title"
          :class="$style.titleInput"
          placeholder="Заголовок"
        />
        <textarea
          v-model="doc.text"
          :class="$style.textarea"
          rows="3"
          placeholder="Вставьте текст или загрузите файл"
          @input="wizard.invalidateDownstream(1)"
        />
        <div :class="$style.rowActions">
          <label :class="$style.fileBtn">
            📎 Файл
            <input
              type="file"
              accept=".txt,.md"
              hidden
              @change="(e) => loadFile(e, index)"
            />
          </label>
          <button type="button" :class="$style.removeBtn" @click="remove(index)">
            Удалить
          </button>
        </div>
      </li>
    </ul>

    <button type="button" :class="$style.addBtn" @click="addEmpty">
      + Добавить документ
    </button>
  </section>
</template>

<style lang="scss" module>
  .step {
    display: flex;
    flex-direction: column;
    gap: var(--gr-space-md);
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

  .summary {
    display: flex;
    gap: var(--gr-space-lg);
    color: var(--ksd-text-secondary-color);
  }

  .list {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: var(--gr-space-sm);
  }

  .row {
    display: flex;
    flex-direction: column;
    gap: var(--gr-space-2xs);
    padding: var(--gr-space-sm);
    border: 1px solid var(--ksd-border-color);
    border-radius: var(--gr-radius-sm);
    background: var(--ksd-bg-color);
  }

  .titleInput,
  .textarea {
    padding: var(--gr-space-xs);
    border: 1px solid var(--ksd-border-color);
    border-radius: var(--gr-radius-sm);
    background: var(--ksd-bg-color);
    color: var(--ksd-text-main-color);
    font-family: inherit;
  }

  .textarea {
    resize: vertical;
    min-height: 100px;
  }

  .rowActions {
    display: flex;
    gap: var(--gr-space-2xs);
    justify-content: flex-end;
  }

  .fileBtn,
  .removeBtn,
  .addBtn {
    padding: var(--gr-space-2xs) var(--gr-space-sm);
    border-radius: var(--gr-radius-sm);
    border: 1px solid var(--ksd-border-color);
    background: transparent;
    color: var(--ksd-text-main-color);
    cursor: pointer;
    font-size: 0.875rem;
  }

  .fileBtn {
    cursor: pointer;
  }

  .removeBtn:hover {
    border-color: var(--gr-status-failed);
    color: var(--gr-status-failed);
  }

  .addBtn {
    align-self: flex-start;
    border-style: dashed;

    &:hover {
      border-color: var(--ksd-accent-color);
      color: var(--ksd-accent-color);
    }
  }
</style>
