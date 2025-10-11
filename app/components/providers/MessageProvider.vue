<script setup lang="ts">
  import { isString } from "@krainovsd/js-helpers";
  import { VMessage } from "@krainovsd/vue-ui";
  import { computed, useTemplateRef } from "vue";
  import { messageSubject } from "@/entities/tech";

  const messageRef = useTemplateRef("message");
  const createMessage = computed(() => messageRef.value?.createMessage);
  messageSubject.useSubscribe((message) => {
    if (isString(message)) {
      createMessage.value?.(message);
    } else {
      createMessage.value?.(message.text, {
        duration: message.duration,
        id: message.id,
        type: message.type,
      });
    }
  });
</script>

<template>
  <VMessage ref="message" :default-duration="8" :default-type="'error'" :max-count="5">
    <slot></slot>
  </VMessage>
</template>

<style lang="scss" module></style>
