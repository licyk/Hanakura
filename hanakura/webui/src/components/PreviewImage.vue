<script setup lang="ts">
import { computed, ref, watch, type Component } from 'vue';
import { useSettings } from '@/api/queries/app';
import { AppIcon, Skeleton, icons } from '@/ui';

/** Lazy image with a fixed aspect ratio, a skeleton while loading, a fallback icon, and NSFW blur. */
const props = withDefaults(defineProps<{ src?: string | null; alt: string; nsfwLevel?: number; isVideo?: boolean; ratio?: string; fallbackIcon?: Component }>(), {
  nsfwLevel: 0,
  ratio: '3 / 4',
});
const settings = useSettings();
const state = ref<'loading' | 'loaded' | 'error'>(props.src ? 'loading' : 'error');
const revealed = ref(false);
watch(
  () => props.src,
  (src) => {
    state.value = src ? 'loading' : 'error';
    revealed.value = false;
  },
);
// Civitai levels: 1 PG, 2 PG-13, 4 R, 8 X, 16 XXX.
const sensitive = computed(() => props.nsfwLevel >= 4);
const blurred = computed(() => sensitive.value && settings.data.value?.content.nsfw_mode !== 'show' && !revealed.value);
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
.reveal {
  position: absolute; left: 50%; top: 50%; translate: -50% -50%; display: inline-flex; align-items: center; gap: var(--app-space-1);
  padding: var(--app-space-1) var(--app-space-3); border: 0; border-radius: var(--md-sys-shape-corner-full); cursor: pointer;
  background: color-mix(in srgb, var(--md-sys-color-inverse-surface) 80%, transparent); color: var(--md-sys-color-inverse-on-surface);
}
</style>
