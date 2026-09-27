/**
 * What a top-level view looked like when the user left it, held in memory only.
 *
 * The views are kept alive, so their own state — a search, an open folder, a selected tab, an
 * expanded panel — survives switching to another view. Two things do not survive on their own and
 * are kept here: where each view's URL last pointed, so its navigation link brings it back as it
 * was, and scroll positions, which a browser resets when an element leaves the document. Nothing
 * here is written to storage: a reload starts every view afresh.
 */
import { reactive, watch } from 'vue';
import { useRoute, useRouter, type LocationQuery, type LocationQueryRaw, type Router } from 'vue-router';

const lastLocations = reactive(new Map<string, string>());

/** Record every location reached, by its path. */
export function trackLocations(router: Router) {
  router.afterEach((to) => lastLocations.set(to.path, to.fullPath));
}

/** Where the view at ``path`` was left, query included; the bare path for one never visited. */
export function lastLocation(path: string): string {
  return lastLocations.get(path) ?? path;
}

/**
 * A kept-alive view's link to its URL query. Only the view on screen follows or writes the URL: a
 * view waiting in the background must not take another view's query for its own. A change it makes
 * meanwhile — a source disabled in the settings, say — is recorded as where it now is, so going back
 * to it does not bring the old query back with it.
 */
export function useViewQuery() {
  const route = useRoute();
  const router = useRouter();
  const name = route.name;
  const path = route.path;
  const shown = () => route.name === name;

  function replace(query: LocationQueryRaw) {
    if (shown()) router.replace({ query });
    else lastLocations.set(path, router.resolve({ path, query }).fullPath);
  }
  function onChange(callback: (query: LocationQuery) => void) {
    watch(
      () => route.query,
      (query) => {
        if (shown()) callback(query);
      },
    );
  }
  return { query: route.query, replace, onChange };
}

export type ScrollSnapshot = [element: Element, top: number, left: number][];

/** Every scrolled element under ``root``, ``root`` included. */
export function captureScroll(root: Element): ScrollSnapshot {
  const snapshot: ScrollSnapshot = [];
  for (const el of [root, ...root.querySelectorAll('*')]) if (el.scrollTop || el.scrollLeft) snapshot.push([el, el.scrollTop, el.scrollLeft]);
  return snapshot;
}

export function restoreScroll(snapshot: ScrollSnapshot) {
  for (const [el, top, left] of snapshot) {
    el.scrollTop = top;
    el.scrollLeft = left;
  }
}
