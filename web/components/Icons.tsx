import type { ReactNode } from 'react';

/**
 * Inline stroke icons. No icon package: eight shapes do not justify a
 * dependency, and drawing them here means they inherit colour from the text
 * they sit beside.
 */
function Ic({ children }: { children: ReactNode }) {
  return (
    <svg
      className="ic"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {children}
    </svg>
  );
}

export const Icons = {
  dashboard: (
    <Ic>
      <rect x="3" y="3" width="7" height="9" rx="1.5" />
      <rect x="14" y="3" width="7" height="5" rx="1.5" />
      <rect x="14" y="12" width="7" height="9" rx="1.5" />
      <rect x="3" y="16" width="7" height="5" rx="1.5" />
    </Ic>
  ),
  inbox: (
    <Ic>
      <path d="M3 12h4.5l1.5 3h6l1.5-3H21" />
      <path d="M5.5 6h13l2.5 6v7a1.5 1.5 0 0 1-1.5 1.5H4A1.5 1.5 0 0 1 2.5 19v-7z" />
    </Ic>
  ),
  radar: (
    <Ic>
      <circle cx="12" cy="12" r="9" />
      <circle cx="12" cy="12" r="1.6" fill="currentColor" stroke="none" />
      <path d="M12 12 18 8" />
    </Ic>
  ),
  cleanup: (
    <Ic>
      <path d="M4 7h16" />
      <path d="M9 7V4.5A1.5 1.5 0 0 1 10.5 3h3A1.5 1.5 0 0 1 15 4.5V7" />
      <path d="M6 7l1 12.5A1.5 1.5 0 0 0 8.5 21h7a1.5 1.5 0 0 0 1.5-1.5L18 7" />
    </Ic>
  ),
  rules: (
    <Ic>
      <path d="M4 6h16M4 12h10M4 18h13" />
      <circle cx="20" cy="12" r="1.4" fill="currentColor" stroke="none" />
    </Ic>
  ),
  activity: (
    <Ic>
      <path d="M3 12h4l2.5-7 4 14 2.5-7H21" />
    </Ic>
  ),
  digest: (
    <Ic>
      <rect x="3.5" y="4" width="17" height="16" rx="2" />
      <path d="M7 9h10M7 13h10M7 17h6" />
    </Ic>
  ),
  privacy: (
    <Ic>
      <path d="M12 3l7 3v6c0 4.6-3 7.9-7 9-4-1.1-7-4.4-7-9V6z" />
      <path d="M9.3 12.2l1.8 1.8 3.6-3.8" />
    </Ic>
  ),
  plug: (
    <Ic>
      <path d="M9 3v6M15 3v6" />
      <path d="M6 9h12v3a6 6 0 0 1-12 0z" />
      <path d="M12 18v3" />
    </Ic>
  ),
  search: (
    <Ic>
      <circle cx="11" cy="11" r="6.5" />
      <path d="M20 20l-4.3-4.3" />
    </Ic>
  ),
  check: (
    <Ic>
      <path d="M20 6 9 17l-5-5" />
    </Ic>
  ),
  x: (
    <Ic>
      <path d="M18 6 6 18M6 6l12 12" />
    </Ic>
  ),
  chevron: (
    <Ic>
      <path d="M9 6l6 6-6 6" />
    </Ic>
  ),
  clock: (
    <Ic>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M12 7.5V12l3 2" />
    </Ic>
  ),
  undo: (
    <Ic>
      <path d="M8 7 4 11l4 4" />
      <path d="M4 11h10a6 6 0 0 1 0 12h-2" />
    </Ic>
  ),
  shield: (
    <Ic>
      <path d="M12 3l7 3v6c0 4.6-3 7.9-7 9-4-1.1-7-4.4-7-9V6z" />
    </Ic>
  ),
  download: (
    <Ic>
      <path d="M12 4v11M8 11l4 4 4-4" />
      <path d="M5 19h14" />
    </Ic>
  ),
  refresh: (
    <Ic>
      <path d="M4 12a8 8 0 0 1 14-5.2M20 12a8 8 0 0 1-14 5.2" />
      <path d="M18 4v4h-4M6 20v-4h4" />
    </Ic>
  ),
  plus: (
    <Ic>
      <path d="M12 5v14M5 12h14" />
    </Ic>
  ),
  mail: (
    <Ic>
      <rect x="3" y="5.5" width="18" height="13" rx="1.5" />
      <path d="M4 6.5l8 6.5 8-6.5" />
    </Ic>
  ),
  bell: (
    <Ic>
      <path d="M6 9a6 6 0 1 1 12 0c0 4 1.5 5.5 2 6H4c.5-.5 2-2 2-6z" />
      <path d="M10 19a2 2 0 0 0 4 0" />
    </Ic>
  ),
  filter: (
    <Ic>
      <path d="M4 6h16M7 12h10M10 18h4" />
    </Ic>
  ),
};

export type IconName = keyof typeof Icons;
