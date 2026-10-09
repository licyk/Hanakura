<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, reactive, ref, watch } from 'vue';
import AppIcon from '@/ui/AppIcon.vue';
import IconButton from '@/ui/IconButton.vue';
import ProgressCircle from '@/ui/ProgressCircle.vue';
import { ChevronLeft, ChevronRight, Eye, Image as ImageIcon, Maximize2, Minimize2, X, ZoomIn, ZoomOut } from '@/ui/icons';
import { trapFocus, useLayer } from '@/ui/layers';
import { containerFrom, prefersReducedMotion } from '@/ui/motion/transitions';

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
 * that dialog's scrim.
 *
 * The interaction is Hanaikada's viewer's: the wheel, a pinch or a double-click zooms, dragging
 * pans a zoomed image, and a sideways drag of a fitted one pulls the page along, after which it
 * slides out and its neighbour slides in; the arrows and the keys play the same slide. The image is
 * placed by script from the measured stage, never by percentages, so a tall picture in a wide
 * window fits by its height.
 */
const props = withDefaults(
  defineProps<{
    items: ViewerItem[];
    fromRect?: DOMRect | null;
    closeLabel?: string;
    previousLabel?: string;
    nextLabel?: string;
    revealLabel?: string;
    zoomInLabel?: string;
    zoomOutLabel?: string;
    fitLabel?: string;
    actualSizeLabel?: string;
  }>(),
  {
    closeLabel: 'Close',
    previousLabel: 'Previous',
    nextLabel: 'Next',
    revealLabel: 'NSFW',
    zoomInLabel: 'Zoom in',
    zoomOutLabel: 'Zoom out',
    fitLabel: 'Fit to window',
    actualSizeLabel: 'Actual size',
  },
);
const open = defineModel<boolean>('open', { default: false });
const index = defineModel<number>('index', { default: 0 });
const emit = defineEmits<{ reveal: [number] }>();

const panel = ref<HTMLElement | null>(null);
const motionStyle = ref<Record<string, string>>({});
const state = ref<'loading' | 'loaded' | 'error'>('loading');
let previousFocus: HTMLElement | null = null;

const count = computed(() => props.items.length);
const current = computed<ViewerItem | undefined>(() => props.items[Math.min(Math.max(index.value, 0), count.value - 1)]);
/** Only a loaded, revealed image zooms and pans; a video keeps its own controls. */
const zoomable = computed(() => !!current.value && !current.value.isVideo && !current.value.blurred && state.value === 'loaded');

// -- geometry: the stage is the whole window, the fit area that minus the gutters the bar and arrows need --

const stage = ref<HTMLElement | null>(null);
const fitArea = ref<HTMLElement | null>(null);
const stageSize = reactive({ w: 0, h: 0 });
const areaSize = reactive({ w: 0, h: 0 });
const natural = reactive({ w: 0, h: 0 });
const view = reactive({ fit: true, scale: 1, x: 0, y: 0 });

const fitScale = computed(() => (natural.w && natural.h && areaSize.w && areaSize.h ? Math.min(areaSize.w / natural.w, areaSize.h / natural.h, 1) : 1));
const scale = computed(() => (view.fit ? fitScale.value : view.scale));
// Sized rather than scaled, so the blur of a hidden image and the corners stay the same on screen at any zoom.
const imageStyle = computed(() => {
  if (!natural.w) return undefined;
  const s = scale.value;
  const left = stageSize.w / 2 + view.x - (natural.w * s) / 2;
  const top = stageSize.h / 2 + view.y - (natural.h * s) / 2;
  return { width: `${natural.w * s}px`, height: `${natural.h * s}px`, transform: `translate(${left}px, ${top}px)` };
});
const zoomLabel = computed(() => `${Math.round(scale.value * 100)}%`);

function measure() {
  if (stage.value) Object.assign(stageSize, { w: stage.value.clientWidth, h: stage.value.clientHeight });
  if (fitArea.value) Object.assign(areaSize, { w: fitArea.value.clientWidth, h: fitArea.value.clientHeight });
}
let resize: ResizeObserver | null = null;
watch([stage, fitArea], ([s, a]) => {
  resize?.disconnect();
  resize = null;
  if (s && a && typeof ResizeObserver !== 'undefined') {
    resize = new ResizeObserver(measure);
    resize.observe(s);
    resize.observe(a);
  }
  measure();
});

watch(
  () => current.value?.src,
  () => {
    state.value = 'loading';
    Object.assign(view, { fit: true, x: 0, y: 0 });
    preload();
  },
);
// The list can shrink under an open viewer (another version picked); nothing left, nothing to show.
watch(count, (n) => {
  if (!n) open.value = false;
  else if (index.value >= n) index.value = n - 1;
});

