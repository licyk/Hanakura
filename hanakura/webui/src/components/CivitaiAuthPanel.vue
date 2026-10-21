<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { useQueryClient } from '@tanstack/vue-query';
import {
  invalidateAfterSignIn,
  sessionEnded,
  useCancelCivitaiSession,
  useCivitaiAuth,
  useCivitaiSession,
  useDisconnectCivitai,
  useSetCivitaiMethod,
  useStartCivitaiAuth,
  type AuthMethod,
  type SignInFlow,
} from '@/api/queries/auth';
import { useUpdateSettings } from '@/api/queries/app';
import type { S, SettingsView } from '@/api/types';
import { formatDate } from '@/format';
import { useI18n } from '@/i18n';
import { AppButton, AppIcon, Badge, Divider, ExpansionPanel, ProgressBar, SegmentedButton, TextField, TokenField, icons, useSnackbar } from '@/ui';

/**
 * Civitai authentication. Signing in on Civitai's website is the main action; a manual API token
 * is the other option and always works on its own. Your own OAuth application is advanced
 * configuration, opened by itself only when signing in cannot work without it.
 */
const props = defineProps<{ settings: SettingsView }>();
const { t, locale } = useI18n();
const snackbar = useSnackbar();
const route = useRoute();
const router = useRouter();
const qc = useQueryClient();
const status = useCivitaiAuth();
const start = useStartCivitaiAuth();
const cancelSession = useCancelCivitaiSession();
const disconnect = useDisconnectCivitai();
const setMethod = useSetCivitaiMethod();
const update = useUpdateSettings();

type Reason = NonNullable<S['LoginSession']['error_code']>;

const state = computed(() => status.data.value);
const connected = computed(() => state.value?.oauth_state === 'connected');
const needsReauth = computed(() => state.value?.oauth_state === 'reauthorization_required');
const accountName = computed(() => state.value?.account?.username ?? state.value?.account?.id ?? '');
const flows = computed(() => state.value?.flows ?? []);
const canSignIn = computed(() => flows.value.length > 0);
// Signing in with a code is offered beside the browser, for a browser that cannot be sent back here.
const offersCode = computed(() => flows.value.includes('browser') && flows.value.includes('device'));
const unavailable = computed(() => (state.value && !canSignIn.value && state.value.unavailable_reason ? t(`auth.unavailable.${state.value.unavailable_reason}`) : ''));
const errorText = computed(() => (state.value?.error_code ? t(`auth.reasons.${state.value.error_code}`) : (state.value?.error ?? '')));

const clientIdPinned = computed(() => props.settings.pinned.includes('auth.civitai.oauth_client_id'));
const clientIdFromEnv = computed(() => props.settings.env_overrides.includes('HANAKURA_AUTH__CIVITAI__OAUTH_CLIENT_ID'));
const clientIdLocked = computed(() => clientIdPinned.value || clientIdFromEnv.value);
const clientIdHelp = computed(() => (clientIdPinned.value ? t('settings.pinned') : clientIdFromEnv.value ? t('settings.envOverrides') : t('auth.clientIdHelp')));
const advancedOpen = ref(false);
watch(
  () => state.value?.unavailable_reason,
  (reason) => {
    if (reason === 'no_client') advancedOpen.value = true;
  },
  { immediate: true },
);

// -- the device sign-in in progress -----------------------------------------

const sessionId = ref<string | null>(null);
const session = useCivitaiSession(sessionId);
const device = computed(() => (session.data.value?.flow === 'device' && !sessionEnded(session.data.value) ? session.data.value : null));
const verificationUrl = computed(() => device.value?.verification_uri_complete ?? device.value?.verification_uri ?? '');

const now = ref(Date.now());
let ticker: ReturnType<typeof setInterval> | undefined;
watch(device, (waiting) => {
  clearInterval(ticker);
  ticker = waiting ? setInterval(() => (now.value = Date.now()), 1000) : undefined;
});
onBeforeUnmount(() => clearInterval(ticker));
const remaining = computed(() => {
  if (!device.value) return '';
  const seconds = Math.max(0, Math.round((Date.parse(device.value.expires_at) - now.value) / 1000));
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;
});

watch(
  () => session.data.value,
  (current) => {
    if (!current || !sessionEnded(current)) return;
    sessionId.value = null;
    if (current.status === 'connected') {
      snackbar.show(t('auth.connected'));
      invalidateAfterSignIn(qc);
    } else if (current.status !== 'cancelled') {
      snackbar.error(t(`auth.reasons.${current.error_code ?? 'failed'}`));
      status.refetch();
    }
  },
);

/** Opens the page in a new tab without handing it this window; says so when the browser blocks it. */
function openVerification(url: string) {
  const tab = window.open('', '_blank');
  if (!tab) {
    snackbar.error(t('auth.device.blocked'));
    return;
  }
  tab.opener = null;
  tab.location.href = url;
}

// -- returning from Civitai --------------------------------------------------

// The callback comes back to the settings page with ?civitai=connected, or =error and a reason.
onMounted(() => {
  const result = route.query.civitai;
  if (!result) return;
  if (result === 'connected') snackbar.show(t('auth.connected'));
  else snackbar.error(t(`auth.reasons.${(route.query.civitai_reason as Reason | undefined) ?? 'failed'}`));
  invalidateAfterSignIn(qc);
  router.replace({ query: { ...route.query, civitai: undefined, civitai_reason: undefined } });
});

async function signIn(flow: SignInFlow) {
  try {
    const begun = await start.mutateAsync({ returnTo: '/#/settings', flow });
    if (begun.flow === 'browser') {
      // Same-tab navigation keeps this browser's binding; the page never sees a credential.
      window.location.assign(begun.authorization_url);
      return;
    }
    sessionId.value = begun.session_id;
    status.refetch();
    openVerification(begun.authorization_url);
  } catch (e) {
    snackbar.error((e as Error).message);
  }
}

