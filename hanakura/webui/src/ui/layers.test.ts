import { mount } from '@vue/test-utils';
import { afterEach, describe, expect, it } from 'vitest';
import { defineComponent, h, nextTick, ref } from 'vue';
import AppDialog from '@/ui/AppDialog.vue';
import ImageViewer from '@/ui/ImageViewer.vue';
import { useLayer } from '@/ui/layers';

const press = (key: string) => document.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true }));
const items = [
  { src: 'a.png', alt: 'a' },
  { src: 'b.png', alt: 'b' },
  { src: 'c.png', alt: 'c' },
];

/** A dialog holding an image viewer, the way the model dialogs do. */
function nested(dialog = ref(true), viewer = ref(true)) {
  const index = ref(0);
  const Nested = defineComponent({
    setup: () => () =>
      h(AppDialog, { open: dialog.value, 'onUpdate:open': (v: boolean) => (dialog.value = v), title: 'Model' }, () =>
        h(ImageViewer, { open: viewer.value, 'onUpdate:open': (v: boolean) => (viewer.value = v), index: index.value, 'onUpdate:index': (v: number) => (index.value = v), items }),
      ),
  });
  return { Nested, dialog, viewer };
}

// Material's buttons need ElementInternals, which happy-dom lacks.
const global = { stubs: { IconButton: { props: ['label'], emits: ['click'], template: '<button type="button" :aria-label="label" @click="$emit(\'click\')" />' } } };

const mounted: { unmount: () => void }[] = [];
afterEach(() => {
  mounted.splice(0).forEach((w) => w.unmount());
  document.body.innerHTML = '';
});

describe('layers', () => {
  it('gives Escape to the topmost layer only', async () => {
    const { Nested, dialog, viewer } = nested();
    mounted.push(mount(Nested, { attachTo: document.body, global }));
    await nextTick();

    press('Escape');
    await nextTick();
    expect(viewer.value).toBe(false);
    expect(dialog.value).toBe(true);

    press('Escape');
    await nextTick();
    expect(dialog.value).toBe(false);
  });

  it("keeps Tab inside the viewer rather than the dialog's trap pulling it back", async () => {
    const { Nested } = nested();
    mounted.push(mount(Nested, { attachTo: document.body, global }));
    await nextTick();
    const viewer = document.querySelector<HTMLElement>('.viewer')!;
    const buttons = [...viewer.querySelectorAll<HTMLElement>('button')];
    buttons[buttons.length - 1].focus();
    press('Tab');
    expect(viewer.contains(document.activeElement)).toBe(true);
  });

  it('stops handing keys to a layer once it closes or its owner goes away', async () => {
    const seen: string[] = [];
    const active = ref(true);
    const Probe = defineComponent({
      setup() {
        useLayer(
          () => active.value,
          (e) => seen.push(e.key),
        );
        return () => null;
      },
    });
    const wrapper = mount(Probe);
    press('a');
    active.value = false;
    await nextTick();
    press('b');
    active.value = true;
    await nextTick();
    wrapper.unmount();
    press('c');
    expect(seen).toEqual(['a']);
  });

  it('leaves a key that a control inside the layer already handled', async () => {
    const seen: string[] = [];
    const Probe = defineComponent({
      setup() {
        useLayer(
          () => true,
          (e) => seen.push(e.key),
        );
        return () => null;
      },
    });
    mounted.push(mount(Probe));
    const event = new KeyboardEvent('keydown', { key: 'Escape', cancelable: true });
    event.preventDefault();
    document.dispatchEvent(event);
    expect(seen).toEqual([]);
  });
});

describe('ImageViewer', () => {
  const viewer = (props: Record<string, unknown> = {}) => {
    const wrapper = mount(ImageViewer, {
      attachTo: document.body,
      global,
      props: { open: true, index: 0, items, 'onUpdate:index': (v: number) => wrapper.setProps({ index: v }), 'onUpdate:open': (v: boolean) => wrapper.setProps({ open: v }), ...props },
    });
    mounted.push(wrapper);
    return wrapper;
  };
  const shown = () => document.querySelector<HTMLImageElement>('.viewer img')?.getAttribute('src');

  it('moves with the arrows, wrapping at either end, and jumps with Home and End', async () => {
    const wrapper = viewer();
    await nextTick();
    expect(shown()).toBe('a.png');
    press('ArrowLeft');
    await nextTick();
    expect(wrapper.props('index')).toBe(2);
    press('ArrowRight');
    await nextTick();
    expect(wrapper.props('index')).toBe(0);
    press('End');
    await nextTick();
    expect(wrapper.props('index')).toBe(2);
    press('Home');
    await nextTick();
    expect(wrapper.props('index')).toBe(0);
    expect(document.querySelector('.counter')?.textContent).toBe('1 / 3');
  });

  it('hides the arrows and the counter for a single image', async () => {
    viewer({ items: [items[0]] });
    await nextTick();
    expect(document.querySelector('.nav')).toBeNull();
    expect(document.querySelector('.counter')).toBeNull();
  });

  it('closes on a click beside the image but not on the image', async () => {
    const wrapper = viewer();
    await nextTick();
    document.querySelector<HTMLElement>('.viewer img')!.click();
    expect(wrapper.emitted('update:open')).toBeUndefined();
    document.querySelector<HTMLElement>('.stage')!.click();
    expect(wrapper.emitted('update:open')?.[0]).toEqual([false]);
  });

  it('asks its owner to reveal a blurred image instead of zooming it', async () => {
    const wrapper = viewer({ items: [{ src: 'x.png', alt: 'x', blurred: true }] });
    await nextTick();
    const img = document.querySelector<HTMLElement>('.viewer img')!;
    expect(img.classList.contains('blurred')).toBe(true);
    img.click();
    expect(wrapper.emitted('reveal')?.[0]).toEqual([0]);
  });

  it('closes itself when the list it shows becomes empty', async () => {
    const wrapper = viewer();
    await wrapper.setProps({ items: [] });
    expect(wrapper.emitted('update:open')?.[0]).toEqual([false]);
  });
});
