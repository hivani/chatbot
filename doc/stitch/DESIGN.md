---
name: Fintech AI Terminal
colors:
  surface: '#0d1511'
  surface-dim: '#0d1511'
  surface-bright: '#333b37'
  surface-container-lowest: '#08100c'
  surface-container-low: '#161d19'
  surface-container: '#1a211d'
  surface-container-high: '#242c28'
  surface-container-highest: '#2f3732'
  on-surface: '#dce5de'
  on-surface-variant: '#bacac1'
  inverse-surface: '#dce5de'
  inverse-on-surface: '#2a322e'
  outline: '#85948c'
  outline-variant: '#3c4a43'
  surface-tint: '#2fe0aa'
  primary: '#44edb7'
  on-primary: '#003828'
  primary-container: '#00d09c'
  on-primary-container: '#00533c'
  inverse-primary: '#006c4f'
  secondary: '#bcc2ff'
  on-secondary: '#00179b'
  secondary-container: '#152ecf'
  on-secondary-container: '#aab3ff'
  tertiary: '#ffc8a3'
  on-tertiary: '#502500'
  tertiary-container: '#ffa15b'
  on-tertiary-container: '#733800'
  error: '#ffb4ab'
  on-error: '#690005'
  error-container: '#93000a'
  on-error-container: '#ffdad6'
  primary-fixed: '#59fdc5'
  primary-fixed-dim: '#2fe0aa'
  on-primary-fixed: '#002116'
  on-primary-fixed-variant: '#00513b'
  secondary-fixed: '#dfe0ff'
  secondary-fixed-dim: '#bcc2ff'
  on-secondary-fixed: '#000b62'
  on-secondary-fixed-variant: '#102bcd'
  tertiary-fixed: '#ffdcc6'
  tertiary-fixed-dim: '#ffb785'
  on-tertiary-fixed: '#301400'
  on-tertiary-fixed-variant: '#713700'
  background: '#0d1511'
  on-background: '#dce5de'
  surface-variant: '#2f3732'
typography:
  display-lg:
    fontFamily: Inter
    fontSize: 32px
    fontWeight: '600'
    lineHeight: 40px
  headline-lg:
    fontFamily: Inter
    fontSize: 24px
    fontWeight: '600'
    lineHeight: 32px
  headline-md:
    fontFamily: Inter
    fontSize: 20px
    fontWeight: '600'
    lineHeight: 28px
  headline-sm:
    fontFamily: Inter
    fontSize: 18px
    fontWeight: '500'
    lineHeight: 26px
  body-lg:
    fontFamily: Inter
    fontSize: 16px
    fontWeight: '400'
    lineHeight: 25.6px
  body-lg-medium:
    fontFamily: Inter
    fontSize: 16px
    fontWeight: '500'
    lineHeight: 25.6px
  body-md:
    fontFamily: Inter
    fontSize: 14px
    fontWeight: '400'
    lineHeight: 22.4px
  body-md-medium:
    fontFamily: Inter
    fontSize: 14px
    fontWeight: '500'
    lineHeight: 22.4px
  label-md:
    fontFamily: Inter
    fontSize: 13px
    fontWeight: '500'
    lineHeight: 18px
  label-sm:
    fontFamily: Inter
    fontSize: 12px
    fontWeight: '500'
    lineHeight: 16px
  mono-data:
    fontFamily: Inter
    fontSize: 13px
    fontWeight: '400'
    lineHeight: 18px
rounded:
  sm: 0.25rem
  DEFAULT: 0.5rem
  md: 0.75rem
  lg: 1rem
  xl: 1.5rem
  full: 9999px
spacing:
  gutter: 1rem
  gutter-desktop: 1.5rem
  margin: 1rem
  margin-desktop: 1.5rem
  space-xs: 0.5rem
  space-sm: 0.75rem
  space-md: 1rem
  space-lg: 1.5rem
  space-xl: 2rem
---

## Brand & Style
The design system establishes a focused, calm, and institutional environment for conversational wealth management and investing intelligence. It rejects hyper-decorative patterns, decorative gradients, and emotional iconography in favor of clarity, computational rigor, and high utility.

