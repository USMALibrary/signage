# signage

Digital signage for the USMA (West Point) Library. Each `.html` file is a
complete, standalone kiosk page (inline CSS + JS, no build step) served via
GitHub Pages at <https://usmalibrary.github.io/signage/>. See `CLAUDE.md` for
architecture and the data pipeline.

## Pages

| File | Screen | Purpose |
|---|---|---|
| `hours.html` | 1920x1080 | Library hours (legacy, CORS-proxy data path) |
| `hours-v2.html` | 1920x1080 | Library hours (data-branch JSON) |
| `hours-sign.html` | 1920x1080 | Library hours, sign layout |
| `hours-weekly-widget.html` | widget | Weekly hours, embeddable widget |
| `frontdesk.html` | 1080x1920 | Front desk portrait board with Rise Vision content zones |
| `admin-office.html` | 1920x1080 | Staff dashboard |
| `admin-office-portrait.html` | 1080x1920 | Staff dashboard, portrait |
| `elevator.html` | portrait | Elevator display with notices panel |
| `research-lab.html` | 1920x1080 | Research lab info (legacy data path) |
| `research-lab-v2.html` | 1920x1080 | Research lab info (data-branch JSON) |
| `haig-room.html` | 1920x1080 | Haig Room reservation/status board |
| `cullum-hall-sign.html` | 1920x1080 | Cullum Hall Archives & Special Collections |
| `coming-soon.html` | 1920x1080 | Placeholder slide |
| `coming-soon-portrait.html` | 1080x1920 | Placeholder slide, portrait |
| `coming-soon-zone.html` | zone | Placeholder for a Rise Vision content zone |
| `portrait-single.html` | 1080x1920 | Single-panel portrait display |
| `genai-guide.html` | 1920x1080 | Promotes the Generative AI research guide to cadets; 5-slide auto-rotating crossfade with a QR to `guides.library.westpoint.edu/GenAI` |
| `genai-guide-portrait.html` | 1080x1920 | Portrait variant of `genai-guide.html` |
| `genai-guide-zone.html` | zone | GenAI guide slides for a Rise Vision content zone: no header/footer, transparent background, 1200x880 canvas auto-scaled to the zone |
| `hi302-overlord-zone.html` | zone | HI 302 MilArt paper: promotes the Operation OVERLORD research guide; 5-slide crossfade with a QR to `guides.library.westpoint.edu/OperationOVERLORD` |

## Build scripts

| Script | Output | Notes |
|---|---|---|
| `scripts/gen-guide-qr.py` | `<name>-qr.svg` | Generic QR generator for any LibGuide page: `python3 scripts/gen-guide-qr.py <url> <out.svg>`. Omits `xmlns` so the SVG passes Rise Vision's HTML Embed HTTPS check. |
| `scripts/gen-genai-qr.py` | `genai-guide-qr.svg` | Regenerates the inline QR used by the `genai-guide*` pages. Requires `segno` (`pip install --user segno`). Re-run and paste the SVG into both pages if the guide URL changes. |
