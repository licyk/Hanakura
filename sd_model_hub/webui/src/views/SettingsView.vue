<script setup lang="ts">
import { computed } from 'vue';
import { RouterLink } from 'vue-router';
import { useMeta, useSettings, useUpdateSettings, useVersion } from '@/api/queries/app';
import { useRoots } from '@/api/queries/library';
import { useSources } from '@/api/queries/sources';
import { useHubs } from '@/api/queries/hubs';
import CivitaiAuthPanel from '@/components/CivitaiAuthPanel.vue';
import { useI18n } from '@/i18n';
import { usePreferencesStore } from '@/stores/preferences';
import { AppIcon, Divider, SegmentedButton, SelectField, Skeleton, Slider, Surface, Switch, TextField, TokenField, icons, useSnackbar } from '@/ui';

const { t, localeOptions } = useI18n();
const settings = useSettings();
const update = useUpdateSettings();
const snackbar = useSnackbar();
const prefs = usePreferencesStore();
const roots = useRoots();
const meta = useMeta();
const sources = useSources();
const hubs = useHubs();
const version = useVersion();

const s = computed(() => settings.data.value);
const sourceList = computed(() => [
  ...(sources.data.value ?? []).map((x) => ({ id: x.id, name: x.name, hub: false })),
  ...(hubs.data.value ?? []).map((x) => ({ id: x.id, name: x.name, hub: true })),
]);

/** Save one field; each change saves on its own with a snackbar confirmation. */
function save(patch: Record<string, unknown>, restart = false) {
  update.mutate(patch, {
    onSuccess: () => snackbar.show(restart ? `${t('common.saved')} · ${t('settings.restartNeeded')}` : t('common.saved')),
    onError: (e) => snackbar.error((e as Error).message),
  });
}
const num = (v: string | number | null) => (v === '' || v === null ? null : Number(v));
const rootOptions = computed(() => [{ value: '', label: '—' }, ...(roots.data.value ?? []).map((r) => ({ value: r.id, label: r.name }))]);
const envNote = (key: string) => (s.value?.env_overrides.includes(key) ? t('settings.envOverrides') : undefined);
/** A value the host application pinned would snap back after saving, so its switch is disabled. */
const isPinned = (dotted: string) => s.value?.pinned.includes(dotted) ?? false;
const librarySwitches = [
  { key: 'delete_to_trash', label: 'settings.deleteToTrash', help: 'settings.deleteToTrashHelp' },
  { key: 'follow_symlinks', label: 'settings.followSymlinks', help: 'settings.followSymlinksHelp' },
  { key: 'show_all_files', label: 'settings.showAllFiles', help: 'settings.showAllFilesHelp' },
  { key: 'combined_view', label: 'settings.combinedView', help: 'settings.combinedViewHelp' },
] as const;
</script>

