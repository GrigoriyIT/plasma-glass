// Sun and moon over a point on Earth, the season, and met.no weather -> scene state.
.pragma library

const RAD = Math.PI / 180;
const SYNODIC = 29.530588853;
const NEW_MOON = Date.UTC(2000, 0, 6, 18, 14);   // a known new moon

// Sun elevation and azimuth (degrees; azimuth from north, clockwise).
// Low-precision solar formulas, good to a fraction of a degree.
function sun(date, lat, lon) {
    const d = (date.getTime() - Date.UTC(2000, 0, 1, 12)) / 86400000;
    const g = (357.529 + 0.98560028 * d) * RAD;
    const q = 280.459 + 0.98564736 * d;
    const L = (q + 1.915 * Math.sin(g) + 0.020 * Math.sin(2 * g)) * RAD;
    const e = (23.439 - 0.00000036 * d) * RAD;
    const ra = Math.atan2(Math.cos(e) * Math.sin(L), Math.cos(L));
    const dec = Math.asin(Math.sin(e) * Math.sin(L));
    const gmst = ((18.697374558 + 24.06570982441908 * d) % 24 + 24) % 24;
    const ha = (gmst * 15 + lon) * RAD - ra;
    const phi = lat * RAD;
    const el = Math.asin(Math.sin(phi) * Math.sin(dec) + Math.cos(phi) * Math.cos(dec) * Math.cos(ha));
    let az = Math.atan2(-Math.sin(ha), Math.tan(dec) * Math.cos(phi) - Math.sin(phi) * Math.cos(ha)) / RAD;
    az = (az + 360) % 360;
    return { elevation: el / RAD, azimuth: az };
}

// Moon phase: 0 new, 0.25 first quarter, 0.5 full, 0.75 last quarter.
function moonPhase(date) {
    const days = (date.getTime() - NEW_MOON) / 86400000;
    return ((days % SYNODIC) + SYNODIC) % SYNODIC / SYNODIC;
}

// The moon follows the sun's path about phase x 24.8 h later: a rough but
// believable position for a picture (full moon rises at sunset).
function moon(date, lat, lon) {
    const p = moonPhase(date);
    const pos = sun(new Date(date.getTime() - p * 24.84 * 3600000), lat, lon);
    pos.phase = p;
    return pos;
}

// Position in scene units of a body at (elevation, azimuth) for a scene of the
// given width: east (90) on the left edge, west (270) on the right; the
// horizon line of the sun is the far ridge.
function place(pos, width) {
    const x = (pos.azimuth - 90) / 180 * width;
    const y = Math.max(110, 575 - pos.elevation * 14);
    return Qt.point(x, y);
}

// Season and snow on the ground (Ufa climate; temperature decides the months between).
function season(date, temp) {
    const m = date.getMonth() + 1;
    let s = m <= 3 || m === 12 ? "winter" : m <= 5 ? "spring" : m <= 8 ? "summer" : "autumn";
    let snow = s === "winter";
    if ((m === 11 || m === 4) && temp !== undefined && temp <= 0.5)
        snow = true;
    if (m === 3 && temp !== undefined && temp > 6)
        snow = false;
    return { season: s, snowGround: snow };
}

// met.no symbol_code (+ instant details) -> clouds, precipitation, fog, thunder.
function weather(symbol, details) {
    const base = (symbol || "").replace(/_(day|night|polartwilight)$/, "");
    const light = base.indexOf("light") === 0, heavy = base.indexOf("heavy") === 0;
    const out = { clouds: 0, precip: "none", intensity: 0.6, fog: 0, thunder: base.indexOf("thunder") >= 0 };
    if (details && details.cloud_area_fraction !== undefined)
        out.clouds = details.cloud_area_fraction / 100;
    else
        out.clouds = { clearsky: 0, fair: 0.2, partlycloudy: 0.5, cloudy: 0.95, fog: 0.6 }[base] ?? 0.9;
    if (base.indexOf("sleet") >= 0)
        out.precip = "sleet";
    else if (base.indexOf("snow") >= 0)
        out.precip = "snow";
    else if (base.indexOf("rain") >= 0)
        out.precip = "rain";
    if (out.precip !== "none")
        out.clouds = Math.max(out.clouds, 0.75);
    out.intensity = light ? 0.3 : heavy ? 0.95 : 0.6;
    if (base === "fog")
        out.fog = 0.75;
    else if (details && details.fog_area_fraction)
        out.fog = Math.min(0.75, details.fog_area_fraction / 100);
    return out;
}
