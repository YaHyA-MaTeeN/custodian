'use client';

import type { ReactNode } from 'react';

export function Loading({ rows = 3 }: { rows?: number }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10, padding: '18px 22px' }}>
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="skeleton" style={{ height: 16, width: `${90 - i * 12}%` }} />
      ))}
    </div>
  );
}

/**
 * ⚠️ An error is shown with the thing to type next.
 *
 * Nearly every failure on these screens is "the API is not running", and a
 * red box that only says "failed to fetch" leaves the reader to guess. The
 * command that fixes it is part of the message.
 */
export function ErrorBox({ error, onRetry }: { error: string; onRetry?: () => void }) {
  return (
    <div className="errorbox">
      <div style={{ marginBottom: onRetry ? 10 : 0 }}>{error}</div>
      {onRetry && (
        <button className="btn btn-ghost btn-sm" onClick={onRetry}>
          Try again
        </button>
      )}
    </div>
  );
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="state">
      <b>{title}</b>
      {children}
    </div>
  );
}
