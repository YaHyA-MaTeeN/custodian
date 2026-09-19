'use client';

import { useState } from 'react';
import { AppShell } from '@/components/AppShell';
import { Icons } from '@/components/Icons';
import { Empty, ErrorBox, Loading } from '@/components/States';
import { useApi } from '@/lib/api';
import { initials, shortDate } from '@/lib/format';
import type { CleanupGroup } from '@/lib/types';

export default function CleanupPage() {
  const { data, error, loading, reload } = useApi<{
    groups: CleanupGroup[];
    totalGrouped: number;
    note: string;
  }>('/api/cleanup');
  const [picked, setPicked] = useState<Set<string>>(new Set());

  function toggle(sender: string) {
    setPicked((prev) => {
      const next = new Set(prev);
      if (next.has(sender)) next.delete(sender);
      else next.add(sender);
      return next;
    });
  }

  const groups = data?.groups ?? [];
  const chosen = groups.filter((g) => picked.has(g.sender));
  const chosenCount = chosen.reduce((n, g) => n + g.count, 0);

  return (
    <AppShell
      title="Backlog cleanup"
      subtitle="Grouped by who sent it — one decision per sender, not per message."
      actions={
        <button className="btn btn-ghost btn-sm" onClick={reload}>
          {Icons.refresh}
          Refresh
        </button>
      }
    >
      <div className="notebox">
        {Icons.shield}
        <div>
          <b>Custodian never deletes.</b> It groups the noise so one decision clears a whole sender,
          and the deleting stays with you, in your own mailbox. That is also why every action it
          does take can be reversed.
        </div>
      </div>

      {error && <ErrorBox error={error} onRetry={reload} />}
      {loading && !data && <div className="card"><Loading rows={5} /></div>}

      {data && (
        <div className="card" style={{ display: 'flex', alignItems: 'center', gap: 26, padding: '20px 24px' }}>
          <div>
            <div style={{ fontFamily: 'var(--f-display)', fontSize: 26, fontWeight: 600 }}>
              {data.totalGrouped.toLocaleString()}
            </div>
            <div style={{ fontSize: 12.5, color: 'var(--ink-2)' }}>messages the agent handled quietly</div>
          </div>
          <div>
            <div style={{ fontFamily: 'var(--f-display)', fontSize: 26, fontWeight: 600 }}>
              {groups.length}
            </div>
            <div style={{ fontSize: 12.5, color: 'var(--ink-2)' }}>senders to decide on</div>
          </div>
          <div>
            <div style={{ fontFamily: 'var(--f-display)', fontSize: 26, fontWeight: 600, color: 'var(--accent)' }}>
              {chosenCount.toLocaleString()}
            </div>
            <div style={{ fontSize: 12.5, color: 'var(--ink-2)' }}>
              selected across {chosen.length} sender{chosen.length === 1 ? '' : 's'}
            </div>
          </div>
          <span style={{ flex: 1 }} />
          <button
            className="btn btn-ghost"
            onClick={() => setPicked(new Set(groups.map((g) => g.sender)))}
          >
            Select all
          </button>
          <button className="btn btn-primary" disabled={chosen.length === 0}>
            {Icons.cleanup}
            Move {chosenCount || ''} to Cleared
          </button>
        </div>
      )}

      {data && groups.length === 0 && (
        <div className="card">
          <Empty title="Nothing grouped yet.">
            Bulk senders show up here once the pipeline has seen them — run{' '}
            <code>python scan.py</code> to work through the backlog.
          </Empty>
        </div>
      )}

      {groups.length > 0 && (
        <div className="card rowlist">
          {groups.map((g) => {
            const on = picked.has(g.sender);
            return (
              <div className="listrow" key={g.sender} style={{ alignItems: 'center' }}>
                <input
                  type="checkbox"
                  checked={on}
                  onChange={() => toggle(g.sender)}
                  aria-label={`Select ${g.name}`}
                  style={{ width: 17, height: 17, accentColor: 'var(--accent)' }}
                />
                <div className="avatar">{initials(g.name, g.sender)}</div>
                <div className="listrow-body">
                  <div className="listrow-top">
                    <b>{g.name}</b>
                    <span className="mono" style={{ fontSize: 12.5, color: 'var(--ink-2)' }}>
                      {g.count} message{g.count === 1 ? '' : 's'}
                    </span>
                  </div>
                  <div className="listrow-meta">
                    {g.sender}
                    {g.accounts.length > 0 && ` · ${g.accounts.join(', ')}`}
                  </div>
                  <div className="listrow-why">{g.why}</div>
                  <div style={{ display: 'flex', gap: 6, marginTop: 8, flexWrap: 'wrap' }}>
                    {g.unsubscribe && <span className="chip chip-accent">one-click unsubscribe</span>}
                    <span className="chip chip-neutral">{g.kind}</span>
                    {g.samples[0] && (
                      <span style={{ fontSize: 11.5, color: 'var(--ink-3)', alignSelf: 'center' }}>
                        latest: {g.samples[0].subject.slice(0, 48)} · {shortDate(g.samples[0].date)}
                      </span>
                    )}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </AppShell>
  );
}
