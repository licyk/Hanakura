import { mount } from '@vue/test-utils';
import { afterEach, describe, expect, it, vi } from 'vitest';
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
  // happy-dom runs no transitions; with reduced motion a slide lands at once, as it does for such users.
  const reduceMotion = () => vi.spyOn(window, 'matchMedia').mockImplementation((query: string) => ({ matches: query.includes('reduce') }) as MediaQueryList);
  const settled = () => new Promise((resolve) => setTimeout(resolve));
  afterEach(() => vi.restoreAllMocks());

  it('moves with the arrows, wrapping at either end, and jumps with Home and End', async () => {
    reduceMotion();
    const wrapper = viewer();
    await nextTick();
    expect(shown()).toBe('a.png');
    press('ArrowLeft');
    await settled();
    expect(wrapper.props('index')).toBe(2);
    press('ArrowRight');
    await settled();
    expect(wrapper.props('index')).toBe(0);
    press('End');
    await nextTick();
    expect(wrapper.props('index')).toBe(2);
    press('Home');
    await nextTick();
    expect(wrapper.props('index')).toBe(0);
    expect(document.querySelector('.counter')?.textContent).toBe('1 / 3');
  });

  it('slides to the neighbour, and a press during a slide lands it and steps on', async () => {
    const wrapper = viewer();
    await nextTick();
    press('ArrowRight');
    await nextTick();
    // The page is on its way out; the step comes when it has left.
    expect(document.querySelector('.slide')?.classList.contains('swipe-out')).toBe(true);
    expect(wrapper.props('index')).toBe(0);
    press('ArrowRight');
    await nextTick();
    expect(wrapper.props('index')).toBe(2);
    expect(document.querySelector('.slide')?.classList.contains('swipe-out')).toBe(false);
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

  /** Lays the stage out at ``w``×``h`` with 64 px gutters, then loads an image of ``iw``×``ih``. */
  async function layOut(w: number, h: number, iw: number, ih: number) {
    const size = (el: Element, width: number, height: number) => {
      Object.defineProperty(el, 'clientWidth', { configurable: true, value: width });
      Object.defineProperty(el, 'clientHeight', { configurable: true, value: height });
    };
    size(document.querySelector('.stage')!, w, h);
    size(document.querySelector('.fit-area.measure')!, w - 128, h - 128);
    const img = document.querySelector<HTMLImageElement>('.viewer img')!;
    Object.defineProperty(img, 'naturalWidth', { configurable: true, value: iw });
    Object.defineProperty(img, 'naturalHeight', { configurable: true, value: ih });
    img.dispatchEvent(new Event('load'));
    await nextTick();
    return img;
  }
  /** Where the image is drawn, to the pixel: [left, top, width, height]. */
  const placed = (img: HTMLImageElement) => {
    const [x, y] = [...img.style.transform.matchAll(/-?[\d.]+/g)].map((m) => Math.round(Number(m[0])));
    return [x, y, Math.round(parseFloat(img.style.width)), Math.round(parseFloat(img.style.height))];
  };
  const pointer = (el: Element, type: string, x: number, y: number) =>
    el.dispatchEvent(new PointerEvent(type, { pointerId: 1, pointerType: 'mouse', button: 0, clientX: x, clientY: y, bubbles: true }));

  it('fits a tall image in a wide window by its height, centred', async () => {
    viewer();
    await nextTick();
    const img = await layOut(1600, 900, 800, 1600);
    // 772 / 1600 of its size: as tall as the window less the gutters, no wider than that allows.
    expect(placed(img)).toEqual([607, 64, 386, 772]);
  });

  it('zooms to the actual size on a double-click and pans with a mouse drag', async () => {
    const wrapper = viewer();
    await nextTick();
    const img = await layOut(1600, 900, 800, 1600);
    img.dispatchEvent(new MouseEvent('dblclick', { clientX: 800, clientY: 450, bubbles: true }));
    await nextTick();
    // The point under the pointer stays put: the image's middle, at the stage's middle.
    expect(placed(img)).toEqual([400, -350, 800, 1600]);

    pointer(img, 'pointerdown', 800, 450);
    pointer(img, 'pointermove', 850, 350);
    pointer(img, 'pointerup', 850, 350);
    img.click();
    await nextTick();
    expect(placed(img)).toEqual([450, -450, 800, 1600]);
    // The click that ends a drag neither closes the viewer nor moves to another image.
    expect(wrapper.emitted('update:open')).toBeUndefined();
    expect(wrapper.props('index')).toBe(0);

    press('0');
    await nextTick();
    expect(placed(img)).toEqual([607, 64, 386, 772]);
  });

  it('zooms with the wheel and the keys', async () => {
    viewer();
    await nextTick();
    const img = await layOut(1600, 900, 800, 1600);
    document.querySelector('.stage')!.dispatchEvent(new WheelEvent('wheel', { deltaY: -200, clientX: 800, clientY: 450, bubbles: true, cancelable: true }));
    await nextTick();
    expect(placed(img)[3]).toBeGreaterThan(772);
    press('0');
    press('+');
    await nextTick();
    expect(placed(img)[3]).toBe(965);
  });

  it('moves to the next image when a fitted one is dragged sideways', async () => {
    reduceMotion();
    const wrapper = viewer();
    await nextTick();
    const img = await layOut(1600, 900, 800, 1600);
    pointer(img, 'pointerdown', 900, 450);
    pointer(img, 'pointermove', 700, 455);
    pointer(img, 'pointerup', 700, 455);
    img.click();
    await settled();
    expect(wrapper.props('index')).toBe(1);
    expect(wrapper.emitted('update:open')).toBeUndefined();
  });

  it('closes on a click beside the image after a drag only when the click is a new one', async () => {
    const wrapper = viewer();
    await nextTick();
    const stage = document.querySelector<HTMLElement>('.stage')!;
    pointer(stage, 'pointerdown', 10, 10);
    pointer(stage, 'pointermove', 10, 200);
    pointer(stage, 'pointerup', 10, 200);
    stage.click();
    expect(wrapper.emitted('update:open')).toBeUndefined();
    pointer(stage, 'pointerdown', 10, 10);
    pointer(stage, 'pointerup', 10, 10);
    stage.click();
    expect(wrapper.emitted('update:open')?.[0]).toEqual([false]);
  });
});
