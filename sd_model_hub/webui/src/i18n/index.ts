import { computed, ref } from 'vue';
import en from '@/i18n/en';
import zhCN from '@/i18n/zh-CN';
import { usePreferencesStore, type Locale, type LocalePreference } from '@/stores/preferences';

const MESSAGES: Record<Locale, typeof en> = { en, 'zh-CN': zhCN };
export const LOCALES: { value: Locale; label: string }[] = [
  { value: 'en', label: 'English' },
  { value: 'zh-CN', label: '简体中文' },
];
export const FALLBACK_LOCALE: Locale = 'en';

/**
 * The supported locale for a BCP 47 tag, or null. Every Chinese variant maps to the one Chinese
 * translation, which reads better to a Traditional Chinese reader than English does.
 */
export function matchLocale(tag: string | null | undefined): Locale | null {
  const lower = tag?.trim().toLowerCase() ?? '';
  if (lower === 'zh' || lower.startsWith('zh-')) return 'zh-CN';
  if (lower === 'en' || lower.startsWith('en-')) return 'en';
  return null;
}

/** ``auto`` becomes the system language when it is supported, English otherwise. */
export function resolveLocale(preference: LocalePreference | string | null | undefined, systemLanguage: string | null | undefined): Locale {
  if (preference && preference !== 'auto' && preference in MESSAGES) return preference as Locale;
  return matchLocale(systemLanguage) ?? FALLBACK_LOCALE;
}

const readSystemLanguage = () => (typeof navigator === 'undefined' ? null : (navigator.language ?? null));
// The system language can change while the app is open; ``auto`` follows it.
const systemLanguage = ref(readSystemLanguage());
if (typeof window !== 'undefined') window.addEventListener('languagechange', () => (systemLanguage.value = readSystemLanguage()));

function lookup(tree: unknown, key: string): string | undefined {
  let node: unknown = tree;
  for (const part of key.split('.')) {
    if (node && typeof node === 'object' && part in (node as Record<string, unknown>)) node = (node as Record<string, unknown>)[part];
    else return undefined;
  }
  return typeof node === 'string' ? node : undefined;
}

export function translate(locale: Locale, key: string, params?: Record<string, string | number>): string {
  const text = lookup(MESSAGES[locale], key) ?? lookup(MESSAGES.en, key) ?? key;
  return params ? text.replace(/\{(\w+)\}/g, (_, name: string) => String(params[name] ?? `{${name}}`)) : text;
}

/** ``t(key, params)`` in the current locale; reactive to the locale preference and, on ``auto``, the system language. */
export function useI18n() {
  const store = usePreferencesStore();
  const locale = computed(() => resolveLocale(store.prefs.locale, systemLanguage.value));
  const t = (key: string, params?: Record<string, string | number>) => translate(locale.value, key, params);
  /** A kind label, falling back to the raw value for kinds without a translation. */
  const kindLabel = (kind: string | null | undefined) => (kind ? (lookup(MESSAGES[locale.value].kinds, kind) ?? kind) : t('common.unknown'));
  /** The language choices, led by ``auto`` naming the language it currently resolves to. */
  const localeOptions = computed<{ value: LocalePreference; label: string }[]>(() => {
    const detected = resolveLocale('auto', systemLanguage.value);
    const label = LOCALES.find((l) => l.value === detected)?.label ?? detected;
    return [{ value: 'auto', label: t('settings.languageAuto', { language: label }) }, ...LOCALES];
  });
  return { t, locale, kindLabel, localeOptions };
}
