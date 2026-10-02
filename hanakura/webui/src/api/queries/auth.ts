import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query';
import { api, unwrap } from '@/api/client';
import { keys } from '@/api/queries/keys';
import type { S } from '@/api/types';

export type AuthMethod = 'manual' | 'oauth';

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

/** Begin an authorization; the caller sends the browser to the returned URL. */
export function useStartCivitaiAuth() {
  return useMutation({
    mutationFn: (returnTo?: string) => unwrap(api.POST('/api/v1/auth/civitai/start', { body: { return_to: returnTo ?? null } })),
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
