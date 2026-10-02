import { QueryClient } from '@tanstack/vue-query';
import { describe, expect, it } from 'vitest';
import { applyJobAnswer, applyJobEvent, markRunning } from '@/api/queries/downloads';
import { keys } from '@/api/queries/keys';
import type { DownloadJob } from '@/api/types';

const job = (over: Partial<DownloadJob> = {}): DownloadJob =>
  ({
    id: 1,
    runner: 'http',
    title: 'model.safetensors',
    state: 'queued',
    rel_dir: '',
    dest_dir: '/d',
    overwrite: false,
    bytes_done: 0,
    attempts: 0,
    meta: {},
    created_at: '2026-01-01T00:00:00Z',
    speed: 0,
    can_pause: true,
    ...over,
  }) as DownloadJob;

const stateOf = (qc: QueryClient) => qc.getQueryData<DownloadJob[]>(keys.downloads)?.[0].state;

describe('download job cache', () => {
  it('keeps the started event when the create answer arrives after it', () => {
    const qc = new QueryClient();
    // The browser posts, the worker starts the job, and the event overtakes the answer.
    const sentAt = performance.now();
    applyJobEvent(qc, job({ state: 'queued' }));
    applyJobEvent(qc, job({ state: 'running' }));
    applyJobAnswer(qc, job({ state: 'queued' }), sentAt);
    expect(stateOf(qc)).toBe('running');
  });

  it('applies an answer to a request sent after the last event', () => {
    const qc = new QueryClient();
    applyJobEvent(qc, job({ state: 'running' }));
    applyJobAnswer(qc, job({ state: 'paused' }), performance.now());
    expect(stateOf(qc)).toBe('paused');
  });

  it('inserts a job the socket has never reported', () => {
    const qc = new QueryClient();
    applyJobAnswer(qc, job(), performance.now());
    expect(stateOf(qc)).toBe('queued');
  });

  it('promotes a queued job on progress, once, and leaves other states alone', () => {
    const qc = new QueryClient();
    applyJobEvent(qc, job({ state: 'queued' }));
    markRunning(qc, 1);
    expect(stateOf(qc)).toBe('running');

    const list = qc.getQueryData<DownloadJob[]>(keys.downloads);
    markRunning(qc, 1);
    expect(qc.getQueryData<DownloadJob[]>(keys.downloads)).toBe(list);

    applyJobEvent(qc, job({ state: 'paused' }));
    markRunning(qc, 1);
    expect(stateOf(qc)).toBe('paused');
  });

  it('does not let a late answer undo a promotion made from progress', () => {
    const qc = new QueryClient();
    const sentAt = performance.now();
    applyJobEvent(qc, job({ state: 'queued' }));
    markRunning(qc, 1);
    applyJobAnswer(qc, job({ state: 'queued' }), sentAt);
    expect(stateOf(qc)).toBe('running');
  });
});
