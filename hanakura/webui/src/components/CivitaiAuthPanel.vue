<script setup lang="ts">
import { computed, onMounted } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { useCivitaiAuth, useDisconnectCivitai, useSetCivitaiMethod, type AuthMethod } from '@/api/queries/auth';
import { useUpdateSettings } from '@/api/queries/app';
import { useStartCivitaiAuth } from '@/api/queries/auth';
import type { SettingsView } from '@/api/types';
import { formatDate } from '@/format';
import { useI18n } from '@/i18n';
import { AppButton, AppIcon, Badge, Divider, SegmentedButton, TextField, TokenField, icons, useSnackbar } from '@/ui';

/**
 * The two ways to authenticate with Civitai, side by side. A manual API token always works,
 * with or without an OAuth application; connecting an account is the other option.
 */
const props = defineProps<{ settings: SettingsView }>();
const { t, locale } = useI18n();
const snackbar = useSnackbar();
const route = useRoute();
const router = useRouter();
const status = useCivitaiAuth();
const start = useStartCivitaiAuth();
const disconnect = useDisconnectCivitai();
const setMethod = useSetCivitaiMethod();
const update = useUpdateSettings();

const state = computed(() => status.data.value);
const connected = computed(() => state.value?.oauth_state === 'connected');
const needsReauth = computed(() => state.value?.oauth_state === 'reauthorization_required');
const accountName = computed(() => state.value?.account?.username ?? state.value?.account?.id ?? '');

// The callback comes back to the settings page with ?civitai=connected or =error.
onMounted(() => {
  const result = route.query.civitai;
  if (!result) return;
  if (result === 'connected') snackbar.show(t('auth.connected'));
  else snackbar.error(t('auth.failed'));
  status.refetch();
  router.replace({ query: { ...route.query, civitai: undefined } });
});

async function connect() {
  try {
    const { authorization_url } = await start.mutateAsync('/#/settings');
    // Same-tab navigation: the backend keeps the credentials, the page never sees them.
    window.location.assign(authorization_url);
  } catch (e) {
    snackbar.error((e as Error).message);
  }
}

function choose(method: AuthMethod) {
  setMethod.mutate(method, { onError: (e) => snackbar.error((e as Error).message) });
}

function saveClientId(value: string) {
  update.mutate({ auth: { civitai: { oauth_client_id: value || null } } }, { onSuccess: () => status.refetch(), onError: (e) => snackbar.error((e as Error).message) });
}

function saveToken(token: string | null) {
  update.mutate(
    { sources: { civitai: { token } } },
    {
      onSuccess: () => {
        snackbar.show(t('common.saved'));
        status.refetch();
      },
      onError: (e) => snackbar.error((e as Error).message),
    },
  );
}
</script>

<template>
  <section class="civitai-auth">
    <header class="head">
      <h3 class="type-title-medium">{{ t('auth.title') }}</h3>
      <Badge v-if="state" :tone="state.effective_method === 'oauth' ? 'primary' : 'neutral'" :value="t(`auth.methods.${state.effective_method}`)" />
    </header>

    <p v-if="state?.env_override" class="type-body-small notice">
      <AppIcon :icon="icons.Info" :size="18" /> {{ t('auth.envOverride') }}
    </p>

    <!-- Manual API token: always available, with or without OAuth. -->
    <TokenField
      :label="t('auth.manualToken')"
      :configured="settings.sources.civitai?.token_configured ?? false"
      :save-label="t('common.save')"
      :clear-label="t('common.clear')"
      :configured-text="t('settings.tokenConfigured')"
      :not-configured-text="t('auth.manualTokenHelp')"
      @save="saveToken($event)"
      @clear="saveToken(null)"
    />

    <Divider />

    <!-- Connected account. -->
    <div class="oauth">
      <div class="oauth-text">
        <span class="type-body-large">{{ t('auth.account') }}</span>
        <span v-if="connected" class="type-body-medium muted">
          {{ accountName || t('auth.connectedAccount') }}
          <template v-if="state?.expires_at"> · {{ t('auth.expires', { at: formatDate(state.expires_at, locale) }) }}</template>
        </span>
        <span v-else-if="needsReauth" class="type-body-medium error">{{ t('auth.needsReauth') }}</span>
        <span v-else class="type-body-medium muted">{{ t('auth.notConnected') }}</span>
      </div>
      <div class="oauth-actions">
        <AppButton v-if="!connected" variant="tonal" :icon="icons.ExternalLink" :loading="start.isPending.value" :disabled="!state?.oauth_configured" @click="connect">
          {{ needsReauth ? t('auth.reconnect') : t('auth.connect') }}
        </AppButton>
        <AppButton v-else variant="outlined" :loading="disconnect.isPending.value" @click="disconnect.mutate()">{{ t('auth.disconnect') }}</AppButton>
      </div>
    </div>

    <TextField
      v-if="!state?.oauth_configured || settings.auth.civitai.oauth_client_id"
      :model-value="settings.auth.civitai.oauth_client_id ?? ''"
      :label="t('auth.clientId')"
      :supporting-text="t('auth.clientIdHelp')"
      @change="saveClientId($event)"
    />

    <!-- Which credential requests use. Only the user changes this. -->
    <div v-if="state && (connected || state.manual_token_configured)" class="method">
      <span class="type-body-large">{{ t('auth.useMethod') }}</span>
      <SegmentedButton
        :model-value="state.method"
        :options="[
          { value: 'manual', label: t('auth.methods.manual') },
          { value: 'oauth', label: t('auth.methods.oauth') },
        ]"
        @update:model-value="choose($event as AuthMethod)"
      />
    </div>
    <p v-if="state?.error" class="type-body-small error">{{ state.error }}</p>
  </section>
</template>

<style scoped>
.civitai-auth { display: flex; flex-direction: column; gap: var(--app-space-3); }
.head { display: flex; align-items: center; gap: var(--app-space-2); }
.head h3 { margin: 0; }
.notice { display: flex; align-items: center; gap: var(--app-space-1); margin: 0; color: var(--md-sys-color-on-surface-variant); }
.oauth { display: flex; align-items: center; justify-content: space-between; gap: var(--app-space-4); flex-wrap: wrap; }
.oauth-text { display: flex; flex-direction: column; min-width: 0; }
.method { display: flex; align-items: center; justify-content: space-between; gap: var(--app-space-4); flex-wrap: wrap; min-height: 56px; }
.error { color: var(--md-sys-color-error); margin: 0; }
</style>
