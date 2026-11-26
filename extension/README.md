# Spark Form Filler (Chrome / Edge)

A Manifest V3 extension that reads a form, asks Spark to match fields against your
saved profile, fills the page, and only submits after you tick the approval box.

## Why an extension?

Web pages are cross-origin. A backend cannot safely read or type into arbitrary
forms. The extension runs the page-side part; Spark runs the profile matching and
records the final submission in its audit log.

## Install (developer mode)

1. Open `chrome://extensions` in Chrome/Edge.
2. Enable **Developer mode**.
3. Choose **Load unpacked** and select this `extension/` folder.
4. Open the extension, expand **Settings**, and set:
   - **Spark backend URL** — `http://localhost:8000` locally, or your HTTPS URL.
   - **Access password** — the same value as `SPARK_OWNER_TOKEN` (default `spark123` locally).
5. Click **Test connection**. It calls the owner-protected config endpoint, so
   it only succeeds when the URL and token are both correct.

## Use

1. Open the form you want to fill.
2. Click the Spark extension icon.
3. Review the matched values. Edit anything that is wrong. Sensitive fields
   (passwords, OTPs, card numbers, uploads) are never filled.
4. Click **Fill form** and check the page.
5. Tick **I reviewed every filled value** and click **Submit form**.

The fill and submit steps are separate. The backend also rejects
`POST /api/forms/submit` unless `approved` is true. This is an honest approval
gate, not a guarantee: a page controls its own submission, so always review the
page before pressing Submit.

## Profiles

Spark uses the profile in **Settings → Your profile** (`GET/PUT /api/profile`).
Only facts you save there are used. The backend rejects any LLM output that
invents data outside the profile.

## Limits

- Includes Shadow DOM? No. Fields inside closed shadow roots are skipped.
- Multi-step forms: analyze each step again as you advance.
- File uploads and payment details are always manual.
- The extension cannot verify that a site actually accepted a submission; it
  records that you approved and triggered it.
