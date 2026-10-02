<script setup lang="ts">
import { useQueryClient } from '@tanstack/vue-query';
import { computed, onBeforeUnmount, onMounted, watch, type ComponentPublicInstance } from 'vue';
import { RouterView, useRoute, useRouter } from 'vue-router';
import { useDownloads } from '@/api/queries/downloads';
import { connectSocket, disconnectSocket } from '@/api/socket';
import AuthDialog from '@/components/AuthDialog.vue';
import DownloadsDrawer from '@/components/DownloadsDrawer.vue';
import { useI18n } from '@/i18n';
import { useDownloadsStore } from '@/stores/downloads';
import { usePreferencesStore } from '@/stores/preferences';
import { useUploadsStore } from '@/stores/uploads';
import { applyTheme, watchSystemTheme } from '@/theme/applyTheme';
import { AppShell, IconButton, TRANSITIONS, icons, type NavItem } from '@/ui';
import { captureScroll, lastLocation, restoreScroll, type ScrollSnapshot } from '@/viewState';

const { t, locale } = useI18n();
const qc = useQueryClient();
const prefs = usePreferencesStore();
const downloadsStore = useDownloadsStore();
const uploads = useUploadsStore();
const jobs = useDownloads();
const route = useRoute();
const router = useRouter();

const themeOptions = () => ({ mode: prefs.prefs.theme, sourceColor: prefs.prefs.sourceColor, contrast: prefs.prefs.contrast });
watch(() => [prefs.prefs.theme, prefs.prefs.sourceColor, prefs.prefs.contrast], () => applyTheme(themeOptions()), { immediate: true });
watch(locale, (l) => (document.documentElement.lang = l), { immediate: true });
const stopTheme = watchSystemTheme(themeOptions);

onMounted(() => {
  connectSocket(qc);
  prefs.loadFromServer();
});

/*
 * Views are kept alive, so each keeps its state while another is shown. Scroll positions are the
 * exception — an element leaving the document loses them — so they are taken as a view is left and
 * put back as it returns, when it returns to the same place.
 */
const scrolls = new WeakMap<Element, { location: string; snapshot: ScrollSnapshot }>();
let view: Element | null = null;
function setView(instance: Element | ComponentPublicInstance | null) {
  const el = instance && '$el' in instance ? instance.$el : instance;
  view = el instanceof Element ? el : null;
}
const stopCapture = router.beforeEach((to, from) => {
  if (view && to.name !== from.name) scrolls.set(view, { location: from.fullPath, snapshot: captureScroll(view.parentElement ?? view) });
});
function restoreView(el: Element) {
  const saved = scrolls.get(el);
  if (saved && saved.location === route.fullPath) restoreScroll(saved.snapshot);
  else if (el.parentElement) el.parentElement.scrollTop = 0;
}

onBeforeUnmount(() => {
  stopTheme();
  stopCapture();
  disconnectSocket();
});

const activeCount = computed(() => (jobs.data.value ?? []).filter((j) => j.state === 'running' || j.state === 'queued').length + uploads.active);
// A destination opens where it was left; choosing the one already on screen takes it back to its start.
const destination = (path: string) => (route.path === path ? path : lastLocation(path));
const nav = computed<NavItem[]>(() => [
  { to: destination('/browse'), label: t('nav.browse'), icon: icons.Search },
  { to: destination('/hubs'), label: t('nav.hubs'), icon: icons.Box },
  { to: destination('/direct'), label: t('nav.direct'), icon: icons.Link },
  { to: destination('/library'), label: t('nav.library'), icon: icons.Library },
  { to: destination('/settings'), label: t('nav.settings'), icon: icons.Settings },
]);
const cycleTheme = () => (prefs.prefs.theme = prefs.prefs.theme === 'light' ? 'dark' : prefs.prefs.theme === 'dark' ? 'system' : 'light');
const themeIcon = computed(() => ({ light: icons.Sun, dark: icons.Moon, system: icons.SunMoon })[prefs.prefs.theme]);
</script>

<template>
  <AppShell :items="nav" :title="t('app.title')">
    <template #rail-top>
      <IconButton :icon="icons.Sparkles" :label="t('app.title')" tonal />
    </template>
    <template #actions>
      <IconButton :icon="icons.Download" :label="t('nav.downloads')" :badge="activeCount || null" @click="downloadsStore.drawerOpen = true" />
      <IconButton :icon="themeIcon" :label="`${t('settings.theme')}: ${t(`settings.themes.${prefs.prefs.theme}`)}`" @click="cycleTheme" />
    </template>
    <RouterView v-slot="{ Component, route }">
      <Transition :name="TRANSITIONS.fadeThrough" mode="out-in" @enter="restoreView">
        <KeepAlive>
          <component :is="Component" :ref="setView" :key="route.name" />
        </KeepAlive>
      </Transition>
    </RouterView>
  </AppShell>
  <DownloadsDrawer />
  <AuthDialog />
</template>
