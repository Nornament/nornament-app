# Design System: Nornament CRM — Mobile

## 1. Visual Theme & Atmosphere

A restrained, jewellery-house interface with warm off-white surfaces, editorial serif headlines, and minimal chrome. The atmosphere is that of a luxury atelier's back office — clean, intentional, never fussy. Density stays low to give breathing room for photo-heavy content (jewellery images need space to shine). Motion is subtle: slight spring translations on tap, skeletal shimmer loaders, nothing that distracts from the product. Asymmetric card layouts prevent the generic app-grid feel. Everything reads at a glance on one thumb.

- **Density:** 4 / 10 — Art Gallery light. Cards have air. Lists use generous row height.
- **Variance:** 6 / 10 — Offset but legible. Bottom sheets, staggered card sizes, not chaos.
- **Motion:** 4 / 10 — Purposeful spring physics. No decorative animation.

---

## 2. Color Palette & Roles

- **Warm Canvas** (`#F7F6F3`) — Primary background surface (app shell, screens)
- **Pure Surface** (`#FFFFFF`) — Card fill, modal sheets, input backgrounds
- **Charcoal Ink** (`#111111`) — Primary text, headings, primary buttons — near-black, never pure black
- **Muted Steel** (`#787774`) — Secondary text, labels, metadata, timestamps
- **Whisper Border** (`#E8E8E4`) — Dividers, card outlines, input borders
- **Nornament Gold** (`#B08C3C`) — Single accent: active tab indicator, status badge highlights, focus rings, rupee amount emphasis
- **Success Sage** (`#2D6E3E`) — Delivered / paid status indicators only
- **Alert Rust** (`#C0392B`) — Overdue / failed states only

**Banned:** Purple, blue-neon, electric teal, gradient fills, any color with saturation above 80%. No pure `#000000` anywhere.

---

## 3. Typography Rules

- **Display / Screen Titles:** `Newsreader` (serif) — weight 500–600, tracking −0.02em. Used for customer names, screen headers, order codes in hero position. This is the brand voice.
- **Body / Labels:** `Outfit` (sans-serif) — weight 400 for body, 500 for labels, 600 for amounts. Clean, legible at small sizes on mobile.
- **Mono / Codes:** `JetBrains Mono` — order codes, enquiry codes, amounts in dense tables. Tabular figures for rupee alignment.
- **Scale (mobile):**
  - Screen title: 22px / Newsreader 500
  - Section heading: 16px / Outfit 600
  - Body: 14px / Outfit 400 — line-height 1.6
  - Caption / metadata: 12px / Outfit 400, Muted Steel
  - Amount emphasis: 18px / Outfit 600, Charcoal Ink

**Banned:** `Inter`, `Georgia`, `Times New Roman`, `Garamond`. No gradient text. No all-caps body text. Minimum body size 14px — never smaller on mobile.

---

## 4. Component Stylings

**Bottom Tab Bar**
Five tabs: Dashboard · Customers · Pipeline · Reports · Settings. Active tab indicator is a 2px Nornament Gold underline + icon fill shift. No label truncation. Background Pure Surface with a soft 0.5px Whisper Border top edge. Height 60px. Safe-area-inset padding applied.

**Cards (Customer, Order, Repair)**
Rounded corners 16px. Pure Surface fill. 1px Whisper Border. Shadow: `0 1px 4px rgba(176,140,60,0.06)` — gold-tinted whisper, not grey box-shadow. Internal padding 16px. Photo thumbnail 52×52px rounded-10px, left-aligned. Status badge right-aligned: pill shape, 6px radius, 11px Outfit 500, no emoji. Photo slots: horizontal scroll strip when multiple images, 80×80px rounded-10px, gap 8px.

**Primary Button**
Background Charcoal Ink `#111111`. Text Pure Surface Outfit 600 15px. Radius 10px. Height 52px. On active: `-1px translateY` spring push, no shadow shift. No outer glow ever. Full-width on mobile forms.

**Ghost / Secondary Button**
1px Whisper Border. Charcoal Ink text. Same radius and height. Used for Cancel, secondary actions.

**Inputs / Forms**
Label above (Outfit 500 13px, Muted Steel). Input background Pure Surface, 1px Whisper Border, radius 10px, height 48px, padding 14px. Focus: border shifts to Nornament Gold 1.5px. Error text below in Alert Rust 12px. No floating labels — label always visible above.

