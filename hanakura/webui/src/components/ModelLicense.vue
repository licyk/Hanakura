<script setup lang="ts">
import type { ModelPermission } from '@/api/types';
import { useI18n } from '@/i18n';
import { AppIcon, icons } from '@/ui';

/** A model's licence: its name when it has one, and what the creator allows and forbids, each at a glance. */
defineProps<{ license?: string | null; permissions: ModelPermission[] }>();
const { t } = useI18n();
</script>

<template>
  <section v-if="license || permissions.length">
    <h3 class="type-title-small">{{ t('detail.license') }}</h3>
    <p v-if="license" class="type-body-medium name">{{ license }}</p>
    <ul v-if="permissions.length" class="permissions">
      <li v-for="p in permissions" :key="p.id" class="permission type-body-medium" :class="p.allowed ? 'allowed' : 'denied'">
        <span class="mark"><AppIcon :icon="p.allowed ? icons.Check : icons.X" :size="18" /></span>
        <span class="visually-hidden">{{ p.allowed ? t('detail.allowed') : t('detail.notAllowed') }}: </span>
        <span class="text">{{ t(`detail.permissions.${p.id}`) }}</span>
      </li>
    </ul>
  </section>
</template>

<style scoped>
h3 { margin: 0 0 var(--app-space-2); }
.name { margin: 0 0 var(--app-space-2); overflow-wrap: anywhere; }
.permissions { list-style: none; margin: 0; padding: 0; display: grid; grid-template-columns: repeat(auto-fill, minmax(min(100%, 280px), 1fr)); gap: var(--app-space-1) var(--app-space-4); }
.permission { display: flex; align-items: center; gap: var(--app-space-2); min-height: 32px; }
.mark { flex: none; display: grid; place-items: center; width: 28px; height: 28px; border-radius: var(--md-sys-shape-corner-full); }
.allowed .mark { background: var(--md-sys-color-primary-container); color: var(--md-sys-color-on-primary-container); }
.denied .mark { background: var(--md-sys-color-error-container); color: var(--md-sys-color-on-error-container); }
.text { min-width: 0; overflow-wrap: anywhere; }
.denied .text { color: var(--md-sys-color-on-surface-variant); }
</style>
