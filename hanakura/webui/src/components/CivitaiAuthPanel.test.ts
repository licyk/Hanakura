import { flushPromises, mount } from '@vue/test-utils';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ref } from 'vue';
import CivitaiAuthPanel from '@/components/CivitaiAuthPanel.vue';
import type { S, SettingsView } from '@/api/types';
import { AppButton, ExpansionPanel, TextField, useSnackbar } from '@/ui';

const mocks = vi.hoisted(() => ({
  status: null as unknown as { value: Partial<S['CivitaiAuthStatus']> },
  session: null as unknown as { value: Partial<S['LoginSession']> | undefined },
  sessionId: null as unknown as { value: string | null },
  start: vi.fn(),
  cancel: vi.fn(),
  invalidate: vi.fn(),
  replace: vi.fn(),
  query: {} as Record<string, string>,
}));

vi.mock('@/api/queries/auth', async () => {
  const { ref: vueRef } = await import('vue');
  mocks.status = vueRef({});
  mocks.session = vueRef(undefined);
  return {
    useCivitaiAuth: () => ({ data: mocks.status, refetch: vi.fn() }),
    useStartCivitaiAuth: () => ({ mutateAsync: mocks.start, isPending: vueRef(false) }),
    useCancelCivitaiSession: () => ({ mutate: mocks.cancel, isPending: vueRef(false) }),
    useCivitaiSession: (id: { value: string | null }) => {
      mocks.sessionId = id;
      return { data: mocks.session };
    },
    useDisconnectCivitai: () => ({ mutate: vi.fn(), isPending: vueRef(false) }),
    useSetCivitaiMethod: () => ({ mutate: vi.fn() }),
    invalidateAfterSignIn: mocks.invalidate,
    sessionEnded: (s?: { status: string }) => !!s && ['connected', 'denied', 'expired', 'cancelled', 'failed'].includes(s.status),
  };
});
vi.mock('@/api/queries/app', () => ({ useUpdateSettings: () => ({ mutate: vi.fn() }) }));
vi.mock('@tanstack/vue-query', () => ({ useQueryClient: () => ({}) }));
vi.mock('vue-router', () => ({ useRoute: () => ({ query: mocks.query }), useRouter: () => ({ replace: mocks.replace }) }));
vi.mock('@/i18n', () => ({ useI18n: () => ({ t: (key: string) => key, locale: ref('en') }) }));

const settings = { pinned: [], env_overrides: [], auth: { civitai: { oauth_client_id: null } }, sources: { civitai: { token_configured: false } } } as unknown as SettingsView;
const baseStatus = { method: 'manual', effective_method: 'manual', oauth_state: 'not_connected', oauth_enabled: true, env_override: false, manual_token_configured: false } as const;

function panel(props: { settings?: SettingsView } = {}) {
  return mount(CivitaiAuthPanel, {
    props: { settings: props.settings ?? settings },
    global: { renderStubDefaultSlot: true, stubs: { AppButton: true, TokenField: true, SegmentedButton: true, AppIcon: true, Badge: true, Divider: true, ProgressBar: true, TextField: true, ExpansionPanel: { template: '<div><slot /></div>', props: ['open'] } } },
  });
}

const button = (wrapper: ReturnType<typeof panel>, label: string) => wrapper.findAllComponents(AppButton).find((b) => b.text() === label)!;

