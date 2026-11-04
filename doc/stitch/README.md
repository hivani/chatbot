# Stitch design source

`stitch_fintech_ai_chatbot_interface.zip` at the repository root is the
canonical UI design export. It contains:

| File | Purpose |
| --- | --- |
| `DESIGN.md` | Stitch design tokens, typography, spacing, and component notes |
| `code.html` | Static reference rendering of the "Fintech AI Terminal" screen |
| `screen.png` | Reference screenshot of the exported design |

`DESIGN.md` is copied here for readable review. The zip remains the source of
truth; if the two disagree, the zip wins.

The production UI lives at `index.html`, `styles.css`, and `app.js`, served by
FastAPI. It adapts the Stitch dark terminal layout to Growchatbot's facts-only
answer contract and maps the Stitch accent to Groww green (`#00B386`).

## Re-syncing a new Stitch export

1. Replace `stitch_fintech_ai_chatbot_interface.zip` with the new export.
2. Re-read `DESIGN.md` for token/component changes.
3. Update `styles.css` tokens and `index.html` markup to match.
4. Keep the answer contract unchanged: ≤ 3 sentences, exactly one official
   citation, a `Last updated from sources` timestamp, and the persistent
   disclaimer.
5. Refresh the copy in this directory and in `architecture.md` /
   `implementation.md` if the design direction changes.

There is no live Stitch MCP connector in this runtime, so the export is applied
manually. The checked-in implementation, not a generated file, is what ships.
