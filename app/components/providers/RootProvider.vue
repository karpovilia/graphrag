<script setup lang="ts">
  import MessageProvider from "./MessageProvider.vue";
  import NotificationProvider from "./NotificationProvider.vue";
</script>

<template>
  <MessageProvider>
    <NotificationProvider>
      <slot></slot>
    </NotificationProvider>
  </MessageProvider>
</template>

<style lang="scss" module></style>
