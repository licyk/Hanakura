<script setup lang="ts">
import { useQueryClient } from '@tanstack/vue-query';
import { computed, onBeforeUnmount, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { previewUrl, saveFile } from '@/api/client';
import { COMBINED_VIEW_ID, keys } from '@/api/queries/keys';
import { useCombinedEntries, useEntries, useLibraryMutations, useRoots, useTree } from '@/api/queries/library';
import { useMeta } from '@/api/queries/app';
import type { FolderEntry, ModelEntry, PathRef, TreeNode } from '@/api/types';
import FileDropZone, { type DroppedFile } from '@/components/FileDropZone.vue';
import FolderTree from '@/components/FolderTree.vue';
import ModelCard from '@/components/ModelCard.vue';
import ModelGrid from '@/components/ModelGrid.vue';
import ModelInfoDialog from '@/components/ModelInfoDialog.vue';
import MoveDialog from '@/components/MoveDialog.vue';
import RenameDialog from '@/components/RenameDialog.vue';
import RootDialog from '@/components/RootDialog.vue';
import { fileExtensionLabel, formatBytes, pathSegments } from '@/format';
import { useI18n } from '@/i18n';
import { useDownloadsStore } from '@/stores/downloads';
import { usePreferencesStore } from '@/stores/preferences';
import { useUploadsStore } from '@/stores/uploads';
import { useSettings } from '@/api/queries/app';
import {
  AppButton,
  AppDialog,
  AppIcon,
  AppMenu,
  Breadcrumbs,
  Checkbox,
  ConfirmDialog,
  EmptyState,
  IconButton,
  PathField,
  PathText,
  SegmentedButton,
  SelectField,
  Skeleton,
  TextField,
  icons,
  type MenuItem,
  useSnackbar,
} from '@/ui';

const { t, kindLabel } = useI18n();
const route = useRoute();
const router = useRouter();
const qc = useQueryClient();
const prefs = usePreferencesStore();
const uploads = useUploadsStore();
const downloadsStore = useDownloadsStore();
const snackbar = useSnackbar();
const settings = useSettings();
const meta = useMeta();
const roots = useRoots();
const m = useLibraryMutations();

const str = (v: unknown) => (typeof v === 'string' ? v : null);
const rootId = ref<string | null>(str(route.query.root) ?? prefs.prefs.lastRoot);
const path = ref(str(route.query.path) ?? '');
const kind = ref<string | null>(null);
const direction = ref(1);

/**
 * A root with no kind hint holds a whole model directory; one with a hint is dedicated to a
 * single kind. An embedding host seeds both, so the complete directory leads the list and is
 * what this view opens on. Roots keep their configured order otherwise.
 */
const sortedRoots = computed(() => {
  const list = roots.data.value ?? [];
  return [...list.filter((r) => !r.kind), ...list.filter((r) => r.kind)];
});

/**
 * "All folders" lists the top level of every root side by side. When library.combined_view is on
 * it leads the root list, ahead of even the whole model directory, and is what the view opens on.
 */
const combinedEnabled = computed(() => settings.data.value?.library.combined_view === true);
const isCombined = computed(() => rootId.value === COMBINED_VIEW_ID);

watch(
  [sortedRoots, combinedEnabled],
  ([list, combined]) => {
    if (!roots.data.value) return;
    // Whether "All folders" exists is not known until the settings arrive; a remembered or
    // first choice waits for them rather than settling on a root and never moving.
    const settingsKnown = !!settings.data.value || settings.isError.value;
    if (!settingsKnown && (rootId.value === null || rootId.value === COMBINED_VIEW_ID)) return;
    const ids = [...(combined && list.length ? [COMBINED_VIEW_ID] : []), ...list.map((r) => r.id)];
    if (!ids.includes(rootId.value ?? '')) {
      rootId.value = ids[0] ?? null;
      path.value = '';
    }
  },
  { immediate: true },
);
watch([rootId, path], ([r, p]) => {
  if (r) prefs.prefs.lastRoot = r;
  router.replace({ query: { root: r ?? undefined, path: p || undefined } });
  selection.value = new Map();
});
// A link pasted while this view is already open must move it, not only fill it on first load.
watch(
  () => [route.query.root, route.query.path],
  ([r, p]) => {
    const nextRoot = str(r) ?? rootId.value;
    const nextPath = str(p) ?? '';
    if (nextRoot !== rootId.value) rootId.value = nextRoot;
    if (nextPath !== path.value) path.value = nextPath;
  },
);

const entries = useEntries(() => (isCombined.value ? null : rootId.value), path, kind);
const combined = useCombinedEntries(isCombined);
const tree = useTree(() => (isCombined.value ? null : rootId.value));
const root = computed(() => roots.data.value?.find((r) => r.id === rootId.value) ?? null);
const current = computed(() => (isCombined.value ? combined : entries));
const loading = computed(() => current.value.isPending.value);
const failed = computed(() => current.value.isError.value);
const failure = computed(() => (current.value.error?.value as Error | null | undefined)?.message);
const rootOptions = computed(() => [
  ...(combinedEnabled.value && sortedRoots.value.length ? [{ value: COMBINED_VIEW_ID, label: t('library.allFolders') }] : []),
  ...sortedRoots.value.map((r) => ({ value: r.id, label: r.name })),
]);
const kindOptions = computed(() => [{ value: '', label: t('browse.allKinds') }, ...(meta.data.value?.kinds ?? []).map((k) => ({ value: k, label: kindLabel(k) }))]);

// No folder's path is "/", so this crumb cannot be mistaken for one.
const ALL_CRUMB = '/';
const crumbs = computed(() => {
  if (isCombined.value) return [{ label: t('library.allFolders'), value: '' }];
  const trail = [{ label: root.value?.name ?? '', value: '' }, ...pathSegments(path.value).map((s) => ({ label: s.name, value: s.path }))];
  return combinedEnabled.value ? [{ label: t('library.allFolders'), value: ALL_CRUMB }, ...trail] : trail;
});

function navigate(to: string) {
  direction.value = to.length >= path.value.length ? 1 : -1;
  path.value = to;
}

function onCrumb(value: string) {
  if (value !== ALL_CRUMB) return navigate(value);
  direction.value = -1;
  rootId.value = COMBINED_VIEW_ID;
  path.value = '';
}

/**
 * Every item carries its root: in "All folders" the folders on screen come from several roots, and
 * each action goes to the one the item belongs to. ``label`` tells equal names apart there, and an
 * ``isRoot`` entry is a whole root kept together because it has files at its top level.
 */
type FolderItem = { type: 'folder'; rootId: string; label: string; rootName: string | null; isRoot: boolean; folder: FolderEntry };
type ModelItem = { type: 'model'; rootId: string; model: ModelEntry };
type Item = FolderItem | ModelItem;
const items = computed<Item[]>(() => {
  // "All folders" holds folders only: a root with files is one entry, so no file is ever loose there.
  if (isCombined.value) {
    return (combined.data.value?.folders ?? []).map(
      (folder): FolderItem => ({ type: 'folder', rootId: folder.root_id, label: folder.label, rootName: folder.root_name, isRoot: folder.is_root, folder }),
    );
  }
  const id = rootId.value ?? '';
  const l = entries.data.value;
  return [
    ...(l?.folders ?? []).map((folder): FolderItem => ({ type: 'folder', rootId: id, label: folder.name, rootName: null, isRoot: false, folder })),
    ...(l?.models ?? []).map((model): ModelItem => ({ type: 'model', rootId: id, model })),
  ];
});
const itemRef = (i: Item): PathRef => ({ root_id: i.rootId, path: i.type === 'folder' ? i.folder.path : i.model.path });
const refKey = (r: PathRef) => JSON.stringify([r.root_id, r.path]);
const itemKey = (i: Item) => `${i.type}:${refKey(itemRef(i))}`;

function openFolder(item: FolderItem) {
  if (!isCombined.value) return navigate(item.folder.path);
  direction.value = 1;
  rootId.value = item.rootId;
  path.value = item.folder.path;
}

/** In "All folders" the side lists the same first-level folders, under the same labels. */
const sideTree = computed<TreeNode | null>(() => {
  if (!isCombined.value) return tree.data.value ?? null;
  if (!combined.data.value) return null;
  const folders = items.value.filter((i): i is FolderItem => i.type === 'folder');
  return { name: t('library.allFolders'), path: '', folder_kind: null, children: folders.map((i) => ({ name: i.label, path: itemKey(i), folder_kind: i.folder.folder_kind ?? null, children: [] })) };
});
function onTreeSelect(key: string) {
  if (!isCombined.value) return navigate(key);
  const item = items.value.find((i) => itemKey(i) === key);
  if (item?.type === 'folder') openFolder(item);
}
const missingRoots = computed(() => {
  const ids = isCombined.value ? (combined.data.value?.missing_roots ?? []) : [];
  return ids.map((id) => roots.data.value?.find((r) => r.id === id)?.name ?? id).join(', ');
});

// Selection
const selection = ref(new Map<string, PathRef>());
const isSelected = (i: Item) => selection.value.has(refKey(itemRef(i)));
const toggle = (i: Item, on: boolean) => {
  const r = itemRef(i);
  const next = new Map(selection.value);
  if (on) next.set(refKey(r), r);
  else next.delete(refKey(r));
  selection.value = next;
};
const selected = computed(() => [...selection.value.values()]);

// Dialogs
const infoOpen = ref(false);
const infoRoot = ref<string | null>(null);
const infoPath = ref<string | null>(null);
const infoRect = ref<DOMRect | null>(null);
function openInfo(item: ModelItem, rect: DOMRect | null) {
  infoRoot.value = item.rootId;
  infoPath.value = item.model.path;
  infoRect.value = rect;
  infoOpen.value = true;
}

const renameOpen = ref(false);
const renameTarget = ref<{ ref: PathRef; name: string; isFile: boolean } | null>(null);
const renameError = ref<string | null>(null);
function startRename(ref_: PathRef, name: string, isFile: boolean) {
  renameTarget.value = { ref: ref_, name, isFile };
  renameError.value = null;
  renameOpen.value = true;
}
function doRename(newName: string) {
  if (!renameTarget.value) return;
  m.rename.mutate(
    { ...renameTarget.value.ref, new_name: newName },
    { onSuccess: () => (renameOpen.value = false), onError: (e) => (renameError.value = (e as Error).message) },
  );
}

const moveOpen = ref(false);
const moveItems = ref<PathRef[]>([]);
function startMove(refs: PathRef[]) {
  moveItems.value = refs;
  moveOpen.value = true;
}
function doMove(dest: { rootId: string; dir: string }) {
  m.move.mutate(
    { items: moveItems.value, dest_root_id: dest.rootId, dest_dir: dest.dir, on_conflict: 'error' },
    {
      onSuccess: () => {
        moveOpen.value = false;
        selection.value = new Map();
        qc.invalidateQueries({ queryKey: ['library'] });
      },
      onError: (e) => snackbar.error((e as Error).message),
    },
  );
}

const deleteOpen = ref(false);
const deleteItems = ref<PathRef[]>([]);
const permanent = ref(false);
const toTrash = computed(() => settings.data.value?.library.delete_to_trash !== false);
function startDelete(refs: PathRef[]) {
  deleteItems.value = refs;
  permanent.value = !toTrash.value;
  deleteOpen.value = true;
}
function doDelete() {
  m.remove.mutate(
    { items: deleteItems.value, permanent: permanent.value },
    {
      onSuccess: () => {
        deleteOpen.value = false;
        selection.value = new Map();
        qc.invalidateQueries({ queryKey: ['library'] });
      },
      onError: (e) => snackbar.error((e as Error).message),
    },
  );
}

// Creating, importing and uploading need one folder to land in, which "All folders" is not.
const canAdd = computed(() => !!rootId.value && !isCombined.value);

const folderOpen = ref(false);
const folderName = ref('');
function doCreateFolder() {
  if (!canAdd.value || !rootId.value || !folderName.value.trim()) return;
  m.createFolder.mutate(
    { root_id: rootId.value, path: path.value, name: folderName.value.trim() },
    {
      onSuccess: () => {
        folderOpen.value = false;
        folderName.value = '';
      },
      onError: (e) => snackbar.error((e as Error).message),
    },
  );
}

const importOpen = ref(false);
const importPath = ref('');
const importMove = ref(false);
function doImport() {
  if (!canAdd.value || !rootId.value || !importPath.value.trim()) return;
  m.importPaths.mutate(
    { sources: [importPath.value.trim()], root_id: rootId.value, rel_dir: path.value, move: importMove.value, on_conflict: 'error' },
    {
      onSuccess: () => {
        importOpen.value = false;
        importPath.value = '';
      },
      onError: (e) => snackbar.error((e as Error).message),
    },
  );
}

const rootDialogOpen = ref(false);
const editingRoot = ref(false);
const rootError = ref<string | null>(null);
function openRootDialog(edit: boolean) {
  editingRoot.value = edit;
  rootError.value = null;
  rootDialogOpen.value = true;
}
function saveRoot(form: { name: string | null; path: string; layout: 'comfyui' | 'sd-webui' | 'custom'; kind: string | null }) {
  const onError = (e: unknown) => (rootError.value = (e as Error).message);
  if (editingRoot.value && rootId.value) {
    m.updateRoot.mutate({ id: rootId.value, body: form }, { onSuccess: () => (rootDialogOpen.value = false), onError });
  } else {
    m.addRoot.mutate(form, {
      onSuccess: (r) => {
        rootDialogOpen.value = false;
        rootId.value = r.id;
        path.value = '';
      },
      onError,
    });
  }
}
const removeRootOpen = ref(false);
function doRemoveRoot() {
  if (!rootId.value) return;
  m.removeRoot.mutate(rootId.value, { onSuccess: () => (removeRootOpen.value = false) });
}

// A host application can fix the model folders; the actions that would change them are then gone.
const rootsLocked = computed(() => meta.data.value?.roots_locked ?? false);
const rootMenu = computed<MenuItem[]>(() =>
  rootsLocked.value
    ? []
    : [
        { id: 'add', label: t('library.addRoot'), icon: icons.Plus },
        { id: 'edit', label: t('library.editRoot'), icon: icons.Pencil, disabled: !root.value },
        { id: 'remove', label: t('library.removeRoot'), icon: icons.Trash2, danger: true, disabled: !root.value },
      ],
);
function onRootMenu(id: string) {
  if (id === 'add') openRootDialog(false);
  if (id === 'edit') openRootDialog(true);
  if (id === 'remove') removeRootOpen.value = true;
}

// A diffusers model is a folder, which a browser cannot save as one download.
const modelMenu = (model: ModelEntry): MenuItem[] => [
  { id: 'info', label: t('common.info'), icon: icons.Info },
  ...(model.is_dir ? [] : [{ id: 'download', label: t('library.download'), icon: icons.Download }]),
  { id: 'rename', label: t('common.rename'), icon: icons.Pencil },
  { id: 'move', label: t('common.move'), icon: icons.Move },
  { id: 'delete', label: t('common.delete'), icon: icons.Trash2, danger: true },
];
function onModelMenu(id: string, item: ModelItem) {
  if (id === 'info') openInfo(item, null);
  if (id === 'download') saveFile(item.rootId, item.model.path);
  if (id === 'rename') startRename(itemRef(item), item.model.name, !item.model.is_dir);
  if (id === 'move') startMove([itemRef(item)]);
  if (id === 'delete') startDelete([itemRef(item)]);
}
const folderMenu = computed<MenuItem[]>(() => [
  { id: 'rename', label: t('common.rename'), icon: icons.Pencil },
  { id: 'move', label: t('common.move'), icon: icons.Move },
  { id: 'delete', label: t('common.delete'), icon: icons.Trash2, danger: true },
]);
function onFolderMenu(id: string, item: FolderItem) {
  if (id === 'rename') startRename(itemRef(item), item.folder.name, false);
  if (id === 'move') startMove([itemRef(item)]);
  if (id === 'delete') startDelete([itemRef(item)]);
}

function rescan() {
  if (!rootId.value) return;
  const targets = isCombined.value ? sortedRoots.value.map((r) => ({ rootId: r.id, path: '' })) : [{ rootId: rootId.value, path: path.value }];
  Promise.all(targets.map((v) => m.scan.mutateAsync(v))).then(
    () => snackbar.show(t('library.scanStarted')),
    (e) => snackbar.error((e as Error).message),
  );
}

// Files land in the folder on screen, whether they were dropped or chosen in the file picker.
function startUpload(files: DroppedFile[]) {
  if (!canAdd.value || !rootId.value || !files.length) return;
  uploads.enqueue(rootId.value, path.value, files);
  snackbar.show(t('library.uploadStarted', { n: files.length }), { actionLabel: t('browse.openDownloads'), action: () => (downloadsStore.drawerOpen = true) });
}

/**
 * Open the system file picker. The input is created here rather than kept in the template: a
 * folder needs the non-standard ``webkitdirectory``, and a fresh input also fires ``change``
 * when the same file is chosen twice.
 */
function pickFiles(directory: boolean) {
  const input = document.createElement('input');
  input.type = 'file';
  input.multiple = true;
  if (directory) input.webkitdirectory = true;
  input.addEventListener('change', () => {
    // The picker gives a folder's structure in webkitRelativePath, which the upload keeps.
    startUpload(Array.from(input.files ?? []).map((file) => ({ file, relativePath: file.webkitRelativePath || file.name })));
  });
  input.click();
}

const uploadMenu = computed<MenuItem[]>(() => [
  { id: 'files', label: t('library.uploadFiles'), icon: icons.File },
  { id: 'folder', label: t('library.uploadFolder'), icon: icons.FolderInput },
]);

const stopListening = uploads.onFinished((item) => {
  if (item.state === 'failed') snackbar.error(t('library.uploadFailed', { name: item.name, error: item.error ?? '' }));
  qc.invalidateQueries({ queryKey: keys.entries(item.rootId) });
  qc.invalidateQueries({ queryKey: keys.entries(COMBINED_VIEW_ID) });
  qc.invalidateQueries({ queryKey: keys.tree(item.rootId) });
});
onBeforeUnmount(stopListening);

/** A file listed only because library.show_all_files is on: shown by its extension, never detected. */
const fileLabel = (model: ModelEntry) => fileExtensionLabel(model.name) ?? t('library.file');

const warningFor = (model: ModelEntry) => (model.mismatch ? t('library.mismatchText') : null);
const baseFor = (model: ModelEntry) => {
  if (!model.is_model) return null;
  const b = model.detection?.base_model ?? model.sidecar?.base_model;
  return b ? (meta.data.value?.base_models.find((x) => x.value === b)?.label ?? b) : null;
};
const kindFor = (model: ModelEntry) => {
  if (!model.is_model) return fileLabel(model);
  const k = model.detection?.kind && model.detection.kind !== 'unknown' ? model.detection.kind : (model.sidecar?.kind ?? model.folder_kind ?? 'unknown');
  return kindLabel(k);
};
</script>

<template>
  <div class="library">
    <EmptyState
      v-if="roots.isSuccess.value && !roots.data.value?.length"
      :icon="icons.HardDrive"
      :title="t('library.noRootsTitle')"
      :text="rootsLocked ? t('library.rootsLocked') : t('library.noRootsText')"
      class="no-roots"
    >
      <AppButton v-if="!rootsLocked" :icon="icons.FolderPlus" @click="openRootDialog(false)">{{ t('library.addRoot') }}</AppButton>
    </EmptyState>

    <template v-else>
      <aside class="side">
        <div class="root-row">
          <SelectField v-model="rootId" :label="t('library.root')" :options="rootOptions" class="root-select" @update:model-value="path = ''" />
          <AppMenu v-if="rootMenu.length" :items="rootMenu" @select="onRootMenu">
            <template #default="{ toggle }"><IconButton :icon="icons.MoreVertical" :label="t('common.more')" @click="toggle" /></template>
          </AppMenu>
        </div>
        <PathText v-if="root" :path="root.path" class="type-body-small muted" />
        <p v-else-if="isCombined" class="type-body-small muted hint">{{ t('library.allFoldersHint') }}</p>
        <p v-if="root && !root.exists" class="type-body-small error">{{ t('library.missing') }}</p>
        <p v-if="missingRoots" class="type-body-small error">{{ t('library.missingRoots', { names: missingRoots }) }}</p>
        <div class="tree" role="tree">
          <FolderTree v-if="sideTree" :node="sideTree" :selected="isCombined ? '' : path" @select="onTreeSelect" />
          <div v-else class="tree-skeleton"><Skeleton v-for="i in 6" :key="i" height="28px" shape="full" /></div>
        </div>
      </aside>

      <section class="main">
        <FileDropZone :label="t('library.dropHere', { folder: path || root?.name || '/' })" :disabled="!canAdd" @files="startUpload">
          <div class="head">
            <Breadcrumbs :crumbs="crumbs" @navigate="onCrumb" />
            <div class="toolbar">
              <template v-if="selection.size">
                <span class="type-label-large">{{ t('library.selected', { n: selection.size }) }}</span>
                <IconButton :icon="icons.Move" :label="t('common.move')" @click="startMove(selected)" />
                <IconButton :icon="icons.Trash2" :label="t('common.delete')" @click="startDelete(selected)" />
                <IconButton :icon="icons.X" :label="t('library.clearSelection')" @click="selection = new Map()" />
              </template>
              <template v-else>
                <template v-if="canAdd">
                  <AppMenu :items="uploadMenu" @select="pickFiles($event === 'folder')">
                    <template #default="{ toggle }">
                      <AppButton variant="tonal" :icon="icons.Upload" @click="toggle">{{ t('library.upload') }}</AppButton>
                    </template>
                  </AppMenu>
                  <AppButton variant="text" :icon="icons.FolderInput" @click="importOpen = true">{{ t('library.import') }}</AppButton>
                  <IconButton :icon="icons.FolderPlus" :label="t('library.newFolder')" @click="folderOpen = true" />
                </template>
                <IconButton :icon="icons.RefreshCw" :label="t('library.rescan')" :spin="m.scan.isPending.value" @click="rescan" />
                <SelectField v-if="!isCombined" :model-value="kind ?? ''" :label="t('library.filterKind')" :options="kindOptions" class="kind" @update:model-value="kind = $event || null" />
                <SegmentedButton
                  v-model="prefs.prefs.libraryView"
                  :options="[
                    { value: 'grid', icon: icons.LayoutGrid, ariaLabel: t('library.grid') },
                    { value: 'list', icon: icons.LayoutList, ariaLabel: t('library.list') },
                  ]"
                />
              </template>
            </div>
          </div>

          <Transition name="shared-axis-x" mode="out-in">
            <div :key="`${rootId}:${path}:${kind}`" class="content" :style="{ '--axis-dir': direction }">
              <div v-if="loading" class="skeletons">
                <div v-for="i in 10" :key="i" class="skeleton-card"><Skeleton height="200px" shape="medium" /><Skeleton width="70%" /></div>
              </div>
              <EmptyState v-else-if="failed" :icon="icons.AlertTriangle" :title="t('common.error')" :text="failure" />
              <EmptyState v-else-if="!items.length && isCombined" :icon="icons.FolderOpen" :title="t('library.emptyTitle')" :text="t('library.allFoldersEmptyText')" />
              <EmptyState v-else-if="!items.length" :icon="icons.FolderOpen" :title="t('library.emptyTitle')" :text="t('library.emptyText')">
                <AppButton variant="tonal" :icon="icons.Upload" :disabled="!canAdd" @click="pickFiles(false)">{{ t('library.upload') }}</AppButton>
                <AppButton variant="text" :icon="icons.FolderInput" @click="importOpen = true">{{ t('library.import') }}</AppButton>
              </EmptyState>
              <ModelGrid v-else :items="items" :item-key="itemKey" :layout="prefs.prefs.libraryView">
                <template #default="{ item }">
                  <button v-if="item.type === 'folder'" type="button" class="folder state-layer" :class="`folder-${prefs.prefs.libraryView}`" @click="openFolder(item)">
                    <span class="folder-icon"><AppIcon :icon="icons.Folder" :size="24" /></span>
                    <span class="folder-text">
                      <span class="type-title-small folder-name">{{ item.label }}</span>
                      <span v-if="item.folder.folder_kind || item.rootName" class="type-body-small muted folder-meta">
                        {{ [item.folder.folder_kind ? kindLabel(item.folder.folder_kind) : null, item.rootName].filter(Boolean).join(' · ') }}
                      </span>
                    </span>
                    <!-- A root cannot be renamed, moved or deleted from here. -->
                    <AppMenu v-if="!item.isRoot" :items="folderMenu" @select="onFolderMenu($event, item)">
                      <template #default="{ toggle }"><IconButton :icon="icons.MoreVertical" :label="t('common.more')" @click.stop="toggle" /></template>
                    </AppMenu>
                  </button>
                  <ModelCard
                    v-else
                    :layout="prefs.prefs.libraryView"
                    :title="item.model.name"
                    :subtitle="formatBytes(item.model.size)"
                    :preview="item.model.preview ? previewUrl(item.rootId, item.model.preview, prefs.prefs.libraryView === 'list' ? 128 : 384) : null"
                    :fallback-icon="item.model.is_model ? undefined : icons.FileText"
                    :kind="kindFor(item.model)"
                    :base="baseFor(item.model)"
                    :warning="warningFor(item.model)"
                    :pending="item.model.is_model && !item.model.detection && (entries.data.value?.pending_detection ?? 0) > 0"
                    :selected="isSelected(item)"
                    @activate="openInfo(item, $event)"
                  >
                    <template #select>
                      <Checkbox
                        :model-value="isSelected(item)"
                        :dense="prefs.prefs.libraryView === 'list'"
                        :class="prefs.prefs.libraryView === 'list' ? '' : 'select-box'"
                        @update:model-value="toggle(item, $event)"
                      />
                    </template>
                    <template #actions>
                      <AppMenu :items="modelMenu(item.model)" @select="onModelMenu($event, item)">
                        <template #default="{ toggle: open }"><IconButton :icon="icons.MoreVertical" :label="t('common.more')" @click="open" /></template>
                      </AppMenu>
                    </template>
                  </ModelCard>
                </template>
              </ModelGrid>
            </div>
          </Transition>
        </FileDropZone>
      </section>
    </template>

    <ModelInfoDialog v-model:open="infoOpen" :root-id="infoRoot" :path="infoPath" :from-rect="infoRect" />
    <RenameDialog v-model:open="renameOpen" :name="renameTarget?.name ?? ''" :is-file="renameTarget?.isFile" :loading="m.rename.isPending.value" :error="renameError" @confirm="doRename" />
    <MoveDialog v-model:open="moveOpen" :count="moveItems.length" :root-id="moveItems[0]?.root_id ?? null" :loading="m.move.isPending.value" @confirm="doMove" />
    <ConfirmDialog
      v-model:open="deleteOpen"
      :title="t('library.deleteTitle', { n: deleteItems.length })"
      :message="permanent ? t('library.deletePermanent') : t('library.deleteTrash')"
      :confirm-label="t('common.delete')"
      :cancel-label="t('common.cancel')"
      :loading="m.remove.isPending.value"
      danger
      @confirm="doDelete"
    >
      <Checkbox v-if="toTrash" v-model="permanent" :label="t('library.permanent')" />
    </ConfirmDialog>
    <AppDialog v-model:open="folderOpen" :title="t('library.newFolder')" width="small">
      <TextField v-model="folderName" :label="t('library.folderName')" @enter="doCreateFolder" />
      <template #actions>
        <AppButton variant="text" @click="folderOpen = false">{{ t('common.cancel') }}</AppButton>
        <AppButton :disabled="!folderName.trim()" :loading="m.createFolder.isPending.value" @click="doCreateFolder">{{ t('common.save') }}</AppButton>
      </template>
    </AppDialog>
    <AppDialog v-model:open="importOpen" :title="t('library.import')" width="small">
      <div class="form">
        <PathField v-model="importPath" :label="t('library.importPath')" :supporting-text="t('library.importHelp')" placeholder="/path/to/model.safetensors" @enter="doImport" />
        <Checkbox v-model="importMove" :label="t('library.importMove')" />
      </div>
      <template #actions>
        <AppButton variant="text" @click="importOpen = false">{{ t('common.cancel') }}</AppButton>
        <AppButton :disabled="!importPath.trim()" :loading="m.importPaths.isPending.value" @click="doImport">{{ t('library.import') }}</AppButton>
      </template>
    </AppDialog>
    <RootDialog v-model:open="rootDialogOpen" :root="editingRoot ? root : null" :loading="m.addRoot.isPending.value || m.updateRoot.isPending.value" :error="rootError" @confirm="saveRoot" />
    <ConfirmDialog
      v-model:open="removeRootOpen"
      :title="t('library.removeRoot')"
      :message="t('library.removeRootText')"
      :confirm-label="t('library.removeRoot')"
      :cancel-label="t('common.cancel')"
      @confirm="doRemoveRoot"
    />
  </div>
