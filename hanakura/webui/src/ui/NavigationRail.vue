<script setup lang="ts">
import type { Component } from 'vue';
import { RouterLink } from 'vue-router';
import AppIcon from '@/ui/AppIcon.vue';

export interface NavItem {
  to: string;
  label: string;
  icon: Component;
  badge?: number;
}
defineProps<{ items: NavItem[] }>();
</script>

<template>
  <nav class="rail" aria-label="Main">
    <div class="top"><slot name="top" /></div>
    <RouterLink v-for="item in items" :key="item.to" v-slot="{ isActive, navigate, href }" :to="item.to" custom>
      <a :href="href" class="dest" :class="{ active: isActive }" :aria-current="isActive ? 'page' : undefined" @click="navigate">
        <span class="indicator state-layer"><AppIcon :icon="item.icon" :size="24" /></span>
        <span class="type-label-medium">{{ item.label }}</span>
      </a>
    </RouterLink>
  </nav>
</template>

<style scoped>
.rail { display: flex; flex-direction: column; align-items: center; gap: var(--app-space-3); width: 88px; padding: var(--app-space-3) 0; background: var(--md-sys-color-surface); }
.top { min-height: 56px; display: grid; place-items: center; margin-bottom: var(--app-space-2); }
.dest { display: flex; flex-direction: column; align-items: center; gap: var(--app-space-1); width: 80px; text-decoration: none; color: var(--md-sys-color-on-surface-variant); }
.indicator {
  display: grid; place-items: center; width: 56px; height: 32px; border-radius: var(--md-sys-shape-corner-full);
  transition: background-color var(--md-sys-motion-duration-short4) var(--md-sys-motion-easing-standard);
}
.active { color: var(--md-sys-color-on-surface); }
.active .indicator { background: var(--md-sys-color-secondary-container); color: var(--md-sys-color-on-secondary-container); }
.dest:focus-visible { outline: none; }
.dest:focus-visible .indicator { outline: 2px solid var(--md-sys-color-secondary); }
</style>