describe('signing in with Civitai', () => {
  const assign = vi.fn();
  const open = vi.fn();
  const close = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    mocks.query = {};
    mocks.session.value = undefined;
    vi.stubGlobal('location', { assign });
    vi.stubGlobal('open', open);
    vi.stubGlobal('close', close);
  });
  afterEach(() => vi.unstubAllGlobals());

  it('explains why it cannot sign in and opens the advanced settings for an OAuth application', () => {
    mocks.status.value = { ...baseStatus, oauth_configured: false, flows: [], unavailable_reason: 'no_client' };
    const wrapper = panel();
    expect(button(wrapper, 'auth.signIn').props('disabled')).toBe(true);
    expect(wrapper.text()).toContain('auth.unavailable.no_client');
    expect(wrapper.findComponent(ExpansionPanel).props('open')).toBe(true);
    wrapper.unmount();
  });

  it('opens Civitai in a new tab and follows the sign-in from here', async () => {
    mocks.status.value = { ...baseStatus, oauth_configured: true, flows: ['browser'], client_source: 'bundled', client_name: 'Civitai ComfyNodes', unavailable_reason: null };
    mocks.start.mockResolvedValue({ flow: 'browser', authorization_url: 'https://auth.civitai.com/authorize?x', session_id: 's' });
    const tab = { opener: {}, location: { href: '' }, close: vi.fn() };
    open.mockReturnValue(tab);
    const wrapper = panel();
    expect(wrapper.text()).toContain('auth.consentApp');
    expect(button(wrapper, 'auth.signInCode')).toBeUndefined();
    // The built-in client needs no client id, so the advanced settings stay closed.
    expect(wrapper.findComponent(ExpansionPanel).props('open')).toBe(false);
    expect(button(wrapper, 'auth.signIn').props('disabled')).toBe(false);
    button(wrapper, 'auth.signIn').vm.$emit('click');
    // Opened while the click is handled, before the server answers, or a browser blocks it.
    expect(open).toHaveBeenCalledWith('', '_blank');
    await flushPromises();
    expect(mocks.start).toHaveBeenCalledWith({ returnTo: '/#/settings?civitai_tab=1', flow: 'auto' });
    expect(tab.opener).toBeNull();
    expect(tab.location.href).toBe('https://auth.civitai.com/authorize?x');
    expect(assign).not.toHaveBeenCalled();
    expect(mocks.sessionId.value).toBe('s');
    mocks.session.value = { id: 's', flow: 'browser', status: 'pending', expires_at: new Date(Date.now() + 300_000).toISOString() };
    await flushPromises();
    expect(wrapper.text()).toContain('auth.browser.prompt');
    expect(button(wrapper, 'auth.signIn').props('disabled')).toBe(true);
    open.mockClear();
    button(wrapper, 'auth.device.open').vm.$emit('click');
    expect(open).toHaveBeenCalledTimes(1);
    mocks.session.value = { id: 's', flow: 'browser', status: 'connected', expires_at: new Date().toISOString() };
    await flushPromises();
    expect(mocks.invalidate).toHaveBeenCalled();
    expect(mocks.sessionId.value).toBeNull();
    expect(useSnackbar().state.queue.at(-1)?.text).toBe('auth.connected');
    expect(wrapper.text()).not.toContain('auth.browser.prompt');
    wrapper.unmount();
  });

  it('sends this tab to Civitai when the browser blocks a new one', async () => {
    mocks.status.value = { ...baseStatus, oauth_configured: true, flows: ['browser'] };
    mocks.start.mockResolvedValue({ flow: 'browser', authorization_url: 'https://auth.civitai.com/authorize?x', session_id: 's' });
    open.mockReturnValue(null);
    const wrapper = panel();
    button(wrapper, 'auth.signIn').vm.$emit('click');
    await flushPromises();
    expect(mocks.start).toHaveBeenCalledWith({ returnTo: '/#/settings', flow: 'auto' });
    expect(assign).toHaveBeenCalledWith('https://auth.civitai.com/authorize?x');
    wrapper.unmount();
  });

  it('closes the new tab when the sign-in cannot begin', async () => {
    mocks.status.value = { ...baseStatus, oauth_configured: true, flows: ['browser'] };
    mocks.start.mockRejectedValue(new Error('No client'));
    const tab = { opener: {}, location: { href: '' }, close: vi.fn() };
    open.mockReturnValue(tab);
    const wrapper = panel();
    button(wrapper, 'auth.signIn').vm.$emit('click');
    await flushPromises();
    expect(tab.close).toHaveBeenCalled();
    expect(useSnackbar().state.queue.at(-1)?.text).toBe('No client');
    wrapper.unmount();
  });

  it('shows the code of a device sign-in, and cancels it', async () => {
    mocks.status.value = { ...baseStatus, oauth_configured: true, flows: ['browser', 'device'] };
    mocks.start.mockResolvedValue({ flow: 'device', authorization_url: 'https://auth.civitai.com/login/oauth/device?code=ABCD', session_id: 'dev-1' });
    const tab = { opener: {}, location: { href: '' } };
    open.mockReturnValue(tab);
    const wrapper = panel();
    button(wrapper, 'auth.signInCode').vm.$emit('click');
    await flushPromises();
    expect(mocks.start).toHaveBeenCalledWith({ returnTo: '/#/settings?civitai_tab=1', flow: 'device' });
    expect(mocks.sessionId.value).toBe('dev-1');
    expect(tab.location.href).toBe('https://auth.civitai.com/login/oauth/device?code=ABCD');
    mocks.session.value = {
      id: 'dev-1',
      flow: 'device',
      status: 'pending',
      user_code: 'ABCD-EFGH',
      verification_uri: 'https://auth.civitai.com/login/oauth/device',
      verification_uri_complete: 'https://auth.civitai.com/login/oauth/device?code=ABCD-EFGH',
      expires_at: new Date(Date.now() + 125_000).toISOString(),
    };
    await flushPromises();
    expect(wrapper.text()).toContain('ABCD-EFGH');
    // The new tab gets no handle on this window.
    expect(tab.opener).toBeNull();
    expect(wrapper.find('a').attributes()).toMatchObject({ target: '_blank', rel: 'noopener noreferrer' });
    expect(button(wrapper, 'auth.signIn').props('disabled')).toBe(true);
    button(wrapper, 'common.cancel').vm.$emit('click');
    expect(mocks.cancel).toHaveBeenCalledWith('dev-1', expect.anything());
    const callbacks = mocks.cancel.mock.calls.at(-1)![1];
    callbacks.onError(new Error('Network unavailable'));
    expect(mocks.sessionId.value).toBe('dev-1');
    expect(useSnackbar().state.queue.at(-1)?.text).toBe('Network unavailable');
    callbacks.onSuccess();
    expect(mocks.sessionId.value).toBeNull();
    wrapper.unmount();
  });

  it('offers a link when the browser blocks the new tab', async () => {
    mocks.status.value = { ...baseStatus, oauth_configured: true, flows: ['device'] };
    mocks.start.mockResolvedValue({ flow: 'device', authorization_url: 'https://auth.civitai.com/login/oauth/device', session_id: 'dev-2' });
    open.mockReturnValue(null);
    const wrapper = panel();
    button(wrapper, 'auth.signIn').vm.$emit('click');
    await flushPromises();
    expect(useSnackbar().state.queue.at(-1)?.text).toBe('auth.device.blocked');
    wrapper.unmount();
  });

  it('refreshes the account once a device sign-in connects, and stops asking', async () => {
    mocks.status.value = { ...baseStatus, oauth_configured: true, flows: ['device'] };
    mocks.start.mockResolvedValue({ flow: 'device', authorization_url: 'https://auth.civitai.com/login/oauth/device', session_id: 'dev-3' });
    open.mockReturnValue({ opener: null, location: { href: '' } });
    const wrapper = panel();
    button(wrapper, 'auth.signIn').vm.$emit('click');
    await flushPromises();
    mocks.session.value = { id: 'dev-3', flow: 'device', status: 'connected', expires_at: new Date().toISOString() };
    await flushPromises();
    expect(mocks.invalidate).toHaveBeenCalled();
    expect(mocks.sessionId.value).toBeNull();
    expect(useSnackbar().state.queue.at(-1)?.text).toBe('auth.connected');
    wrapper.unmount();
  });

  it('explains a server the built-in sign-in cannot return to', () => {
    mocks.status.value = { ...baseStatus, oauth_configured: true, flows: [], client_source: 'bundled', client_name: 'Civitai ComfyNodes', unavailable_reason: 'callback_unsupported' };
    const wrapper = panel();
    expect(button(wrapper, 'auth.signIn').props('disabled')).toBe(true);
    expect(wrapper.text()).toContain('auth.unavailable.callback_unsupported');
    expect(wrapper.text()).not.toContain('auth.consentApp');
    wrapper.unmount();
  });

  it.each(['denied', 'insufficient_scope'])('says why a returning sign-in failed (%s), and cleans the address', (reason) => {
    mocks.status.value = { ...baseStatus, oauth_configured: true, flows: ['browser'] };
    mocks.query = { civitai: 'error', civitai_reason: reason };
    const wrapper = panel();
    expect(useSnackbar().state.queue.at(-1)?.text).toBe(`auth.reasons.${reason}`);
    expect(mocks.replace).toHaveBeenCalledWith({ query: { civitai: undefined, civitai_reason: undefined, civitai_tab: undefined } });
    expect(close).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it('closes the tab a sign-in opened once Civitai sends it back', () => {
    mocks.status.value = { ...baseStatus, oauth_configured: true, flows: ['browser'] };
    mocks.query = { civitai_tab: '1', civitai: 'connected' };
    const wrapper = panel();
    expect(useSnackbar().state.queue.at(-1)?.text).toBe('auth.connected');
    expect(mocks.replace).toHaveBeenCalledWith({ query: { civitai: undefined, civitai_reason: undefined, civitai_tab: undefined } });
    expect(close).toHaveBeenCalled();
    wrapper.unmount();
  });

  it('locks a client id the host application pinned', () => {
    mocks.status.value = { ...baseStatus, oauth_configured: true, flows: ['browser'] };
    const wrapper = panel({ settings: { ...settings, pinned: ['auth.civitai.oauth_client_id'] } as SettingsView });
    expect(wrapper.findComponent(TextField).props()).toMatchObject({ disabled: true, supportingText: 'settings.pinned' });
    wrapper.unmount();
  });
});
