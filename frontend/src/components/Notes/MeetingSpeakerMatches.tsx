import { Button } from '@/components/ui/button';
import { NativeSelect, NativeSelectOption } from '@/components/ui/native-select';

export type MeetingSpeaker = {
  speaker_id: string;
  samples: { text: string; start: number; end: number; association: 'segment_speaker' | 'time_overlap' }[];
  candidates: { open_id: string; name: string; reasons: string[] }[];
};
export type SpeakerMatch = { speaker_id: string; open_id: string };
const stamp = (seconds: number) => `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(Math.floor(seconds % 60)).padStart(2, '0')}`;
const reasonLabels: Record<string, string> = {
  speaker_identity_unverified: '发言中包含自我介绍，身份待核对',
  attendance_statement_unverified: '材料中被列为参会人，待核对',
  task_ownership_not_attendance: '被提到负责事项，不代表正在发言',
  mention_not_attendance: '发言中提到此人',
  visual_prose_not_attendance: '画面材料出现此姓名',
  name_collision: '存在同名联系人',
  exact_hotword_match_only: '姓名或已设置别名一致',
  time_overlap_not_identity: '时间重叠，不能单独确定身份',
  visible_name_not_speaker_identity: '对应时刻画面出现姓名',
  visual_context_not_speaker_identity: '画面线索，尚未确认发言人',
};

export function MeetingSpeakerMatches({ speakers, contacts, matches, confirmedMatches, disabled, onMatch, onSearch }: {
  speakers: MeetingSpeaker[]; contacts: { open_id: string; name: string }[]; matches: Record<string, string>;
  confirmedMatches: Record<string, string>; disabled: boolean; onMatch: (speaker: string, contact: string) => void; onSearch: (speaker: string, name: string) => void;
}) {
  return <section aria-label="说话人与联系人" className="flex flex-col gap-3">
    <div><h3 className="text-sm font-medium">说话人与联系人</h3><p className="mt-1 text-sm text-muted-foreground">短句帮助你辨认说话人；姓名候选不等于身份确认，不会自动加入通知名单。</p></div>
    {!speakers.length && <p className="text-sm text-muted-foreground">这份录制没有可用的说话人标识，仍可在下方确认实际参会人。</p>}
    {speakers.map(speaker => <div key={speaker.speaker_id} className="flex flex-col gap-2 border-b py-3">
      <h4 className="text-sm font-medium">说话人 {speaker.speaker_id}</h4>
      {speaker.samples.map((sample, index) => <blockquote key={index} className="border-l-2 pl-3 text-sm">
        <p className="break-words">{sample.text}</p><p className="mt-1 text-xs text-muted-foreground">{stamp(sample.start)}–{stamp(sample.end)}{sample.association === 'time_overlap' && ' · 时间重叠片段，仅供参考'}</p>
      </blockquote>)}
      {!!speaker.candidates.length && <div className="text-xs text-muted-foreground">{speaker.candidates.map(candidate => <p key={candidate.open_id} className="break-words">候选：{candidate.name} · {[...new Set(candidate.reasons.map(reason => reasonLabels[reason] || '材料中的姓名线索'))].join('；')} · 仅供核对</p>)}</div>}
      {matches[speaker.speaker_id] && <p className="text-xs text-muted-foreground">{confirmedMatches[speaker.speaker_id] === matches[speaker.speaker_id] ? '已保存的人工对应' : '新对应，确认保存后生效'}</p>}
      <div className="flex flex-wrap items-center gap-2">
        <NativeSelect aria-label={`说话人${speaker.speaker_id}对应的联系人`} value={matches[speaker.speaker_id] || ''} disabled={disabled} onChange={event => onMatch(speaker.speaker_id, event.target.value)}>
          <NativeSelectOption value="">暂未确认 / 清空对应</NativeSelectOption>
          {contacts.map(contact => <NativeSelectOption key={contact.open_id} value={contact.open_id}>{contact.name}（{contact.open_id}）</NativeSelectOption>)}
        </NativeSelect>
        <Button type="button" variant="ghost" size="sm" disabled={disabled} aria-label={`为说话人${speaker.speaker_id}查找联系人`} onClick={() => onSearch(speaker.speaker_id, speaker.candidates.length === 1 ? speaker.candidates[0].name : '')}>查找联系人</Button>
      </div>
    </div>)}
  </section>;
}
