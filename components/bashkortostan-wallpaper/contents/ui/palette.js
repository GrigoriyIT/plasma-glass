// Colours of the panorama for a given sun elevation, season and weather.
.pragma library

function hex(c) {
    return [parseInt(c.substr(1, 2), 16) / 255, parseInt(c.substr(3, 2), 16) / 255, parseInt(c.substr(5, 2), 16) / 255];
}

function mix(a, b, t) {
    return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t];
}

function clamp(v, lo, hi) {
    return Math.max(lo, Math.min(hi, v));
}

function rgba(c, a) {
    return Qt.rgba(clamp(c[0], 0, 1), clamp(c[1], 0, 1), clamp(c[2], 0, 1), a === undefined ? 1 : a);
}

function grey(c, k) {
    const l = 0.3 * c[0] + 0.59 * c[1] + 0.11 * c[2];
    return [l * k, l * k, l * k];
}

// Sky and light by sun elevation (degrees). light multiplies the daylight
// colour of every layer.
const KEYS = [
    { e: -18, top: "#060a1a", hor: "#131a33", light: [0.15, 0.18, 0.30] },
    { e: -9,  top: "#101839", hor: "#36305c", light: [0.27, 0.27, 0.44] },
    { e: -3,  top: "#25336b", hor: "#c9706a", light: [0.52, 0.44, 0.56] },
    { e: 2,   top: "#4869ab", hor: "#f2a565", light: [0.95, 0.72, 0.55] },
    { e: 8,   top: "#4c82cb", hor: "#f0cfa4", light: [1.0, 0.9, 0.78] },
    { e: 20,  top: "#3b79cd", hor: "#b9d5ee", light: [1.0, 1.0, 1.0] },
    { e: 60,  top: "#2d6cc6", hor: "#a6caed", light: [1.04, 1.04, 1.04] }
];

function sky(e) {
    if (e <= KEYS[0].e)
        return { top: hex(KEYS[0].top), hor: hex(KEYS[0].hor), light: KEYS[0].light };
    for (let i = 1; i < KEYS.length; i++) {
        if (e <= KEYS[i].e) {
            const a = KEYS[i - 1], b = KEYS[i], t = (e - a.e) / (b.e - a.e);
            return { top: mix(hex(a.top), hex(b.top), t), hor: mix(hex(a.hor), hex(b.hor), t), light: mix(a.light, b.light, t) };
        }
    }
    const k = KEYS[KEYS.length - 1];
    return { top: hex(k.top), hor: hex(k.hor), light: k.light };
}

// Daylight colours by season; "winter" is used whenever snow lies on the ground.
const BASE = {
    far:        { all: "#7d9abd" },
    mid:        { all: "#5d7c8e" },
    shikhan:    { summer: "#6f8653", autumn: "#8c8150", winter: "#dbe3ec", spring: "#7f9a55" },
    shikhanRock:{ all: "#cfc7b1", winter: "#eef2f6" },
    hills:      { summer: "#3e6243", autumn: "#56603f", winter: "#c6d0da", spring: "#4d7346" },
    hillConifers: { all: "#294332" },
    hillCrowns: { summer: "#4c7a3d", autumn: "#d39a2d", winter: "#8c8478", spring: "#8bbf55" },
    plain:      { summer: "#77a04b", autumn: "#a8904e", winter: "#edf2f7", spring: "#8ebf59" },
    near:       { summer: "#4d7934", autumn: "#88773a", winter: "#e4ebf2", spring: "#689a3b" },
    grass:      { summer: "#3e6a29", autumn: "#a2883d", winter: "#b7bfc8", spring: "#5d9a34" },
    pines:      { all: "#21402c" },
    yurt:       { all: "#e6d9bf" },
    horses:     { all: "#4a3222" },
    yurtBand:   { all: "#a2382a" },
    yurtDoor:   { all: "#6a4829" },
    birchTrunks:{ all: "#efeee6" },
    birchMarks: { all: "#2b2a28" },
    birchBranches: { all: "#5b4a3a" },
    birchCrowns:{ summer: "#5b9a41", autumn: "#e5b03a", winter: "#7a6e62", spring: "#a5d36a" }
};