</template>

<style scoped>
.library { display: grid; grid-template-columns: 280px minmax(0, 1fr); height: 100%; }
.no-roots { grid-column: 1 / -1; align-self: center; }
.side { display: flex; flex-direction: column; gap: var(--app-space-2); padding: var(--app-space-4); border-right: 1px solid var(--md-sys-color-outline-variant); min-height: 0; }
.root-row { display: flex; align-items: center; gap: var(--app-space-1); }
.root-select { flex: 1; min-width: 0; }
.hint { margin: 0; }
.error { color: var(--md-sys-color-error); margin: 0; }
.tree { flex: 1; overflow: auto; margin: 0 calc(-1 * var(--app-space-2)); }
.tree-skeleton { display: flex; flex-direction: column; gap: var(--app-space-2); padding: var(--app-space-2); }
.main { min-width: 0; overflow: auto; }
.head { position: sticky; top: 0; z-index: 5; display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: var(--app-space-2); padding: var(--app-space-3) var(--app-space-4); background: var(--md-sys-color-surface-container-low); }
.toolbar { display: flex; flex-wrap: wrap; align-items: center; gap: var(--app-space-2); }
.kind { min-width: 150px; }
.content { position: relative; padding: 0 var(--app-space-4) var(--app-space-6); }
.skeletons { display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: var(--app-space-3); }
.skeleton-card { display: flex; flex-direction: column; gap: var(--app-space-2); }
.folder {
  display: flex; align-items: center; gap: var(--app-space-3); width: 100%; padding: var(--app-space-2) var(--app-space-1) var(--app-space-2) var(--app-space-3);
  border: 0; border-radius: var(--md-sys-shape-corner-medium); background: var(--md-sys-color-surface-container); color: var(--md-sys-color-on-surface); cursor: pointer; text-align: left; font: inherit;
}
.folder-grid { min-height: 64px; }
.folder-list { min-height: 56px; }
.folder-icon { display: grid; place-items: center; width: 40px; height: 40px; border-radius: var(--md-sys-shape-corner-small); background: var(--md-sys-color-secondary-container); color: var(--md-sys-color-on-secondary-container); flex: none; }
.folder-text { flex: 1; min-width: 0; display: flex; flex-direction: column; }
.folder-name, .folder-meta { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.select-box { padding: 2px; border-radius: var(--md-sys-shape-corner-small); background: color-mix(in srgb, var(--md-sys-color-surface) 70%, transparent); }
.form { display: flex; flex-direction: column; gap: var(--app-space-3); }
@media (max-width: 839px) {
  .library { grid-template-columns: minmax(0, 1fr); grid-template-rows: auto 1fr; }
  .side { border-right: 0; border-bottom: 1px solid var(--md-sys-color-outline-variant); }
  .tree { max-height: 160px; }
}
</style>