<template>
  <div class="settings">
    <div v-if="!s" class="skeletons"><Skeleton v-for="i in 4" :key="i" height="160px" shape="medium" /></div>
    <template v-else>
      <Surface :level="0" shape="large" class="section">
        <h2 class="type-title-large">{{ t('settings.sections.appearance') }}</h2>
        <div class="field-row">
          <span class="type-body-large">{{ t('settings.theme') }}</span>
          <SegmentedButton
            v-model="prefs.prefs.theme"
            :options="[
              { value: 'light', icon: icons.Sun, label: t('settings.themes.light') },
              { value: 'dark', icon: icons.Moon, label: t('settings.themes.dark') },
              { value: 'system', icon: icons.SunMoon, label: t('settings.themes.system') },
            ]"
          />
        </div>
        <label class="field-row">
          <span class="type-body-large">{{ t('settings.sourceColor') }}</span>
          <input v-model="prefs.prefs.sourceColor" type="color" class="color" :aria-label="t('settings.sourceColor')" />
        </label>
        <Slider v-model="prefs.prefs.contrast" :label="t('settings.contrast')" :min="0" :max="1" :step="0.5" ticks />
        <div class="field-row">
          <span class="type-body-large">{{ t('settings.language') }}</span>
          <SelectField v-model="prefs.prefs.locale" :options="localeOptions" />
        </div>
      </Surface>

      <Surface :level="0" shape="large" class="section">
        <h2 class="type-title-large">{{ t('settings.sections.roots') }}</h2>
        <ul class="roots">
          <li v-for="r in roots.data.value ?? []" :key="r.id" class="type-body-medium">
            <AppIcon :icon="icons.HardDrive" :size="20" />
            <strong>{{ r.name }}</strong> <span class="muted">{{ t(`library.layouts.${r.layout}`) }} · {{ r.path }}</span>
          </li>
        </ul>
        <p v-if="meta.data.value?.roots_locked" class="type-body-small muted">{{ t('library.rootsLocked') }}</p>
        <RouterLink v-else to="/library" class="link type-label-large">{{ t('settings.manageRoots') }}</RouterLink>
      </Surface>

      <Surface :level="0" shape="large" class="section">
        <h2 class="type-title-large">{{ t('settings.sections.sources') }}</h2>
        <div v-for="src in sourceList" :key="src.id" class="source">
          <Switch :model-value="s.sources[src.id]?.enabled ?? true" :label="src.name" @update:model-value="save({ sources: { [src.id]: { enabled: $event } } })" />
          <!-- Civitai has two ways to authenticate, so it gets its own panel. -->
          <CivitaiAuthPanel v-if="src.id === 'civitai'" :settings="s" />
          <TokenField
            v-else
            :label="t('settings.tokenLabel', { source: src.name })"
            :configured="s.sources[src.id]?.token_configured ?? false"
            :save-label="t('common.save')"
            :clear-label="t('common.clear')"
            :configured-text="t('settings.tokenConfigured')"
            :not-configured-text="t('settings.tokenNotConfigured')"
            @save="save({ sources: { [src.id]: { token: $event } } })"
            @clear="save({ sources: { [src.id]: { token: null } } })"
          />
          <TextField
            v-if="src.hub"
            :model-value="s.sources[src.id]?.endpoint ?? ''"
            :label="t('settings.endpoint')"
            :supporting-text="t('settings.endpointHelp')"
            @change="save({ sources: { [src.id]: { endpoint: $event || null } } })"
          />
          <Divider />
        </div>
      </Surface>

      <Surface :level="0" shape="large" class="section">
        <h2 class="type-title-large">{{ t('settings.sections.network') }}</h2>
        <div class="grid">
          <TextField :model-value="s.network.proxy ?? ''" :label="t('settings.proxy')" :supporting-text="envNote('SD_MODEL_HUB_NETWORK__PROXY') ?? t('settings.proxyHelp')" @change="save({ network: { proxy: $event || null } })" />
          <TextField :model-value="s.network.timeout" type="number" :label="t('settings.timeout')" @change="save({ network: { timeout: num($event) } })" />
          <TextField :model-value="s.network.max_concurrent_downloads" type="number" :min="1" :max="16" :label="t('settings.concurrent')" :supporting-text="t('settings.concurrentHelp')" @change="save({ network: { max_concurrent_downloads: num($event) } }, true)" />
          <TextField :model-value="s.network.max_retries" type="number" :min="0" :max="20" :label="t('settings.retries')" @change="save({ network: { max_retries: num($event) } })" />
        </div>
      </Surface>

      <Surface :level="0" shape="large" class="section">
        <h2 class="type-title-large">{{ t('settings.sections.downloads') }}</h2>
        <div class="field-row">
          <span class="type-body-large">{{ t('settings.defaultRoot') }}</span>
          <SelectField :model-value="s.downloads.default_root ?? ''" :options="rootOptions" @update:model-value="save({ downloads: { default_root: $event || null } })" />
        </div>
        <Switch :model-value="s.downloads.save_preview" :label="t('settings.savePreview')" @update:model-value="save({ downloads: { save_preview: $event } })" />
        <Switch :model-value="s.downloads.save_metadata" :label="t('settings.saveMetadata')" @update:model-value="save({ downloads: { save_metadata: $event } })" />
        <Switch :model-value="s.downloads.write_webui_metadata" :label="t('settings.writeWebui')" @update:model-value="save({ downloads: { write_webui_metadata: $event } })" />
        <Switch :model-value="s.downloads.verify_hash" :label="t('settings.verifyHash')" @update:model-value="save({ downloads: { verify_hash: $event } })" />
      </Surface>

      <Surface :level="0" shape="large" class="section">
        <h2 class="type-title-large">{{ t('settings.sections.content') }} &amp; {{ t('settings.sections.library') }}</h2>
        <div class="field-row">
          <span class="type-body-large">{{ t('settings.nsfwMode') }}</span>
          <SegmentedButton
            :model-value="s.content.nsfw_mode"
            :options="[
              { value: 'hide', label: t('settings.nsfw.hide') },
              { value: 'blur', label: t('settings.nsfw.blur') },
              { value: 'show', label: t('settings.nsfw.show') },
            ]"
            @update:model-value="save({ content: { nsfw_mode: $event } })"
          />
        </div>
        <Switch
          v-for="sw in librarySwitches"
          :key="sw.key"
          :model-value="s.library[sw.key]"
          :label="t(sw.label)"
          :supporting-text="isPinned(`library.${sw.key}`) ? t('settings.pinned') : t(sw.help)"
          :disabled="isPinned(`library.${sw.key}`)"
          @update:model-value="save({ library: { [sw.key]: $event } })"
        />
      </Surface>

      <Surface :level="0" shape="large" class="section">
        <h2 class="type-title-large">{{ t('settings.sections.server') }}</h2>
        <div class="grid">
          <TextField :model-value="s.server.host" :label="t('settings.host')" :supporting-text="t('settings.restartNeeded')" @change="save({ server: { host: $event } }, true)" />
          <TextField :model-value="s.server.port" type="number" :label="t('settings.port')" :supporting-text="t('settings.restartNeeded')" @change="save({ server: { port: num($event) } }, true)" />
        </div>
        <TokenField
          :label="t('settings.accessToken')"
          :configured="s.server.access_token_configured"
          :save-label="t('common.save')"
          :clear-label="t('common.clear')"
          :configured-text="t('settings.tokenConfigured')"
          :not-configured-text="t('settings.accessTokenHelp')"
          @save="save({ server: { access_token: $event } })"
          @clear="save({ server: { access_token: null } })"
        />
      </Surface>

      <Surface :level="0" shape="large" class="section">
        <h2 class="type-title-large">{{ t('settings.sections.about') }}</h2>
        <dl class="about type-body-medium">
          <dt class="muted">{{ t('settings.version') }}</dt>
          <dd>{{ version.data.value?.version ?? '—' }}</dd>
          <dt class="muted">{{ t('settings.dataDir') }}</dt>
          <dd>{{ s.data_dir }}</dd>
          <dt class="muted">{{ t('settings.settingsFile') }}</dt>
          <dd>{{ s.settings_file }}</dd>
          <template v-if="s.env_overrides.length">
            <dt class="muted">{{ t('settings.envOverrides') }}</dt>
            <dd>{{ s.env_overrides.join(', ') }}</dd>
          </template>
        </dl>
      </Surface>
    </template>
  </div>