// Share of the horizon colour mixed in: aerial perspective.
const HAZE = { far: 0.55, mid: 0.4, shikhan: 0.27, shikhanRock: 0.27, hills: 0.22, hillConifers: 0.22,
               hillCrowns: 0.22, plain: 0.12, near: 0.03, grass: 0.03, pines: 0.05, horses: 0.04 };

function base(name, season) {
    const b = BASE[name];
    return hex(b[season] || b.all || b.summer);
}

// state: { elevation, season, snowGround, clouds (0..1), fog (0..1) }
function colours(st) {
    const s = sky(st.elevation);
    const c = st.clouds, f = st.fog;
    let top = s.top, hor = s.hor, light = s.light;
    // Overcast: flatter, greyer sky and dimmer light.
    top = mix(top, grey(top, 1.15), c * 0.8);
    hor = mix(hor, grey(hor, 1.0), c * 0.75);
    light = mix(light, grey(light, 0.82), c * 0.6);
    const season = st.snowGround ? "winter" : st.season;
    const out = { skyTop: rgba(top), skyHorizon: rgba(hor), skyMid: rgba(mix(top, hor, 0.45)) };
    for (const name in BASE) {
        const lit = base(name, season);
        let col = [lit[0] * light[0], lit[1] * light[1], lit[2] * light[2]];
        const h = HAZE[name] || 0;
        const haze = clamp(h + f * (1 - h) * (0.35 + h), 0, 0.92);
        col = mix(col, hor, haze);
        out[name] = rgba(col);
    }
    // Water reflects the sky: between the horizon and the zenith, a bit darker.
    out.river = rgba(mix(mix(hor, top, 0.35), [0, 0, 0], 0.18));
    out.shimmer = rgba(mix(hor, [1, 1, 1], 0.35), clamp(0.25 + 0.5 * (1 - c), 0, 0.75));
    out.yurtShade = Qt.rgba(0, 0, 0, 0.16);
    out.smoke = rgba(mix(hor, [0.92, 0.92, 0.92], 0.5), 0.32);
    const day = clamp((st.elevation + 4) / 14, 0, 1);
    // Clouds: white by day, warm near sunset, dark blue at night, grey when overcast.
    let cloud = mix(mix([0.16, 0.19, 0.28], mix(hor, [1, 1, 1], 0.45), day), [1, 1, 1], day * 0.6);
    cloud = mix(cloud, grey(cloud, 0.82), c * 0.7);
    // Rain and snow clouds are heavy and dark.
    if (st.precip && st.precip !== "none")
        cloud = mix(cloud, grey(cloud, 0.62), 0.55);
    out.cloud = rgba(cloud);
    out.cloudShade = rgba(mix(mix(cloud, hor, 0.35), [0, 0, 0], 0.16));
    out.fog = rgba(mix(mix(hor, [1, 1, 1], 0.55), [0.75, 0.8, 0.9], 1 - day));
    // Lamp in the yurt: lit from dusk to dawn.
    out.lamp = clamp((-st.elevation + 1) / 6, 0, 1) * 0.95;
    out.rain = rgba(mix([0.55, 0.6, 0.7], [0.85, 0.88, 0.95], day), 0.55);
    out.snow = rgba(mix([0.7, 0.74, 0.85], [1, 1, 1], day), 0.95);
    // The sun: white-yellow high, orange low.
    const low = clamp(1 - st.elevation / 12, 0, 1);
    out.sun = rgba(mix([1, 0.98, 0.9], [1, 0.62, 0.32], low));
    out.sunGlow = rgba(mix([1, 0.95, 0.8], [1, 0.55, 0.3], low), 0.32 * (1 - c));
    out.stars = clamp((-st.elevation - 6) / 8, 0, 1) * clamp(1 - c * 1.3, 0, 1) * (1 - f);
    return out;
}
