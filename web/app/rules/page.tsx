'use client';

import { useState } from 'react';
import { AppShell } from '@/components/AppShell';
import { Icons } from '@/components/Icons';
import { Empty, ErrorBox, Loading } from '@/components/States';
import { api, useApi } from '@/lib/api';
import { fullDate } from '@/lib/format';
import type { Rule } from '@/lib/types';

export default function RulesPage() {
  const { data, error, loading, reload } = useApi<{ rules: Rule[] }>('/api/rules');
  const [scope, setScope] = useState<'sender' | 'domain'>('sender');
  const [target, setTarget] = useState('');
  const [shouldBe, setShouldBe] = useState('');
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  async function add(e: React.FormEvent) {
    e.preventDefault();
    if (!target.trim() || !shouldBe.trim()) return;
    setBusy(true);
    setProblem(null);
    try {
      await api.post('/api/rules', { scope, target, should_be: shouldBe, was: '' });
      setTarget('');
      setShouldBe('');
      reload();
    } catch (err) {
      setProblem(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function remove(id: number) {
    setProblem(null);
    try {
      await api.del(`/api/rules/${id}`);
      reload();
    } catch (err) {
      setProblem(err instanceof Error ? err.message : String(err));
    }
  }

  return (
    <AppShell
      title="Rules"
      subtitle="Corrections you have made. These are the settings — there is no preferences screen."
    >
      <div className="notebox">
        {Icons.rules}
        <div>
          A correction is weighted far above any passive signal and takes effect on the next message,
          not after a retraining cycle — it is a lookup, not a weight. The pipeline consults these
          before it trusts anything a model said.
        </div>
      </div>

      <form className="card panel" onSubmit={add}>
        <div className="panel-h">
          <h3>Tell Custodian it got something wrong</h3>
        </div>
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'flex-end' }}>
          <label style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            <span className="section-label">Scope</span>
            <select
              className="filter-chip"
              value={scope}
              onChange={(e) => setScope(e.target.value as 'sender' | 'domain')}
              style={{ padding: '9px 12px' }}
            >
              <option value="sender">This sender</option>
              <option value="domain">This whole domain</option>
            </select>
          </label>
          <label style={{ display: 'flex', flexDirection: 'column', gap: 6, flex: '1 1 240px' }}>
            <span className="section-label">{scope === 'sender' ? 'Email address' : 'Domain'}</span>
            <input
              className="searchbox"
              style={{ padding: '10px 13px' }}
              placeholder={scope === 'sender' ? 'hira.r@partner-co.com' : 'fbr.gov.pk'}
              value={target}
              onChange={(e) => setTarget(e.target.value)}
              required
            />
          </label>
          <label style={{ display: 'flex', flexDirection: 'column', gap: 6, flex: '1 1 280px' }}>
            <span className="section-label">What should happen instead</span>
            <input
              className="searchbox"
              style={{ padding: '10px 13px' }}
              placeholder="always show me — never file this"
              value={shouldBe}
              onChange={(e) => setShouldBe(e.target.value)}
              required
            />
          </label>
          <button className="btn btn-primary" type="submit" disabled={busy}>
            {Icons.plus}
            {busy ? 'Saving…' : 'Add rule'}
          </button>
        </div>
      </form>

      {problem && <ErrorBox error={problem} />}
      {error && <ErrorBox error={error} onRetry={reload} />}
      {loading && !data && <div className="card"><Loading rows={3} /></div>}

      {data && data.rules.length === 0 && (
        <div className="card">
          <Empty title="No corrections yet.">
            That is the expected state at the start — rules exist because something went wrong once,
            not because a form asked you to fill them in.
          </Empty>
        </div>
      )}

      {data && data.rules.length > 0 && (
        <div className="card rowlist">
          {data.rules.map((r) => (
            <div className="listrow" key={r.id}>
              <div className="icon-tile">{Icons.rules}</div>
              <div className="listrow-body">
                <div className="listrow-top">
                  <b>
                    {r.scope === 'domain' ? 'Anything from ' : 'Mail from '}
                    <span className="mono">{r.target}</span> → {r.shouldBe}
                  </b>
                  <span className="listrow-time">{fullDate(r.at)}</span>
                </div>
                <div className="listrow-why">
                  {r.was ? `was: ${r.was} · ` : ''}
                  recorded from the {r.source === 'app' ? 'app' : 'mailbox'}
                </div>
              </div>
              <button className="btn btn-ghost btn-sm" onClick={() => remove(r.id)}>
                {Icons.x}
                Delete
              </button>
            </div>
          ))}
        </div>
      )}
    </AppShell>
  );
}
