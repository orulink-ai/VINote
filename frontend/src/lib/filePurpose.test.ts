import { expect, it } from 'vitest';
import { originalPurpose, originalFormat, formatFilter, fileGenerationPath } from './filePurpose';
it('uses actual purpose before filename or legacy content type', () => {
  expect(originalPurpose({ purpose: 'note', filename: 'meeting.mp4', source_type: 'meeting_video' })).toBe('note');
  expect(originalPurpose({ purpose: 'meeting', filename: 'minutes.pdf' })).toBe('meeting');
  expect(originalPurpose({ filename: 'unlinked.mp3' })).toBe('unknown');
  expect(originalPurpose({ purpose: 'unknown', filename: 'unlinked.pdf' })).toBe('unknown');
});
it('preserves legacy format links without separate screen/video filters', () => {
  expect(formatFilter('screen')).toBe('video'); expect(formatFilter('recording')).toBe('audio'); expect(formatFilter('file')).toBe('document');
  expect(originalFormat('screen')).toBe(originalFormat('video')); expect(formatFilter('bad')).toBe('all');
  expect(fileGenerationPath('meeting')).toBe('/generate?mode=file&meeting=1'); expect(fileGenerationPath('note')).toBe('/generate?mode=file');
});
