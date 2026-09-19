// The shapes api.py returns. Kept in one file so a change to the Python side
// shows up here as a type error rather than as an empty box on a screen.

export type Kind = 'reply' | 'filed' | 'machine' | 'dormant' | 'private' | 'unseen';

export interface Message {
  id: string;
  messageId: string;
  account: string;
  sender: string;
  senderName: string;
  subject: string;
  date: string;
  dateRaw: string;
  unread: boolean;
  kind: Kind;
  why: string;
  held: boolean;
  unsubscribe: boolean;
  categories: string[];
}

export interface Decision {
  stage: string;
  decision: string;
  reason: string;
  score: number | null;
  at: string;
}

export interface MessageDetail extends Message {
  decisions: Decision[];
  body: string;
  bodySource: string;
  blocked: boolean;
}

export interface Health {
  ok: boolean;
  mailbox: {
    connected: boolean;
    account: string;
    door: string;
    capabilities: Record<string, boolean>;
    error: string;
    disabled: boolean;
  };
  counts: {
    messages: number;
    bodies: number;
    decisions: number;
    corrections: number;
    actions: number;
  };
  retentionDays: number;
}

export interface Account {
  account: string;
  messages: number;
  lastSeen: string;
  live: boolean;
  door: string;
}

export interface Reminder {
  messageId: string;
  id: string;
  kind: string;
  due: string;
  daysLeft: number | null;
  subject: string;
  why: string;
  done: boolean;
  urgency: 'past' | 'today' | 'soon' | 'week' | 'later';
}

export interface Action {
  id: number;
  messageId: string;
  providerId: string;
  action: string;
  verb: string;
  detail: string;
  before: string;
  undone: boolean;
  at: string;
  reversible: boolean;
}

export interface Overview {
  stats: {
    headersHeld: number;
    bodiesHeld: number;
    bodiesMb: number;
    needsReply: number;
    scored: number;
    handledWithoutAsking: number;
    actionsThisWeek: number;
    decisions: number;
    corrections: number;
  };
  needsYou: Message[];
  remindersDue: Reminder[];
  remindersPending: Reminder[];
  recentActivity: Action[];
}

export interface CleanupGroup {
  sender: string;
  name: string;
  domain: string;
  count: number;
  kind: Kind;
  why: string;
  unsubscribe: boolean;
  samples: { id: string; subject: string; date: string }[];
  accounts: string[];
}

export interface Rule {
  id: number;
  scope: 'sender' | 'domain' | 'message';
  target: string;
  was: string;
  shouldBe: string;
  source: string;
  at: string;
}

export interface Digest {
  periodDays: number;
  generatedAt: string;
  worthSending: boolean;
  silenceIsCorrect: boolean;
  sections: {
    sortedAndCleared: Record<string, number>;
    needsReply: Message[];
    handledQuietly: number;
    deadlinesAhead: Reminder[];
    learned: { scope: string; target: string; shouldBe: string; at: string }[];
  };
}

export interface Privacy {
  holdings: { table: string; plain: string; rows: number }[];
  depths: { depth: number; sees: string; count: number; share: number }[];
  passport: { messageId: string; stage: string; what: string; reason: string; at: string }[];
  neverHeld: string;
  retentionDays: number;
}
