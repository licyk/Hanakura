import { computed, type ComputedRef } from 'vue';
import { useSettings } from '@/api/queries/app';

/** Civitai levels: 1 PG, 2 PG-13, 4 R, 8 X, 16 XXX. */
export const SENSITIVE_LEVEL = 4;

/** Whether an image of this level is drawn blurred until revealed: the thumbnails and the larger view share the rule. */
export function useNsfwHidden(): ComputedRef<(level: number | undefined) => boolean> {
  const settings = useSettings();
  return computed(() => {
    const hide = settings.data.value?.content.nsfw_mode !== 'show';
    return (level) => hide && (level ?? 0) >= SENSITIVE_LEVEL;
  });
}
