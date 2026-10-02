import { createRouter, createWebHashHistory, type RouteRecordRaw } from 'vue-router';
import { trackLocations } from '@/viewState';

const routes: RouteRecordRaw[] = [
  { path: '/', redirect: '/browse' },
  { path: '/browse', name: 'browse', component: () => import('@/views/BrowseView.vue') },
  { path: '/hubs', name: 'hubs', component: () => import('@/views/HubsView.vue') },
  { path: '/direct', name: 'direct', component: () => import('@/views/DirectView.vue') },
  { path: '/library', name: 'library', component: () => import('@/views/LibraryView.vue') },
  { path: '/settings', name: 'settings', component: () => import('@/views/SettingsView.vue') },
];

if (import.meta.env.DEV) {
  routes.push({ path: '/dev/components', name: 'dev-components', component: () => import('@/views/DevComponentsView.vue') });
}

// Hash history: the UI works at any deployment sub-path with no server-side rewrites.
export const router = createRouter({ history: createWebHashHistory(), routes });
trackLocations(router);