function onLoad(event: Event) {
  const img = event.target as HTMLImageElement;
  Object.assign(natural, { w: img.naturalWidth, h: img.naturalHeight });
  state.value = 'loaded';
  measure();
}

function preload() {
  const i = index.value;
  if (count.value < 2) return;
  for (const neighbour of [props.items[(i + 1) % count.value], props.items[(i - 1 + count.value) % count.value]]) {
    if (!neighbour || neighbour.isVideo) continue;
    const img = new Image();
    img.referrerPolicy = 'no-referrer';
    img.src = neighbour.src;
  }
}

// -- zoom and pan -------------------------------------------------------------------------------------

/** Zooms to ``next`` keeping the image point under (px, py) — the stage's centre by default — in place. */
function zoomAt(next: number, px = stageSize.w / 2, py = stageSize.h / 2) {
  if (!zoomable.value) return;
  const clamped = Math.min(16, Math.max(0.05, next));
  const s = scale.value;
  const left = stageSize.w / 2 + view.x - (natural.w * s) / 2;
  const top = stageSize.h / 2 + view.y - (natural.h * s) / 2;
  const qx = (px - left) / s;
  const qy = (py - top) / s;
  view.fit = false;
  view.scale = clamped;
  view.x = px - qx * clamped - stageSize.w / 2 + (natural.w * clamped) / 2;
  view.y = py - qy * clamped - stageSize.h / 2 + (natural.h * clamped) / 2;
}
const fit = () => Object.assign(view, { fit: true, x: 0, y: 0 });
const actual = (px?: number, py?: number) => zoomAt(1, px, py);

function stagePoint(event: MouseEvent) {
  const rect = stage.value!.getBoundingClientRect();
  return [event.clientX - rect.left, event.clientY - rect.top] as const;
}

function onWheel(event: WheelEvent) {
  if (!zoomable.value) return;
  event.preventDefault();
  // A line or a page of wheel is worth what a pixel wheel sends for one notch.
  const unit = event.deltaMode === WheelEvent.DOM_DELTA_LINE ? 33 : event.deltaMode === WheelEvent.DOM_DELTA_PAGE ? 400 : 1;
  zoomAt(scale.value * Math.pow(1.0015, -event.deltaY * unit), ...stagePoint(event));
}

function onDoubleClick(event: MouseEvent) {
  if (!zoomable.value || !(event.target as HTMLElement).classList.contains('image')) return;
  if (view.fit || Math.abs(scale.value - fitScale.value) < 0.01) actual(...stagePoint(event));
  else fit();
}

const pointers = new Map<number, { x: number; y: number }>();
let pinchStart: { distance: number; scale: number; cx: number; cy: number } | null = null;
let panStart: { x: number; y: number; vx: number; vy: number } | null = null;
let swipeStart: { x: number; y: number } | null = null;
let downAt: { x: number; y: number } | null = null;
// Set once a press travels: the click that ends a drag, a swipe or a pinch must not close the viewer.
let moved = false;

function onPointerDown(event: PointerEvent) {
  const target = event.target as HTMLElement;
  // A player's controls and the reveal button keep their own pointer: no pan, pinch or swipe there.
  if (event.button !== 0 || target.closest('video, button')) return;
  try {
    target.setPointerCapture?.(event.pointerId);
  } catch {
    /* a pointer the browser no longer tracks */
  }
  if (!pointers.size) moved = false;
  pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
  if (pointers.size === 2) {
    moved = true;
    // A second finger means a pinch, not a swipe.
    swipeStart = panStart = null;
    if (swipe.dx && !swipe.busy) void slideTo('swipe-in', 0);
    if (!zoomable.value) return;
    const [a, b] = [...pointers.values()];
    const rect = stage.value!.getBoundingClientRect();
    pinchStart = { distance: Math.hypot(a.x - b.x, a.y - b.y), scale: scale.value, cx: (a.x + b.x) / 2 - rect.left, cy: (a.y + b.y) / 2 - rect.top };
  } else {
    downAt = { x: event.clientX, y: event.clientY };
    panStart = { x: event.clientX, y: event.clientY, vx: view.x, vy: view.y };
    swipeStart = view.fit && !swipe.busy ? { x: event.clientX, y: event.clientY } : null;
  }
}

