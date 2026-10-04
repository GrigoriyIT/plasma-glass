.pragma library

// Production calendar: federal days off come from xmlcalendar.ru (with the
// government's transfers); regional days off are listed here, because no free
// machine-readable source carries them.
//
// xmlcalendar "days" per month: listed day = non-working, "N*" = shortened
// working day, "N+" = day off moved from another date.

const REGIONS = {
    "": { name: "только федеральный", years: {} },
    // Республика Башкортостан. Status [П-втор], not checked against the primary act
    // (Закон РБ о праздничных днях, указ Главы РБ на 2026 год):
    //   s.glavbukh.ru/files/docsnew/27_11_2025/PrCalRB.pdf (Главбух, 27.11.2025),
    //   grossoffer.ru/work-calendar/2026/RU-BAS/. Both: 24 December is a working day;
    //   altera-audit.ru disagrees (counts 24 December as a day off).
    "02": {
        name: "Республика Башкортостан",
        years: {
            "2026": {
                off: {
                    "2026-03-20": "Ураза-байрам",
                    "2026-05-27": "Курбан-байрам",
                    "2026-10-12": "День Республики Башкортостан (перенос с 11 октября)"
                },
                short: ["2026-03-19", "2026-05-26"]
            }
        }
    }
};

const FEDERAL_NAMES = {
    "01-01": "Новогодние каникулы", "01-02": "Новогодние каникулы", "01-03": "Новогодние каникулы",
    "01-04": "Новогодние каникулы", "01-05": "Новогодние каникулы", "01-06": "Новогодние каникулы",
    "01-07": "Рождество Христово", "01-08": "Новогодние каникулы",
    "02-23": "День защитника Отечества", "03-08": "Международный женский день",
    "05-01": "Праздник Весны и Труда", "05-09": "День Победы",
    "06-12": "День России", "11-04": "День народного единства"
};

function iso(y, m, d) {
    return y + "-" + String(m).padStart(2, "0") + "-" + String(d).padStart(2, "0");
}

const MONTHS_GEN = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля",
                    "августа", "сентября", "октября", "ноября", "декабря"];

// xmlcalendar JSON -> { "YYYY-MM-DD": { off, short, moved, from: "MM-DD" of the moved day off } }
function parseFederal(json) {
    const d = JSON.parse(json), out = {}, movedFrom = {};
    (d.transitions || []).forEach(tr => {
        const f = tr.from.split("."), t = tr.to.split(".");   // "MM.DD"
        movedFrom[iso(d.year, +t[0], +t[1])] = f[0] + "-" + f[1];
    });
    d.months.forEach(m => m.days.split(",").forEach(tok => {
        const n = parseInt(tok, 10);
        if (!n)
            return;
        const key = iso(d.year, m.month, n);
        out[key] = { off: tok.indexOf("*") < 0, short: tok.indexOf("*") >= 0, moved: tok.indexOf("+") >= 0, from: movedFrom[key] || "" };
    }));
    return out;
}

function movedName(from) {
    const what = FEDERAL_NAMES[from];
    const when = (+from.slice(3, 5)) + " " + MONTHS_GEN[+from.slice(0, 2) - 1];
    return (what ? what + " " : "") + "(перенос с " + when + ")";
}

// What kind of day is `date` (a local Date)? federal: merged parseFederal() maps.
function dayInfo(date, federal, region) {
    const key = iso(date.getFullYear(), date.getMonth() + 1, date.getDate());
    const weekend = date.getDay() === 0 || date.getDay() === 6;
    const reg = (REGIONS[region] || REGIONS[""]).years[String(date.getFullYear())] || { off: {}, short: [] };
    const fed = federal[key];
    if (reg.off[key])
        return { off: true, regional: true, name: reg.off[key] };
    if (fed && fed.off) {
        const name = FEDERAL_NAMES[key.slice(5)] || (fed.from ? movedName(fed.from)
                   : fed.moved ? "перенос выходного дня" : (weekend ? "" : "нерабочий день"));
        return { off: true, regional: false, name: name };
    }
    if (fed || reg.short.indexOf(key) >= 0)
        return { off: false, short: (fed && fed.short) || reg.short.indexOf(key) >= 0 };
    return { off: weekend, short: false };
}

// The nearest Monday–Friday that is a day off, within `horizon` days from `from`.
function nextWeekdayOff(from, federal, region, horizon) {
    const start = new Date(from.getFullYear(), from.getMonth(), from.getDate());
    for (let i = 0; i <= horizon; i++) {
        const d = new Date(start.getFullYear(), start.getMonth(), start.getDate() + i);
        if (d.getDay() === 0 || d.getDay() === 6)
            continue;
        const info = dayInfo(d, federal, region);
        if (info.off)
            return { date: d, days: i, name: info.name, regional: info.regional };
    }
    return null;
}

function regionNames() {
    return Object.keys(REGIONS).map(k => ({ code: k, name: REGIONS[k].name }));
}

function hasYear(region, year) {
    return region === "" || !!(REGIONS[region] && REGIONS[region].years[String(year)]);
}
