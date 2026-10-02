import { useInfiniteQuery, useMutation, useQuery } from '@tanstack/vue-query';
import { computed, type MaybeRefOrGetter, toValue } from 'vue';
import { api, unwrap } from '@/api/client';
import { keys } from '@/api/queries/keys';

export interface SearchParams {
  query: string;
  kind: string | null;
  base_model: string | null;
  sort: string | null;
}

export const useSources = () => useQuery({ queryKey: keys.sources, queryFn: () => unwrap(api.GET('/api/v1/sources')), staleTime: 60_000 });

/** Infinite search: each page carries an opaque cursor for the next. */
export function useModelSearch(source: MaybeRefOrGetter<string | null>, params: MaybeRefOrGetter<SearchParams>) {
  return useInfiniteQuery({
    queryKey: computed(() => keys.search(toValue(source) ?? '', { ...toValue(params) })),
    enabled: computed(() => !!toValue(source)),
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) => {
      const p = toValue(params);
      return unwrap(
        api.GET('/api/v1/sources/{source}/models', {
          params: {
            path: { source: toValue(source)! },
            query: { query: p.query, kind: p.kind ?? undefined, base_model: p.base_model ?? undefined, sort: p.sort ?? undefined, limit: 24, cursor: pageParam ?? undefined },
          },
        }),
      );
    },
    getNextPageParam: (last) => last.next_cursor ?? undefined,
    staleTime: 60_000,
  });
}

export function useModelDetail(source: MaybeRefOrGetter<string | null>, id: MaybeRefOrGetter<string | null>) {
  return useQuery({
    queryKey: computed(() => keys.model(toValue(source) ?? '', toValue(id) ?? '')),
    enabled: computed(() => !!toValue(source) && !!toValue(id)),
    queryFn: () => unwrap(api.GET('/api/v1/sources/{source}/models/{model_id}', { params: { path: { source: toValue(source)!, model_id: toValue(id)! } } })),
    staleTime: 120_000,
  });
}

export function useIdentify() {
  return useMutation({ mutationFn: (sha256: string) => unwrap(api.POST('/api/v1/sources/identify', { body: { sha256 } })) });
}