Targeted at modern investors, analysts, and self-directed retail capital allocators, the visual style combines minimalism with structural dark-mode engineering:
- **Aesthetic Movement:** Modern Functional Minimalism with structural low-contrast borders.
- **Atmosphere:** Deep, low-fatigue slate blacks, precise hairline structural framing, and surgical accents.
- **Emotional Response:** High confidence, disciplined focus, analytical clarity, and prompt responsiveness without visual fatigue.

## Colors
The palette uses strict chromatic constraints to preserve analytical legibility under prolonged viewing sessions. Zero saturated decorative tints outside purposeful interactive indicators.

### Palette Architecture
- **Primary Accent (`#00D09C`):** Used strictly for core functional actions, active states, focus rings, confirmed executions, and the conversational AI indicator mark. High-visibility green calibrated for dark backgrounds.
- **Secondary Accent (`#5367FF`):** Dedicated to user message containers and contextual secondary user-driven metadata.
- **Canvas Base (`#121212`):** Primary viewport backdrop providing high contrast with zero pure-black harshness.
- **Structural Surfaces (`#1B1B1F`):** Applied to persistent navigation, side panels, and low-layer card surfaces.
- **Elevated Surfaces (`#24242A`):** Used for dynamic elements, input bars, modal overlays, dropdown menus, and interactive hover states.
- **Borders & Dividers (`#2E2E36`):** Crisp 1px structural framing across all card edges, splitters, table dividers, and input borders.
- **Text & Content Hierarchy:**
  - High Emphasis (`#FFFFFF`): Main data readouts, user queries, assistant responses, titles. Meets WCAG AAA against base and card surfaces.
  - Medium/Muted Emphasis (`#A0A3B1`): Metadata, timestamps, helper descriptions, table headers, inactive labels, and icon fills. Exceeds WCAG AA contrast standards.

## Typography
Typography relies entirely on `Inter` to enforce crisp horizontal rhythm, balanced counters, and high numerical clarity essential for financial tickers, balances, and long-form AI reasoning.

- **Body Scale:** All primary conversational paragraphs and assistant reasoning blocks strictly use 16px with an exact 1.6 line-height (`25.6px`) for optimal readability across dense financial answers.
- **Numerical Formatting:** Set all financial metrics, values, and tabular figures using tabular numerals (`tnum`, `cv05`) within the variable font settings to ensure uniform vertical alignment.
- **Purity:** No stylistic alternate flourishes or emoji glyphs are allowed in system-generated typography.

## Layout & Spacing
The layout adheres strictly to an 8px grid architecture. Spacing steps scale in direct multiples of 8px (with 4px reserved only for precise input inner offsets and icon alignment).

### Layout Structure
- **Desktop (1024px+):** Collapsible lateral control sidebar locked to `280px` (`#1B1B1F`), bound to a central fluid conversational canvas with a constrained content container maxed at `840px` to maintain strict typographic line-length limits.
- **Tablet (768px – 1023px):** Sidebar converts to an off-canvas drawer. The chat transcript expands to fluid canvas margins of `1.5rem` (24px).
- **Mobile (<768px):** Single-column layout. Chat container edges pad with `1rem` (16px). Fixed persistent input anchored at the lower safe area.

### Vertical Rhythm
Conversational turn-taking enforces deliberate spatial pacing:
- Successive messages from the same author: `space-xs` (8px).
- Message turn switch (User to Assistant or vice-versa): `space-xl` (32px).
- Internal element gaps within cards, tickers, and citations: `space-sm` (12px) to `space-md` (16px).

## Elevation & Depth
Elevation is achieved exclusively through surface-luminance stacking and hairline borders rather than heavy drop shadows. Heavy blurs and diffused glows are prohibited.

