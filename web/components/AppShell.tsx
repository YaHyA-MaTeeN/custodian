'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import type { ReactNode } from 'react';
import { Icons } from './Icons';
import { useApi } from '@/lib/api';
import type { Health } from '@/lib/types';

const NAV: { href: string; label: string; icon: keyof typeof Icons }[] = [
  { href: '/', label: 'Dashboard', icon: 'dashboard' },
  { href: '/inbox', label: 'Inbox', icon: 'inbox' },
  { href: '/deadlines', label: 'Deadlines', icon: 'radar' },
  { href: '/cleanup', label: 'Cleanup', icon: 'cleanup' },
  { href: '/rules', label: 'Rules', icon: 'rules' },
  { href: '/activity', label: 'Activity', icon: 'activity' },
  { href: '/digest', label: 'Digest', icon: 'digest' },
  { href: '/privacy', label: 'Privacy & data', icon: 'privacy' },
  { href: '/connect', label: 'Mailboxes', icon: 'plug' },
];

function Sidebar({ health }: { health: Health | null }) {
  const pathname = usePathname();
  const mailbox = health?.mailbox;

  return (
    <aside className="sidebar">
      <div>
        <div className="wordmark">
          <span className="wm-dot" />
          Custodian
        </div>
        <div className="wm-sub">Inbox agent</div>
      </div>

      <nav className="side-nav">
        {NAV.map((item) => {
          const active =
            item.href === '/' ? pathname === '/' : pathname.startsWith(item.href);
          return (
            <Link key={item.href} href={item.href} className={active ? 'navitem active' : 'navitem'}>
              {Icons[item.icon]}
              <span>{item.label}</span>
            </Link>
          );
        })}
      </nav>

      <div className="side-foot">
        {/*
          The connection state is not decoration. Every screen behind this
          sidebar is read out of the local database, and some of them can only
          do half their job when the mailbox itself is closed — so it says
          which of the two it is, always, rather than only when something
          fails.
        */}
        <div className={mailbox?.connected ? 'foot-row ok' : 'foot-row off'}>
          {mailbox?.connected ? Icons.check : Icons.clock}
          <div className="foot-text">
            <b>{mailbox?.connected ? mailbox.account || 'mailbox open' : 'database only'}</b>
            <span>
              {mailbox?.connected
                ? `${mailbox.door} · live`
                : mailbox?.disabled
                  ? 'started with --no-mailbox'
                  : 'no mailbox opened'}
            </span>
          </div>
        </div>
        {health && (
          <div style={{ fontFamily: 'var(--f-mono)', fontSize: 10.5, color: 'var(--ink-3)', paddingLeft: 2 }}>
            {health.counts.messages.toLocaleString()} headers · {health.counts.bodies} texts held
          </div>
        )}
      </div>
    </aside>
  );
}

export function AppShell({
  title,
  subtitle,
  actions,
  children,
}: {
  title: string;
  subtitle?: string;
  actions?: ReactNode;
  children: ReactNode;
}) {
  const { data: health } = useApi<Health>('/api/health');

  return (
    <div className="appshell">
      <Sidebar health={health} />
      <div className="main">
        <div className="topbar">
          <div>
            <h1>{title}</h1>
            {subtitle && <div className="sub">{subtitle}</div>}
          </div>
          <div className="topbar-actions">{actions}</div>
        </div>
        <div className="content">{children}</div>
      </div>
    </div>
  );
}
