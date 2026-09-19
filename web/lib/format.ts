import type { Kind } from './types';

export function shortDate(iso: string): string {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  const now = new Date();
  const sameDay = d.toDateString() === now.toDateString();
  if (sameDay) return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  const days = Math.round((now.getTime() - d.getTime()) / 86400000);
  if (days < 7 && days >= 0) return d.toLocaleDateString([], { weekday: 'short' });
  return d.toLocaleDateString([], { day: 'numeric', month: 'short' });
}

export function fullDate(iso: string): string {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  return d.toLocaleString([], {
    weekday: 'short', day: 'numeric', month: 'short',
    hour: '2-digit', minute: '2-digit',
  });
}

/** The chip a message wears, and what it is allowed to claim. */
export function kindChip(kind: Kind): { label: string; tone: string } {
  switch (kind) {
    case 'reply':
      return { label: 'needs a reply', tone: 'chip-ask' };
    case 'private':
      return { label: 'never opened', tone: 'chip-red' };
    case 'machine':
      return { label: 'machine', tone: 'chip-neutral' };
    case 'dormant':
      return { label: 'never engaged', tone: 'chip-neutral' };
    case 'filed':
      return { label: 'filed', tone: 'chip-plain' };
    default:
      return { label: 'not scored yet', tone: 'chip-amber' };
  }
}

export function urgencyTone(u: string): string {
  if (u === 'past' || u === 'today') return 'chip-red';
  if (u === 'soon') return 'chip-amber';
  if (u === 'week') return 'chip-amber';
  return 'chip-neutral';
}

export function daysLabel(days: number | null): string {
  if (days === null) return 'no date';
  if (days < 0) return `${Math.abs(days)}d overdue`;
  if (days === 0) return 'today';
  if (days === 1) return '1 day';
  return `${days} days`;
}

export function initials(name: string, fallback: string): string {
  const src = (name || fallback || '?').trim();
  const parts = src.split(/[\s@.]+/).filter(Boolean);
  if (parts.length === 0) return '?';
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[1][0]).toUpperCase();
}
