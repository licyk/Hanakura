<script setup lang="ts">
import { useI18n } from '@/i18n';
import { IconButton, Switch, collapseHooks, icons } from '@/ui';

/**
 * What can be done with the selection, shown below the toolbar while something is selected. The
 * toolbar itself stays as it is, so nothing it offers moves or disappears while selecting.
 */
defineProps<{ count: number; total: number }>();
const keep = defineModel<boolean>('keep', { default: false });
const emit = defineEmits<{ clear: []; selectAll: []; move: []; delete: [] }>();
const { t } = useI18n();
</script>

<template>
  <!-- The slot grows to the bar's height, so the contents below slide down instead of jumping. -->
  <Transition name="collapse" v-bind="collapseHooks">
    <div v-if="count" class="selection-slot">
      <div class="selection-bar" role="toolbar" :aria-label="t('library.selected', { n: count })">
        <IconButton :icon="icons.X" :label="t('library.clearSelection')" @click="emit('clear')" />
        <span class="type-title-small count">{{ t('library.selected', { n: count }) }}</span>
        <IconButton :icon="icons.SquareCheck" :label="t('library.selectAll')" :disabled="count >= total" @click="emit('selectAll')" />
        <span class="spacer" />
        <IconButton :icon="icons.FolderInput" :label="t('library.moveTo')" @click="emit('move')" />
        <IconButton :icon="icons.Trash2" :label="t('common.delete')" @click="emit('delete')" />
        <Switch v-model="keep" class="keep" :label="t('library.keepSelection')" />
      </div>
    </div>
  </Transition>
</template>

<style scoped>
/* A row of its own, also inside a toolbar that wraps. */
.selection-slot { flex: 1 0 100%; }
.selection-bar {
  display: flex; align-items: center; gap: var(--app-space-1); flex-wrap: wrap; padding: 0 var(--app-space-2);
  min-height: 56px; border-radius: var(--md-sys-shape-corner-large); background: var(--md-sys-color-secondary-container); color: var(--md-sys-color-on-secondary-container);
  --md-icon-button-icon-color: var(--md-sys-color-on-secondary-container);
}
.count { white-space: nowrap; }
.spacer { flex: 1; }
.keep { min-height: 40px; gap: var(--app-space-2); }
</style>
