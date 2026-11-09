# Wine Cellar 🍷

A quiet, considered home for your private wine collection. Runs locally on Debian with FastAPI, SQLite, local Ollama vision models, and dual-provider wine catalog enrichment (**WineAPI.io** + **Grapeminds**).

---

## Architecture & Features

- **Local-First & Private**: Cellar data is stored locally. If you enable cloud vision, catalog lookup, or SMTP, the relevant image, query, or email is sent to the configured provider.
- **3-Tier Label Scanning**: Local Ollama vision (default `qwen2.5vl:7b`) with automatic cloud escalation to **OpenRouter** and **WineAPI.io Label Recognition (`POST /identify/image`)** when local reads fail or are uncertain.
- **Dual-Provider Wine Catalog Explorer**: User-selectable search across **WineAPI.io** (default, US-focused with retail market pricing) and **Grapeminds** (EU/Global), with automatic cross-provider fallback when a query returns empty.
- **Market Price & Purchase Tracking**: Record both what you paid (`purchase_price`) and retail market value (`market_price`, automatically populated from WineAPI.io price ranges).
- **Cards & Sortable Table Views**: Browse your collection either as grouped **Cards** or as a bottle-by-bottle **Table** sortable by ID, Wine Name, Producer, Vintage, Region, Country, Color, Drinking Window, Location, or Comment/Status. View and sort preferences are persisted in `localStorage`.
- **One-Click CSV Export**: Export your currently visible/filtered collection to a 20-column UTF-8 BOM CSV spreadsheet (`wine-cellar-YYYY-MM-DD.csv`).
- **Interactive Filtering & Full-Text Search**:
  - Click top-level metric cards (**In the Cellar**, **Red**, **White**, **Rosé**) or any rack/shelf in **Where it rests** to filter your collection (including hierarchical descendant locations).
  - Full-text multi-word search indexes wine names, producers, regions, grape varieties, bottle IDs, comments, **food pairings**, **catalog/sommelier tasting notes**, **descriptions**, and **personal tasting journal notes**, displaying contextual match snippets (`🍽 Pairing`, `📝 Tasting note`, `📖 Description`).
- **Drinking Window Tracking**: Optional `drink_from` and `drink_until` year fields with automatic urgency badges (**Ready to drink**, **Drink soon**, **Hold**, **Past peak**) on cards and in the sortable table.
- **Normalized Wine Colors**: Unified **Color** selector (`Red`, `White`, `Rosé`, `Sparkling`, `Dessert`, `Fortified`, `Orange`) with color-coded badges.
- **Bottle Checkout Workflow ("Check Out a Bottle 🍷")**:
  - Check out bottles from the top action bar, navigation menu, card/table row actions, or directly by scanning a bottle's QR code with a phone camera (`/wines/{qr_id}` deep-link).
  - Records `checkout_date`, `comment` (defaulting to `"Opened"`), sensory tasting journal notes, and optional updates to wine tasting notes & food pairings (with a prompt to apply updates either to the entire wine group or only the checked-out bottle).
- **Permanent Deletion**: Distinct admin deletion flow for mistaken entries, completely purging data from SQLite.
- **Batch Management**: Add consecutive bottles with one QR prefix, edit identical-bottle groups atomically (from either Cards or Table view), and move locations safely with conflict checks.
- **Database Reliability**: SQLite running with `PRAGMA foreign_keys = ON;`, `PRAGMA journal_mode = WAL;`, and automatic startup schema migrations.
- **Multi-User Accounts & Access Control**: The `cellar` account serves as root administrator. Users can request cellar access with their username and email. Admins approve requests with automated email delivery. Includes password recovery ("Forgot password"), interactive show/hide password toggles, self-service password changes, user deactivation, and tasting note author attribution.
- **Admin-Specific Permissions**: Role boundaries enforce that only admin accounts can approve/reject users, add/edit/delete storage locations, delete wines (single or batch), and generate bottle labels.
- **Session Authentication**: Secure signed HTTP-only cookies with configurable 12-hour TTL and PBKDF2-HMAC-SHA256 password hashing.
- **Supervised Restart**: In-app restart via Settings dialog through systemd user service.
- **Printable QR Labels**: Web UI admin generator and standalone CLI tool creating 160-label sheets (SpartanIndustrial® R001, 1″ × 0.5″) with QR codes and history tracking.
- **Wine Labels & Automated Housekeeping**: Bottle label photos are stored in `wine-labels/` (with backwards-compatible `uploads/` routing). Automatic startup and deletion housekeeping purges unreferenced images so disk storage stays synchronized with active database records.

