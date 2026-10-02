<script setup lang="ts">
import '@material/web/progress/linear-progress.js';

/** ``value`` is 0 to 1; omit it for an indeterminate bar. */
defineProps<{ value?: number | null; label?: string }>();
</script>

<template>
  <md-linear-progress
    class="bar"
    :value.prop="value ?? 0"
    :indeterminate.prop="value === null || value === undefined"
    :aria-label="label"
  />
</template>

<style scoped>
.bar { width: 100%; --md-linear-progress-track-shape: var(--md-sys-shape-corner-full); }
</style>
