<script setup lang="ts">
/**
 * A path on one line, cut at the start when it does not fit, so the end that tells folders apart
 * stays visible. The whole path is in the tooltip.
 */
defineProps<{ path: string }>();
</script>

<template>
  <span class="path-text" :title="path"><bdi dir="ltr">{{ path }}</bdi></span>
</template>

<style scoped>
/* Right-to-left moves the ellipsis to the start. The path itself must stay isolated as
   left-to-right: a leading "/" has no direction of its own, and in a right-to-left line it is
   drawn at the far end, so "/root/model" read "root/model/". */
.path-text { display: block; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; direction: rtl; text-align: left; }
</style>
