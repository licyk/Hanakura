import { computed, type Ref } from 'vue';
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query';
import { api, unwrap } from '@/api/client';
import { keys } from '@/api/queries/keys';
import type { S } from '@/api/types';

export type AuthMethod = 'manual' | 'oauth';
export type SignInFlow = 'auto' | 'browser' | 'device';
export type LoginSession = S['LoginSession'];

/** Which Civitai credential is in use. Never carries a token. */
export const useCivitaiAuth = () =>
  useQuery({ queryKey: keys.civitaiAuth, queryFn: () => unwrap(api.GET('/api/v1/auth/civitai/status')), refetchOnWindowFocus: true });

function refresh(qc: ReturnType<typeof useQueryClient>) {
  return (status: S['CivitaiAuthStatus']) => {
    qc.setQueryData(keys.civitaiAuth, status);
    qc.invalidateQueries({ queryKey: keys.settings });
    qc.invalidateQueries({ queryKey: keys.sources });
  };
}

/** After an account was connected: the status, and every query whose answer may depend on the account. */
export function invalidateAfterSignIn(qc: ReturnType<typeof useQueryClient>) {
  qc.invalidateQueries({ queryKey: keys.civitaiAuth });
  qc.invalidateQueries({ queryKey: keys.settings });
  qc.invalidateQueries({ queryKey: keys.sources });
}

/** Begin a sign-in. A browser one returns Civitai's consent page; a device one, a code to confirm there. */
export function useStartCivitaiAuth() {
  return useMutation({
    mutationFn: ({ returnTo, flow = 'auto' }: { returnTo?: string; flow?: SignInFlow }) =>
      unwrap(api.POST('/api/v1/auth/civitai/start', { body: { return_to: returnTo ?? null, flow } })),
  });
}

const ENDED = new Set(['connected', 'denied', 'expired', 'cancelled', 'failed']);
export const sessionEnded = (session: LoginSession | undefined) => !!session && ENDED.has(session.status);

/**
 * One sign-in's state while it waits. The server does the polling of Civitai, so asking here
 * costs Civitai nothing; asking stops once the sign-in has ended, or when the id is cleared.
 */
export function useCivitaiSession(id: Ref<string | null>) {
  return useQuery({
    queryKey: computed(() => [...keys.civitaiAuth, 'session', id.value] as const),
    queryFn: () => unwrap(api.GET('/api/v1/auth/civitai/sessions/{session_id}', { params: { path: { session_id: id.value ?? '' } } })),
    enabled: computed(() => !!id.value),
    refetchInterval: (query) => (sessionEnded(query.state.data) ? false : 2000),
    refetchOnWindowFocus: false,
    retry: false,
  });
}

export function useCancelCivitaiSession() {
  return useMutation({
    mutationFn: (id: string) => unwrap(api.POST('/api/v1/auth/civitai/sessions/{session_id}/cancel', { params: { path: { session_id: id } } })),
  });
}

export function useDisconnectCivitai() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: () => unwrap(api.POST('/api/v1/auth/civitai/disconnect')), onSuccess: refresh(qc) });
}

export function useSetCivitaiMethod() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: (method: AuthMethod) => unwrap(api.POST('/api/v1/auth/civitai/method', { body: { method } })), onSuccess: refresh(qc) });
}
