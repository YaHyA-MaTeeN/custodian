'use client';

import { useMemo, useState } from 'react';
import { AppShell } from '@/components/AppShell';
import { Icons } from '@/components/Icons';
import { Empty, ErrorBox, Loading } from '@/components/States';
import { api, useApi } from '@/lib/api';
import { fullDate, shortDate } from '@/lib/format';
import type { Action } from '@/lib/types';

export default function ActivityPage() {
  const { data, error, loading, reload } = useApi<{ actions: Action[]; reversible: number }>(
    '/api/activity?limit=120',
  );
  const [busy, setBusy] = useState<number | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [confirming, setConfirming] = useState<Action | null>(null);

  const byDay = useMemo(() => {
    const groups = new Map<string, Action[]>();
    for (const a of data?.actions ?? []) {
      const day = a.at ? new Date(a.at).toDateString() : 'unknown';
      const list = groups.get(day) ?? [];
      list.push(a);
      groups.set(day, list);
    }
    return Array.from(groups.entries());
  }, [data]);

  async function undo(a: Action) {
    setBusy(a.id);
    setProblem(null);
    try {
      await api.post(`/api/activity/${a.id}/undo`);
      setConfirming(null);
      reload();
    } catch (e) {
      setProblem(e instanceof Error ? e.message : String(e));
      setConfirming(null);
    } finally {
      setBusy(null);
    }
  }

  return (
    <AppShell
      title="Activity"
      subtitle="Everything Custodian has done, across every mailbox, in plain words."
      actions={
        <button className="btn btn-ghost btn-sm" onClick={reload}>
          {Icons.refresh}
          Refresh
        </button>
      }
    >
      <div className="notebox">
        {Icons.undo}
        <div>
          Every action recorded what the state was before it, which is what makes undo possible at
          all. An undo is itself an entry — the log is added to, never rewritten.
          {data && ` ${data.reversible} of the entries below can still be reversed.`}
        </div>
      </div>

      {problem && <ErrorBox error={problem} />}
      {error && <ErrorBox error={error} onRetry={reload} />}
      {loading && !data && <div className="card"><Loading rows={5} /></div>}

      {confirming && (
        <div className="card panel" style={{ borderColor: 'var(--accent)' }}>
          <div className="panel-h">
            <h3>Reverse this?</h3>
          </div>
          <div style={{ fontSize: 13, color: 'var(--ink-2)', marginBottom: 6 }}>
            <b style={{ color: 'var(--ink)' }}>
              {confirming.verb} {confirming.detail}
            </b>
          </div>
          <div style={{ fontSize: 12.5, color: 'var(--ink-2)' }}>
            It was done {fullDate(confirming.at)}. The state before it was{' '}
            <span className="mono">{confirming.before || '(not recorded)'}</span>, and that is what
            it will be put back to.
          </div>
          <div style={{ display: 'flex', gap: 9, marginTop: 14 }}>
            <button
              className="btn btn-primary btn-sm"
              disabled={busy === confirming.id}
              onClick={() => undo(confirming)}
            >
              {busy === confirming.id ? 'Reversing…' : 'Yes, put it back'}
            </button>
            <button className="btn btn-ghost btn-sm" onClick={() => setConfirming(null)}>
              Cancel
            </button>
          </div>
        </div>
      )}

      {data && data.actions.length === 0 && (
        <div className="card">
          <Empty title="Nothing has been done yet.">
            Actions appear here as the agent files, archives, reminds and corrects.
          </Empty>
        </div>
      )}

      {byDay.map(([day, actions]) => (
        <div key={day}>
          <div className="section-label" style={{ marginBottom: 10 }}>
            {day}
          </div>
          <div className="card rowlist">
            {actions.map((a) => (
              <div className="listrow" key={a.id}>
                <div className="icon-tile">{Icons.activity}</div>
                <div className="listrow-body">
                  <div className="listrow-top">
                    <b>
                      {a.verb} {a.detail && <span style={{ fontWeight: 500 }}>— {a.detail}</span>}
                    </b>
                    <span className="listrow-time">{shortDate(a.at)}</span>
                  </div>
                  <div className="listrow-why">
                    {a.before ? `before: ${a.before}` : 'nothing to put back'}
                    {a.undone && ' · already reversed'}
                  </div>
                </div>
                {a.reversible ? (
                  <button className="btn btn-ghost btn-sm" onClick={() => setConfirming(a)}>
                    {Icons.undo}
                    Undo
                  </button>
                ) : (
                  <span className="chip chip-neutral" style={{ alignSelf: 'center' }}>
                    {a.undone ? 'undone' : 'final'}
                  </span>
                )}
              </div>
            ))}
          </div>
        </div>
      ))}
    </AppShell>
  );
}
