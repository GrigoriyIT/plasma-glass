# Troubleshooting

## Plasma or Konsole crashes on start, Chrome is installed

Chrome 154+ writes `cache-12` files into `~/.cache/fontconfig` and replaces the
system `cache-9` files with symlinks to them. Check:

```bash
ls -l ~/.cache/fontconfig | grep -c '^l'   # anything above 0 means a poisoned cache
```

Repair and prevent it:

```bash
rm -rf ~/.cache/fontconfig && fc-cache -f
components/chrome-fontconfig-fix/install.sh
```

## The glass or the corners stopped working after an update

`liquidglass`, KDE Rounded Corners and InputActions are compiled against KWin.
After a KWin upgrade rebuild them (see [INSTALL.md](INSTALL.md)) and log out and in.
Re-running the MacTahoe installer overwrites the patched effect and the edited
theme SVGs; re-apply sections 2, 3 and 5 of INSTALL.md afterwards.

## A theme change does not show

- Aurorae window decoration: switch the decoration to Breeze and back.
- Plasma theme: `rm ~/.cache/plasma_theme_*.kcache; systemctl --user restart plasma-plasmashell`.
- KWin effect library: log out and in.
- Already open applications pick up a new Kvantum palette only after a restart.

## Guake

- Started from an SSH session it aborts (no `XAUTHORITY`): use `systemd-run --user guake`.
- F12 does nothing on HP laptops: the key sends a media code; set the shortcut in
  *System Settings → Shortcuts → Guake Toggle*.

## Sticky notes appear on the desktop

A three-finger touch registered as a middle click and pasted the clipboard. Remove
*Paste* from the desktop's middle-button action.

## Recording key presses to debug a shortcut

Don't. It captures everything typed, passwords included. Assign the key in
System Settings instead; the dialog shows what the key actually sends.
