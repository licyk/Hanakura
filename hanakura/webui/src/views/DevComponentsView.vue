<script setup lang="ts">
import { ref } from 'vue';
import {
  AppButton,
  AppCard,
  AppDialog,
  Badge,
  Breadcrumbs,
  Checkbox,
  EmptyState,
  ExpansionPanel,
  Fab,
  FilterChip,
  IconButton,
  ProgressBar,
  ProgressCircle,
  SearchField,
  SegmentedButton,
  SelectField,
  Skeleton,
  Slider,
  Switch,
  Tabs,
  TextField,
  Tooltip,
  icons,
  useSnackbar,
} from '@/ui';

/** Development only: every ui/ component, in both themes, for visual review. */
const text = ref('hello');
const check = ref(true);
const on = ref(true);
const slider = ref(40);
const chip = ref(false);
const seg = ref<'a' | 'b' | 'c'>('a');
const tab = ref<'one' | 'two'>('one');
const select = ref<string | null>('x');
const dialog = ref(false);
const expanded = ref(true);
const snackbar = useSnackbar();
</script>

<template>
  <div class="gallery">
    <div v-for="theme in ['light', 'dark']" :key="theme" class="panel" :data-theme-preview="theme">
      <h2 class="type-title-large">{{ theme }}</h2>
      <div class="row">
        <AppButton>Filled</AppButton>
        <AppButton variant="tonal" :icon="icons.Download">Tonal</AppButton>
        <AppButton variant="outlined">Outlined</AppButton>
        <AppButton variant="text">Text</AppButton>
        <AppButton loading>Loading</AppButton>
        <IconButton :icon="icons.Settings" label="Settings" :badge="3" />
        <Fab :icon="icons.Plus" label="Create" />
      </div>
      <div class="row">
        <TextField v-model="text" label="Text field" :icon="icons.Search" />
        <SearchField v-model="text" placeholder="Search" />
        <SelectField v-model="select" label="Select" :options="[{ value: 'x', label: 'X' }, { value: 'y', label: 'Y' }]" />
      </div>
      <div class="row">
        <Checkbox v-model="check" label="Checkbox" />
        <FilterChip v-model="chip" label="Filter chip" />
        <SegmentedButton v-model="seg" :options="[{ value: 'a', label: 'A' }, { value: 'b', label: 'B' }, { value: 'c', label: 'C' }]" />
        <Tooltip text="A tooltip"><Badge value="hover me" tone="neutral" /></Tooltip>
      </div>
      <Switch v-model="on" label="Switch" supporting-text="Supporting text" />
      <Slider v-model="slider" label="Slider" />
      <Tabs v-model="tab" :tabs="[{ value: 'one', label: 'One' }, { value: 'two', label: 'Two' }]" />
      <ProgressBar :value="0.4" />
      <ProgressBar />
      <div class="row">
        <ProgressCircle />
        <ProgressCircle :value="0.7" />
        <Skeleton width="120px" height="40px" />
      </div>
      <Breadcrumbs :crumbs="[{ label: 'root', value: '' }, { label: 'loras', value: 'loras' }, { label: 'style', value: 'loras/style' }]" />
      <AppCard interactive style="max-width: 240px; padding: 16px">Interactive card</AppCard>
      <EmptyState :icon="icons.Box" title="Empty state" text="Supporting text" />
      <ExpansionPanel v-model:open="expanded" label="Expansion panel" supporting-text="Click the header" :icon="icons.FileText">
        <p class="type-body-medium">Content that slides open and closed.</p>
      </ExpansionPanel>
      <div class="row">
        <AppButton variant="tonal" @click="dialog = true">Dialog</AppButton>
        <AppButton variant="tonal" @click="snackbar.show('Snackbar message', { actionLabel: 'Undo', action: () => undefined })">Snackbar</AppButton>
      </div>
    </div>
    <AppDialog v-model:open="dialog" title="Dialog">Dialog body</AppDialog>
  </div>
</template>

<style scoped>
.gallery { display: grid; grid-template-columns: repeat(auto-fit, minmax(420px, 1fr)); gap: var(--app-space-4); padding: var(--app-space-4); }
.panel { display: flex; flex-direction: column; gap: var(--app-space-3); padding: var(--app-space-4); border-radius: var(--md-sys-shape-corner-large); background: var(--md-sys-color-surface); color: var(--md-sys-color-on-surface); }
.row { display: flex; flex-wrap: wrap; align-items: center; gap: var(--app-space-2); }
</style>
