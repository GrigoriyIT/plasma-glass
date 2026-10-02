#!/bin/bash
# Guake as a Mac-ergonomics drop-down terminal for the Kubuntu look:
# slides strictly vertically from the top edge (own KWin effect "quakeslide"),
# one third of the screen, theme-matching dark style, stock prompt, F12 via
# KDE global shortcuts talking to the running Guake over D-Bus (no launch
# feedback, no dock icon). Run as the desktop user inside the Plasma session.
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
B=~/plasma-fix-backup/before-guake-$(date +%F-%H%M); mkdir -p $B
gsettings list-recursively | grep "^guake" > $B/guake-gsettings.txt
cp -a ~/.config/kwinrc ~/.config/kwinrulesrc $B/ 2>/dev/null || true

# Screen size for the forced geometry (Guake misreads it under XWayland).
read SW SH < <(kscreen-doctor -o 2>/dev/null | sed 's/\x1b\[[0-9;]*m//g' | awk '/Geometry:/{split($3,a,"x"); print a[1], a[2]; exit}')
SW=${SW:-1920}; SH=${SH:-1080}; H=$((SH / 3))

# 1. Guake settings
fc-list : family | grep -qx "Hack" && FONT="Hack 11" || FONT="Monospace 11"
g(){ gsettings set "$@"; }
g guake.general start-at-login true
g guake.general window-height 33
g guake.general window-width 100
g guake.general window-tabbar true
g guake.general use-scrollbar false
g guake.general hide-tabs-if-one-tab false
g guake.general background-image-file ""
g guake.general use-default-font false
g guake.style.font style "$FONT"
g guake.style.font palette-name "Custom"
g guake.style.font palette "#232627:#ed1515:#11d116:#f67400:#1d99f3:#9b59b6:#1abc9c:#fcfcfc:#7f8c8d:#c0392b:#1cdc9a:#fdbc4b:#3daee9:#8e44ad:#16a085:#ffffff:#dedede:#1f1f1f"
g guake.style.font bold-is-bright false
g guake.style.background transparency 90
g guake.keybindings.global show-hide disabled   # "" makes Guake nag at login
g guake.keybindings.global show-focus disabled

# 2. Vertical slide effect
mkdir -p ~/.local/share/kwin/effects
rm -rf ~/.local/share/kwin/effects/quakeslide
cp -r "$HERE/quakeslide" ~/.local/share/kwin/effects/
kwriteconfig6 --file kwinrc --group Plugins --key quakeslideEnabled true

# 3. KWin rule: pinned to the very top edge, full width, one third high
R=kwinrulesrc; id=guake-quake-console
if ! grep -q "^\[$id\]" ~/.config/$R 2>/dev/null; then
    count=$(kreadconfig6 --file $R --group General --key count --default 0)
    rules=$(kreadconfig6 --file $R --group General --key rules)
    kwriteconfig6 --file $R --group General --key count $((count + 1))
    kwriteconfig6 --file $R --group General --key rules "${rules:+$rules,}$id"
fi
kwriteconfig6 --file $R --group $id --key Description "Guake drop-down console"
kwriteconfig6 --file $R --group $id --key wmclass "[Gg]uake"
kwriteconfig6 --file $R --group $id --key wmclassmatch 3
# only the terminal window; the Preferences dialog has the same class
kwriteconfig6 --file $R --group $id --key title "Guake!"
kwriteconfig6 --file $R --group $id --key titlematch 1
kwriteconfig6 --file $R --group $id --key position "0,0"
kwriteconfig6 --file $R --group $id --key positionrule 2
kwriteconfig6 --file $R --group $id --key size "$SW,$H"
kwriteconfig6 --file $R --group $id --key sizerule 2
# never in the dock / Alt+Tab / pager
for k in skiptaskbar skippager skipswitcher; do
    kwriteconfig6 --file $R --group $id --key $k true
    kwriteconfig6 --file $R --group $id --key ${k}rule 2
done

