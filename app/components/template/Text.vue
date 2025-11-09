<script setup lang="ts">
  import { isArray } from "@krainovsd/js-helpers";
  import { VHomeOutlined } from "@krainovsd/vue-icons";
  import { VButton, VText } from "@krainovsd/vue-ui";
  import { useAsyncData, useRoute } from "nuxt/app";
  import { computed, useTemplateRef, watch } from "vue";
  import type { ICityGraphText } from "@/entities/cities";
  import { createPagePath } from "@/entities/tech";
  import { mdFormat } from "@/components/organisms/CityGraph/lib/md-format";
  import { mergeHighlights } from "@/lib/merge-highlights";

  type Highlight = {
    start: number;
    length: number;
  };
  type HighlightMap = Record<string, Highlight[]>;

  const route = useRoute();
  const { data: info } = await useAsyncData<{ name: string; text: ICityGraphText[] }>(
    `text/${route.params.gid}/${route.params.gid}/${route.params.tid}`,
    () => $fetch(`/api/text/${route.params.gid}/${route.params.tid}`),
  );
  const textRef = useTemplateRef("text");
  const pids = computed(() => {
    const pids: number[] = [];

    if (route.params.pid != undefined && !Number.isNaN(+route.params.pid)) {
      pids.push(+route.params.pid);
    }
    if (isArray(route.query.paragraph)) {
      route.query.paragraph.forEach((p) => {
        if (p != undefined && !Number.isNaN(+p)) {
          pids.push(+p);
        }
      });
    } else if (route.query.paragraph != undefined && !Number.isNaN(+route.query.paragraph)) {
      pids.push(+route.query.paragraph);
    }

    return pids;
  });
  const highlightMap = computed<HighlightMap>(() => {
    if (!isArray(route.query.highlight)) {
      return {};
    }

    const highlights: HighlightMap = {};

    for (const highlight of route.query.highlight) {
      const [pid, start, length] = highlight?.split?.(",") ?? [];
      if (
        pid != undefined &&
        !Number.isNaN(+pid) &&
        start != undefined &&
        !Number.isNaN(+start) &&
        length != undefined &&
        !Number.isNaN(+length)
      ) {
        highlights[pid] ??= [];
        highlights[pid].push({ start: +start, length: +length });
      }
    }

    Object.keys(highlights).forEach((key) => {
      const mergedHighlights = mergeHighlights(highlights[key]);
      highlights[key] = mergedHighlights;
    });

    return highlights;
  });
  const preprocessedText = computed<ICityGraphText[] | undefined>(() => {
    console.log(highlightMap.value);

    return info.value?.text;
  });

  watch(
    () => [textRef.value, pids.value] as const,
    ([textRef, pids]) => {
      if (textRef == undefined || pids.length === 0) return;

      try {
        const paragraph = textRef.querySelector<HTMLElement>(`[data-id="${pids[0]}"]`);
        paragraph?.scrollIntoView?.({ behavior: "auto" });
      } catch (error) {
        console.error(error);
      }
    },
    { immediate: true, flush: "pre" },
  );
</script>

<template>
  <div ref="container" :class="$style.base">
    <div :class="$style.graph">
      <div :class="$style.header">
        <NuxtLink :to="createPagePath.home">
          <VButton>
            <template #icon>
              <VHomeOutlined />
            </template>
          </VButton>
        </NuxtLink>
        <VText size="lg"> {{ info?.name }}</VText>
      </div>
      <ClientOnly>
        <div v-if="isArray(preprocessedText)" ref="text" :class="$style.text">
          <VText
            v-for="(paragraph, index) in preprocessedText"
            :key="index"
            :class="[$style.paragraph, pids.includes(paragraph.pid) && $style.selected]"
            :data-id="paragraph.pid.toString()"
            v-html="mdFormat(paragraph.text)"
          ></VText>
        </div>

        <div v-else>Text not found</div>
      </ClientOnly>
    </div>
  </div>
</template>

<style lang="scss" module>
  .base {
    display: flex;
    gap: var(--ksd-padding);
    width: 100%;
    height: 100%;
    overflow: hidden;
  }

  .graph {
    display: flex;
    flex-direction: column;
    gap: var(--ksd-padding);
    width: 100%;
    height: 100%;
    flex: 1;
  }

  .empty {
    display: flex;
    flex-direction: column;
    width: 100%;
    height: 100%;
    align-items: center;
    justify-content: center;
    gap: var(--ksd-padding);
  }

  .header {
    display: flex;
    align-items: center;
    gap: var(--ksd-padding-lg);
  }

  .text {
    display: flex;
    width: 100%;
    height: 100%;
    flex-direction: column;
    gap: var(--ksd-padding);
    overflow: auto;
  }

  .paragraph {
    position: relative;
    &.selected {
      &::before {
        content: "";
        position: absolute;

        transform: rotate(-90deg);
        left: 0;
        width: 0;
        height: 0;
        border-top: 6px solid transparent;
        border-bottom: 6px solid transparent;
        border-right: 10px solid var(--ksd-accent-color);
      }
    }
  }
</style>