</template>

<style scoped>
/* One column of sections, each as wide as the window allows. */
.settings { display: flex; flex-direction: column; align-items: stretch; gap: var(--app-space-4); width: 100%; padding: var(--app-space-4) var(--app-space-6) var(--app-space-8); }
.skeletons { display: flex; flex-direction: column; gap: var(--app-space-4); }
.section { display: flex; flex-direction: column; gap: var(--app-space-2); padding: var(--app-space-4) var(--app-space-6) var(--app-space-6); }
h2 { margin: 0 0 var(--app-space-2); }
.field-row { display: flex; align-items: center; justify-content: space-between; gap: var(--app-space-4); min-height: 56px; flex-wrap: wrap; }
.color { width: 56px; height: 40px; padding: 0; border: 1px solid var(--md-sys-color-outline); border-radius: var(--md-sys-shape-corner-small); background: transparent; cursor: pointer; }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: var(--app-space-3); }
.source { display: flex; flex-direction: column; gap: var(--app-space-2); }
.roots { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: var(--app-space-2); }
.roots li { display: flex; align-items: center; gap: var(--app-space-2); overflow-wrap: anywhere; }
.link { color: var(--md-sys-color-primary); text-decoration: none; }
.about { display: grid; grid-template-columns: max-content minmax(0, 1fr); gap: var(--app-space-2) var(--app-space-4); margin: 0; }
.about dd { margin: 0; overflow-wrap: anywhere; }
@media (max-width: 599px) {
  .settings { padding: var(--app-space-3); }
  .section { padding: var(--app-space-4); }
}
</style>
