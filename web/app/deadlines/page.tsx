'use client';

import { useState } from 'react';
import { AppShell } from '@/components/AppShell';
import { Icons } from '@/components/Icons';
import { Empty, ErrorBox, Loading } from '@/components/States';
import { api, useApi } from '@/lib/api';
import { daysLabel, fullDate, urgencyTone } from '@/lib/format';
import type { Reminder } from '@/lib/types';

const GROUPS: { key: string; label: string; match: (r: Reminder) => boolean }[] = [
  { key: 'overdue', label: 'Overdue', match: (r) => r.urgency === 'past' },
  { key: 'today', label: 'Today', match: (r) => r.urgency === 'today' },
  { key: 'soon', label: 'Next few days', match: (r) => r.urgency === 'soon' },
  { key: 'week', label: 'This week', match: (r) => r.urgency === 'week' },
  { key: 'later', label: 'Later', match: (r) => r.urgency === 'later' },
];

export default function DeadlinesPage() {
  const { data, error, loading, reload } = useApi<{ deadlines: Reminder[]; due: Reminder[] }>(
    '/api/deadlines',
  );
  const [busy, setBusy] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);

  async function dismiss(r: Reminder) {
    setBusy(`${r.messageId}-${r.kind}`);
    setProblem(null);
    try {
      await api.post(`/api/deadlines/${encodeURIComponent(r.messageId)}/dismiss?kind=${r.kind}`);
      reload();
    } catch (e) {
      setProblem(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  }

  const live = (data?.deadlines ?? []).filter((r) => !r.done);

  return (
    <AppShell
      title="Deadline radar"
      subtitle="Everything with a date, and when we mean to say something about it."
      actions={
        <button className="btn btn-ghost btn-sm" onClick={reload}>
          {Icons.refresh}
          Refresh
        </button>
      }
    >
      <div className="notebox">
        {Icons.clock}
        <div>
          Lead time is set by what the thing is, not by a fixed countdown — a bill gets a day, a
          renewal gets weeks. Stage 16 works that out when the commitment is recorded, in code, and
          this screen only reads it.
        </div>
      </div>

      {error && <ErrorBox error={error} onRetry={reload} />}
      {problem && <ErrorBox error={problem} />}
      {loading && !data && <div className="card"><Loading rows={4} /></div>}

      {data && live.length === 0 && (
        <div className="card">
          <Empty title="Nothing is being watched yet.">
            A date becomes a commitment when the pipeline finds one — run{' '}
            <code>python agent.py</code> over some mail, or let{' '}
            <code>python web.py --watch</code> run in the background.
          </Empty>
        </div>
      )}

      {data &&
        GROUPS.map((g) => {
          const items = live.filter(g.match);
          if (items.length === 0) return null;
          return (
            <div key={g.key}>
              <div className="section-label" style={{ marginBottom: 10 }}>
                {g.label}
              </div>
              <div className="card rowlist">
                {items.map((r) => (
                  <div className="listrow" key={`${r.messageId}-${r.kind}`}>
                    <div className="icon-tile">{r.kind === 'snooze' ? Icons.clock : Icons.bell}</div>
                    <div className="listrow-body">
                      <div className="listrow-top">
                        <b>{r.subject || '(no subject)'}</b>
                        <span className={`chip ${urgencyTone(r.urgency)}`}>{daysLabel(r.daysLeft)}</span>
                      </div>
                      <div className="listrow-meta">
                        {fullDate(r.due)} · {r.kind === 'snooze' ? 'snoozed until then' : 'reminder'}
                      </div>
                      {r.why && <div className="listrow-why">{r.why}</div>}
                      <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
                        <button
                          className="btn btn-ghost btn-sm"
                          disabled={busy === `${r.messageId}-${r.kind}`}
                          onClick={() => dismiss(r)}
                        >
                          {busy === `${r.messageId}-${r.kind}` ? 'Dismissing…' : 'Dismiss'}
                        </button>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          );
        })}
    </AppShell>
  );
}
