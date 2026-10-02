import { onBeforeUnmount, onMounted, ref, type Ref } from 'vue';

/** Whether a CSS media query matches, kept current as the window changes. */
export function useMediaQuery(query: string): Ref<boolean> {
  const list = typeof window !== 'undefined' && typeof window.matchMedia === 'function' ? window.matchMedia(query) : null;
  const matches = ref(list?.matches ?? false);
  const update = (event: MediaQueryListEvent) => (matches.value = event.matches);
  onMounted(() => list?.addEventListener('change', update));
  onBeforeUnmount(() => list?.removeEventListener('change', update));
  return matches;
}
