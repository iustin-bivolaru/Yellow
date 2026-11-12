---
name: yellow-ui
description: Design system for the Yellow phone UI — colors, typography, components, PWA rules. Use whenever editing templates/, style.css, app.js, or anything the user sees on their phone.
---

# Yellow UI rules

Static HTML from Jinja2, one `style.css`, a small vanilla `app.js`. No frameworks, no CDN, no build step. The site must work offline once loaded (via the service worker).

## Tokens (in `:root` of style.css; use these, never raw hex)
```css
--yellow: #FFD400;   --yellow-soft: #FFF3B0;  --yellow-deep: #E6B800;
--ink: #1A1A1A;      --ink-muted: #5C5C5C;    --paper: #FFFDF5;  --card: #FFFFFF;
--radius: 14px;      --gap: 12px;             --tap: 44px;
```
For dark mode, use `@media (prefers-color-scheme: dark)` and set `--paper: #121212; --card: #1E1E1E; --ink: #F5F5F5; --ink-muted: #A8A8A8`. Yellow stays yellow. Text sitting **on** yellow is always `#1A1A1A`, in both themes.

## Layout (mobile-first, 390px wide is the reference)
1. Sticky yellow header: "Yellow", the date, and an archive icon.
2. "AI in a nutshell": 3 sentences on `--yellow-soft`.
3. **Top 5**: large cards.
4. **New on radar**: horizontally scrolling tech chips.
5. Sticky category chip bar that filters the feed in place (JS toggles a `hidden` attribute; no reload).
6. Feed cards: title (links out, `rel="noopener"`), 1–2 line summary, source badge, importance dots (1–5) and tech tags.
7. Footer: links to the last 30 days.

## Rules
- System font stack. Base size 16px, line-height 1.5. Don't go below 13px.
- Every tap target is at least `--tap` tall. No hover-only interactions.
- Text contrast must be WCAG AA or better in both themes.
- **Autoescape on.** Feed titles and snippets are untrusted, so never use `|safe` on them.
- Cards degrade gracefully if summary, score or tags are missing.
- PWA: `manifest.json` (theme_color `#FFD400`, display `standalone`, icons 192/512), `<meta name="theme-color">`, and `sw.js` with cache-first for assets and network-first for `index.html`.
- Respect `prefers-reduced-motion`, and keep animations ≤ 150ms.
- Check changes at 390×844 in both light and dark mode before calling a UI change done.