function onPointerMove(event: PointerEvent) {
  if (!pointers.has(event.pointerId)) return;
  pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
  if (downAt && Math.hypot(event.clientX - downAt.x, event.clientY - downAt.y) > 6) moved = true;
  if (pinchStart && pointers.size === 2) {
    const [a, b] = [...pointers.values()];
    zoomAt((pinchStart.scale * Math.hypot(a.x - b.x, a.y - b.y)) / pinchStart.distance, pinchStart.cx, pinchStart.cy);
  } else if (panStart && !view.fit) {
    view.x = panStart.vx + event.clientX - panStart.x;
    view.y = panStart.vy + event.clientY - panStart.y;
  } else if (swipeStart && pointers.size === 1 && !swipe.busy) {
    // Only a sideways drag moves the page; with nowhere to go it gives way reluctantly.
    const dx = event.clientX - swipeStart.x;
    if (Math.abs(dx) > Math.abs(event.clientY - swipeStart.y)) {
      swipe.motion = '';
      swipe.dx = canGo() ? dx : dx / 4;
    }
  }
}

function onPointerUp(event: PointerEvent) {
  pointers.delete(event.pointerId);
  if (pointers.size < 2) pinchStart = null;
  if (swipeStart && pointers.size === 0) {
    const dx = event.clientX - swipeStart.x;
    if (Math.abs(dx) > 60 && Math.abs(dx) > Math.abs(event.clientY - swipeStart.y) && canGo()) void swipeTo(dx < 0 ? 1 : -1);
    else if (swipe.dx) void slideTo('swipe-in', 0);
  }
  swipeStart = panStart = null;
  if (!pointers.size) downAt = null;
}

function onPointerCancel(event: PointerEvent) {
  swipeStart = null;
  if (swipe.dx && !swipe.busy) void slideTo('swipe-in', 0);
  onPointerUp(event);
}

/** A click beside the picture closes; on a hidden one it asks for the reveal. */
function onStageClick(event: MouseEvent) {
  if (moved) {
    moved = false;
    return;
  }
  const target = event.target as HTMLElement;
  if (target.classList.contains('image')) {
    if (current.value?.blurred) emit('reveal', index.value);
  } else if (!target.closest('video, button')) {
    open.value = false;
  }
}

// -- sliding: a swipe drags the page, then it slides out and its neighbour slides in from the other --
// -- side; the arrows and the keys play the same slide ------------------------------------------------

const slide = ref<HTMLElement | null>(null);
const swipe = reactive({ dx: 0, motion: '' as '' | 'swipe-out' | 'swipe-in', busy: false });
const slideStyle = computed(() => (swipe.dx ? { transform: `translateX(${swipe.dx}px)` } : undefined));
// The list wraps around, so either way leads somewhere as soon as there are two.
const canGo = () => count.value > 1;
/** One move of ``by`` places: the model's prop catches up only after the owner renders, so two steps in a row must be one move. */
function go(by: number) {
  if (canGo()) index.value = (((index.value + by) % count.value) + count.value) % count.value;
}

// A newer slide or an interruption bumps ``generation``; an older slide then stops where it is.
let generation = 0;
// Ends the transition in flight at once, and the step the running slide has not taken yet.
let settle: (() => void) | null = null;
let pendingDir: 1 | -1 | null = null;

/** Move the page to ``dx`` with one of the swipe transitions; resolves when it gets there. */
function slideTo(motion: 'swipe-out' | 'swipe-in', dx: number): Promise<void> {
  settle?.();
  const el = slide.value;
  if (!el || swipe.dx === dx || prefersReducedMotion()) {
    Object.assign(swipe, { motion: '', dx });
    return Promise.resolve();
  }
  Object.assign(swipe, { motion, dx });
  return new Promise((resolve) => {
    const done = (event?: TransitionEvent) => {
      // The image's own fade ends here too, bubbling up.
      if (event && (event.target !== el || event.propertyName !== 'transform')) return;
      el.removeEventListener('transitionend', done);
      clearTimeout(timer);
      if (settle === finish) settle = null;
      resolve();
    };
    const finish = () => done();
    settle = finish;
    el.addEventListener('transitionend', done);
    const timer = setTimeout(done, 1000);
  });
}

async function swipeTo(dir: 1 | -1) {
  const run = ++generation;
  swipe.busy = true;
  pendingDir = dir;
  try {
    const width = stageSize.w || window.innerWidth;
    await slideTo('swipe-out', -dir * width);
    if (run !== generation) return;
    pendingDir = null;
    go(dir);
    // The neighbour starts beyond the opposite edge, laid out there before it moves in.
    Object.assign(swipe, { motion: '', dx: prefersReducedMotion() ? 0 : dir * width });
    await nextTick();
    void slide.value?.offsetWidth;
    if (run !== generation) return;
    await slideTo('swipe-in', 0);
  } finally {
    if (run === generation) Object.assign(swipe, { busy: false, motion: '', dx: 0 });
  }
}

