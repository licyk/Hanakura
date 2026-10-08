<script setup lang="ts">
import { computed, ref, watch, type Component } from 'vue';
import { useNsfwHidden } from '@/components/nsfw';
import { AppIcon, Skeleton, icons } from '@/ui';

/**
 * Lazy image with a fixed aspect ratio, a skeleton while loading, a fallback icon, and NSFW blur.
 * With ``openLabel`` the picture is a button that emits ``open`` with its rectangle, for a larger
 * view to grow from; ``revealed`` can be bound so that view and this one share the reveal.
 */
const props = withDefaults(defineProps<{ src?: string | null; alt: string; nsfwLevel?: number; isVideo?: boolean; ratio?: string; fallbackIcon?: Component; openLabel?: string }>(), {
  nsfwLevel: 0,
  ratio: '3 / 4',
  openLabel: undefined,
});
const emit = defineEmits<{ open: [DOMRect] }>();
const revealed = defineModel<boolean>('revealed', { default: false });
const hidden = useNsfwHidden();
const state = ref<'loading' | 'loaded' | 'error'>(props.src ? 'loading' : 'error');
watch(
  () => props.src,
  (src) => {
    state.value = src ? 'loading' : 'error';
    revealed.value = false;
  },
);
const blurred = computed(() => hidden.value(props.nsfwLevel) && !revealed.value);
const onOpen = (event: MouseEvent) => emit('open', (event.currentTarget as HTMLElement).getBoundingClientRect());
</script>

<template>
  <div class="preview" :style="{ aspectRatio: ratio }">
    <Skeleton v-if="state === 'loading'" class="fill" height="100%" shape="small" />
    <div v-if="state === 'error'" class="fallback"><AppIcon :icon="fallbackIcon ?? icons.Image" :size="24" /></div>
    <video v-if="src && isVideo" v-show="state !== 'error'" class="media" :class="{ blurred }" :src="src" muted loop autoplay playsinline @loadeddata="state = 'loaded'" @error="state = 'error'" />
    <img
      v-else-if="src"
      v-show="state !== 'error'"
      class="media"
      :class="{ blurred, loaded: state === 'loaded' }"
      :src="src"
      :alt="alt"
      loading="lazy"
      decoding="async"
      referrerpolicy="no-referrer"
      draggable="false"
      @load="state = 'loaded'"
      @error="state = 'error'"
    />
    <!-- A sibling laid over the picture, not a parent: the reveal button cannot sit inside another button. -->
    <button v-if="openLabel && src && state !== 'error'" type="button" class="open" :aria-label="openLabel" :title="openLabel" @click.stop="onOpen" />
    <button v-if="blurred && state === 'loaded'" type="button" class="reveal type-label-medium" @click.stop="revealed = true">
      <AppIcon :icon="icons.Eye" :size="18" /> NSFW
    </button>
  </div>
</template>

<style scoped>
.preview { position: relative; width: 100%; overflow: hidden; background: var(--md-sys-color-surface-container-high); }
.fill { position: absolute; inset: 0; }
.fallback { position: absolute; inset: 0; display: grid; place-items: center; color: var(--md-sys-color-on-surface-variant); }
.media { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; opacity: 0; transition: opacity var(--md-sys-motion-duration-medium1) var(--md-sys-motion-easing-standard), filter var(--md-sys-motion-duration-medium2) var(--md-sys-motion-easing-standard); }
.media.loaded, video.media { opacity: 1; }
.blurred { filter: blur(24px) saturate(0.8); transform: scale(1.1); }
.open { position: absolute; inset: 0; padding: 0; border: 0; background: transparent; cursor: zoom-in; }
.open:focus-visible { outline: 2px solid var(--md-sys-color-primary); outline-offset: -2px; }
.reveal {
  position: absolute; left: 50%; top: 50%; translate: -50% -50%; display: inline-flex; align-items: center; gap: var(--app-space-1);
  padding: var(--app-space-1) var(--app-space-3); border: 0; border-radius: var(--md-sys-shape-corner-full); cursor: pointer;
  background: color-mix(in srgb, var(--md-sys-color-inverse-surface) 80%, transparent); color: var(--md-sys-color-inverse-on-surface);
}
</style>
