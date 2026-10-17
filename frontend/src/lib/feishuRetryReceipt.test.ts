import { beforeEach, expect, it, vi } from 'vitest';
vi.mock('./feishuPublishReceipt', () => ({ publishScope: () => () => {} }));
import { beginRetryReceipt, observeRetryReceipt, readRetryReceipt } from './feishuRetryReceipt';
import type { Delivery } from './feishu';
const job = (status: Delivery['status'], phase: string = status): Delivery => ({ id: 'original', status, phase, document_url: '', error: '', recipients: {} });
beforeEach(() => localStorage.clear());
it('keeps old failed GETs blocked across reopen, rejects another retry and unrelated jobs', () => {
  beginRetryReceipt('owner', 'note', 'original');
  observeRetryReceipt('owner', 'note', job('failed'));
  expect(readRetryReceipt('owner', 'note')?.jobId).toBe('original');
  expect(() => beginRetryReceipt('owner', 'note', 'other')).toThrow(/原重试/);
  expect(() => observeRetryReceipt('owner', 'note', { ...job('completed'), id: 'other' })).toThrow(/原重试/);
  expect(readRetryReceipt('another-owner', 'note')).toBeNull();
});
it('resolves a final failure only after observing running, and never resolves unknown', () => {
  beginRetryReceipt('owner', 'note', 'original');
  observeRetryReceipt('owner', 'note', job('processing'));
  observeRetryReceipt('owner', 'note', job('failed', 'unknown'));
  expect(readRetryReceipt('owner', 'note')).not.toBeNull();
  observeRetryReceipt('owner', 'note', job('failed'));
  expect(readRetryReceipt('owner', 'note')).toBeNull();
});
it('resolves a completed GET without requiring a processing observation', () => {
  beginRetryReceipt('owner', 'note', 'original');
  observeRetryReceipt('owner', 'note', job('completed'));
  expect(readRetryReceipt('owner', 'note')).toBeNull();
});
