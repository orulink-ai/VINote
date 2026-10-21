import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { FeishuObjectPicker } from './FeishuObjectPicker';
import type { FeishuObject } from '@/lib/feishu';
const objects: FeishuObject[] = [{ id: 'ou_one', name: '项目负责人', kind: 'contact' }, { id: 'oc_one', name: '项目组', kind: 'group' }, { id: 'oc_two', name: '项目组', kind: 'group' }];
const originalScroll = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'scrollIntoView');
beforeEach(() => Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', { configurable: true, value: vi.fn() }));
afterEach(() => { cleanup(); if (originalScroll) Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', originalScroll); else Reflect.deleteProperty(HTMLElement.prototype, 'scrollIntoView') });
const open = () => fireEvent.click(screen.getByRole('combobox', { name: '绑定对象' }));

it('bounds the popup/list and reports exact matches grouped by contact and group', () => {
  const onChange = vi.fn(); render(<FeishuObjectPicker objects={objects} value="" onChange={onChange} disabled={false} isCurrent={() => true} />); open();
  expect(screen.getByRole('status')).toHaveTextContent('找到 3 个对象 · 联系人 1 · 群 2');
  expect(screen.getByText('联系人（1）')).toBeVisible(); expect(screen.getByText('群（2）')).toBeVisible();
  expect(screen.getByRole('listbox')).toHaveClass('overflow-y-auto', 'max-h-[min(18rem,45vh)]');
  expect(screen.getByRole('dialog', { name: '选择飞书对象' }).className).toContain('max-h-');
  expect(onChange).not.toHaveBeenCalled();
  fireEvent.change(screen.getByRole('combobox', { name: '搜索联系人或群' }), { target: { value: '负责人' } });
  expect(screen.getByRole('status')).toHaveTextContent('找到 1 个对象 · 联系人 1 · 群 0');
  expect(screen.getAllByRole('option')).toHaveLength(1);
  fireEvent.change(screen.getByRole('combobox', { name: '搜索联系人或群' }), { target: { value: '未命中' } });
  expect(screen.getByRole('status')).toHaveTextContent('找到 0 个对象'); expect(screen.getByText('没有匹配的可见对象，请调整名称或类型。')).toBeVisible();
  expect(onChange).not.toHaveBeenCalled();
});
it('filters contacts/groups independently and commits the explicitly clicked fixed ID for duplicate names', () => {
  const onChange = vi.fn(); render(<FeishuObjectPicker objects={objects} value="" onChange={onChange} disabled={false} isCurrent={() => true} />); open();
  fireEvent.click(screen.getByText('联系人', { selector: 'button' })); expect(screen.getAllByRole('option')).toHaveLength(1);
  fireEvent.click(screen.getByText('群', { selector: 'button' })); expect(screen.getAllByRole('option')).toHaveLength(2);
  expect(onChange).not.toHaveBeenCalled(); fireEvent.click(screen.getByRole('option', { name: '项目组 · 群 · oc_two' }));
  expect(onChange).toHaveBeenCalledExactlyOnceWith('oc_two'); expect(screen.getByRole('combobox', { name: '绑定对象' })).toHaveAttribute('aria-expanded', 'false');
});
it('does not choose a same-name object on open or an invalidated owner, and closes when disabled', () => {
  const onChange = vi.fn(); let current = true;
  const view = render(<FeishuObjectPicker objects={objects} value="oc_one" onChange={onChange} disabled={false} isCurrent={() => current} />); open();
  current = false; fireEvent.click(screen.getByRole('option', { name: '项目组 · 群 · oc_two' })); expect(onChange).not.toHaveBeenCalled();
  view.rerender(<FeishuObjectPicker objects={objects} value="oc_one" onChange={onChange} disabled={true} isCurrent={() => false} />);
  expect(screen.queryByRole('listbox')).toBeNull(); expect(onChange).not.toHaveBeenCalled();
});
it('supports keyboard search and explicit Enter selection without a native select', () => {
  const onChange = vi.fn(); render(<FeishuObjectPicker objects={objects} value="" onChange={onChange} disabled={false} isCurrent={() => true} />); open();
  expect(document.querySelector('select')).toBeNull(); const search = screen.getByRole('combobox', { name: '搜索联系人或群' });
  fireEvent.change(search, { target: { value: '负责人' } }); fireEvent.keyDown(search, { key: 'ArrowDown' });
  expect(onChange).not.toHaveBeenCalled(); fireEvent.keyDown(search, { key: 'Enter' }); expect(onChange).toHaveBeenCalledExactlyOnceWith('ou_one');
});

it.each(['unknown', 'departed'])('ignores obsolete %s markers in cached objects and keeps explicit contact selection available', status => {
  const onChange = vi.fn();
  const cached = { ...objects[0], status, selectable: false };
  render(<FeishuObjectPicker objects={[cached]} value="" onChange={onChange} disabled={false} isCurrent={() => true} />); open();
  const option = screen.getByRole('option', { name: '项目负责人 · 联系人' });
  expect(option).not.toHaveAttribute('aria-disabled', 'true');
  expect(screen.queryByText(/状态未核验|已离职|重新授权获取状态/)).toBeNull();
  fireEvent.click(option); expect(onChange).toHaveBeenCalledExactlyOnceWith('ou_one');
});
