# Screenshots

This directory hosts the PNG references inlined into the persona pages
(`operator.html`, etc.). Phase 15 ships no PNGs by default — the
walkthrough renders without them and pages link to the
`docs/recipes/*.md` reference cards instead.

## How to add a screenshot

1. Pin a browser window to 1280x800 (consistent aspect ratio across
   captures keeps the page layout clean).
2. Capture only the relevant pane (the terminal, the curl response,
   the Mailhog message — not the whole desktop).
3. Save as `<persona>-<step-number>-<short-name>.png`. Example:
   `operator-3-attach-domain.png`.
4. Optimise: `pngquant --quality=65-80 file.png --output file.png`
   typically halves the file size with no visible degradation.
5. Reference inline from the persona HTML:
   ```html
   <img src="screenshots/operator-3-attach-domain.png"
        alt="saasctl domain attach output"
        style="max-width: 100%; border: 1px solid #e0e0e0;">
   ```

## Asset budget

Aim for &lt; 100 KB per image. The walkthrough is meant to load offline
from a tarball; bloated captures undermine the design intent.

## What NOT to capture

- Real customer data — synthesise with `acme.test` / `example.com`.
- Real bearer tokens or API key secrets — use the literal `sk_live_…`
  in screenshots, never a real value.
- Operator IP allowlists — local-dev runs cleartext, but anything
  destined for the public repo gets the placeholder treatment.
