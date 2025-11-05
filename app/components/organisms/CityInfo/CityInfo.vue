<script setup lang="ts">
  import { VDrawer, VText } from "@krainovsd/vue-ui";
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
  };

  const props = defineProps<Props>();
  defineEmits<Emits>();
  const open = ref(false);
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

  watch(
    () => [props.selectedLink, props.selectedNodes] as const,
    ([link, nodes]) => {
      if (link != undefined || nodes.length > 0) {
        open.value = true;
      } else {
        open.value = false;
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
      <VText v-for="(text, index) in content" :key="index" v-html="mdFormat(text)"></VText>
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
</style>
