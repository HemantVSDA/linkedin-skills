# Sub-skill: Generate an illustration for a post

Adds an optional image to a draft (an infographic, a checklist card, a
quote-card or a picture) and attaches it on publish. Runs on any agent (Claude
Code, Codex, OpenClaw).

## When this runs

- User says "add an image", "make an infographic", "make a quote-card", or
  "add a cover" for a post.
- Offer it once after a post draft is approved, when a visual would lift reach
  (image posts earn ~1.33x engagement over text-only; portrait 4:5 beats
  square and landscape).

## Backends (mirrors the publish layer)

`lib.image_backend()` reports which is active:

- **google** — `GEMINI_API_KEY` set (Google AI Studio key, billing linked).
  Gemini draws; the brand layer (logo, typeset text) runs locally with Pillow;
  images are local files that `lib.publish` uploads through Publora. Wins when
  both keys are set.
- **pixfaro** — `PIXFARO_TOKEN` set and no Google key: hosted generation and
  templates (see "Pixfaro notes" at the end).
- **manual** — neither: the skill drafts the image prompt or card text and asks
  the user to make it and paste the URL. Never blocks a draft.

If the user says they DID add a key, do not repeat any signup pitch: run
`python3 scripts/check_config.py` in the linkedin-skills folder, which names the
exact problem (key not loaded, rejected, logo path missing, OCR not installed).

## Step 1: plan the words first

Before any image is made, write the exact text the visual will carry, word for
word: a headline (12 words max), up to 6 short items (8 words max each), an
optional footer. Use the user's real figures from the Story Bank; never invent
one. For a tax or legal topic, a footer such as "General information, not tax
advice." follows the voice profile. Text on the visual is the norm on LinkedIn
(quote cards, checklists, frameworks, comparisons); a wordless picture is the
exception.

## Step 2: pick the route

| Route | Call | When | Text accuracy | Cost |
|---|---|---|---|---|
| **A. AI-designed** | `lib.designed(headline, items, style=..., footer=...)` | Short text, a designed infographic look | OCR-verified; falls back to B on any miss | ~$0.034 per try |
| **B. Picture + typed text** | `lib.text_card(headline, items, scene="...", footer=...)` | Deadlines, rates, $ amounts, form codes, longer text | Exact by construction | ~$0.034 |
| **C. Typed card** | `lib.quote_card("<hook line>")` or `lib.text_card(headline, items)` | Hook quote, simple checklist or framework | Exact by construction | $0 |
| **Picture only** | `lib.illustrate(prompt, kind="portrait")` | Story posts where mood beats information | No text planned | ~$0.034 |

Rules of thumb: a quote of the hook goes to C. A checklist or framework goes to
A when the text is short, else B. Anything whose value is a precise figure
(a CRA deadline, a credit rate, a dollar threshold) is safest on B or C.

How route A stays honest (`lib/text_check.py`): a local OCR engine reads the
finished image; every planned item must be there, and items with a digit, %, $,
/ or & must match character for character. A miss gets one targeted edit
("correct X, keep everything else"), at most twice; still wrong, it is rebuilt
as route B automatically. Gemini is never asked to proofread its own image: it
auto-corrects while reading, which hides the very typo being checked.

```python
from lib import designed, text_card, quote_card, publish

r = designed("5 records CRA asks for in an SR&ED review",
             ["Dated project notes", "Timesheets per project", "Contractor invoices"],
             style="Minimal flat-vector infographic with small line icons, off-white background.",
             footer="General information, not tax advice.")
# r["route"] is "A" (verified) or "B" (fell back); r["text_check"] is the OCR report
publish("post", draft_text, "https://www.linkedin.com/post/new/", media_urls=[r["url"]],
        scheduled_time=iso_time)
```

## Step 3: pictures (route A/B scenes and `illustrate`)

- Describe the scene in full sentences, not keyword lists: subject,
  composition, style, palette, and the purpose of the image. Use photographic
  or design vocabulary for control. Say what you want, not what you don't.
- Ask for "a clean, wordless illustration" when the picture carries no text
  (route B does this for you). The model still sketches text-like marks now and
  then; they are scribbles, not words, but look before approving.
