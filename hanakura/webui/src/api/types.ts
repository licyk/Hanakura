import type { components } from '@/api/schema';

/** Shorthand for the generated schemas. */
export type S = components['schemas'];

export type SettingsView = S['SettingsView'];
export type SourceInfo = S['SourceInfo'];
export type ModelSummary = S['ModelSummary'];
export type ModelDetail = S['ModelDetail'];
export type ModelVersion = S['ModelVersion'];
export type ModelFile = S['ModelFile'];
export type SearchPage = S['SearchPage'];
export type HubInfo = S['HubInfo'];
export type RepoSummary = S['RepoSummary'];
export type RepoDetail = S['RepoDetail'];
export type RepoFile = S['RepoFile'];
export type DownloadJob = S['DownloadJob'];
export type DownloadCreate = S['DownloadCreate'];
export type RootInfo = S['RootInfo'];
export type FolderListing = S['FolderListing'];
export type ModelEntry = S['ModelEntry'];
export type FolderEntry = S['FolderEntry'];
export type CombinedListing = S['CombinedListing'];
export type PathRef = S['PathRef'];
export type TreeNode = S['TreeNode'];
export type ModelInfo = S['ModelInfo'];
export type DetectionResult = S['DetectionResult'];
export type IdentifyResult = S['IdentifyResult'];
export type AppMeta = S['AppMeta'];

/** Socket event payloads, typed from the same schema as REST. */
export type ServerEvents = { [K in keyof S['ServerEvents']]: S['ServerEvents'][K] };