# Guake and its popup menus stay under the glass + corner effects like every
# other window (excluding the class also strips the glass from its menus,
# which then become unreadable).
wc=$(kreadconfig6 --file kwinrc --group Effect-liquidglass --key WindowClasses | grep -vx guake)
kwriteconfig6 --file kwinrc --group Effect-liquidglass --key WindowClasses "$wc"
ex=$(kreadconfig6 --file kwinrc --group Round-Corners --key Exclusions | tr "," "\n" | grep -vx guake | paste -sd, -)
kwriteconfig6 --file kwinrc --group Round-Corners --key Exclusions "$ex"

# Readable tab bar, scoped to Guake's notebook widget only.
mkdir -p ~/.config/gtk-3.0; touch ~/.config/gtk-3.0/gtk.css
grep -q "notebook-teminals" ~/.config/gtk-3.0/gtk.css || cat >> ~/.config/gtk-3.0/gtk.css <<'CSS'

/* Guake tab bar: dark strip matching the console, readable labels */
#notebook-teminals > header { border-radius: 0; background-color: rgba(31, 31, 31, 0.92); border: none; box-shadow: none; }
#notebook-teminals > header tab { border-radius: 0; background-color: transparent; color: #9a9a9a; border: none; box-shadow: none; padding: 4px 12px; }
#notebook-teminals > header tab label { color: #9a9a9a; }
#notebook-teminals > header tab:checked { background-color: rgba(255, 255, 255, 0.10); border-radius: 0; }
#notebook-teminals > header tab:checked label { color: #f0f0f0; }
#notebook-teminals > header tab button { color: #9a9a9a; min-height: 16px; min-width: 16px; }
/* as tall as its text */
#notebook-teminals > header { padding: 0; min-height: 0; }
#notebook-teminals > header tabs { margin: 0; padding: 0; min-height: 0; }
#notebook-teminals > header tab { padding: 1px 10px; min-height: 0; margin: 0; }
#notebook-teminals > header tab label { padding: 0; margin: 0; min-height: 0; }
#notebook-teminals > header tab button,
#notebook-teminals > header button { padding: 0 2px; margin: 0; min-height: 14px; min-width: 14px; }
#notebook-teminals > header button image { -gtk-icon-transform: scale(0.8); }
CSS

qdbus6 org.kde.KWin /KWin reconfigure
qdbus6 org.kde.KWin /Effects org.kde.kwin.Effects.unloadEffect quakeslide >/dev/null 2>&1 || true
qdbus6 org.kde.KWin /Effects org.kde.kwin.Effects.loadEffect quakeslide >/dev/null
for e in liquidglass kwin4_effect_shapecorners; do qdbus6 org.kde.KWin /Effects org.kde.kwin.Effects.reconfigureEffect $e >/dev/null 2>&1 || true; done

# 4. F12 -> D-Bus show_hide on the already running Guake
cat > ~/.local/share/applications/guake-toggle.desktop <<'DESK'
[Desktop Entry]
Type=Application
Name=Guake Toggle
Comment=Show/hide the Guake drop-down terminal
Exec=sh -c "dbus-send --session --type=method_call --dest=org.guake3.RemoteControl /org/guake3/RemoteControl org.guake3.RemoteControl.show_hide || guake"
Icon=guake
NoDisplay=true
StartupNotify=false
X-KDE-StartupNotify=false
X-KDE-GlobalAccel-CommandShortcut=true
DESK
kbuildsycoca6 >/dev/null 2>&1 || true
python3 - <<'PY'
import dbus
ka = dbus.Interface(dbus.SessionBus().get_object("org.kde.kglobalaccel", "/kglobalaccel"), "org.kde.KGlobalAccel")
action = ["guake-toggle.desktop", "_launch", "Guake Toggle", "Guake Toggle"]
ka.doRegister(action)
F12 = 0x0100003B
ka.setForeignShortcutKeys(action, dbus.Array([dbus.Struct([dbus.Array([F12, 0, 0, 0], signature="i")])], signature="(ai)"))
PY

echo "done; backup: $B"