**Status Badges**
Pill, 6px radius. Colour-coded backgrounds at 12% opacity of their foreground:
- New Enquiry: `#B08C3C` text on `#FAF4E8` bg
- In Progress / Active: `#2A65C0` text on `#EAF0FB` bg
- Delivered / Paid: `#2D6E3E` text on `#E8F3EC` bg
- Cancelled / Lost: `#787774` text on `#F0EFED` bg
- Overdue: `#C0392B` text on `#FBEAE8` bg

**Bottom Sheet / Modals**
Drag handle (36×4px, rounded, `#E8E8E4`). Radius 20px top corners. White fill. Springs up from bottom — no full-screen modals for forms. Max height 90dvh with internal scroll.

**Photo Gallery Strip**
Horizontal scroll. 80×80px thumbnails, radius 10px, gap 8px. Tap to expand full-screen lightbox. Delete button: 20×20px `×` in top-right, Pure Surface bg with Charcoal Ink icon, tap target extended to 44px.

**Skeletal Loaders**
Match exact card dimensions. Shimmer animation: linear-gradient sweep from left, warm off-white to slightly lighter, 1.5s infinite. No circular spinners anywhere.

**Empty States**
Centred illustration area (SVG, no Unsplash), 140px, Muted Steel stroke. Short factual copy (e.g., "No orders yet — add your first from a customer profile"). One CTA button below.

---

## 5. Layout Principles

- Single-column always — this is a mobile app, no grid complexity
- List rows: 72px height for customer/order rows with thumbnail, 56px without
- Section headers: sticky, Warm Canvas background, 14px Outfit 600, Muted Steel, uppercase tracking 0.08em
- Safe area insets on all edges (notch, home indicator)
- All touch targets minimum 44×44px — tap areas extend beyond visible element bounds via padding
- Scroll containers use `overflow-y: auto` with `-webkit-overflow-scrolling: touch`
- No horizontal overflow anywhere — horizontal scroll only in explicitly designed strip components
- Full-height screens use `min-height: 100dvh` — never `100vh` (iOS Safari jump)
- Internal content max-width: 100% — no artificial desktop-style centering on mobile

---

## 6. Motion & Interaction

- **Spring defaults:** stiffness 120, damping 18 — weighty, decisive, not bouncy
- **Screen transitions:** Slide left/right for drill-down navigation, 280ms spring. No fade-only transitions.
- **Bottom sheet entry:** Spring up from y+60 to y0, 240ms. Backdrop fades 0→0.4 opacity.
- **Card tap:** Scale 0.98 on press, spring back on release — tactile without lifting off the screen
- **List stagger:** Cards enter with 30ms cascade delay per item. Y: +12 → 0, opacity: 0 → 1.
- **Skeleton shimmer:** CSS `@keyframes shimmer` on `background-position`, 1.5s infinite — performance-safe
- **Status badge pulse (active jobs only):** Subtle 2s infinite opacity 1→0.7 pulse on "In Workshop" / "In Progress" badges only
- **Animate via:** `transform` and `opacity` exclusively. Never `top`, `left`, `height`, `width`

---

## 7. Anti-Patterns (Banned)

- No emojis in UI (not in nav, not in badges, not in copy)
- No `Inter` font
- No `Georgia`, `Times New Roman`, or generic serifs
- No pure black `#000000` anywhere
- No neon outer glows or coloured box-shadows
- No gradients on buttons, cards, or backgrounds
- No gradient text on headings
- No custom tap cursors
- No overlapping elements — every element has its own clean spatial zone
- No 3-column equal grids
- No AI copywriting: "Seamless", "Elevate", "Unleash", "Next-Gen", "Powerful"
- No generic placeholder names: "John Doe", "Acme Corp", "Customer 001"
- No fake precision numbers: "99.9% accuracy", "10,000+ happy clients"
- No full-screen modals for simple forms — use bottom sheets
- No circular loading spinners — skeletal loaders only
- No `h-screen` / `100vh` — always `min-h-[100dvh]`
- No broken Unsplash links — use local placeholder or `picsum.photos` with fixed seeds
- No horizontal overflow on any screen
- No touch targets smaller than 44×44px
