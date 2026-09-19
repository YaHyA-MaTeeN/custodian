'use client';

import { Suspense, useEffect, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import { AppShell } from '@/components/AppShell';
import { Icons } from '@/components/Icons';
import { Empty, ErrorBox, Loading } from '@/components/States';
import { useApi } from '@/lib/api';
import { fullDate, initials, kindChip, shortDate } from '@/lib/format';
import type { Account, Message, MessageDetail } from '@/lib/types';

const VIEWS = [
  { key: 'all', label: 'Everything' },
  { key: 'people', label: 'Possibly a person' },
  { key: 'reply', label: 'Needs a reply' },
  { key: 'machine', label: 'Machines' },
  { key: 'held', label: 'Text held' },
] as const;

function InboxInner() {
  const params = useSearchParams();
  const [view, setView] = useState<string>(params.get('view') ?? 'all');
  const [account, setAccount] = useState<string>('');
  const [query, setQuery] = useState<string>('');
  const [debounced, setDebounced] = useState<string>('');
  const [selected, setSelected] = useState<string | null>(params.get('open'));

  // Envelope search (UC-28, BR-102). Typing should not fire a request per key.
  useEffect(() => {
    const t = setTimeout(() => setDebounced(query.trim()), 250);
    return () => clearTimeout(t);
  }, [query]);

  const listPath =
    `/api/messages?view=${view}` +
    (account ? `&account=${encodeURIComponent(account)}` : '') +
    (debounced ? `&q=${encodeURIComponent(debounced)}` : '');

  const list = useApi<{ total: number; messages: Message[] }>(listPath);
  const { data: accounts } = useApi<{ accounts: Account[] }>('/api/accounts');
  const detail = useApi<MessageDetail>(selected ? `/api/messages/${encodeURIComponent(selected)}` : null);

  // Nothing chosen yet: open the first row, so the pane is never an empty box.
  useEffect(() => {
    if (!selected && list.data && list.data.messages.length > 0) {
      setSelected(list.data.messages[0].id);
    }
  }, [list.data, selected]);

  return (
    <AppShell
      title="Unified inbox"
      subtitle="One list across every connected mailbox. Each row carries the reason it is where it is."
      actions={
        <div className="searchbox" style={{ minWidth: 280 }}>
          {Icons.search}
          <input
            aria-label="Search every connected mailbox"
            placeholder="Search sender, subject, account…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
      }
    >
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center' }}>
        {VIEWS.map((v) => (
          <button
            key={v.key}
            className={view === v.key ? 'filter-chip on' : 'filter-chip'}
            onClick={() => setView(v.key)}
          >
            {v.label}
          </button>
        ))}
        <span style={{ flex: 1 }} />
        {(accounts?.accounts?.length ?? 0) > 1 && (
          <select
            className="filter-chip"
            value={account}
            onChange={(e) => setAccount(e.target.value)}
            aria-label="Filter by mailbox"
          >
            <option value="">All accounts</option>
            {accounts?.accounts.map((a) => (
              <option key={a.account} value={a.account}>
                {a.account}
              </option>
            ))}
          </select>
        )}
        {list.data && (
          <span className="section-label">{list.data.total} shown</span>
        )}
      </div>

      {list.error && <ErrorBox error={list.error} onRetry={list.reload} />}

      <div style={{ display: 'grid', gridTemplateColumns: '400px minmax(0,1fr)', gap: 20, alignItems: 'start' }}>
        <div className="card" style={{ maxHeight: '72vh', overflow: 'auto' }}>
          {list.loading && !list.data && <Loading rows={6} />}
          {list.data && list.data.messages.length === 0 && (
            <Empty title="Nothing matches that.">
              {debounced
                ? 'Search covers the envelope only — sender, subject, account. The words inside a message are not held, so they cannot be searched.'
                : 'No messages in this view yet.'}
            </Empty>
          )}
          <div className="rowlist">
            {list.data?.messages.map((m) => {
              const chip = kindChip(m.kind);
              const isSel = m.id === selected;
              return (
                <button
                  key={m.id}
                  onClick={() => setSelected(m.id)}
                  className="listrow"
                  style={{
                    width: '100%',
                    textAlign: 'left',
                    background: isSel ? 'var(--accent-soft)' : 'transparent',
                    border: 'none',
                    borderBottom: '1px solid var(--rule-soft)',
                  }}
                >
                  <div className="avatar">{initials(m.senderName, m.sender)}</div>
                  <div className="listrow-body">
                    <div className="listrow-top">
                      <b style={{ fontWeight: m.unread ? 700 : 500 }}>
                        {m.senderName || m.sender}
                      </b>
                      <span className="listrow-time">{shortDate(m.date)}</span>
                    </div>
                    <div className="listrow-meta" style={{ color: 'var(--ink)' }}>
                      {m.subject || '(no subject)'}
                    </div>
                    <div style={{ display: 'flex', gap: 6, marginTop: 8, flexWrap: 'wrap' }}>
                      <span className={`chip ${chip.tone}`}>{chip.label}</span>
                      {m.held && <span className="chip chip-plain">text held</span>}
                    </div>
                  </div>
                </button>
              );
            })}
          </div>
        </div>

        <div className="card panel" style={{ minHeight: 320 }}>
          {!selected && <Empty title="Choose a message." />}
          {selected && detail.loading && !detail.data && <Loading rows={5} />}
          {selected && detail.error && <ErrorBox error={detail.error} onRetry={detail.reload} />}
          {detail.data && <Detail m={detail.data} />}
        </div>
      </div>
    </AppShell>
  );
}

function Detail({ m }: { m: MessageDetail }) {
  const chip = kindChip(m.kind);
  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 16, alignItems: 'flex-start' }}>
        <div>
          <h2 style={{ fontSize: 20 }}>{m.subject || '(no subject)'}</h2>
          <div style={{ fontSize: 12.5, color: 'var(--ink-2)', marginTop: 6 }}>
            {m.senderName ? `${m.senderName} · ` : ''}
            {m.sender} · to {m.account} · {fullDate(m.date)}
          </div>
        </div>
        <span className={`chip ${chip.tone}`}>{chip.label}</span>
      </div>

      {/*
        UC-29 step 1.1 — the reason is already on the item. Nobody should have
        to go looking for why a message was treated the way it was.
      */}
      <div
        style={{
          marginTop: 16,
          background: 'var(--ask-soft)',
          border: '1px solid color-mix(in srgb, var(--ask) 22%, transparent)',
          borderRadius: 8,
          padding: '12px 16px',
          fontSize: 12.5,
        }}
      >
        <b style={{ color: 'var(--ask)' }}>Why: </b>
        {m.why}
      </div>

      {m.decisions.length > 0 && (
        <div style={{ marginTop: 14 }}>
          <div className="section-label" style={{ marginBottom: 8 }}>
            Decisions on record
          </div>
          <div className="card" style={{ boxShadow: 'none' }}>
            <table className="data">
              <thead>
                <tr>
                  <th>Stage</th>
                  <th>Decided</th>
                  <th>Reason</th>
                  <th>Score</th>
                </tr>
              </thead>
              <tbody>
                {m.decisions.map((d) => (
                  <tr key={d.stage}>
                    <td className="mono">{d.stage}</td>
                    <td>{d.decision}</td>
                    <td style={{ color: 'var(--ink-2)' }}>{d.reason}</td>
                    <td className="mono">{d.score === null ? '—' : d.score.toFixed(2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <div style={{ marginTop: 18 }}>
        {m.blocked ? (
          <div className="errorbox">
            <b>Not opened.</b>
            <div style={{ marginTop: 6 }}>{m.why}</div>
            <div style={{ marginTop: 10, color: 'var(--ink-2)' }}>
              This kind of mail is never read — not from a cache, not live. You are told it arrived
              and nothing more.
            </div>
          </div>
        ) : (
          <>
            <pre
              style={{
                whiteSpace: 'pre-wrap',
                wordWrap: 'break-word',
                font: '13.5px/1.7 var(--f-body)',
                background: 'var(--surface-2)',
                border: '1px solid var(--rule-soft)',
                borderRadius: 8,
                padding: '18px 20px',
                margin: 0,
                maxHeight: 360,
                overflow: 'auto',
              }}
            >
              {m.body || '(nothing to show)'}
            </pre>
            <div className="mono" style={{ fontSize: 11, color: 'var(--ink-3)', marginTop: 8 }}>
              {m.bodySource}
            </div>
          </>
        )}
      </div>

      {/*
        ⚠️ No Send button, and not because it is unbuilt.
        A draft leaves under the Owner's name, and the approval for that lives
        on WhatsApp where the person actually is. A second approval surface
        here would be a second place for a wrong yes to happen.
      */}
      <div className="notebox" style={{ marginTop: 18 }}>
        {Icons.shield}
        <div>
          Replies are approved on WhatsApp, not here. This screen reads the mailbox and shows the
          agent's reasoning; nothing on it can send in your name.
        </div>
      </div>
    </div>
  );
}

export default function InboxPage() {
  return (
    <Suspense fallback={<div className="state">Loading…</div>}>
      <InboxInner />
    </Suspense>
  );
}
