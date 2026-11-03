# Google Drive

Google Drive as an ordinary folder, `~/GoogleDrive`, mounted with
[rclone](https://rclone.org/) at login, with a *Google Диск* place in Dolphin.

KDE's own route (Online Accounts + kio-gdrive) does not work: the sign-in
succeeds, but Google refuses Drive access to KDE's OAuth client ("Requested
resource is forbidden", KDE bugs 454030, 508751). rclone talks to the Drive API
directly.

```bash
components/google-drive/install.sh                          # rclone's built-in client id
components/google-drive/install.sh CLIENT_ID CLIENT_SECRET  # your own client id (recommended)
```

The script installs the current rclone from rclone.org (the Ubuntu package is
years behind), opens the browser for the Google sign-in, installs and starts the
`rclone-gdrive` user service and adds the Dolphin place. The access token stays
in `~/.config/rclone/rclone.conf` (mode 600).

How the folder behaves (`rclone-gdrive.service`):

- `--vfs-cache-mode full`: opened files are cached locally (up to 10 GB, kept 30
  days), edits are uploaded in the background, so any program can work on them.
- Files that are not in the cache need the network to open.
- Google Docs, Sheets and Slides appear as .docx, .xlsx, .pptx.
- Changes made elsewhere show up within a minute (`--poll-interval 1m`).

```bash
systemctl --user status rclone-gdrive      # state
journalctl --user -u rclone-gdrive         # log
systemctl --user restart rclone-gdrive     # remount
```

## Your own client id

rclone's shared client id is being retired and stops working during 2026, and
it is rate-limited for everyone. Create your own (free):

1. [Google Cloud Console](https://console.cloud.google.com/) → create a project
   (any name, e.g. *rclone*), or use one you already have. In an existing
   project, still create a separate *Desktop app* client for rclone (step 5):
   either app's key can then be revoked without breaking the other.
2. *APIs & Services → Library* → **Google Drive API** → *Enable*.
3. *Google Auth Platform* (OAuth consent screen) → *Get started*: app name,
   support e-mail, audience **External**, contact e-mail.
4. *Data access* → add the scopes `.../auth/drive`, `.../auth/docs`,
   `.../auth/drive.metadata.readonly`.
5. *Clients* → *Create client* → type **Desktop app** → note the client ID and
   the client secret.
6. *Audience* → **Publish app** (In production). In *Testing* mode Google lets
   the sign-in expire after a week. If *Publish* is greyed out, fill in a
   homepage and a privacy policy URL in *Branding* first. A personal app
   needs no verification; at sign-in click through "Google hasn't verified this
   app" (*Advanced* → *Go to … (unsafe)*). Publishing also stops the weekly
   expiry for every other app that signs in through the same project.
7. `components/google-drive/install.sh CLIENT_ID CLIENT_SECRET` — it switches
   the existing remote to your client and signs in again.
