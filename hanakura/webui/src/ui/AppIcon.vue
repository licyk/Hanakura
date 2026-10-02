<script setup lang="ts">
import type { Component } from 'vue';

/** Wraps a Lucide icon: fixed sizes, one stroke width, colour from the current text colour. */
withDefaults(defineProps<{ icon: Component; size?: 18 | 20 | 24; label?: string; spin?: boolean }>(), { size: 24 });
</script>

<template>
  <component
    :is="icon"
    :size="size"
    :stroke-width="1.75"
    color="currentColor"
    class="app-icon"
    :class="{ spin }"
    :aria-hidden="label ? undefined : 'true'"
    :aria-label="label"
    :role="label ? 'img' : undefined"
  />
</template>

<style scoped>
.app-icon { flex: none; display: inline-block; vertical-align: middle; }
.spin { animation: app-icon-spin 1s linear infinite; }
@keyframes app-icon-spin { to { transform: rotate(360deg); } }
</style>
