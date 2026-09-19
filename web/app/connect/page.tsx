'use client';

import { AppShell } from '@/components/AppShell';
import { Icons } from '@/components/Icons';
import { ErrorBox, Loading } from '@/components/States';
import { useApi } from '@/lib/api';
import { shortDate } from '@/lib/format';
import type { Account, Health } from '@/lib/types';

const PERMISSIONS = [
  ['Read', 'To classify and file. The message text is never stored — only what we conclude from it.'],
  ['Label & archive', "To sort, snooze and clear, using your mailbox's own labels and folders."],
  ['Send as you', 'Only ever used after you approve one specific draft, on WhatsApp.'],
  ['Calendar', 'So a deadline we find can also sit on your calendar, if you want that.'],
];

export default function ConnectPage() {
  const health = useApi<Health>('/api/health');
  const accounts = useApi<{ accounts: Account[] }>('/api/accounts');
  const mailbox = health.data?.mailbox;

  return (
    <AppShell
      title="Mailboxes"
      subtitle="Which doors are open, what they can do, and what that permission actually allows."
    >
      {health.error && <ErrorBox error={health.error} onRetry={health.reload} />}
      {health.loading && !health.data && <div className="card"><Loading rows={3} /></div>}

      {mailbox && (
        <div className="card panel">
          <div className="panel-h">
            <h3>Right now</h3>
            <span className={`chip ${mailbox.connected ? 'chip-plain' : 'chip-amber'}`}>
              {mailbox.connected ? 'open' : 'closed'}
            </span>
          </div>
          {mailbox.connected ? (
            <>
              <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                <div className="icon-tile">{Icons.mail}</div>
                <div>
                  <b style={{ fontSize: 14 }}>{mailbox.account}</b>
                  <div style={{ fontSize: 12.5, color: 'var(--ink-2)' }}>
                    connected through {mailbox.door}
                  </div>
                </div>
              </div>
              <div style={{ display: 'flex', gap: 7, flexWrap: 'wrap', marginTop: 14 }}>
                {Object.entries(mailbox.capabilities).map(([cap, on]) => (
                  <span key={cap} className={`chip ${on ? 'chip-accent' : 'chip-neutral'}`}>
                    {cap}
                    {on ? '' : ' — no'}
                  </span>
                ))}
              </div>
              <p style={{ fontSize: 12.5, color: 'var(--ink-2)', marginTop: 14, marginBottom: 0, lineHeight: 1.6 }}>
                The pipeline was never told which door this is. It asks a connector what it can do,
                never who it is — which is why a third kind of mailbox is one new file and nothing
                else changes.
              </p>
            </>
          ) : (
            <div style={{ fontSize: 13, color: 'var(--ink-2)' }}>
              {mailbox.disabled
                ? 'The API was started with --no-mailbox, so every screen here is reading the local database only. Restart it without that flag to open the mailbox.'
                : mailbox.error
                  ? `The mailbox did not open: ${mailbox.error}`
                  : 'No mailbox is open. Run python connect.py at the keyboard to sign in, then restart the API.'}
            </div>
          )}
        </div>
      )}

      <div className="card">
        <div className="panel" style={{ paddingBottom: 0 }}>
          <div className="panel-h">
            <h3>Mailboxes this database has seen</h3>
          </div>
        </div>
        {accounts.loading && !accounts.data && <Loading rows={2} />}
        <div className="rowlist">
          {accounts.data?.accounts.map((a) => (
            <div className="listrow" key={a.account}>
              <div className="icon-tile">{Icons.mail}</div>
              <div className="listrow-body">
                <div className="listrow-top">
                  <b>{a.account}</b>
                  <span className={`chip ${a.live ? 'chip-plain' : 'chip-neutral'}`}>
                    {a.live ? `open · ${a.door}` : 'not open now'}
                  </span>
                </div>
                <div className="listrow-meta">
                  {a.messages.toLocaleString()} messages · newest {shortDate(a.lastSeen)}
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="card">
        <div className="panel" style={{ paddingBottom: 0 }}>
          <div className="panel-h">
            <h3>What connecting a mailbox grants</h3>
          </div>
        </div>
        <div className="rowlist">
          {PERMISSIONS.map(([name, what]) => (
            <div className="listrow" key={name}>
              <span style={{ color: 'var(--plain)', marginTop: 2 }}>{Icons.check}</span>
              <div className="listrow-body">
                <div className="listrow-top">
                  <b>{name}</b>
                </div>
                <div className="listrow-meta">{what}</div>
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="notebox">
        {Icons.shield}
        <div>
          Permanent delete is never requested, and no function in this codebase performs one. Two
          independent barriers, not a setting — which is also why everything Custodian does can be
          put back.
        </div>
      </div>
    </AppShell>
  );
}
