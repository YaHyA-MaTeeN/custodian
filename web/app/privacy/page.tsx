'use client';

import { useState } from 'react';
import { AppShell } from '@/components/AppShell';
import { Icons } from '@/components/Icons';
import { ErrorBox, Loading } from '@/components/States';
import { api, useApi } from '@/lib/api';
import { fullDate } from '@/lib/format';
import type { Privacy } from '@/lib/types';

export default function PrivacyPage() {
  const { data, error, loading, reload } = useApi<Privacy>('/api/privacy');
  const [exported, setExported] = useState<{ path: string; sizeMb: number } | null>(null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  async function exportAll() {
    setBusy(true);
    setProblem(null);
    try {
      const res = await api.post<{ path: string; sizeMb: number }>('/api/privacy/export');
      setExported(res);
    } catch (e) {
      setProblem(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <AppShell
      title="Privacy & data"
      subtitle="We read, but we don't keep — and here is the row count behind that sentence."
    >
      {error && <ErrorBox error={error} onRetry={reload} />}
      {problem && <ErrorBox error={problem} />}
      {loading && !data && <div className="card"><Loading rows={5} /></div>}

      {data && (
        <>
          <div className="notebox">
            {Icons.shield}
            <div>
              {data.neverHeld} Message text that is kept lives in a bounded window of{' '}
              {data.retentionDays} days and is trimmed in code every time the app starts — not by a
              policy page.
            </div>
          </div>

          <div className="card">
            <div className="panel" style={{ paddingBottom: 0 }}>
              <div className="panel-h">
                <h3>How deep anything was read</h3>
              </div>
            </div>
            <table className="data">
              <thead>
                <tr>
                  <th>Depth</th>
                  <th>What it sees</th>
                  <th>Messages</th>
                  <th>Share</th>
                </tr>
              </thead>
              <tbody>
                {data.depths.map((d) => (
                  <tr key={d.depth}>
                    <td>
                      <span
                        className={`chip ${
                          d.depth === 1 ? 'chip-plain' : d.depth === 3 ? 'chip-accent' : 'chip-amber'
                        }`}
                      >
                        depth {d.depth}
                      </span>
                    </td>
                    <td>{d.sees}</td>
                    <td className="mono">{d.count.toLocaleString()}</td>
                    <td className="mono">{d.share}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="card">
            <div className="panel" style={{ paddingBottom: 0 }}>
              <div className="panel-h">
                <h3>What has actually left this machine</h3>
                <span className="section-label">{data.passport.length} recorded</span>
              </div>
            </div>
            {data.passport.length === 0 ? (
              <div className="state">
                <b>Nothing has left this machine.</b>
                No message has been escalated to a rented model yet. When one is, it appears here
                with the reason it was sent and what was removed first.
              </div>
            ) : (
              <table className="data">
                <thead>
                  <tr>
                    <th>When</th>
                    <th>Stage</th>
                    <th>What</th>
                    <th>Why</th>
                  </tr>
                </thead>
                <tbody>
                  {data.passport.map((p, i) => (
                    <tr key={i}>
                      <td className="mono">{fullDate(p.at)}</td>
                      <td className="mono">{p.stage}</td>
                      <td>{p.what}</td>
                      <td style={{ color: 'var(--ink-2)' }}>{p.reason}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>

          <div className="card">
            <div className="panel" style={{ paddingBottom: 0 }}>
              <div className="panel-h">
                <h3>Everything we hold about you</h3>
              </div>
            </div>
            <table className="data">
              <thead>
                <tr>
                  <th>Rows</th>
                  <th>Table</th>
                  <th>In plain words</th>
                </tr>
              </thead>
              <tbody>
                {data.holdings.map((h) => (
                  <tr key={h.table}>
                    <td className="mono">{h.rows.toLocaleString()}</td>
                    <td className="mono">{h.table}</td>
                    <td style={{ color: 'var(--ink-2)' }}>{h.plain}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
            <div className="card panel">
              <h3 style={{ fontSize: 15, marginBottom: 6 }}>Export everything</h3>
              <p style={{ fontSize: 12.5, color: 'var(--ink-2)', margin: '0 0 14px', lineHeight: 1.55 }}>
                Written as readable JSON, next to the database on this machine. Nothing is uploaded
                anywhere to produce it.
              </p>
              <button className="btn btn-ghost" onClick={exportAll} disabled={busy}>
                {Icons.download}
                {busy ? 'Writing…' : 'Write the export file'}
              </button>
              {exported && (
                <div style={{ marginTop: 12, fontSize: 12.5, color: 'var(--plain)' }}>
                  Written: <span className="mono">{exported.path}</span> ({exported.sizeMb} MB)
                </div>
              )}
            </div>

            <div className="card panel">
              <h3 style={{ fontSize: 15, marginBottom: 6 }}>Erase everything</h3>
              <p style={{ fontSize: 12.5, color: 'var(--ink-2)', margin: '0 0 14px', lineHeight: 1.55 }}>
                {/*
                  ⚠️ Deliberately not a button. An erasure request is exactly
                  what an attacker would send, and a web page cannot tell who is
                  on the other end of it. It stays where identity is certain.
                */}
                Erasure is not exposed to the browser. It disconnects every mailbox and destroys
                everything learned, so it runs where identity is certain — at the keyboard, with{' '}
                <span className="mono">python my_data.py --erase</span>. Your mailbox itself is left
                exactly as it is.
              </p>
              <button className="btn btn-danger" disabled>
                Only at the keyboard
              </button>
            </div>
          </div>
        </>
      )}
    </AppShell>
  );
}
