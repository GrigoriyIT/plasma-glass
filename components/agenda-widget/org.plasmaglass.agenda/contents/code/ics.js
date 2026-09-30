.pragma library

// Minimal iCalendar reader: VEVENT with DTSTART/DTEND/DURATION, RRULE
// (DAILY/WEEKLY+BYDAY/MONTHLY/YEARLY, INTERVAL, COUNT, UNTIL), EXDATE,
// RECURRENCE-ID overrides and cancelled events.

// Russian zones have no DST, so a fixed offset is exact. Other TZIDs fall back to local time.
const ZONES = {
    "UTC": 0, "Etc/UTC": 0, "GMT": 0,
    "Europe/Kaliningrad": 2, "Europe/Moscow": 3, "Europe/Simferopol": 3, "Europe/Volgograd": 3, "Europe/Kirov": 3,
    "Europe/Samara": 4, "Europe/Ulyanovsk": 4, "Europe/Saratov": 4, "Europe/Astrakhan": 4,
    "Asia/Yekaterinburg": 5, "Asia/Omsk": 6, "Asia/Novosibirsk": 7, "Asia/Barnaul": 7, "Asia/Tomsk": 7,
    "Asia/Novokuznetsk": 7, "Asia/Krasnoyarsk": 7, "Asia/Irkutsk": 8, "Asia/Chita": 9, "Asia/Yakutsk": 9,
    "Asia/Khandyga": 9, "Asia/Vladivostok": 10, "Asia/Ust-Nera": 10, "Asia/Magadan": 11, "Asia/Sakhalin": 11,
    "Asia/Srednekolymsk": 11, "Asia/Kamchatka": 12, "Asia/Anadyr": 12
};
const WEEKDAYS = { SU: 0, MO: 1, TU: 2, WE: 3, TH: 4, FR: 5, SA: 6 };

function parseDate(value, params) {
    if (/^\d{8}$/.test(value))
        return { t: new Date(+value.slice(0, 4), +value.slice(4, 6) - 1, +value.slice(6, 8)).getTime(), allDay: true };
    const m = /^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})(Z?)$/.exec(value);
    if (!m)
        return null;
    const y = +m[1], mo = +m[2] - 1, d = +m[3], h = +m[4], mi = +m[5], s = +m[6];
    if (m[7])
        return { t: Date.UTC(y, mo, d, h, mi, s), allDay: false };
    const zone = params.TZID;
    if (zone && ZONES[zone] !== undefined)
        return { t: Date.UTC(y, mo, d, h - ZONES[zone], mi, s), allDay: false };
    return { t: new Date(y, mo, d, h, mi, s).getTime(), allDay: false };
}

function parseDuration(v) {
    const m = /^[+-]?P(?:(\d+)W)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?$/.exec(v);
    if (!m)
        return 0;
    return (((+m[1] || 0) * 7 + (+m[2] || 0)) * 86400 + (+m[3] || 0) * 3600 + (+m[4] || 0) * 60 + (+m[5] || 0)) * 1000;
}

function text(v) {
    return v.replace(/\\n/gi, " ").replace(/\\([,;\\])/g, "$1").trim();
}

