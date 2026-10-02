import { defineStore } from 'pinia';
import { reactive, watch } from 'vue';
import { getClientState, putClientState } from '@/api/queries/app';
import type { ThemeMode } from '@/theme/applyTheme';
import { DEFAULT_SOURCE_COLOR } from '@/theme/scheme';

export type Locale = 'en' | 'zh-CN';
/** ``auto`` follows the system language; the others fix one. */
export type LocalePreference = 'auto' | Locale;

export interface Preferences {
  theme: ThemeMode;
  sourceColor: string;
  contrast: number;
  locale: LocalePreference;
  lastSource: string;
  lastHub: string;
  lastRoot: string | null;
  libraryView: 'grid' | 'list';
}

const STORAGE_KEY = 'hanakura:preferences';
const SERVER_KEY = 'preferences';

const DEFAULTS: Preferences = {
  theme: 'system',
  sourceColor: DEFAULT_SOURCE_COLOR,
  contrast: 0,
  locale: 'auto',
  lastSource: 'civitai',
  lastHub: 'huggingface',
  lastRoot: null,
  libraryView: 'grid',
};

function readLocal(): Partial<Preferences> {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY) ?? '{}');
  } catch {
    return {};
  }
}

/**
 * Interface preferences are client state. They persist to the server's client-state endpoint, so
 * they follow the user across browsers, with a localStorage copy so index.html can apply the theme
 * before the bundle loads.
 */
export const usePreferencesStore = defineStore('preferences', () => {
  const prefs = reactive<Preferences>({ ...DEFAULTS, ...readLocal() });
  let serverTimer: ReturnType<typeof setTimeout> | undefined;
  let loaded = false;

  watch(
    prefs,
    (value) => {
      try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(value));
      } catch {
        /* private mode */
      }
      if (!loaded) return;
      clearTimeout(serverTimer);
      serverTimer = setTimeout(() => putClientState(SERVER_KEY, { ...value }).catch(() => undefined), 500);
    },
    { deep: true },
  );

  async function loadFromServer() {
    try {
      const remote = await getClientState<Partial<Preferences>>(SERVER_KEY);
      if (remote && typeof remote === 'object') Object.assign(prefs, remote);
    } catch {
      /* offline or needs a token: keep local values */
    }
    loaded = true;
  }

  return { prefs, loadFromServer };
});
