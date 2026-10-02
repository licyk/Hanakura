import { flushPromises, mount } from '@vue/test-utils';
import { describe, expect, it } from 'vitest';
import { KeepAlive, defineComponent, h, ref } from 'vue';
import { RouterView, createMemoryHistory, createRouter, type LocationQuery } from 'vue-router';
import { captureScroll, lastLocation, restoreScroll, trackLocations, useViewQuery } from '@/viewState';

describe('view state', () => {
  it('keeps a background view off the URL and remembers where it was left', async () => {
    const seen: LocationQuery[] = [];
    const count = ref(0);
    let replace: ReturnType<typeof useViewQuery>['replace'] = () => undefined;
    const Counted = defineComponent({
      setup() {
        const route = useViewQuery();
        route.onChange((q) => seen.push(q));
        replace = route.replace;
        return () => h('p', `a ${count.value}`);
      },
    });
    const Other = defineComponent({ render: () => h('p', 'b') });
    const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/a', name: 'a', component: Counted }, { path: '/b', name: 'b', component: Other }] });
    trackLocations(router);
    const App = defineComponent({ render: () => h(RouterView, null, { default: ({ Component }: { Component: unknown }) => h(KeepAlive, null, [Component ? h(Component as never) : null]) }) });

    await router.push('/a?x=1');
    const wrapper = mount(App, { global: { plugins: [router] } });
    await flushPromises();
    await router.push('/b?y=2');
    await flushPromises();
    expect(seen).toEqual([]);

    // A change made while hidden moves the remembered place, not the URL on screen.
    replace({ x: '3' });
    await flushPromises();
    expect(router.currentRoute.value.fullPath).toBe('/b?y=2');
    expect(lastLocation('/a')).toBe('/a?x=3');
    expect(lastLocation('/b')).toBe('/b?y=2');
    expect(lastLocation('/never')).toBe('/never');

    await router.push(lastLocation('/a'));
    await flushPromises();
    expect(seen.map((q) => q.x)).toEqual(['3']);
    replace({ x: '4' });
    await flushPromises();
    expect(router.currentRoute.value.fullPath).toBe('/a?x=4');
    wrapper.unmount();
  });

  it('captures scrolled elements and puts them back', () => {
    const root = document.createElement('div');
    const inner = document.createElement('div');
    const still = document.createElement('div');
    root.append(inner, still);
    root.scrollTop = 120;
    inner.scrollLeft = 40;
    const snapshot = captureScroll(root);
    expect(snapshot.map(([el]) => el)).toEqual([root, inner]);
    root.scrollTop = 0;
    inner.scrollLeft = 0;
    restoreScroll(snapshot);
    expect([root.scrollTop, inner.scrollLeft]).toEqual([120, 40]);
  });
});
