<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue';
import AppIcon from '@/ui/AppIcon.vue';
import IconButton from '@/ui/IconButton.vue';
import ProgressCircle from '@/ui/ProgressCircle.vue';
import { ChevronLeft, ChevronRight, Eye, Image as ImageIcon, X } from '@/ui/icons';
import { trapFocus, useLayer } from '@/ui/layers';
import { containerFrom } from '@/ui/motion/transitions';

export interface ViewerItem {
  src: string;
  alt: string;
  isVideo?: boolean;
  /** Shown blurred until revealed; the owner decides, since only it knows the content settings. */
  blurred?: boolean;
}

/**
 * Images at the size of the window, above whatever opened them — usually a dialog. It is a layer
 * of its own (``useLayer``), so Escape, the arrows and Tab act here and never on the dialog
 * underneath, and it is teleported to the end of the document, so a click on it cannot reach
 * that dialog's scrim. A click on an image larger than the window shows it at its own size.
 */
const props = withDefaults(
  defineProps<{ items: ViewerItem[]; fromRect?: DOMRect | null; closeLabel?: string; previousLabel?: string; nextLabel?: string; revealLabel?: string }>(),
  { closeLabel: 'Close', previousLabel: 'Previous', nextLabel: 'Next', revealLabel: 'NSFW' },
);
const open = defineModel<boolean>('open', { default: false });
const index = defineModel<number>('index', { default: 0 });
const emit = defineEmits<{ reveal: [number] }>();

const panel = ref<HTMLElement | null>(null);
const motionStyle = ref<Record<string, string>>({});
const state = ref<'loading' | 'loaded' | 'error'>('loading');
const zoomed = ref(false);
const zoomable = ref(false);
let previousFocus: HTMLElement | null = null;

const count = computed(() => props.items.length);
const current = computed<ViewerItem | undefined>(() => props.items[Math.min(Math.max(index.value, 0), count.value - 1)]);

function go(step: number) {
  if (count.value < 2) return;
  index.value = (index.value + step + count.value) % count.value;
}

watch(
  () => current.value?.src,
  () => {
    state.value = 'loading';
    zoomed.value = false;
    zoomable.value = false;
  },
);
// The list can shrink under an open viewer (another version picked); nothing left, nothing to show.
watch(count, (n) => {
  if (!n) open.value = false;
  else if (index.value >= n) index.value = n - 1;
});

useLayer(
  () => open.value,
  (event) => {
    const keys: Record<string, () => void> = {
      Escape: () => (open.value = false),
      ArrowLeft: () => go(-1),
      ArrowRight: () => go(1),
      Home: () => (index.value = 0),
      End: () => (index.value = count.value - 1),
    };
    // A focused video takes the arrows for seeking.
    if (event.key !== 'Escape' && (document.activeElement as HTMLElement | null)?.tagName === 'VIDEO') return;
    const action = keys[event.key];
    if (action) {
      event.preventDefault();
      action();
    }
    trapFocus(event, panel.value);
  },
);

watch(
  open,
  async (value) => {
    if (value) {
      previousFocus = document.activeElement as HTMLElement | null;
      state.value = 'loading';
      zoomed.value = false;
      motionStyle.value = {};
      await nextTick();
      motionStyle.value = containerFrom(props.fromRect, new DOMRect(0, 0, window.innerWidth, window.innerHeight));
      panel.value?.focus();
    } else {
      previousFocus?.focus?.();
    }
  },
  { immediate: true },
);

function onLoad(event: Event) {
  state.value = 'loaded';
  const img = event.target as HTMLImageElement;
  zoomable.value = img.naturalWidth > img.clientWidth + 1 || img.naturalHeight > img.clientHeight + 1;
}

function onMediaClick() {
  if (current.value?.blurred) emit('reveal', index.value);
  else if (zoomable.value) zoomed.value = !zoomed.value;
}

/** A horizontal swipe changes the image on a touch screen; a zoomed image pans instead. */
let swipeStart: { x: number; y: number } | null = null;
function onPointerDown(event: PointerEvent) {
  swipeStart = event.pointerType === 'mouse' || zoomed.value ? null : { x: event.clientX, y: event.clientY };
}
function onPointerUp(event: PointerEvent) {
  if (!swipeStart) return;
  const dx = event.clientX - swipeStart.x;
  const dy = event.clientY - swipeStart.y;
  swipeStart = null;
  if (Math.abs(dx) > 48 && Math.abs(dx) > Math.abs(dy) * 1.5) go(dx < 0 ? 1 : -1);
}
</script>

