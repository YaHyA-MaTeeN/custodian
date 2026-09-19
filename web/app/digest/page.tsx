'use client';

import { useState } from 'react';
import { AppShell } from '@/components/AppShell';
import { Icons } from '@/components/Icons';
import { ErrorBox, Loading } from '@/components/States';
import { useApi } from '@/lib/api';
import { daysLabel, fullDate } from '@/lib/format';
import type { Digest } from '@/lib/types';

const PERIODS = [
  { days: 1, label: 'Daily' },
  { days: 7, label: 'Weekly' },
  { days: 30, label: 'Monthly' },
];

export default function DigestPage() {
  const [days, setDays] = useState(7);
  const { data, error, loading, reload } = useApi<Digest>(`/api/digest?days=${days}`);

  return (
    <AppShell
      title="Digest"
      subtitle="One message, on your schedule, covering every mailbox. Never a stream."
      actions={
        <button className="btn btn-ghost btn-sm" onClick={reload}>
          {Icons.refresh}
          Rebuild
        </button>
      }
    >
      <div style={{ display: 'grid', gridTemplateColumns: '300px minmax(0,1fr)', gap: 24, alignItems: 'start' }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
          <div className="card panel">
            <h3 style={{ fontSize: 15, marginBottom: 6 }}>Period</h3>
            <p style={{ fontSize: 12, color: 'var(--ink-2)', margin: '0 0 12px' }}>
              A quiet period sends nothing at all. Silence is a correct outcome, not a failure.
            </p>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {PERIODS.map((p) => (
                <button
                  key={p.days}
                  className={days === p.days ? 'filter-chip on' : 'filter-chip'}
                  style={{ justifyContent: 'flex-start', padding: '10px 14px', borderRadius: 7 }}
                  onClick={() => setDays(p.days)}
                >
                  {p.label}
                </button>
              ))}
            </div>
          </div>

          <div className="card panel">
            <h3 style={{ fontSize: 15, marginBottom: 8 }}>Where this goes</h3>
            <p style={{ fontSize: 12.5, color: 'var(--ink-2)', margin: 0, lineHeight: 1.6 }}>
              In the product this arrives as one WhatsApp message, so someone who never opens this
              app still learns everything that happened. This page is the same content, rendered for
              a screen.
            </p>
          </div>
        </div>

        <div>
          {error && <ErrorBox error={error} onRetry={reload} />}
          {loading && !data && <div className="card"><Loading rows={6} /></div>}

          {data && !data.worthSending && (
            <div className="card panel">
              <h3 style={{ fontSize: 17 }}>Nothing would be sent.</h3>
              <p style={{ fontSize: 13.5, color: 'var(--ink-2)', marginTop: 8 }}>
                Nothing happened in the last {data.periodDays} day{data.periodDays === 1 ? '' : 's'}{' '}
                that is worth a message. No digest goes out, and that is recorded as the correct
                outcome rather than as an empty send.
              </p>
            </div>
          )}

          {data && data.worthSending && (
            <div className="card panel">
              <div className="panel-h">
                <div>
                  <h3 style={{ fontSize: 18 }}>
                    Your {days === 1 ? 'day' : days === 7 ? 'week' : 'month'} with Custodian
                  </h3>
                  <div style={{ fontSize: 12, color: 'var(--ink-3)', marginTop: 4 }}>
                    built {fullDate(data.generatedAt)}
                  </div>
                </div>
                <span className="chip chip-accent">would send</span>
              </div>

              <Section title="Sorted and cleared">
                {Object.keys(data.sections.sortedAndCleared).length === 0 ? (
                  <Line>Nothing was acted on.</Line>
                ) : (
                  Object.entries(data.sections.sortedAndCleared).map(([verb, n]) => (
                    <Line key={verb}>
                      <b>{n}</b> {verb}
                    </Line>
                  ))
                )}
                <Line>
                  <b>{data.sections.handledQuietly}</b> handled without asking you
                </Line>
              </Section>

              <Section title="Waiting on you">
                {data.sections.needsReply.length === 0 ? (
                  <Line>Nothing needs a reply.</Line>
                ) : (
                  data.sections.needsReply.map((m) => (
                    <Line key={m.id}>
                      <b>{m.senderName || m.sender}</b> — {m.subject || '(no subject)'}
                    </Line>
                  ))
                )}
              </Section>

              <Section title="Ahead, not urgent enough to interrupt">
                {data.sections.deadlinesAhead.length === 0 ? (
                  <Line>Nothing on the radar.</Line>
                ) : (
                  data.sections.deadlinesAhead.map((d) => (
                    <Line key={`${d.messageId}-${d.kind}`}>
                      <b>{d.subject}</b> — {daysLabel(d.daysLeft)}
                    </Line>
                  ))
                )}
              </Section>

              {data.sections.learned.length > 0 && (
                <Section title="What it learned from you">
                  {data.sections.learned.map((l, i) => (
                    <Line key={i}>
                      <span className="mono">{l.target}</span> → {l.shouldBe}
                    </Line>
                  ))}
                </Section>
              )}
            </div>
          )}
        </div>
      </div>
    </AppShell>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{ marginTop: 18 }}>
      <div className="section-label" style={{ marginBottom: 8 }}>
        {title}
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>{children}</div>
    </div>
  );
}

function Line({ children }: { children: React.ReactNode }) {
  return (
    <div
      style={{
        fontSize: 13,
        color: 'var(--ink-2)',
        paddingLeft: 14,
        borderLeft: '2px solid var(--rule)',
      }}
    >
      {children}
    </div>
  );
}
