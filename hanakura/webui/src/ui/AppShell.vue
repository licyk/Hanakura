<script setup lang="ts">
import { computed } from 'vue';
import { useWindowClass } from '@/theme/breakpoints';
import NavigationBar from '@/ui/NavigationBar.vue';
import NavigationRail, { type NavItem } from '@/ui/NavigationRail.vue';
import Snackbar from '@/ui/Snackbar.vue';
import TopAppBar from '@/ui/TopAppBar.vue';

/** Navigation switches between a bottom bar (compact) and a rail (medium and wider). */
defineProps<{ items: NavItem[]; title: string }>();
const windowClass = useWindowClass();
const compact = computed(() => windowClass.value === 'compact');
</script>

<template>
  <div class="shell" :class="{ compact }">
    <NavigationRail v-if="!compact" :items="items" class="rail"><template #top><slot name="rail-top" /></template></NavigationRail>
    <div class="main-column">
      <TopAppBar :title="title"><template #actions><slot name="actions" /></template></TopAppBar>
      <main class="content"><slot /></main>
    </div>
    <NavigationBar v-if="compact" :items="items" class="bottom" />
    <Snackbar />
  </div>
</template>

<style scoped>
.shell { display: grid; grid-template-columns: auto 1fr; height: 100%; background: var(--md-sys-color-surface); }
.shell.compact { grid-template-columns: 1fr; grid-template-rows: 1fr auto; }
.main-column { display: flex; flex-direction: column; min-width: 0; min-height: 0; }
.content {
  position: relative; flex: 1; min-height: 0; overflow: auto; margin: 0 var(--app-space-4) var(--app-space-4) 0;
  background: var(--md-sys-color-surface-container-low); border-radius: var(--md-sys-shape-corner-large);
  /* Reserve the scrollbar's width so content does not jump when it appears. */
  scrollbar-gutter: stable;
}
.compact .content { margin: 0; border-radius: 0; }
</style>
