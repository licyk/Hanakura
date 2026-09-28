<script setup lang="ts">
import { ref, type Component } from 'vue';
import PreviewImage from '@/components/PreviewImage.vue';
import { AppCard, AppIcon, Badge, Tooltip, icons } from '@/ui';

/**
 * Preview, name, kind and base-model badges, and actions. Used for source results and for local
 * models, with different action slots.
 */
defineProps<{
  title: string;
  subtitle?: string | null;
  preview?: string | null;
  previewIsVideo?: boolean;
  nsfwLevel?: number;
  kind?: string | null;
  base?: string | null;
  warning?: string | null;
  /** Shown in place of the preview when there is none, e.g. a file icon for a plain file. */
  fallbackIcon?: Component;
  pending?: boolean;
  selected?: boolean;
  /** Something in the list is selected: every card shows its checkbox, not only on hover. */
  selecting?: boolean;
  layout?: 'grid' | 'list';
}>();
/** ``activate`` carries the card's rectangle, for a dialog to grow from, and the event, for its modifier keys. */
const emit = defineEmits<{ activate: [DOMRect | null, (MouseEvent | KeyboardEvent)?] }>();
const card = ref<InstanceType<typeof AppCard> | null>(null);
const onActivate = (event: MouseEvent | KeyboardEvent) => emit('activate', card.value?.el?.getBoundingClientRect() ?? null, event);
defineExpose({ rect: () => card.value?.el?.getBoundingClientRect() ?? null });
</script>

<template>
  <AppCard ref="card" interactive :selected="selected" class="model-card" :class="[layout ?? 'grid', { selecting, checked: selected }]" @activate="onActivate">
    <!-- In a row the checkbox leads; over a 72px thumbnail it would cover the picture. -->
    <div v-if="$slots.select && layout === 'list'" class="select-lead" @click.stop><slot name="select" /></div>
    <div class="media">
      <PreviewImage :src="preview" :alt="title" :nsfw-level="nsfwLevel" :is-video="previewIsVideo" :ratio="layout === 'list' ? '1 / 1' : '3 / 4'" :fallback-icon="fallbackIcon" />
      <div v-if="$slots.select && layout !== 'list'" class="select-slot" @click.stop><slot name="select" /></div>
    </div>
    <div class="body">
      <div class="text">
        <h3 class="type-title-small title" :title="title">{{ title }}</h3>
        <p v-if="subtitle" class="type-body-small muted subtitle">{{ subtitle }}</p>
        <div class="badges">
          <Badge v-if="pending" tone="neutral" value="…" />
          <Badge v-else-if="kind" tone="primary" :value="kind" />
          <Badge v-if="base" tone="neutral" :value="base" />
          <Tooltip v-if="warning" :text="warning"><span class="warn"><AppIcon :icon="icons.AlertTriangle" :size="18" :label="warning" /></span></Tooltip>
        </div>
      </div>
      <div class="actions" @click.stop><slot name="actions" /></div>
    </div>
  </AppCard>
</template>

<style scoped>
.model-card { height: 100%; }
.media { position: relative; }
.select-slot { position: absolute; top: var(--app-space-1); left: var(--app-space-1); }
/* With a mouse, a picture's checkbox comes on hover, and on every card once selecting: it would
   otherwise cover every preview. A touch screen has no hover, so there it always shows. */
@media (hover: hover) {
  .select-slot { opacity: 0; transition: opacity var(--md-sys-motion-duration-short3) var(--md-sys-motion-easing-standard); }
  .model-card:hover .select-slot, .model-card:focus-within .select-slot, .selecting .select-slot, .checked .select-slot { opacity: 1; }
}
/* min-width: 0 is what keeps the actions on the card: a long file name is one unbreakable word,
   and without it this row refuses to shrink below that word and pushes the menu out of the card. */
.body { display: flex; align-items: flex-start; gap: var(--app-space-1); padding: var(--app-space-3) var(--app-space-1) var(--app-space-2) var(--app-space-3); flex: 1; min-width: 0; }
.text { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 2px; }
.title { margin: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.subtitle { margin: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.badges { display: flex; flex-wrap: wrap; align-items: center; gap: var(--app-space-1); margin-top: var(--app-space-1); }
.badges :deep(.badge) { height: 20px; padding: 0 var(--app-space-2); border-radius: var(--md-sys-shape-corner-small); }
.warn { color: var(--md-sys-color-error); display: inline-flex; }
.actions { display: flex; flex-direction: column; flex: none; }
.list { flex-direction: row; align-items: center; }
.list .media { width: 56px; flex: none; border-radius: var(--md-sys-shape-corner-small); overflow: hidden; }
.list .body { align-items: center; padding: var(--app-space-1) var(--app-space-1) var(--app-space-1) var(--app-space-3); }
.list .actions { flex-direction: row; align-items: center; }
.list .badges { margin-top: 0; }
/* Padded on both sides: against the thumbnail the dense checkbox reads as part of the picture. */
.select-lead { display: flex; align-items: center; padding: 0 var(--app-space-3) 0 var(--app-space-2); }
</style>