### Tiers of Depth
- **Level 0 (Base Canvas):** `#121212` — Root viewport layer.
- **Level 1 (Structural Containers):** `#1B1B1F` framed by `1px solid #2E2E36` — Side navigation, historical session lists, market overview cards.
- **Level 2 (Active/Elevated Controls):** `#24242A` framed by `1px solid #2E2E36` — Interactive search bars, primary prompt input docked at the bottom, hover state backgrounds.
- **Level 3 (Overlays & Flyouts):** `#24242A` framed by `1px solid #2E2E36` with a tight, non-diffused technical shadow: `0 4px 16px rgba(0, 0, 0, 0.45)` — Used exclusively for tooltips, financial asset quick-views, and command palettes.
- **Focus Indication:** `0 0 0 2px #00D09C` with no soft outer glow.

## Shapes
A disciplined corner radius system between 12px and 16px maintains a modern software feel that remains clean and executive.

- **Cards, Sidebars, and Message Panels:** Standardized at `16px` (`rounded-xl` / 1rem equivalent in this configuration) for external borders.
- **Input Fields & Textarea Containers:** `12px` to `14px` border radius to ground interactive typing zones.
- **Buttons, Ticker Chips, and Filters:** Scaled to `12px` or full-pill (`9999px`) strictly for compact filter chips.
- **Divider and Hairline Stroke:** Uniformly `1px` thickness; no thick outlines or asymmetric borders.

## Components

### Chat Message Bubbles
- **User Prompt:** Background `#5367FF`, text `#FFFFFF`, radius `16px 16px 4px 16px`. Maximum width `75%`. No border.
- **Assistant Response:** Background `#1B1B1F`, border `1px solid #2E2E36`, text `#FFFFFF`, radius `16px 16px 16px 4px`. Stretches across layout column up to container max width (`840px`). Body text strictly 16px with 1.6 line height.
- **Assistant Identifier / AI Mark:** Geometric 16x16px indicator in `#00D09C` preceding system outputs.

### Chat Prompt Bar (Input Container)
- **Container:** Background `#24242A`, border `1px solid #2E2E36`, radius `16px`, padding `12px 16px`.
- **Text Area:** Transparent background, zero border, font size 16px, text `#FFFFFF`, placeholder `#A0A3B1`.
- **Send Action Button:** Solid `#00D09C` fill, rounded `12px`, 36x36px dimension, containing a `#121212` icon glyph. Disabled state: `#2E2E36` fill with `#A0A3B1` icon glyph.

### Action Buttons
- **Primary Action:** Solid `#00D09C` fill, text `#121212` (Inter 600), radius `12px`, height `40px` or `48px`, padding `0 20px`. Hover: 90% opacity.
- **Secondary Action:** Background `#24242A`, border `1px solid #2E2E36`, text `#FFFFFF`, radius `12px`. Hover: border `#A0A3B1`.
- **Ghost/Tertiary Action:** Transparent background, text `#A0A3B1`. Hover: text `#FFFFFF`, background `#1B1B1F`.

### Financial Data Cards & Citation Chips
- **Asset/Stock Quote Snippet:** Background `#1B1B1F`, border `1px solid #2E2E36`, radius `12px`, padding `12px 16px`. Displays symbol (`#FFFFFF`), company label (`#A0A3B1`), and delta value with `#00D09C` for gains.
- **Source/Citation Chips:** Background `#24242A`, border `1px solid #2E2E36`, text `#A0A3B1`, radius `8px`, padding `4px 10px`, font size 12px. Hover: text `#00D09C`, border `#00D09C`.

### Form Controls (Checkboxes & Radios)
- **Base Box/Circle:** Background `#1B1B1F`, border `1px solid #2E2E36`, dimensions 18x18px.
- **Selected State:** Fill `#00D09C`, border `#00D09C`, checkmark `#121212`.
- **Focus Ring:** 2px solid `#00D09C` offset by 2px `#121212`.

### Lists & Ticker Streams
- **Divided Lists:** Transparent or `#1B1B1F` rows, separated by continuous `1px solid #2E2E36`. Padding `12px 16px`.
- **Hover State:** Background shifts to `#24242A` across the entire row hit area with transition `150ms ease`.