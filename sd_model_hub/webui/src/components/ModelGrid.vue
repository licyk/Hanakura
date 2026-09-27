<script setup lang="ts" generic="T">
import { computed, onBeforeUnmount, ref, watch } from 'vue';
import { ProgressCircle, staggerStyle } from '@/ui';

/**
 * A responsive grid. Infinite scrolling for sources (``load-more``) and incremental rendering for
 * large local folders (only ``window`` items are mounted until the user scrolls near the end).
 */
const props = withDefaults(
  defineProps<{ items: T[]; itemKey: (item: T) => string | number; layout?: 'grid' | 'list'; hasMore?: boolean; loadingMore?: boolean; windowSize?: number }>(),
  { layout: 'grid', windowSize: 120 },
);
const emit = defineEmits<{ 'load-more': [] }>();
const sentinel = ref<HTMLElement | null>(null);
const shown = ref(props.windowSize);
watch(
  () => props.items,
  (items, old) => {
    if (!old || items[0] !== old[0]) shown.value = props.windowSize;
  },
);
const visible = computed(() => props.items.slice(0, shown.value));

let observer: IntersectionObserver | null = null;
watch(sentinel, (el) => {
  observer?.disconnect();
  if (!el) return;
  observer = new IntersectionObserver(
    (entries) => {
      if (!entries.some((e) => e.isIntersecting)) return;
      if (shown.value < props.items.length) shown.value += props.windowSize;
      else if (props.hasMore && !props.loadingMore) emit('load-more');
    },
    { rootMargin: '600px' },
  );
  observer.observe(el);
});
onBeforeUnmount(() => observer?.disconnect());
</script>

<template>
  <div class="grid-wrap">
    <TransitionGroup name="list" tag="div" class="model-grid" :class="`layout-${layout}`">
      <div v-for="(item, i) in visible" :key="itemKey(item)" class="cell" :style="staggerStyle(i % 24)">
        <slot :item="item" />
      </div>
    </TransitionGroup>
    <div ref="sentinel" class="sentinel">
      <ProgressCircle v-if="loadingMore" :size="32" />
    </div>
  </div>
</template>

<style scoped>
.grid-wrap { position: relative; }
.model-grid { position: relative; display: grid; gap: var(--app-space-3); }
.layout-grid { grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); }
.layout-list { grid-template-columns: 1fr; gap: var(--app-space-2); }
/* Cards grow with a wide window instead of only multiplying into ever more narrow columns. */
@media (min-width: 1200px) {
  .layout-grid { grid-template-columns: repeat(auto-fill, minmax(clamp(200px, 11vw, 320px), 1fr)); }
}
@media (max-width: 599px) {
  .layout-grid { grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: var(--app-space-2); }
}
.cell { min-width: 0; }
.sentinel { display: grid; place-items: center; min-height: 48px; }
</style>
