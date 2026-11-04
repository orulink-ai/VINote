import { expect, it } from 'vitest';
import { calendarDay, dayLabel } from './contentDates';
it('preserves explicit date-only values and rejects invalid dates without guessing', () => {
  expect(calendarDay('2026-11-04')).toBe('2026-11-04');
  expect(calendarDay('2026-02-30')).toBe('');
  expect(calendarDay('')).toBe('');
  expect(dayLabel('', '录制日期未记录')).toBe('录制日期未记录');
});
it('groups timestamped records by the users calendar day', () => {
  const date = new Date('2026-11-04T23:30:00Z');
  const expected = `${date.getFullYear()}-${String(date.getMonth()+1).padStart(2,'0')}-${String(date.getDate()).padStart(2,'0')}`;
  expect(calendarDay(date.toISOString())).toBe(expected);
});