function parse(ics) {
    const lines = ics.replace(/\r?\n[ \t]/g, "").split(/\r?\n/);
    const events = [];
    let ev = null;
    for (const line of lines) {
        if (line === "BEGIN:VEVENT") {
            ev = { exdates: [] };
            continue;
        }
        if (line === "END:VEVENT") {
            if (ev && ev.start && ev.status !== "CANCELLED")
                events.push(ev);
            ev = null;
            continue;
        }
        if (!ev)
            continue;
        const colon = line.indexOf(":");
        if (colon < 0)
            continue;
        const head = line.slice(0, colon).split(";"), value = line.slice(colon + 1), params = {};
        head.slice(1).forEach(p => {
            const eq = p.indexOf("=");
            if (eq > 0)
                params[p.slice(0, eq).toUpperCase()] = p.slice(eq + 1).replace(/^"|"$/g, "");
        });
        switch (head[0].toUpperCase()) {
        case "UID": ev.uid = value; break;
        case "SUMMARY": ev.summary = text(value); break;
        case "LOCATION": ev.location = text(value); break;
        case "STATUS": ev.status = value.toUpperCase(); break;
        case "DTSTART": ev.start = parseDate(value, params); break;
        case "DTEND": ev.end = parseDate(value, params); break;
        case "DURATION": ev.duration = parseDuration(value); break;
        case "RECURRENCE-ID": ev.recurrenceId = parseDate(value, params); break;
        case "EXDATE":
            value.split(",").forEach(v => {
                const d = parseDate(v, params);
                if (d)
                    ev.exdates.push(d.t);
            });
            break;
        case "RRULE": {
            const r = {};
            value.split(";").forEach(p => {
                const eq = p.indexOf("=");
                r[p.slice(0, eq).toUpperCase()] = p.slice(eq + 1);
            });
            ev.rrule = r;
            break;
        }
        }
    }
    // an overridden instance replaces the master's occurrence at RECURRENCE-ID
    const byUid = {};
    events.forEach(e => { if (!e.recurrenceId && e.uid) byUid[e.uid] = e; });
    events.forEach(e => { if (e.recurrenceId && byUid[e.uid]) byUid[e.uid].exdates.push(e.recurrenceId.t); });
    return events;
}

function shift(d, years, months, days) {
    return new Date(d.getFullYear() + years, d.getMonth() + months, d.getDate() + days,
                    d.getHours(), d.getMinutes(), d.getSeconds());
}

function occurrences(ev, from, to) {
    const dur = ev.end ? ev.end.t - ev.start.t : (ev.duration || (ev.start.allDay ? 86400e3 : 0));
    const out = [];
    const push = t => {
        if (t + Math.max(dur, 1) > from && t < to && ev.exdates.indexOf(t) < 0)
            out.push({ t: t, end: t + dur });
    };
    if (!ev.rrule || ev.recurrenceId) {
        push(ev.start.t);
        return out;
    }
    const r = ev.rrule, freq = r.FREQ, interval = +(r.INTERVAL || 1);
    const until = r.UNTIL ? (parseDate(r.UNTIL, {}) || { t: Infinity }).t : Infinity;
    const count = r.COUNT ? +r.COUNT : Infinity;
    const start = new Date(ev.start.t);
    const byday = r.BYDAY ? r.BYDAY.split(",").map(d => WEEKDAYS[d.slice(-2)]).filter(d => d !== undefined) : null;
    // without COUNT, skip straight to the window for fast rules
    const period = freq === "DAILY" ? interval * 86400e3 : freq === "WEEKLY" ? interval * 7 * 86400e3 : 0;
    let k = count === Infinity && period ? Math.max(0, Math.floor((from - ev.start.t - dur) / period) - 1) : 0;
    let n = 0;
    for (let guard = 0; guard < 3000; guard++, k++) {
        let cands;
        if (freq === "DAILY") {
            cands = [shift(start, 0, 0, k * interval)];
        } else if (freq === "WEEKLY") {
            const base = shift(start, 0, 0, k * 7 * interval);
            if (byday && byday.length) {
                const monday = shift(base, 0, 0, -((base.getDay() + 6) % 7));
                cands = byday.map(d => shift(monday, 0, 0, (d + 6) % 7)).filter(d => d >= start).sort((a, b) => a - b);
            } else {
                cands = [base];
            }
        } else if (freq === "MONTHLY") {
            cands = [shift(start, 0, k * interval, 0)];
        } else if (freq === "YEARLY") {
            cands = [shift(start, k * interval, 0, 0)];
        } else {
            break;
        }
        for (const d of cands) {
            const t = d.getTime();
            if (t > until || n >= count)
                return out;
            n++;
            push(t);
        }
        if (cands.length && cands[0].getTime() >= to)
            break;
    }
    return out;
}

// All occurrences of all events of one calendar within [from, to).
function collect(ics, from, to, calendar) {
    const out = [];
    parse(ics).forEach(ev => occurrences(ev, from, to).forEach(o => out.push({
        t: o.t, end: o.end, allDay: ev.start.allDay, calendar: calendar,
        summary: ev.summary || "(без названия)", location: ev.location || ""
    })));
    return out;
}
