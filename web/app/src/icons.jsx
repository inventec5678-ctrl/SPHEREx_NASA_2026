const svg = (d, fill) => <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" fill={fill ? 'currentColor' : 'none'} stroke={fill ? 'none' : 'currentColor'} strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><path d={d} /></svg>
export const ICON = {
  play: svg('M8 5.5v13l10.5-6.5z', true),
  pause: svg('M7 5h3.5v14H7zM13.5 5H17v14h-3.5z', true),
  prev: svg('M15 5l-7 7 7 7'),
  next: svg('M9 5l7 7-7 7'),
  target: svg('M12 3v4M12 17v4M3 12h4M17 12h4M12 9a3 3 0 1 0 0 6a3 3 0 1 0 0-6'),
  check: svg('M5 12.5l4.5 4.5L19 7.5'),
  alert: svg('M12 6v7M12 17.5v.5'),
  dot: svg('M12 12h.01'),
  reset: svg('M4 12a8 8 0 1 0 2.4-5.7M4 4v4.5h4.5'),
  plus: svg('M12 5v14M5 12h14'),
  minus: svg('M5 12h14'),
  settings: svg('M4 7h10M18 7h2M4 17h4M12 17h8M16 4v6M10 14v6'),
  close: svg('M6 6l12 12M18 6L6 18'),
}
