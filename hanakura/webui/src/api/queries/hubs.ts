import { useInfiniteQuery, useQuery } from '@tanstack/vue-query';
import { computed, type MaybeRefOrGetter, toValue } from 'vue';
import { api, unwrap } from '@/api/client';
import { keys } from '@/api/queries/keys';

export const useHubs = () => useQuery({ queryKey: keys.hubs, queryFn: () => unwrap(api.GET('/api/v1/hubs')), staleTime: 60_000 });

export function useRepoSearch(hub: MaybeRefOrGetter<string>, query: MaybeRefOrGetter<string>, sort: MaybeRefOrGetter<string | null>) {
  return useInfiniteQuery({
    queryKey: computed(() => keys.hubSearch(toValue(hub), { query: toValue(query), sort: toValue(sort) })),
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) =>
      unwrap(
        api.GET('/api/v1/hubs/{hub}/repos', {
          params: { path: { hub: toValue(hub) }, query: { query: toValue(query), sort: toValue(sort) ?? undefined, limit: 30, cursor: pageParam ?? undefined } },
        }),
      ),
    getNextPageParam: (last) => last.next_cursor ?? undefined,
    staleTime: 60_000,
  });
}

export function useRepo(hub: MaybeRefOrGetter<string>, repoId: MaybeRefOrGetter<string | null>, revision: MaybeRefOrGetter<string | null>) {
  return useQuery({
    queryKey: computed(() => keys.repo(toValue(hub), toValue(repoId) ?? '', toValue(revision))),
    enabled: computed(() => !!toValue(repoId)),
    queryFn: () =>
      unwrap(
        api.GET('/api/v1/hubs/{hub}/repos/{repo_id}', {
          params: { path: { hub: toValue(hub), repo_id: toValue(repoId)! }, query: { revision: toValue(revision) ?? undefined } },
        }),
      ),
    staleTime: 120_000,
    retry: false,
  });
}
