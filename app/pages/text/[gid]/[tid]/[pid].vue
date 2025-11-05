<script setup lang="ts">
  import { isArray } from "@krainovsd/js-helpers";
  import { VHomeOutlined } from "@krainovsd/vue-icons";
  import { VButton, VText } from "@krainovsd/vue-ui";
  import { useAsyncData, useRoute } from "nuxt/app";
  import { useTemplateRef, watch } from "vue";
  import type { ICityGraphText } from "@/entities/cities";
  import { createPagePath } from "@/entities/tech";
  import { mdFormat } from "@/components/organisms/CityGraph/lib/md-format";

  const route = useRoute();
  const { data: info } = await useAsyncData<{ name: string; text: ICityGraphText[] }>(
    `text/${route.params.gid}/${route.params.gid}/${route.params.tid}`,
    () => $fetch(`/api/text/${route.params.gid}/${route.params.tid}`),
  );
  const textRef = useTemplateRef("text");

  watch(
    textRef,
    (textRef) => {
      if (textRef == undefined) return;

      try {
        const paragraph = textRef.querySelector<HTMLElement>(`[data-id="${route.params.pid}"]`);
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
        <div v-if="isArray(info?.text)" ref="text" :class="$style.text">
          <VText
            v-for="(paragraph, index) in info?.text"
            :key="index"
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
</style>
