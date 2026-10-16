<script setup lang="ts" generic="T extends string">
import '@material/web/tabs/tabs.js';
import '@material/web/tabs/primary-tab.js';
import { computed } from 'vue';

const props = defineProps<{ tabs: { value: T; label: string }[] }>();
const model = defineModel<T>({ required: true });
const index = computed(() => Math.max(0, props.tabs.findIndex((t) => t.value === model.value)));

function onChange(event: Event) {
  const i = (event.target as HTMLElement & { activeTabIndex: number }).activeTabIndex;
  const tab = props.tabs[i];
  if (tab) model.value = tab.value;
}
</script>

<template>
  <md-tabs :active-tab-index.prop="index" @change="onChange">
    <md-primary-tab v-for="t in tabs" :key="t.value">{{ t.label }}</md-primary-tab>
  </md-tabs>
</template>

<style scoped>
/* A rounded bar, as wide as its row, on the same container tone as the app's other controls; its
   divider is dropped (the rounded box is the edge) and the indicator is a rounded pill. */
md-tabs {
  border-radius: var(--md-sys-shape-corner-large);
  overflow: hidden;
  background: var(--md-sys-color-surface-container);
  --md-divider-color: transparent;
  --md-primary-tab-container-color: transparent;
  --md-primary-tab-container-shape: var(--md-sys-shape-corner-large);
  --md-primary-tab-active-indicator-shape: var(--md-sys-shape-corner-full);
  --md-primary-tab-active-indicator-height: 3px;
}
</style>
