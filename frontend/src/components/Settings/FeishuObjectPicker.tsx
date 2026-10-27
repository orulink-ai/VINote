import { useEffect, useState } from 'react';
import { Check, ChevronsUpDown } from 'lucide-react';
import type { FeishuObject } from '@/lib/feishu';
import { Button } from '@/components/ui/button';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { Command, CommandInput, CommandList, CommandEmpty, CommandGroup, CommandItem } from '@/components/ui/command';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';

export function FeishuObjectPicker({ objects, value, onChange, disabled, isCurrent }: {
  objects: FeishuObject[]; value: string; onChange: (id: string) => void; disabled: boolean; isCurrent: () => boolean;
}) {
  const [open, setOpen] = useState(false), [query, setQuery] = useState('');
  const [kind, setKind] = useState('all');
  const selected = objects.find(item => item.id === value);
  const counts = new Map<string, number>();
  for (const item of objects) { const key = `${item.kind}:${item.name}`; counts.set(key, (counts.get(key) || 0) + 1) }
  const matching = objects.filter(item => (kind === 'all' || item.kind === kind) && item.name.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()));
  const contacts = matching.filter(item => item.kind === 'contact'), groups = matching.filter(item => item.kind === 'group');
  const label = (item: FeishuObject) => `${item.name} · ${item.kind === 'group' ? '群' : '联系人'}${(counts.get(`${item.kind}:${item.name}`) || 0) > 1 ? ` · ${item.id}` : ''}`;
  useEffect(() => { if (disabled) setOpen(false) }, [disabled]);
  const changeOpen = (next: boolean) => {
    if (next && (disabled || !isCurrent())) return;
    setOpen(next); if (!next) { setQuery(''); setKind('all') }
  };
  const select = (id: string) => {
    if (disabled || !isCurrent() || !objects.some(item => item.id === id)) return;
    onChange(id); changeOpen(false);
  };
  return <Popover open={open} onOpenChange={changeOpen}>
    <PopoverTrigger asChild>
      <Button id="feishu-object-target" variant="outline" role="combobox" aria-label="绑定对象" aria-haspopup="dialog" aria-expanded={open} disabled={disabled} className="w-full justify-between" >
        <span className="truncate">{selected ? label(selected) : '请选择联系人或群'}</span><ChevronsUpDown aria-hidden="true" data-icon="inline-end" />
      </Button>
    </PopoverTrigger>
    <PopoverContent aria-label="选择飞书对象" align="start" collisionPadding={16} className="flex w-[var(--radix-popover-trigger-width)] max-w-[calc(100vw-2rem)] max-h-[min(28rem,var(--radix-popover-content-available-height))] flex-col overflow-hidden p-0">
      <Command label="搜索联系人或群" shouldFilter={false} className="h-auto min-h-0 [&_[cmdk-input-wrapper]]:shrink-0">
        <CommandInput aria-label="搜索联系人或群" placeholder="搜索联系人或群名称…" value={query} onValueChange={setQuery} />
        <ToggleGroup type="single" value={kind} onValueChange={next => { if (next) setKind(next) }} aria-label="对象类型" size="sm" className="shrink-0 justify-start px-2 pt-2">
          <ToggleGroupItem value="all">全部</ToggleGroupItem><ToggleGroupItem value="contact">联系人</ToggleGroupItem><ToggleGroupItem value="group">群</ToggleGroupItem>
        </ToggleGroup>
        <p role="status" aria-live="polite" className="shrink-0 px-3 py-2 text-xs text-muted-foreground">找到 {matching.length} 个对象 · 联系人 {contacts.length} · 群 {groups.length}</p>
        <CommandList aria-label="匹配的飞书对象" className="max-h-[min(18rem,45vh)] min-h-0 overflow-y-auto overscroll-contain">
          <CommandEmpty>没有匹配的可见对象，请调整名称或类型。</CommandEmpty>
          {!!contacts.length && <CommandGroup heading={`联系人（${contacts.length}）`}>{contacts.map(item => <CommandItem key={item.id} value={item.id} onSelect={() => select(item.id)} aria-label={label(item)}><span className="min-w-0 break-words">{label(item)}</span>{value === item.id && <Check aria-hidden="true" className="ml-auto" />}</CommandItem>)}</CommandGroup>}
          {!!groups.length && <CommandGroup heading={`群（${groups.length}）`}>{groups.map(item => <CommandItem key={item.id} value={item.id} onSelect={() => select(item.id)} aria-label={label(item)}><span className="min-w-0 break-words">{label(item)}</span>{value === item.id && <Check aria-hidden="true" className="ml-auto" />}</CommandItem>)}</CommandGroup>}
        </CommandList>
      </Command>
    </PopoverContent>
  </Popover>;
}
