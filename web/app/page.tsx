'use client';

import Link from 'next/link';
import { AppShell } from '@/components/AppShell';
import { Icons } from '@/components/Icons';
import { Empty, ErrorBox, Loading } from '@/components/States';
import { useApi } from '@/lib/api';
import { daysLabel, fullDate, initials, shortDate, urgencyTone } from '@/lib/format';
import type { Account, Overview } from '@/lib/types';

export default function DashboardPage() {
  const { data, error, loading, reload } = useApi<Overview>('/api/overview');
  const { data: accounts } = useApi<{ accounts: Account[] }>('/api/accounts');

  return (
    <AppShell
      title="Dashboard"
      subtitle="What the agent did, and the few things it could not decide alone."
      actions={
        <button className="btn btn-ghost btn-sm" onClick={reload}>
          {Icons.refresh}
          Refresh
        </button>
      }
    >
      {error && <ErrorBox error={error} onRetry={reload} />}
      {loading && !data && <div className="card"><Loading rows={4} /></div>}

      {data && (
        <>
          <div className="stat-row">
            <div className="card stat-card">
              <div className="n">{data.stats.headersHeld.toLocaleString()}</div>
              <div className="l">headers held — every email, ever</div>
              <div className="foot">{data.stats.bodiesHeld} texts kept ({data.stats.bodiesMb} MB)</div>
            </div>
            <div className="card stat-card">
              <div className="n accent">{data.stats.needsReply}</div>
              <div className="l">need a reply</div>
              {/* The denominator travels with the number. "0 need a reply" and
                  "nothing has been scored yet" are different facts. */}
              <div className="foot">of {data.stats.scored} scored so far</div>
            </div>
            <div className="card stat-card">
              <div className="n">{data.stats.handledWithoutAsking}</div>
              <div className="l">handled without asking you</div>
              <div className="foot">{data.stats.actionsThisWeek} actions this week</div>
            </div>
            <div className="card stat-card">
              <div className="n">{data.remindersDue.length}</div>
              <div className="l">reminders due now</div>
              <div className="foot">{data.remindersPending.length} more being watched</div>
            </div>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1.45fr 1fr', gap: 22, alignItems: 'start' }}>
            <div className="card">
              <div className="panel" style={{ paddingBottom: 0 }}>
                <div className="panel-h">
                  <h3>Needs you</h3>
                  <Link href="/inbox?view=reply">Open inbox {Icons.chevron}</Link>
                </div>
              </div>
              {data.needsYou.length === 0 ? (
                <Empty title="Nothing is waiting on you.">
                  Either the gate scored everything as no-reply, or nothing has been scored yet —
                  run <code>python agent.py</code> to score the backlog.
                </Empty>
              ) : (
                <div className="rowlist">
                  {data.needsYou.map((m) => (
                    <div className="listrow" key={m.id}>
                      <div className="avatar">{initials(m.senderName, m.sender)}</div>
                      <div className="listrow-body">
                        <div className="listrow-top">
                          <b>{m.senderName || m.sender}</b>
                          <span className="listrow-time">{shortDate(m.date)}</span>
                        </div>
                        <div className="listrow-meta">{m.subject || '(no subject)'}</div>
                        <div className="listrow-why">{m.why}</div>
                        <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
                          <Link className="btn btn-ghost btn-sm" href={`/inbox?open=${encodeURIComponent(m.id)}`}>
                            Open
                          </Link>
                          <span className="chip chip-ask" style={{ alignSelf: 'center' }}>
                            needs a reply
                          </span>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: 22 }}>
              <div className="card">
                <div className="panel" style={{ paddingBottom: 0 }}>
                  <div className="panel-h">
                    <h3>Deadline radar</h3>
                    <Link href="/deadlines">All {Icons.chevron}</Link>
                  </div>
                </div>
                {data.remindersDue.length === 0 && data.remindersPending.length === 0 ? (
                  <Empty title="Nothing with a date yet.">
                    Commitments are recorded by stage 16 as mail is processed.
                  </Empty>
                ) : (
                  <div className="rowlist">
                    {[...data.remindersDue].slice(0, 5).map((r) => (
                      <div className="listrow" key={`${r.messageId}-${r.kind}`}>
                        <div className="icon-tile">{Icons.bell}</div>
                        <div className="listrow-body">
                          <div className="listrow-top">
                            <b>{r.subject || '(no subject)'}</b>
                            <span className={`chip ${urgencyTone(r.urgency)}`}>{daysLabel(r.daysLeft)}</span>
                          </div>
                          <div className="listrow-meta">{r.why || r.kind}</div>
                        </div>
                      </div>
                    ))}
                    {data.remindersPending.slice(0, 3).map((r) => (
                      <div className="listrow" key={`${r.messageId}-${r.kind}-pending`}>
                        <div className="icon-tile">{Icons.clock}</div>
                        <div className="listrow-body">
                          <div className="listrow-top">
                            <b>{r.subject || '(no subject)'}</b>
                            <span className={`chip ${urgencyTone(r.urgency)}`}>{daysLabel(r.daysLeft)}</span>
                          </div>
                          <div className="listrow-meta">
                            being watched · {shortDate(r.due)}
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              <div className="card">
                <div className="panel" style={{ paddingBottom: 0 }}>
                  <div className="panel-h">
                    <h3>Your mailboxes</h3>
                    <Link href="/connect">Manage {Icons.chevron}</Link>
                  </div>
                </div>
                <div className="rowlist">
                  {(accounts?.accounts ?? []).map((a) => (
                    <div className="listrow" key={a.account}>
                      <div className="icon-tile">{Icons.mail}</div>
                      <div className="listrow-body">
                        <div className="listrow-top">
                          <b>{a.account}</b>
                          <span
                            className="dot"
                            style={{ background: a.live ? 'var(--plain)' : 'var(--ink-3)' }}
                          />
                        </div>
                        <div className="listrow-meta">
                          {a.messages.toLocaleString()} messages · last {shortDate(a.lastSeen)}
                          {a.live ? ` · open through ${a.door}` : ' · not open right now'}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              <div className="card">
                <div className="panel" style={{ paddingBottom: 0 }}>
                  <div className="panel-h">
                    <h3>Recent activity</h3>
                    <Link href="/activity">Full log {Icons.chevron}</Link>
                  </div>
                </div>
                {data.recentActivity.length === 0 ? (
                  <Empty title="Nothing has been done yet." />
                ) : (
                  <div className="rowlist">
                    {data.recentActivity.map((a) => (
                      <div className="listrow" key={a.id} style={{ padding: '12px 22px' }}>
                        <span
                          className="dot"
                          style={{ marginTop: 7, background: a.undone ? 'var(--ink-3)' : 'var(--plain)' }}
                        />
                        <div className="listrow-body">
                          <div className="listrow-top">
                            <span style={{ fontSize: 12.5 }}>
                              {a.verb} <b>{a.detail || '—'}</b>
                            </span>
                            <span className="listrow-time">{shortDate(a.at)}</span>
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </div>

          <div className="notebox">
            {Icons.shield}
            <div>
              Every reason on these screens was recorded by the pipeline at the moment it decided,
              not reconstructed afterwards. Nothing here re-decides anything, and nothing on this
              page can send mail — that gate lives in the code, not in a setting.
              <span style={{ color: 'var(--ink-3)' }}> Last read {fullDate(new Date().toISOString())}.</span>
            </div>
          </div>
        </>
      )}
    </AppShell>
  );
}