/** Ends any slide in flight where it was headed, without taking the step it still owed. */
function interrupt() {
  generation++;
  settle?.();
  pendingDir = null;
  Object.assign(swipe, { busy: false, motion: '', dx: 0 });
}

/**
 * The arrows and the keys. From rest the page slides; a press during a slide (quick presses, a held
 * key) lands the slide at once and steps straight on, so every press still moves by one.
 */
function step(dir: 1 | -1) {
  if (!swipe.busy) {
    if (canGo()) void swipeTo(dir);
    return;
  }
  const owed = pendingDir ?? 0;
  interrupt();
  go(owed + dir);
}

function jump(to: number) {
  interrupt();
  index.value = to;
}

// -- keyboard and lifecycle ---------------------------------------------------------------------------

useLayer(
  () => open.value,
  (event) => {
    const keys: Record<string, () => void> = {
      Escape: () => (open.value = false),
      ArrowLeft: () => step(-1),
      ArrowRight: () => step(1),
      Home: () => jump(0),
      End: () => jump(count.value - 1),
    };
    if (zoomable.value) {
      Object.assign(keys, {
        '+': () => zoomAt(scale.value * 1.25),
        '=': () => zoomAt(scale.value * 1.25),
        '-': () => zoomAt(scale.value / 1.25),
        '0': fit,
        '1': () => actual(),
      });
    }
    // A focused video takes the arrows for seeking.
    if (event.key !== 'Escape' && (document.activeElement as HTMLElement | null)?.tagName === 'VIDEO') return;
    const action = event.ctrlKey || event.metaKey || event.altKey ? undefined : keys[event.key];
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
      fit();
      motionStyle.value = {};
      await nextTick();
      motionStyle.value = containerFrom(props.fromRect, new DOMRect(0, 0, window.innerWidth, window.innerHeight));
      panel.value?.focus();
      measure();
      preload();
    } else {
      interrupt();
      pointers.clear();
      previousFocus?.focus?.();
    }
  },
  { immediate: true },
);
onBeforeUnmount(() => {
  resize?.disconnect();
  interrupt();
});
</script>

<template>
  <Teleport to="body">
    <Transition name="scrim">
      <div v-if="open" class="scrim" />
    </Transition>
    <Transition name="container">
      <div v-if="open && current" ref="panel" class="viewer" role="dialog" aria-modal="true" :aria-label="current.alt" tabindex="-1" :style="motionStyle">
        <div
          ref="stage"
          class="stage"
          :class="{ zoomable, zoomed: zoomable && !view.fit, video: current.isVideo }"
          @wheel="onWheel"
          @dblclick="onDoubleClick"
          @pointerdown="onPointerDown"
          @pointermove="onPointerMove"
          @pointerup="onPointerUp"
          @pointercancel="onPointerCancel"
          @click="onStageClick"
        >
          <div ref="fitArea" class="fit-area measure" aria-hidden="true" />
          <!-- What a swipe moves: everything on the stage. -->
          <div ref="slide" class="slide" :class="swipe.motion" :style="slideStyle">
            <img
              v-if="!current.isVideo && state !== 'error'"
              :key="current.src"
              class="image"
              :class="{ loaded: state === 'loaded', blurred: current.blurred, fitted: view.fit }"
              :style="imageStyle"
              :src="current.src"
              :alt="current.alt"
              decoding="async"
              referrerpolicy="no-referrer"
              draggable="false"
              @load="onLoad"
              @error="state = 'error'"
            />
            <div class="fit-area">
              <div v-if="state === 'loading'" class="status"><ProgressCircle /></div>
              <div v-else-if="state === 'error'" class="status fallback"><AppIcon :icon="ImageIcon" :size="24" /></div>
              <video
                v-if="current.isVideo"
                v-show="state !== 'error'"
                :key="current.src"
                class="media"
                :class="{ blurred: current.blurred }"
                :src="current.src"
                :controls="!current.blurred"
                autoplay
                loop
                playsinline
                @loadeddata="state = 'loaded'"
                @error="state = 'error'"
                @click="current.blurred && emit('reveal', index)"
              />
              <button v-if="current.blurred && state === 'loaded'" type="button" class="reveal type-label-large" @click="emit('reveal', index)">
                <AppIcon :icon="Eye" :size="20" /> {{ revealLabel }}
              </button>
            </div>
          </div>
        </div>
        <div class="bar">
          <span v-if="count > 1" class="counter pill type-label-large" aria-live="polite">{{ index + 1 }} / {{ count }}</span>
          <template v-if="zoomable">
            <IconButton class="wide" tonal :icon="ZoomOut" :label="zoomOutLabel" @click="zoomAt(scale / 1.25)" />
            <span class="zoom pill wide type-label-large">{{ zoomLabel }}</span>
            <IconButton class="wide" tonal :icon="ZoomIn" :label="zoomInLabel" @click="zoomAt(scale * 1.25)" />
            <IconButton tonal :icon="view.fit ? Maximize2 : Minimize2" :label="view.fit ? actualSizeLabel : fitLabel" @click="view.fit ? actual() : fit()" />
          </template>
          <IconButton class="close" tonal :icon="X" :label="closeLabel" @click="open = false" />
        </div>
        <template v-if="count > 1">
          <IconButton class="nav prev" tonal :icon="ChevronLeft" :label="previousLabel" @click="step(-1)" />
          <IconButton class="nav next" tonal :icon="ChevronRight" :label="nextLabel" @click="step(1)" />
        </template>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