---

## Configuration

Application settings are centralized in [`.env.example`](./.env.example).
Copy it to `.env` in this directory and edit the values you need:

```sh
cp .env.example .env
```

The app loads `.env` first and then fills any missing values from `.env.auth`;
process environment variables take precedence over both files. Keep local
configuration and credentials out of Git. The sample documents settings for
authentication, data paths, providers, quota limits, request timeouts, SMTP,
and label uploads. Required administrator credentials must be set, and
invalid boolean or non-positive numeric settings cause startup to fail with an
explicit error.

`WINE_APP_DATA_DIR` controls the default location of the SQLite database,
label images, provider cache and usage files, email log, and generated QR
labels. Individual paths can be overridden with the corresponding path
settings in `.env.example`. `CELLAR_DATABASE_URL` can override the default
SQLite database URL.

---

## Label reading (3-Tier Vision Pipeline)

Wine-label scanning (`POST /wines/scan` via `VisionService.extract_from_image`) uses a three-tier pipeline:

1. **Tier 1 — Local Ollama (`OLLAMA_VISION_MODEL`)**: Reads the label locally first. If both `winery` and `name` are extracted with confidence `>= 0.65`, the local read is returned immediately without consuming any cloud API quota.
2. **Tier 2 — OpenRouter Vision Fallback (`OPENROUTER_API_KEY`)**: Tried when Ollama fails or reports a weak identity read.
3. **Tier 3 — WineAPI.io Label Recognition (`WINEAPIIO_KEY`, `POST /identify/image`)**: Automatically rescues scans whenever local Ollama (and OpenRouter, if configured) fails or leaves a weak read. Combines WineAPI.io label OCR (`visionDetails.rawLabelText`) with catalog candidate matching (`wine` and `suggestions`) to extract `winery`, `name`, `vintage`, `region`, `country_of_origin`, `grape_type`, normalized `color`, and matched catalog ID (`wineapi:<uuid>`). Non-JPEG/PNG uploads (such as WebP or GIF) are converted to JPEG in memory automatically.

Configure vision and catalog credentials in `.env`:

```dotenv
OLLAMA_URL=http://localhost:11434
OLLAMA_VISION_MODEL=qwen2.5vl:7b

OPENROUTER_API_KEY=your-openrouter-api-key
OPENROUTER_VISION_MODEL=qwen/qwen2.5-vl-72b-instruct:free

WINEAPIIO_KEY=your-wineapi-io-key
WINEAPIIO_REQUESTS_PER_DAY=100
```

