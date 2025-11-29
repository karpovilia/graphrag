<script setup lang="ts">
  import { VDrawer, VText, VButton } from "@krainovsd/vue-ui";
  import { VEditOutlined } from "@krainovsd/vue-icons";
  import { computed, ref, watch } from "vue";
  import type { ICityGraphNodeText } from "../../../entities/cities/cities.types";
  import { mdFormat } from "../CityGraph/lib/md-format";

  export type ICityNodeInfo = {
    id: id;
    texts: ICityGraphNodeText[];
    name: string;
  };
  export type ICityLinkInfo = {
    id: id;
    explanation: string;
    name: string;
  };

  type Props = {
    selectedNodes: ICityNodeInfo[];
    selectedLink: ICityLinkInfo | null;
    mountRoot: HTMLElement | null;
  };
  type Emits = {
    close: [];
    updateNodeName: [nodeId: id, newName: string];
    updateNodeText: [nodeId: id, textId: number, newText: string];
    updateLinkExplanation: [linkId: id, newExplanation: string];
  };

  const props = defineProps<Props>();
  const emit = defineEmits<Emits>();
  const open = ref(false);
  const isEditing = ref(false);
  const editingNodeName = ref("");
  const editingNodeTexts = ref<Record<number, string>>({});
  const editingLinkExplanation = ref("");
  const title = computed(() => {
    if (props.selectedNodes.length > 0) {
      return props.selectedNodes.map((n) => n.name).join(", ");
    }

    return props.selectedLink?.name;
  });
  const content = computed(() => {
    if (props.selectedNodes.length === 1) {
      return props.selectedNodes[0].texts.map((t) => t.text);
    } else if (props.selectedNodes.length > 1) {
      let textMap: Record<string, string> = {};
      for (const text of props.selectedNodes[0].texts) {
        textMap[text.id] = text.text;
      }
      for (let i = 1; i < props.selectedNodes.length; i++) {
        const newTextMap: Record<string, string> = {};
        for (const text of props.selectedNodes[i].texts ?? []) {
          if (textMap[text.id] != undefined) {
            newTextMap[text.id] = text.text;
          }
        }

        textMap = newTextMap;
        if (Object.keys(textMap).length === 0) break;
      }

      return Object.values(textMap);
    }

    return props.selectedLink ? [props.selectedLink.explanation] : [];
  });

  const isSingleNode = computed(() => props.selectedNodes.length === 1);
  const isSingleLink = computed(() => props.selectedLink !== null && props.selectedNodes.length === 0);

  function startEditing() {
    isEditing.value = true;
    if (isSingleNode.value) {
      const node = props.selectedNodes[0];
      editingNodeName.value = node.name;
      editingNodeTexts.value = {};
      node.texts.forEach((text) => {
        editingNodeTexts.value[text.id] = text.text;
      });
    } else if (isSingleLink.value && props.selectedLink) {
      editingLinkExplanation.value = props.selectedLink.explanation;
    }
  }

  function cancelEditing() {
    isEditing.value = false;
    editingNodeName.value = "";
    editingNodeTexts.value = {};
    editingLinkExplanation.value = "";
  }

  function saveEditing() {
    if (isSingleNode.value) {
      const node = props.selectedNodes[0];
      if (editingNodeName.value !== node.name) {
        emit("updateNodeName", node.id, editingNodeName.value);
      }
      node.texts.forEach((text) => {
        const newText = editingNodeTexts.value[text.id];
        if (newText !== undefined && newText !== text.text) {
          emit("updateNodeText", node.id, text.id, newText);
        }
      });
    } else if (isSingleLink.value && props.selectedLink) {
      if (editingLinkExplanation.value !== props.selectedLink.explanation) {
        emit("updateLinkExplanation", props.selectedLink.id, editingLinkExplanation.value);
      }
    }
    cancelEditing();
  }

  watch(
    () => [props.selectedLink, props.selectedNodes] as const,
    ([link, nodes]) => {
      if (link != undefined || nodes.length > 0) {
        open.value = true;
      } else {
        open.value = false;
        cancelEditing();
      }
    },
    { immediate: true },
  );
</script>

<template>
  <VDrawer
    v-if="$props.mountRoot"
    v-model="open"
    :target="$props.mountRoot"
    :header="title"
    :class="$style.root"
    :class-name-body="$style.body"
    :close-by-click-outside="false"
    :block="true"
    :mask="false"
    :width="535"
  >
    <template #content>
      <div :class="$style.actions" v-if="isSingleNode || isSingleLink">
        <VButton v-if="!isEditing" @click="startEditing">
          <template #icon>
            <VEditOutlined />
          </template>
          Edit
        </VButton>
        <div v-else :class="$style.editActions">
          <VButton @click="saveEditing">Save</VButton>
          <VButton @click="cancelEditing">Cancel</VButton>
        </div>
      </div>

      <div v-if="isEditing && isSingleNode" :class="$style.editForm">
        <div :class="$style.formGroup">
          <label :class="$style.label">Node Name</label>
          <input
            v-model="editingNodeName"
            :class="$style.input"
            type="text"
          />
        </div>
        <div :class="$style.formGroup" v-for="text in selectedNodes[0].texts" :key="text.id">
          <label :class="$style.label">Text #{{ text.id }}</label>
          <textarea
            v-model="editingNodeTexts[text.id]"
            :class="$style.textarea"
            rows="4"
          ></textarea>
        </div>
      </div>

      <div v-else-if="isEditing && isSingleLink" :class="$style.editForm">
        <div :class="$style.formGroup">
          <label :class="$style.label">Explanation</label>
          <textarea
            v-model="editingLinkExplanation"
            :class="$style.textarea"
            rows="6"
          ></textarea>
        </div>
      </div>

      <div v-else>
        <VText v-for="(text, index) in content" :key="index" v-html="mdFormat(text)"></VText>
      </div>
    </template>
  </VDrawer>
</template>

<style lang="scss" module>
  .root {
    height: 100%;
    overflow: hidden;

    & > div {
      overflow: hidden;
    }
  }

  .body {
    display: flex;
    flex-direction: column;
    gap: var(--ksd-padding);
    overflow: auto;
  }

  .actions {
    display: flex;
    justify-content: flex-end;
    margin-bottom: var(--ksd-padding);
  }

  .editActions {
    display: flex;
    gap: 8px;
  }

  .editForm {
    display: flex;
    flex-direction: column;
    gap: var(--ksd-padding);
  }

  .formGroup {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  .label {
    font-size: 14px;
    font-weight: 500;
    color: var(--ksd-color-text);
  }

  .input {
    padding: 8px 12px;
    font-size: 14px;
    border: 1px solid var(--ksd-color-border);
    border-radius: 4px;
    background: var(--ksd-color-background);
    color: var(--ksd-color-text);
    width: 100%;
    box-sizing: border-box;

    &:focus {
      outline: none;
      border-color: var(--ksd-color-primary);
    }
  }

  .textarea {
    padding: 8px 12px;
    font-size: 14px;
    border: 1px solid var(--ksd-color-border);
    border-radius: 4px;
    background: var(--ksd-color-background);
    color: var(--ksd-color-text);
    width: 100%;
    box-sizing: border-box;
    resize: vertical;
    font-family: inherit;

    &:focus {
      outline: none;
      border-color: var(--ksd-color-primary);
    }
  }
</style>