function cancel() {
  if (!sessionId.value) return;
  cancelSession.mutate(sessionId.value, {
    onSuccess: () => {
      sessionId.value = null;
      status.refetch();
    },
    onError: (e) => snackbar.error((e as Error).message),
  });
}

function choose(method: AuthMethod) {
  setMethod.mutate(method, { onError: (e) => snackbar.error((e as Error).message) });
}

function saveClientId(value: string) {
  update.mutate({ auth: { civitai: { oauth_client_id: value.trim() || null } } }, { onSuccess: () => status.refetch(), onError: (e) => snackbar.error((e as Error).message) });
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

    <!-- The account, and signing in on Civitai's website. -->
    <div class="oauth">
      <div class="oauth-text">
        <span class="type-body-large">{{ t('auth.account') }}</span>
        <span v-if="connected" class="type-body-medium muted">
          {{ accountName || t('auth.connectedAccount') }}
          <template v-if="state?.expires_at"> · {{ t('auth.expires', { at: formatDate(state.expires_at, locale) }) }}</template>
        </span>
        <span v-else-if="needsReauth" class="type-body-medium error">{{ t('auth.needsReauth') }}</span>
        <span v-else-if="unavailable" class="type-body-medium muted">{{ unavailable }}</span>
        <span v-else class="type-body-medium muted">{{ t('auth.notConnected') }}</span>
        <span v-if="!connected && canSignIn && state?.client_name" class="type-body-small muted">{{ t('auth.consentApp', { name: state.client_name }) }}</span>
      </div>
      <div class="oauth-actions">
        <template v-if="!connected">
          <AppButton v-if="offersCode" variant="text" :disabled="!!device || start.isPending.value" @click="signIn('device')">{{ t('auth.signInCode') }}</AppButton>
          <AppButton :icon="icons.ExternalLink" :loading="start.isPending.value" :disabled="!canSignIn || !!device" @click="signIn('auto')">
            {{ needsReauth ? t('auth.reconnect') : t('auth.signIn') }}
          </AppButton>
        </template>
        <AppButton v-else variant="outlined" :loading="disconnect.isPending.value" @click="disconnect.mutate()">{{ t('auth.disconnect') }}</AppButton>
      </div>
    </div>

    <!-- A device sign-in waiting for the code to be confirmed on Civitai. -->
    <div v-if="device" class="device" role="status" aria-live="polite">
      <span class="type-body-medium">{{ t('auth.device.prompt') }}</span>
      <span class="code type-headline-small">{{ device.user_code }}</span>
      <a class="type-body-small link" :href="verificationUrl" target="_blank" rel="noopener noreferrer">{{ device.verification_uri }}</a>
      <ProgressBar :label="t('auth.device.waiting')" />
      <div class="device-actions">
        <span class="type-body-small muted">{{ t('auth.device.remaining', { time: remaining }) }}</span>
        <span class="device-buttons">
          <AppButton variant="text" :loading="cancelSession.isPending.value" @click="cancel">{{ t('common.cancel') }}</AppButton>
          <AppButton variant="tonal" :icon="icons.ExternalLink" @click="openVerification(verificationUrl)">{{ t('auth.device.open') }}</AppButton>
        </span>
      </div>
    </div>

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
    <p v-if="errorText && !device" class="type-body-small error">{{ errorText }}</p>

    <Divider />

    <!-- Manual API token: always available, with or without signing in. -->
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

    <ExpansionPanel v-model:open="advancedOpen" :icon="icons.KeyRound" :label="t('auth.advanced')" :supporting-text="t('auth.advancedHelp')">
      <div class="advanced">
        <TextField
          :model-value="settings.auth.civitai.oauth_client_id ?? ''"
          :label="t('auth.clientId')"
          :supporting-text="clientIdHelp"
          :disabled="clientIdLocked"
          @change="saveClientId($event)"
        />
      </div>
    </ExpansionPanel>
  </section>
</template>

<style scoped>
.civitai-auth { display: flex; flex-direction: column; gap: var(--app-space-3); }
.head { display: flex; align-items: center; gap: var(--app-space-2); }
.head h3 { margin: 0; }
.notice { display: flex; align-items: center; gap: var(--app-space-1); margin: 0; color: var(--md-sys-color-on-surface-variant); }
.oauth { display: flex; align-items: center; justify-content: space-between; gap: var(--app-space-4); flex-wrap: wrap; }
.oauth-text { display: flex; flex-direction: column; min-width: 0; }
.oauth-actions { display: flex; flex-wrap: wrap; gap: var(--app-space-2); }
.device {
  display: flex; flex-direction: column; gap: var(--app-space-2); padding: var(--app-space-4);
  border-radius: var(--md-sys-shape-corner-medium); background: var(--md-sys-color-surface-container-high);
}
.code { font-variant-numeric: tabular-nums; letter-spacing: 0.12em; color: var(--md-sys-color-primary); }
.link { color: var(--md-sys-color-primary); overflow-wrap: anywhere; }
.device-actions { display: flex; align-items: center; justify-content: space-between; gap: var(--app-space-2); flex-wrap: wrap; }
.device-buttons { display: flex; gap: var(--app-space-2); }
.method { display: flex; align-items: center; justify-content: space-between; gap: var(--app-space-4); flex-wrap: wrap; min-height: 56px; }
.advanced { display: flex; flex-direction: column; gap: var(--app-space-3); padding-block: var(--app-space-2); }
.error { color: var(--md-sys-color-error); margin: 0; }
</style>