Choose a vision-capable model ID from the
[OpenRouter model catalog](https://openrouter.ai/models). Optionally set `OPENROUTER_SITE_URL` and `OPENROUTER_APP_NAME` to identify the application in OpenRouter's request metadata.

Scanned label images are stored in `wine-labels/`; their filename is saved in the
wine entry's `photo_path` field when the user confirms and saves the bottle.
A backward-compatible route `/uploads/{filename}` and filesystem symlink
(`uploads -> wine-labels`) ensure existing bookmarks and links continue working.
An automated housekeeping process runs on startup and on bottle deletion,
removing orphan images from disk so that only images referenced in the database
are preserved.

---

## Wine Catalog Explorer & Dual-Provider Enrichment (WineAPI.io + Grapeminds)

The app includes an integrated **Wine Catalog Explorer** (`GET /grapeminds/search`, `GET /grapeminds/details/{id}`):

- **Selectable Catalog Provider with Automatic Fallback**:
  - **WineAPI.io (default)**: US-based catalog that includes retail price ranges (`market_price`), wine colors, grape varieties, regions, critic scores, tasting notes, and food pairings. Protected by a daily request budget (`WINEAPIIO_REQUESTS_PER_DAY=100`).
  - **Grapeminds**: European/global catalog with sensory flavor profiles, pairings, and tasting notes. Protected by a monthly request budget (`GRAPEMINDS_MONTHLY_LIMIT=200`).
  - **Both APIs Combined**: Queries both catalogs simultaneously.
  - **Automatic Fallback**: Whichever provider the user selects, if a search returns zero matches, the backend (`WineEnrichmentService.search_catalog`) automatically queries the other provider and notifies the user in the UI.
- **Query Pre-Seeding**: When opened from a bottle registration or edit dialog, the search bar is pre-seeded with the current winery and wine name.
- **Conflict-Aware Merging**: Selecting a catalog entry presents a side-by-side comparison of current form values against catalog metadata (`name`, `winery`, `vintage`, `color`, `region`, `country_of_origin`, `grape_type`, `market_price`, `description`, `pairing`, `grapeminds_tasting_notes`, `flavor_profile`).
- **Non-Destructive Safety & Cancel Protection**: Fields with conflicting values are unchecked by default to prevent accidental overwrite, and **Cancel** buttons at both the top and bottom of the Explorer return cleanly to your prior view without losing drafted edits.

Configure catalog keys in `.env`:

```dotenv
WINEAPIIO_KEY=your-wineapi-io-key
WINEAPIIO_REQUESTS_PER_DAY=100

GRAPEMINDS_API_KEY=your-grapeminds-api-key
GRAPEMINDS_MONTHLY_LIMIT=200
GRAPEMINDS_MOCK_MODE=false
```

---

## Collection Views, Filtering, Drinking Windows & CSV Export

### 1. Cards View vs. Sortable Table View
- Switch between **Cards** and **Table** using the view tabs in the **Your collection** header; your selected view and table sort column/direction are saved in `localStorage`.
- **Cards View**: Groups identical wines together, showing bottle counts, storage locations, normalized color badge, drinking window badge, comments, group edit (`Edit all N bottles`), and group checkout (`Check out bottle 🍷`).
- **Table View**: Displays one row per bottle with sortable column headers (**ID**, **Wine Name**, **Producer**, **Vintage**, **Region**, **Country**, **Color**, **Drinking Window**, **Location**, **Comment / Status**) and row actions (**Edit**, **Edit group (N)**, **Check out 🍷**, **Details**, **Notes**, **Delete**).
- **Export CSV**: Click **Export CSV** in the collection header to download the currently visible/filtered bottles (sorted in your current order) as a UTF-8 BOM CSV file (`wine-cellar-YYYY-MM-DD.csv`).

### 2. Interactive Filtering & Pairing / Tasting Notes Search
- **Metric Cards**: Click **In the Cellar**, **Red**, **White**, or **Rosé** at the top of the page to filter by color (or reset filters).
- **Storage Locations**: Click any location card or sub-rack in **Where it rests** (or use the toolbar location dropdown) to filter by that location and all of its child/descendant racks.
- **Active Filters Bar**: Displays removable pill badges for active color, location, and search filters with a **Clear all** button.
- **Food Pairing & Tasting Notes Search**: Search multi-word queries across wine identity, grape varieties, comments, **food pairings** (e.g., *steak*, *oysters*, *lamb*), **catalog tasting notes**, **descriptions**, and **personal tasting notes**, with highlighted match snippets on cards and table rows.

### 3. Drinking Window Badges
- Each wine supports optional `drink_from` and `drink_until` year fields (`1800–2200`, validated so `drink_until >= drink_from`).
- Cards and table rows display a status badge based on the current year:
  - **Hold** (`current_year < drink_from`)
  - **Ready to drink** (`drink_from <= current_year < drink_until`)
  - **Drink soon** (`current_year == drink_until`, final year of window)
  - **Past peak** (`current_year > drink_until`)

---

## Bottle Checkout ("Check Out a Bottle 🍷") vs. Deletion

The cellar distinguishes between checking out a bottle (consuming/gifting) and deleting an erroneous entry:

### 1. Check Out a Bottle 🍷 (Consumption / Removal)
- Accessible from the top hero bar (**Check out a bottle**), **Menu → Check out a bottle**, any bottle card/table row (**Check out 🍷**), or by scanning a bottle's QR code with a phone camera (opening `/wines/{qr_id}` automatically launches the checkout dialog for that bottle).
- Look up a bottle by typing its QR ID, picking from the autocomplete list, or using the in-browser camera QR scanner (**Scan QR 📷**).
- Prompts for checkout details:
  - **Checkout Date**: Defaults to today's date (`YYYY-MM-DD`).
  - **Comment**: Defaults to `"Opened"` (or enter e.g. `"Gifted to Sarah"`).
  - **Wine Tasting Notes & Food Pairing**: Pre-filled from the wine record so you can refine them; if the bottle belongs to a multi-bottle group and you modify these fields, the app asks whether to apply the update to **all bottles of this wine** or **only this bottle**.
  - **Personal Tasting Journal Entry**: Optional sensory sliders (**Tannin**, **Acidity**, **Body**, **Alcohol**, **Fruit Intensity**), aroma descriptors, and tasting notes.
- Atomically marks the bottle's status as inactive (`removed` / `gifted` / `broken` via `POST /wines/{qr_id}/checkout` or `/remove`) while preserving it in database history under the **Checked out (inactive)** or **All bottles** filter. Returning a bottle to the cellar (`Return to cellar`) restores its status to `in_cellar`.

### 2. Delete Bottle (Purge)
- Permanently deletes a bottle and all of its associated tasting notes from the database (`DELETE /wines/{qr_id}`).
- Intended only for mistaken or duplicate entries; restricted to administrators and requires explicit confirmation.

---

## Run the app

Install dependencies and run the FastAPI app from this directory:

```sh
pip install -r requirements.txt
uvicorn main:app --host 127.0.0.1 --port 8000
```

### Running under systemd & Supervised Restart
For continuous background operation, deploy with `./deploy.sh`. It installs and enables
`systemd/wine-app.service` as a user unit and manages runtime restarts:

```sh
./deploy.sh
systemctl --user status wine-app.service
```

The web UI includes a supervised **Settings → Restart server** button (`POST /admin/restart`), which triggers a graceful restart via systemd and polls `/auth/session` until the server is back online.

### Running Tests
Execute the comprehensive test suite (114 tests across 17 test suites):

```sh
.venv/bin/python -m unittest discover -s . -p 'test_*.py'
```

---

## Printable bottle QR labels

Generate printable labels either directly from the web application or using the command line tool:

### 1. In-App Web Interface (Admin Only)
Open **Menu → Generate Bottle Labels** while signed in as an admin:
- Pre-fills with the next recommended starting number (auto-detected from active cellar bottles and previous sheets).
- Live preview calculates ending number and detects conflicts in real time.
- Clicking **Generate & Download PDF ↗** streams the PDF file and triggers an immediate browser download.

### 2. Standalone CLI Tool
Run the label generator from this directory:

```sh
python generate_labels.py
```

### Template & Layout Specifications
- **Template**: **SpartanIndustrial® R001**
- **Sheet Size**: Standard US Letter (8.5″ × 11″)
- **Label Dimensions**: 1.0″ width × 0.5″ height (160 labels per sheet: 8 columns across × 20 rows down)
- **Margins & Spacing**: Left/Right margin 0.4375″, Top/Bottom margin 0.5375″, Horizontal pitch 1.325″, Vertical pitch 0.725″
- **Design**: 0.40″ × 0.40″ QR code on the left (linking to `/wines/{qr_id}`) and auto-scaling, centered bottle identifier text on the right.
- **Print Setting**: Print at 100% / actual size (do not select "Fit to Page").

Generated PDFs are saved in `wine-bottle-QR-codes/` and used numeric IDs are recorded in `used_label_numbers.json` to prevent accidental duplicate label printing.

---

## Multi-User Accounts & Access Control

The app supports multi-user collaboration for household members and guests:

- **Root Admin (`cellar`)**: The primary administrative account. Automatically seeded and protected against deletion, demotion, or deactivation.
- **Access Requests**: Guests and household members can request access by providing their username, email address, and optional initial password (`POST /auth/request-access`).
- **Admin Approval & Email Delivery**: The admin reviews pending requests under **Menu → Users & Access** and approves or declines them. Upon approval, an email is sent to the user (`email_service.py` with SMTP support or local fallback logging in `sent_emails.log`). If no password was provided at registration, a secure activation link is included; its validity is configured by `ACCOUNT_ACTIVATION_TTL_HOURS` (48 hours by default).
- **Forgot Password Recovery**: Users can request password recovery (`POST /auth/forgot-password`). A secure reset token is emailed (`POST /auth/reset-password`); its validity is configured by `PASSWORD_RESET_TTL_HOURS` (1 hour by default).
- **Show/Hide Password**: An interactive eye icon toggle appears beside all password fields.
- **User Roles & Account Management**: Supports `admin` and `user` roles. Admins can deactivate/reactivate users or permanently delete accounts.
- **Admin Privilege Boundaries**: Sensitive operations are restricted exclusively to administrators:
  - Approving or declining user access requests (`POST /admin/users/...`)
  - Adding, editing, or deleting storage locations (`POST/PATCH/DELETE /locations/...`)
  - Permanently deleting wine bottles, individually or via batch deletion (`DELETE /wines/...`, `DELETE /wines/batch`)
  - Generating and downloading printable label sheets (`POST /admin/labels/generate`)
  - Running label directory housekeeping (`POST /admin/housekeeping/sync-labels`)
  - Restarting the cellar service (`POST /admin/restart`)
- **Profile & Change Password**: Logged-in users can update their own password via **Menu → My Account**.
- **Tasting Note Attribution**: Tasting notes automatically record and display the name of the author.

Optional SMTP configuration in `.env`:

```dotenv
SMTP_HOST=smtp.gmail.com        # Leave blank for local fallback to sent_emails.log
SMTP_PORT=587
SMTP_USER=your-email@gmail.com
SMTP_PASSWORD=your-app-password
SMTP_FROM=cellar@local
SMTP_TLS=true
```

---

## Sign-in configuration

The API and cellar data require a username and password. Set these values in
`.env` before starting the app (or in `.env.auth` if they are omitted from
`.env`):

```dotenv
CELLAR_USERNAME=your-username
CELLAR_PASSWORD=use-a-unique-password-at-least-10-characters
CELLAR_SESSION_SECRET=replace-with-at-least-32-random-characters
WINE_APP_TTL_DAYS=30
CELLAR_COOKIE_SECURE=false
```

The password must contain at least 10 characters. The app refuses to start
without all three credentials configured. The session cookie is HTTP-only and
signed; its lifetime is configurable with `WINE_APP_TTL_DAYS` (30 days by
default), or with `CELLAR_SESSION_TTL_HOURS` for an hours-based override. Keep
`CELLAR_COOKIE_SECURE=false` only for local HTTP development; set it to `true`
when serving the app over HTTPS.