- Default style when Voice & Brand Profile §6 sets none: clean, non-literal,
  professional editorial, brand colours on an off-white background.
- Never generate fake people, fake team photos or fake offices for a company:
  it misrepresents the firm and is what LinkedIn's "Seems like AI slop" button
  is pressed for. Real team photos are used as they are.
- `kind` sets the shape: `portrait` / `post` / `carousel` / `quote` 4:5
  (default for the feed), `square` 1:1, `wide` / `link` 16:9, `story` 9:16.
- `reference_images=[path, ...]` (Google) sends up to 14 local images as style
  references, e.g. two approved past visuals for a consistent series.

## Step 4: brand overlay

`illustrate` and `designed` stamp the brand logo bottom-right by default
(`overlay="default"`). The Google backend reads the brand from `.env`:

```
BRAND_LOGO_PATH=path/to/logo.png   # transparent PNG
BRAND_PRIMARY=#2c366c              # bands and headline panels
BRAND_ACCENT=#4aa6dd               # rules and bullet markers
BRAND_BACKGROUND=#f5f3ee           # off-white canvas
BRAND_HANDLE=@yourcompany          # used when there is no logo
```

Mirror the same values in Voice & Brand Profile §6. `overlay={"text": "@handle"}`
stamps a handle instead; `overlay=False` skips it. Re-saving with the overlay
also drops embedded C2PA metadata, as Pixfaro's composited images did.

## Step 5: show, refine, confirm

- Show the image (its local `path` or `url`), the route, the `cost`, and for
  route A the OCR report: planned text next to what was read, each marked
  found or not. Never attach an image the user has not seen and approved.
- Tweaks ("darker background", "swap the icon") go through `lib.refine(r["id"],
  "<instruction>")`, which edits the clean, un-stamped image and re-applies the
  logo. Cheaper and more consistent than regenerating. Edits degrade after 5-7
  rounds; start fresh past that. Text changes on a route B/C card are a re-run
  of `text_card` / `quote_card` (free and exact), not a refine.
- On approval: `publish("post", draft_text, target_url, media_urls=[r["url"]])`.
  A local file is uploaded through Publora's flow (draft, upload, schedule);
  with no `scheduled_time` the post stays a draft in Publora, as without images.
  On the manual tier the output lists the files to attach in the composer.

## Multi-image grid (LinkedIn, up to 10)

LinkedIn posts can carry up to 10 images in a grid (not a swipeable carousel,
which the API does not support). `lib.illustrate_set([p1, p2, ...], kind="portrait")`
generates one per prompt; pass every `url` in `media_urls=[...]`. Typed cards
can join the same list. LinkedIn cannot mix images with video in one post.

## Cost-guard

- Google default: `gemini-nano-banana-2.1` at 1K, ~$0.034 per image. `cost` on
  each result is an estimate from the price table; Google exposes no balance,
  so real spend is in AI Studio -> Spend. Route C cards cost nothing.
- `gemini-3-pro-image` (~$0.134) only when the user asks by name; the result's
  `premium` flag says when it was used. `resolution="2K"` (~$0.05) for a print
  or a detailed infographic.
- `lib.available_models()` lists the models the key can call, with prices.

## Hard rules

- Plan the text before the image; never let the model choose the words.
- A figure that matters (deadline, rate, amount, form code) is either typeset
  (B/C) or OCR-verified (A). Never ship unverified model-drawn numbers.
- Respect the user's cost: cheap model + 1K unless asked.
- Never attach an image the user has not seen and approved.

## Pixfaro notes (when it is the active backend)

`illustrate` / `refine` / `illustrate_set` return hosted URLs; `refine` edits
by `img_...` id. Overlays take `{"text"|"logo_id", "position", "color"}`;
`lib.brand_logo(path)` uploads a logo once (full-scope key) and returns the
`logo_id` for §6. `quote_card(..., style="brand")` and `card(template, slots)`
render Pixfaro templates (`lib.available_templates()` lists them). `low_balance`
on a result means the prepaid balance is under $1: say so before generating more.
