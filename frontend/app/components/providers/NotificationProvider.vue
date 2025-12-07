<script setup lang="ts">
  import { VNotification } from "@krainovsd/vue-ui";
  import { computed, useTemplateRef } from "vue";
  import { notificationSubject } from "@/entities/tech";

  const noticeRef = useTemplateRef("notice");
  const createNotification = computed(() => noticeRef.value?.createNotification);
  notificationSubject.useSubscribe((notification) => {
    createNotification.value?.(notification.text, notification.title, notification);
  });
</script>

<template>
  <VNotification
    ref="notice"
    :default-type="'error'"
    :default-duration="8"
    :max-count="3"
    :position="'top-right'"
  >
    <slot></slot>
  </VNotification>
</template>

<style lang="scss" module></style>
