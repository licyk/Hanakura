import { flushPromises, mount } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { DownloadJob } from '@/api/types';
import DownloadItem from '@/components/DownloadItem.vue';
import { IconButton, useSnackbar } from '@/ui';

const mocks = vi.hoisted(() => ({ push: vi.fn(), locate: vi.fn(), store: { drawerOpen: true, progress: new Map() } }));
vi.mock('vue-router', () => ({ useRouter: () => ({ push: mocks.push }) }));
vi.mock('@/api/queries/downloads', () => ({ useJobAction: () => ({ mutate: vi.fn() }), useRemoveJob: () => ({ mutate: vi.fn() }) }));
vi.mock('@/api/queries/library', () => ({ locatePath: mocks.locate }));
vi.mock('@/stores/downloads', () => ({ useDownloadsStore: () => mocks.store }));
vi.mock('@/i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }));

function item(job: Partial<DownloadJob>) {
  const full = {
    id: 1,
    runner: 'http',
    title: 'model.safetensors',
    state: 'completed',
    dest_dir: '/models/loras',
    rel_dir: 'loras',
    bytes_done: 10,
    total_bytes: 10,
    speed: 0,
    can_pause: true,
    ...job,
  } as DownloadJob;
  return mount(DownloadItem, { props: { job: full }, global: { stubs: { IconButton: true, ProgressBar: true, AppIcon: true } } });
}

const folderButton = (wrapper: ReturnType<typeof item>) => wrapper.findAllComponents(IconButton).find((b) => b.props('label') === 'downloads.openFolder')!;

describe('a finished download', () => {
  beforeEach(() => {
    mocks.push.mockReset();
    mocks.locate.mockReset();
    mocks.store.drawerOpen = true;
  });

  it('opens the folder it landed in without asking the server when it knows the root', async () => {
    const wrapper = item({ root_id: 'comfy', final_path: '/models/loras/model.safetensors' });
    folderButton(wrapper).vm.$emit('click');
    await flushPromises();
    expect(mocks.locate).not.toHaveBeenCalled();
    expect(mocks.push).toHaveBeenCalledWith({ path: '/library', query: { root: 'comfy', path: 'loras' } });
    expect(mocks.store.drawerOpen).toBe(false);
    wrapper.unmount();
  });

  it('asks the server which root holds an absolute destination folder', async () => {
    mocks.locate.mockResolvedValue({ root_id: 'found', path: '' });
    const wrapper = item({ root_id: null });
    folderButton(wrapper).vm.$emit('click');
    await flushPromises();
    expect(mocks.locate).toHaveBeenCalledWith('/models/loras');
    expect(mocks.push).toHaveBeenCalledWith({ path: '/library', query: { root: 'found', path: undefined } });
    wrapper.unmount();
  });

  it('says so rather than navigating when the folder is outside every root', async () => {
    mocks.locate.mockRejectedValue(new Error('not inside any model root'));
    const snackbar = useSnackbar();
    const wrapper = item({ root_id: null, dest_dir: '/tmp/elsewhere' });
    folderButton(wrapper).vm.$emit('click');
    await flushPromises();
    expect(mocks.push).not.toHaveBeenCalled();
    expect(snackbar.state.queue.at(-1)?.text).toBe('downloads.openFolderFailed');
    wrapper.unmount();
  });

  it('offers no folder button while the download is still running', () => {
    const wrapper = item({ state: 'running', root_id: 'comfy' });
    expect(folderButton(wrapper)).toBeUndefined();
    wrapper.unmount();
  });
});
