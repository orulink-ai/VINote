export type FilePurpose = 'meeting' | 'note';
export type FilePurposeView = FilePurpose | 'unknown';

/** Purpose is not a media format. Older ambiguous media stays unclassified. */
export function originalPurpose(file: { purpose?: string; filename: string; source_type?: string }): FilePurposeView {
  if (file.purpose === 'meeting' || file.purpose === 'note') return file.purpose;
  if (file.purpose === 'unknown' || file.purpose === 'unassigned') return 'unknown';
  if (['meeting_recording', 'meeting_video'].includes(file.source_type || '')) return 'meeting';
  if (/\.(pdf|docx|md|txt|srt|vtt|json)$/i.test(file.filename)) return 'note';
  return 'unknown';
}
export const fileGenerationPath = (purpose: FilePurpose) => purpose === 'meeting'
  ? '/generate?mode=file&meeting=1' : '/generate?mode=file';
export const purposeLabel = (purpose: FilePurposeView) => purpose === 'meeting' ? '会议资料' : purpose === 'note' ? '笔记资料' : '待确认用途';
export function originalFormat(category: string) {
  return category === 'recording' || category === 'audio' ? 'audio' : category === 'screen' || category === 'video' ? 'video' : 'document';
}
export function formatFilter(value: string | null) {
  if (value === 'recording') return 'audio';
  if (value === 'screen') return 'video';
  if (value === 'file') return 'document';
  return value === 'audio' || value === 'video' || value === 'document' ? value : 'all';
}
