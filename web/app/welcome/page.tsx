import Link from 'next/link';
import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Custodian — an agent that runs your inbox for you',
  description:
    'It clears the rubbish by itself, and asks you on WhatsApp before it sends anything as you.',
};

const STATS = [
  ['~126', 'emails a knowledge worker gets, per day'],
  ['2.6–3.1h', 'spent on email every day — 28% of the workweek'],
  ['24%', 'of that mail is actually relevant to them'],
  ['74×', 'times a day they check, just in case'],
];

const LAYERS = [
  ['LAYER 1', 'Header rules', 'Our own code. Microseconds. Handles most of what arrives.', 'Free'],
  ['LAYER 2', 'Libraries', 'Dates, amounts, and structured data senders already embed.', 'Free'],
  ['LAYER 3', 'Our own model', 'A small classifier that runs on our own CPU, in milliseconds.', 'Free'],
  ['LAYER 4', 'Rented model', 'Writing only. Never classification. Names removed first.', 'Metered'],
];

const TRUST = [
  ['Sensitive mail is read least', 'Bank, government and account-security mail is detected from sender and subject alone — before anything opens it. Not our model, not a rented one, nobody.'],
  ['Names never leave', 'Before a draft reaches an external model, every name, address and number is replaced with a placeholder and restored locally afterwards.'],
  ['Nothing sends itself', 'The model proposes; you confirm, every time something would go out under your name. That gate is code, not a setting you could leave on by accident.'],
  ['We never delete for you', 'Junk is grouped in one place and you press delete. Everything else we do records the state before it, so it can be put back.'],
];

export default function WelcomePage() {
  return (
    <main style={{ maxWidth: 1060, margin: '0 auto', padding: '0 40px 80px' }}>
      <header
        style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '26px 0', borderBottom: '1px solid var(--rule-soft)',
        }}
      >
        <div className="wordmark">
          <span className="wm-dot" />
          Custodian
        </div>
        <Link className="btn btn-primary btn-sm" href="/">
          Open the app
        </Link>
      </header>

      <section style={{ padding: '80px 0 20px', maxWidth: 740 }}>
        <span className="eyebrow">An inbox agent, not another inbox</span>
        <h1 style={{ fontSize: 54, lineHeight: 1.06, letterSpacing: '-.024em', margin: '18px 0 0' }}>
          An agent that runs your inbox for you.
        </h1>
        <p style={{ fontSize: 19, lineHeight: 1.55, color: 'var(--ink-2)', maxWidth: '56ch', marginTop: 20 }}>
          It clears the rubbish by itself, and{' '}
          <b style={{ color: 'var(--ink)' }}>asks you on WhatsApp</b> before it ever sends anything
          as you. No app to open, no settings form to fill in.
        </p>
        <div style={{ display: 'flex', gap: 12, marginTop: 30 }}>
          <Link className="btn btn-primary" href="/">
            Open the app
          </Link>
          <Link className="btn btn-ghost" href="/privacy">
            See what it holds
          </Link>
        </div>
      </section>

      <section
        style={{
          display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 1,
          background: 'var(--rule)', border: '1px solid var(--rule)',
          borderRadius: 10, overflow: 'hidden', marginTop: 44,
        }}
      >
        {STATS.map(([n, l]) => (
          <div key={l} style={{ background: 'var(--surface)', padding: '24px 20px' }}>
            <div style={{ fontFamily: 'var(--f-display)', fontSize: 30, fontWeight: 600, color: 'var(--accent)' }}>
              {n}
            </div>
            <div style={{ fontSize: 12.5, color: 'var(--ink-2)', marginTop: 6, lineHeight: 1.4 }}>{l}</div>
          </div>
        ))}
      </section>

      <section style={{ padding: '70px 0', borderTop: '1px solid var(--rule-soft)', marginTop: 60 }}>
        <span className="eyebrow">The insight</span>
        <h2 style={{ fontSize: 31, maxWidth: '20ch', marginTop: 10 }}>
          The problem was never volume. It is not knowing when to check.
        </h2>
        <p style={{ fontSize: 16, color: 'var(--ink-2)', maxWidth: '62ch', marginTop: 14, lineHeight: 1.6 }}>
          People check 74 times a day because they cannot afford to miss the one email that
          mattered. Every other tool in this space makes the inbox nicer to sit in. Custodian&rsquo;s
          job is to remove the sitting.
        </p>

        <div style={{ display: 'flex', gap: 14, marginTop: 34 }}>
          {LAYERS.map(([tag, name, what, cost]) => (
            <div
              key={name}
              className="card"
              style={{ flex: 1, padding: '20px 18px', boxShadow: 'none' }}
            >
              <div className="mono" style={{ fontSize: 11, color: 'var(--ink-3)', letterSpacing: '.08em' }}>
                {tag}
              </div>
              <h4 style={{ fontFamily: 'var(--f-display)', fontSize: 16, margin: '8px 0 6px' }}>{name}</h4>
              <p style={{ fontSize: 12.5, color: 'var(--ink-2)', margin: 0, lineHeight: 1.5 }}>{what}</p>
              <div
                className="mono"
                style={{
                  marginTop: 14, fontSize: 11, fontWeight: 600,
                  color: cost === 'Free' ? 'var(--plain)' : 'var(--red)',
                }}
              >
                {cost}
              </div>
            </div>
          ))}
        </div>
      </section>

      <section style={{ padding: '10px 0 70px' }}>
        <span className="eyebrow">Privacy</span>
        <h2 style={{ fontSize: 31, marginTop: 10 }}>We read, but we don&rsquo;t keep.</h2>
        <p style={{ fontSize: 16, color: 'var(--ink-2)', maxWidth: '62ch', marginTop: 14, lineHeight: 1.6 }}>
          An email passes through memory — wiped in seconds — and is never written to storage. What
          persists is the conclusion, not the message. The database has no column for a body, which
          is the privacy claim expressed as a schema rather than as a promise.
        </p>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 18, marginTop: 30 }}>
          {TRUST.map(([title, body]) => (
            <div key={title} className="card" style={{ padding: '22px 24px', boxShadow: 'none' }}>
              <h4 style={{ fontFamily: 'var(--f-display)', fontSize: 16.5, marginBottom: 8 }}>{title}</h4>
              <p style={{ fontSize: 13, color: 'var(--ink-2)', margin: 0, lineHeight: 1.55 }}>{body}</p>
            </div>
          ))}
        </div>
      </section>

      <section
        style={{
          background: 'var(--ink)', borderRadius: 14, padding: '48px 46px',
          display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 36,
        }}
      >
        <div>
          <h3 style={{ color: 'var(--surface)', fontSize: 26, maxWidth: '18ch' }}>
            Stop checking. Start being told.
          </h3>
          <p style={{ color: '#B9C7CD', fontSize: 14, marginTop: 10, maxWidth: '44ch' }}>
            The app reads the same database and the same decisions the agent recorded — every reason
            you see on a screen was written at the moment it was made.
          </p>
        </div>
        <Link className="btn" style={{ background: 'var(--surface)', color: 'var(--ink)' }} href="/">
          Open the app
        </Link>
      </section>
    </main>
  );
}