<template>
  <Teleport to="body">
    <Transition name="scrim">
      <div v-if="open" class="scrim" />
    </Transition>
    <Transition name="container">
      <div
        v-if="open && current"
        ref="panel"
        class="viewer"
        role="dialog"
        aria-modal="true"
        :aria-label="current.alt"
        tabindex="-1"
        :style="motionStyle"
        @pointerdown="onPointerDown"
        @pointerup="onPointerUp"
        @pointercancel="swipeStart = null"
      >
        <div class="stage" :class="{ zoomed }" @click.self="open = false">
          <Transition name="fade-through" mode="out-in">
            <div :key="current.src" class="frame" @click.self="open = false">
              <div v-if="state === 'loading'" class="status"><ProgressCircle /></div>
              <div v-else-if="state === 'error'" class="status fallback"><AppIcon :icon="ImageIcon" :size="24" /></div>
              <video
                v-if="current.isVideo"
                v-show="state !== 'error'"
                class="media"
                :class="{ blurred: current.blurred }"
                :src="current.src"
                :controls="!current.blurred"
                autoplay
                loop
                playsinline
                @loadeddata="state = 'loaded'"
                @error="state = 'error'"
              />
              <img
                v-else
                v-show="state !== 'error'"
                class="media"
                :class="{ blurred: current.blurred, zoomable: zoomable && !current.blurred, zoomed }"
                :src="current.src"
                :alt="current.alt"
                decoding="async"
                referrerpolicy="no-referrer"
                draggable="false"
                @load="onLoad"
                @error="state = 'error'"
                @click="onMediaClick"
              />
              <button v-if="current.blurred && state === 'loaded'" type="button" class="reveal type-label-large" @click="emit('reveal', index)">
                <AppIcon :icon="Eye" :size="20" /> {{ revealLabel }}
              </button>
            </div>
          </Transition>
        </div>
        <div class="bar">
          <span v-if="count > 1" class="counter type-label-large" aria-live="polite">{{ index + 1 }} / {{ count }}</span>
          <IconButton class="close" tonal :icon="X" :label="closeLabel" @click="open = false" />
        </div>
        <template v-if="count > 1">
          <IconButton class="nav prev" tonal :icon="ChevronLeft" :label="previousLabel" @click="go(-1)" />
          <IconButton class="nav next" tonal :icon="ChevronRight" :label="nextLabel" @click="go(1)" />
        </template>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
/* Above dialogs (40, 41), below the snackbar (50), so a message about the page stays readable. */
.scrim { position: fixed; inset: 0; z-index: 45; background: color-mix(in srgb, var(--md-sys-color-scrim) 88%, transparent); }
.viewer { position: fixed; inset: 0; z-index: 46; outline: none; overscroll-behavior: contain; }
.stage { position: absolute; inset: 0; display: grid; place-items: center; overflow: hidden; padding: calc(2 * var(--app-space-8)); }
.stage.zoomed { place-items: start center; overflow: auto; padding: 0; touch-action: pan-x pan-y; }
.frame { position: relative; display: grid; place-items: center; width: 100%; height: 100%; min-width: 0; min-height: 0; }
.zoomed .frame { width: auto; height: auto; min-width: 100%; min-height: 100%; }
.media { max-width: 100%; max-height: 100%; object-fit: contain; border-radius: var(--md-sys-shape-corner-small); box-shadow: var(--app-elevation-3); user-select: none; }
.media.zoomable { cursor: zoom-in; }
.media.zoomed { max-width: none; max-height: none; cursor: zoom-out; border-radius: 0; }
.blurred { filter: blur(32px) saturate(0.8); cursor: pointer; }
.status { position: absolute; inset: 0; display: grid; place-items: center; pointer-events: none; }
.fallback { color: var(--md-sys-color-inverse-on-surface); }
.reveal {
  position: absolute; left: 50%; top: 50%; translate: -50% -50%; display: inline-flex; align-items: center; gap: var(--app-space-2);
  padding: var(--app-space-2) var(--app-space-4); border: 0; border-radius: var(--md-sys-shape-corner-full); cursor: pointer;
  background: var(--md-sys-color-inverse-surface); color: var(--md-sys-color-inverse-on-surface);
}
.bar { position: absolute; top: 0; right: 0; display: flex; align-items: center; gap: var(--app-space-2); padding: var(--app-space-3); padding-top: max(var(--app-space-3), env(safe-area-inset-top)); }
.counter { padding: var(--app-space-1) var(--app-space-3); border-radius: var(--md-sys-shape-corner-full); background: var(--md-sys-color-surface-container-high); color: var(--md-sys-color-on-surface); }
.nav { position: absolute; top: 50%; translate: 0 -50%; }
.prev { left: var(--app-space-3); }
.next { right: var(--app-space-3); }
@media (max-width: 599px) {
  /* A phone: the image takes the width, the arrows move to the bottom edge, clear of the picture. */
  .stage { padding: calc(2 * var(--app-space-8)) 0; }
  .media { border-radius: 0; }
  .nav { top: auto; bottom: max(var(--app-space-3), env(safe-area-inset-bottom)); translate: none; }
}
</style>
