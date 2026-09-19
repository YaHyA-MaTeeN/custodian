import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'Custodian',
  description: 'An agent that runs your inbox for you.',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <head>
        {/*
          Loaded with a plain link rather than next/font on purpose: next/font
          fetches at build time, and a build that needs the network to succeed
          is a build that fails on a laptop with no internet. The fallback
          stacks in globals.css carry the page until these arrive.
        */}
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="" />
        <link
          rel="stylesheet"
          href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Sans:ital,wght@0,400;0,500;0,600;1,400&family=IBM+Plex+Serif:wght@500;600&display=swap"
        />
      </head>
      <body>{children}</body>
    </html>
  );
}