/* Above dialogs (40, 41), below the snackbar (50), so a message about the page stays readable. */
.scrim { position: fixed; inset: 0; z-index: 45; background: color-mix(in srgb, var(--md-sys-color-scrim) 88%, transparent); }
.viewer { position: fixed; inset: 0; z-index: 46; outline: none; overscroll-behavior: contain; }
.stage { position: absolute; inset: 0; overflow: hidden; touch-action: none; user-select: none; }
.stage.video { touch-action: auto; }
.stage.zoomable .image { cursor: zoom-in; }
.stage.zoomed .image { cursor: grab; }
.stage.zoomed:active .image { cursor: grabbing; }
.slide { position: absolute; inset: 0; }
/* Where a fitted image, a video and the status sit: the window less room for the bar and the arrows. */
.fit-area { position: absolute; inset: calc(2 * var(--app-space-8)); }
.fit-area.measure { visibility: hidden; pointer-events: none; }
.slide .fit-area { pointer-events: none; }
.slide .fit-area > * { pointer-events: auto; }
.image {
  position: absolute; top: 0; left: 0; max-width: none; opacity: 0; box-shadow: var(--app-elevation-3);
  transition: opacity var(--md-sys-motion-duration-short4) var(--md-sys-motion-easing-standard);
}
.image.fitted { border-radius: var(--md-sys-shape-corner-small); }
.image.loaded { opacity: 1; }
.media { position: absolute; inset: 0; margin: auto; max-width: 100%; max-height: 100%; border-radius: var(--md-sys-shape-corner-small); box-shadow: var(--app-elevation-3); }
.blurred { filter: blur(32px) saturate(0.8); cursor: pointer; }
.status { position: absolute; inset: 0; display: grid; place-items: center; pointer-events: none !important; }
.fallback { color: var(--md-sys-color-inverse-on-surface); }
.reveal {
  position: absolute; left: 50%; top: 50%; translate: -50% -50%; display: inline-flex; align-items: center; gap: var(--app-space-2);
  padding: var(--app-space-2) var(--app-space-4); border: 0; border-radius: var(--md-sys-shape-corner-full); cursor: pointer;
  background: var(--md-sys-color-inverse-surface); color: var(--md-sys-color-inverse-on-surface);
}
.bar { position: absolute; top: 0; right: 0; display: flex; align-items: center; gap: var(--app-space-2); padding: var(--app-space-3); padding-top: max(var(--app-space-3), env(safe-area-inset-top)); }
.pill { padding: var(--app-space-1) var(--app-space-3); border-radius: var(--md-sys-shape-corner-full); background: var(--md-sys-color-surface-container-high); color: var(--md-sys-color-on-surface); }
.zoom { min-width: 56px; text-align: center; }
.nav { position: absolute; top: 50%; translate: 0 -50%; }
.prev { left: var(--app-space-3); }
.next { right: var(--app-space-3); }
@media (max-width: 599px) {
  /* A phone: the image takes the width, the arrows move to the bottom edge, clear of the picture. */
  .fit-area { inset: calc(2 * var(--app-space-8)) 0; }
  .image.fitted, .media { border-radius: 0; }
  .wide { display: none; }
  .nav { top: auto; bottom: max(var(--app-space-3), env(safe-area-inset-bottom)); translate: none; }
}
</style>
