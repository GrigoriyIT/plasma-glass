import QtQuick
import QtQuick.Layouts
import QtQuick.LocalStorage
import org.kde.plasma.plasmoid
import org.kde.plasma.core as PlasmaCore
import org.kde.notification

// Desktop card: MOEX perpetual futures (USDRUBF/EURRUBF/CNYRUBF) against the
// Bank of Russia official rate, plus Brent futures. MOEX ISS public data is
// delayed by ~15 minutes. Sharp moves light the tile up and send a notification.
// Urals has no free daily quote: its tile is an estimate = Brent + the official
// monthly discount (Ministry of Economic Development average, from Argus, minus
// Brent's monthly average); month/year charts show the official averages dashed.
PlasmoidItem {
    id: root

    Plasmoid.backgroundHints: PlasmaCore.Types.NoBackground
    preferredRepresentation: fullRepresentation

    readonly property string iss: "https://iss.moex.com/iss/engines/futures/markets/forts/securities"
    // hourPct / dayPct: move thresholds that count as "sharp"
    readonly property var instruments: [
        { key: "USD", title: "USD/RUB", secid: "USDRUBF", cbrCode: "USD", cbrId: "R01235", decimals: 2, prefix: "", hourPct: 0.8, dayPct: 1.5 },
        { key: "EUR", title: "EUR/RUB", secid: "EURRUBF", cbrCode: "EUR", cbrId: "R01239", decimals: 2, prefix: "", hourPct: 0.8, dayPct: 1.5 },
        { key: "CNY", title: "CNY/RUB", secid: "CNYRUBF", cbrCode: "CNY", cbrId: "R01375", decimals: 3, prefix: "", hourPct: 0.8, dayPct: 1.5 },
        { key: "BR",  title: "Brent",   asset: "BR", decimals: 2, prefix: "$", hourPct: 1.5, dayPct: 3.0 },
        { key: "URALS", title: "Urals", derived: true, decimals: 2, prefix: "≈$" },
        { key: "IMOEX", title: "Индекс МосБиржи", secid: "IMOEXF", decimals: 1, prefix: "", hourPct: 1.0, dayPct: 2.5 },
        { key: "GOLD", title: "Золото", secid: "GLDRUBF", decimals: 0, prefix: "", suffix: "₽/г", hourPct: 1.0, dayPct: 2.5 }
    ]
    // tile rows: currencies, oil, market
    readonly property var layoutRows: [["USD", "EUR", "CNY"], ["BR", "URALS"], ["IMOEX", "GOLD"]]
    function instrument(key) {
        return instruments.find(ins => ins.key === key);
    }
    readonly property var ranges: [
        { id: "day", label: "День" }, { id: "week", label: "Неделя" },
        { id: "month", label: "Месяц" }, { id: "year", label: "Год" }
    ]

    readonly property string range: Plasmoid.configuration.range || "day"
    readonly property real sensitivity: Plasmoid.configuration.alertSensitivity > 0 ? Plasmoid.configuration.alertSensitivity : 1
    property var dayMarket: ({})   // key -> { points: [{t, v}], base, secid }; always kept fresh for alerts
    property var market: ({})      // same for the selected range when it is not "day"
    property var cbr: ({})         // code -> { today, next, nextDate }
    property var cbrHist: ({})     // code -> [{t, v}] ascending, t = effective from
    property var alerts: ({})      // key -> { dir, kind, text }
    property var notified: ({})    // "KEY:kind:dir" -> true, reset when the move calms down
    property var urals: ({})       // "YYYY-MM" -> official monthly average, $/bbl
    property var brentYear: null   // stitched front-month Brent { points, base } for monthly averages
    property real lastUralsFetch: 0
    property real lastBrentYearFetch: 0
    readonly property var uralsMonthSlugs: ["yanvar", "fevral", "mart", "aprel", "may", "iyun",
                                            "iyul", "avgust", "sentyabr", "oktyabr", "noyabr", "dekabr"]
    property var keyRate: null     // { rate, prev, since, next }  (since/next: "YYYY-MM-DD")
    property real lastKeyRateFetch: 0
    property string brentSecid: ""
    property string brentExpiry: ""
    property real dataTime: 0
    property real lastDayFetch: 0
    property real lastRangeFetch: 0
    property real lastCbrFetch: 0
    property real lastContractFetch: 0
    property bool offline: false
    property bool started: false

    // ---- time helpers (exchange and CBR work in Moscow time, UTC+3) ----
    function mskParse(s) {
        const p = s.split(/[- :]/);
        return Date.UTC(+p[0], +p[1] - 1, +p[2], +p[3] - 3, +p[4], +(p[5] || 0));
    }
    function mskDate(offsetDays) {
        return new Date(Date.now() + 3 * 3600e3 + offsetDays * 86400e3).toISOString().slice(0, 10);
    }
    function cbrDate(iso) {
        return iso.slice(8, 10) + "/" + iso.slice(5, 7) + "/" + iso.slice(0, 4);
    }
    function mskHour() {
        const d = new Date(Date.now() + 3 * 3600e3);
        return d.getUTCHours() + d.getUTCMinutes() / 60;
    }
    function fmtPct(v) {
        return (v > 0 ? "+" : "−") + Math.abs(v).toLocaleString(Qt.locale("ru_RU"), "f", 1) + "%";
    }

    function get(url, onOk, onFail, quiet) {
        const x = new XMLHttpRequest();
        x.onreadystatechange = function () {
            if (x.readyState !== XMLHttpRequest.DONE)
                return;
            if (x.status !== 200) {
                if (!quiet) {
                    console.warn("markets: HTTP", x.status, x.statusText, url);
                    root.offline = true;
                }
                if (onFail)
                    onFail();
                return;
            }
            try {
                onOk(x.responseText);
                if (!quiet)
                    root.offline = false;
            } catch (e) {
                console.warn("markets:", url, e);
                if (onFail)
                    onFail();
            }
        };
        x.open("GET", url);
        x.send();
    }

    // ---- MOEX ----
    function candleQuery(r) {
        if (r === "week")
            return "interval=60&from=" + mskDate(-7);
        if (r === "month")
            return "interval=24&from=" + mskDate(-31);
        if (r === "year")
            return "interval=24&from=" + mskDate(-366);
        // newest 500 ten-minute candles: the last session plus the one before it
        return "interval=10&from=" + mskDate(-7) + "&iss.reverse=true";
    }

    // candles columns: open, close, high, low, value, volume, begin, end
    function fetchRows(secid, r, then, onFail) {
        get(iss + "/" + secid + "/candles.json?iss.meta=off&" + candleQuery(r), function (txt) {
            then(JSON.parse(txt).candles.data.slice().sort((a, b) => a[6] < b[6] ? -1 : 1));
        }, onFail);
    }

    function buildSeries(r, rows, secid) {
        let base;
        if (r === "day") {
            const day = rows[rows.length - 1][6].slice(0, 10);
            const prev = rows.filter(row => row[6].slice(0, 10) < day);
            rows = rows.filter(row => row[6].slice(0, 10) === day);
            base = prev.length ? prev[prev.length - 1][1] : rows[0][0];
        } else {
            base = rows[0][0];
        }
        return { points: rows.map(row => ({ t: mskParse(row[7]), v: row[1] })), base: base, secid: secid };
    }

    function store(r, key, series) {
        if (r === "day") {
            const m = Object.assign({}, dayMarket);
            m[key] = series;
            dayMarket = m;
            updateAlerts();
        } else {
            if (r !== range)
                return;
            const m = Object.assign({}, market);
            m[key] = series;
            market = m;
        }
        // a daily candle "ends" at 23:59; cap at the public-data delay
        const end = series.points[series.points.length - 1].t;
        dataTime = Math.max(dataTime, Math.min(Date.now() - 15 * 60e3, end));
        saveCache(r);
    }

    function fetchInstrument(ins, r) {
        if (ins.derived)
            return;
        if (ins.asset && r === "year")
            return fetchBrentYear(series => store("year", ins.key, series));
        const secid = ins.asset ? brentSecid : ins.secid;
        if (!secid)
            return;
        fetchRows(secid, r, rows => {
            if (rows.length)
                store(r, ins.key, buildSeries(r, rows, secid));
        });
    }

    // Brent: the BR contract with the largest open interest that has not expired yet.
    function fetchContract(then) {
        get(iss + ".json?iss.meta=off&iss.only=securities,marketdata"
                + "&securities.columns=SECID,ASSETCODE,LASTTRADEDATE&marketdata.columns=SECID,OPENPOSITION", function (txt) {
            const d = JSON.parse(txt), oi = {}, today = mskDate(0);
            d.marketdata.data.forEach(row => oi[row[0]] = row[1] || 0);
            let best = null;
            d.securities.data.forEach(row => {
                if (row[1] === "BR" && row[2] >= today && (!best || oi[row[0]] > oi[best[0]]))
                    best = row;
            });
            if (!best)
                return;
            brentSecid = best[0];
            brentExpiry = best[2];
            lastContractFetch = Date.now();
            then();
        });
    }

    // A year of Brent spans ~13 monthly contracts: stitch a front-month series,
    // rolling to the next contract 5 days before expiry (early in the contract month).
    function fetchBrentYear(then) {
        const codes = "FGHJKMNQUVXZ", now = new Date(Date.now() + 3 * 3600e3);
        const list = [];
        for (let k = -12; k <= 2; k++) {
            const d = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth() + k, 3));
            list.push({ secid: "BR" + codes[d.getUTCMonth()] + (d.getUTCFullYear() % 10), expiry: d.getTime(), rows: [] });
        }
        let pending = list.length;
        const done = () => {
            if (--pending)
                return;
            const byDay = {};
            list.forEach(c => c.rows.forEach(row => {
                const day = row[6].slice(0, 10), t = mskParse(row[6]);
                const cur = byDay[day];
                if (c.expiry - t < 5 * 86400e3)
                    return;
                if (!cur || c.expiry < cur.expiry)
                    byDay[day] = { expiry: c.expiry, t: mskParse(row[7]), v: row[1], open: row[0] };
            }));
            const days = Object.keys(byDay).sort().filter(d => d >= mskDate(-366));
            if (days.length < 2)
                return;
            const series = { points: days.map(d => ({ t: byDay[d].t, v: byDay[d].v })), base: byDay[days[0]].open, secid: "BR" };
            brentYear = series;
            lastBrentYearFetch = Date.now();
            saveCache("urals");
            then(series);
        };
        list.forEach(c => fetchRows(c.secid, "year", rows => { c.rows = rows; done(); }, done));
    }

    // ---- Urals: one page per month on economy.gov.ru, published ~5 days after month end ----
    function fetchUrals() {
        lastUralsFetch = Date.now();
        const now = new Date(Date.now() + 3 * 3600e3);
        for (let k = 1; k <= 12; k++) {
            const d = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth() - k, 1));
            const ym = d.toISOString().slice(0, 7);
            if (urals[ym] !== undefined)
                continue;
            get("https://www.economy.gov.ru/material/departments/d12/konyunktura_mirovyh_tovarnyh_rynkov/"
                    + "o_srednem_urovne_cen_nefti_sorta_yurals_za_" + uralsMonthSlugs[d.getUTCMonth()]
                    + "_" + d.getUTCFullYear() + "_goda.html", function (txt) {
                const text = txt.replace(/<[^>]+>/g, " ").replace(/&nbsp;/g, " ").replace(/\s+/g, " ");
                const m = /Средняя цена\s*(\d+(?:,\d+)?)\s*долл/.exec(text);
                if (!m)
                    return;
                const u = {};
                Object.keys(urals).sort().slice(-12).forEach(key => u[key] = urals[key]);
                u[ym] = parseFloat(m[1].replace(",", "."));
                urals = u;
                saveCache("urals");
            }, null, true);
        }
    }

    function brentMonthly() {
        const acc = {}, out = {};
        if (!brentYear)
            return out;
        brentYear.points.forEach(p => {
            const m = new Date(p.t + 3 * 3600e3).toISOString().slice(0, 7);
            (acc[m] = acc[m] || []).push(p.v);
        });
        Object.keys(acc).forEach(m => out[m] = acc[m].reduce((a, b) => a + b, 0) / acc[m].length);
        return out;
    }

    // month -> Urals minus Brent average, for months with an official figure
    readonly property var uralsDiscounts: {
        const bm = brentMonthly(), out = {};
        Object.keys(urals).forEach(m => { if (bm[m]) out[m] = urals[m] - bm[m]; });
        return out;
    }
    readonly property string uralsLastMonth: Object.keys(uralsDiscounts).sort().slice(-1)[0] || ""

    function monthOf(t) {
        return new Date(t + 3 * 3600e3).toISOString().slice(0, 7);
    }
    function discountAt(t) {
        const d = uralsDiscounts[monthOf(t)];
        return d !== undefined ? d : uralsDiscounts[uralsLastMonth];
    }
    // Brent series shifted by the discount of each point's month (latest known for recent months).
    function uralsSeries(brent) {
        if (!brent || !brent.points.length || !uralsLastMonth)
            return null;
        const perMonth = range === "month" || range === "year";
        const flat = uralsDiscounts[uralsLastMonth];
        const disc = t => perMonth ? discountAt(t) : flat;
        return {
            points: brent.points.map(p => ({ t: p.t, v: p.v + disc(p.t) })),
            base: brent.base + disc(brent.points[0].t),
            secid: brent.secid
        };
    }
    function uralsRef(s) {
        if (!s || !(range === "month" || range === "year"))
            return null;
        return s.points.map(p => urals[monthOf(p.t)] !== undefined ? urals[monthOf(p.t)] : NaN);
    }
    function uralsNote() {
        const m = uralsLastMonth;
        if (!m)
            return "оценка · нет данных Минэка";
        const names = ["янв", "фев", "мар", "апр", "май", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"];
        const f = v => v.toLocaleString(Qt.locale("ru_RU"), "f", 2);
        const d = uralsDiscounts[m];
        return "оценка · Минэк " + names[+m.slice(5, 7) - 1] + " $" + f(urals[m])
             + " (" + (d < 0 ? "−" : "+") + "$" + f(Math.abs(d)) + ")";
    }

    function seriesFor(ins) {
        const src = range === "day" ? dayMarket : market;
        return ins.derived ? uralsSeries(src.BR) : (src[ins.key] || null);
    }

    // ---- key rate: current value from the rate table, next meeting from the CBR calendar ----
    function fetchKeyRate() {
        lastKeyRateFetch = Date.now();
        const from = mskDate(-400), to = mskDate(0);
        const d2 = iso => iso.slice(8, 10) + "." + iso.slice(5, 7) + "." + iso.slice(0, 4);
        get("https://www.cbr.ru/hd_base/KeyRate/?UniDbQuery.Posted=True&UniDbQuery.From=" + d2(from)
                + "&UniDbQuery.To=" + d2(to), function (txt) {
            const re = /<td>(\d\d)\.(\d\d)\.(\d{4})<\/td>\s*<td>([\d,]+)<\/td>/g;
            const rows = [];   // newest first
            let m;
            while ((m = re.exec(txt)))
                rows.push({ date: m[3] + "-" + m[2] + "-" + m[1], v: parseFloat(m[4].replace(",", ".")) });
            if (!rows.length)
                return;
            let i = 0;
            while (i + 1 < rows.length && rows[i + 1].v === rows[0].v)
                i++;
            keyRate = Object.assign({}, keyRate, {
                rate: rows[0].v,
                prev: i + 1 < rows.length ? rows[i + 1].v : NaN,
                since: rows[i].date
            });
            saveCache("keyrate");
        }, null, true);
        get("https://www.cbr.ru/dkp/cal_mp/", function (txt) {
            const months = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля",
                            "августа", "сентября", "октября", "ноября", "декабря"];
            const text = txt.replace(/<[^>]+>/g, " ").replace(/&nbsp;/g, " ").replace(/\s+/g, " ");
            const re = /(\d{1,2}) ([а-я]+) (\d{4}) года Заседание Совета директоров Банка России по ключевой ставке/g;
            const today = mskDate(0);
            let m, next = "";
            while ((m = re.exec(text))) {
                const mo = months.indexOf(m[2]);
                if (mo < 0)
                    continue;
                const iso = m[3] + "-" + String(mo + 1).padStart(2, "0") + "-" + String(+m[1]).padStart(2, "0");
                if (iso >= today && (!next || iso < next))
                    next = iso;
            }
            keyRate = Object.assign({}, keyRate, { next: next });
            saveCache("keyrate");
        }, null, true);
    }

    readonly property string keyRateText: {
        const k = keyRate;
        if (!k || !k.rate)
            return "";
        const f = v => v.toLocaleString(Qt.locale("ru_RU"), "f", 2);
        const months = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля",
                        "августа", "сентября", "октября", "ноября", "декабря"];
        let s = "Ключевая ставка " + f(k.rate) + "%";
        if (!isNaN(k.prev) && k.prev !== undefined && k.prev !== null)
            s += (k.rate < k.prev ? " ↓" : " ↑") + " с " + f(k.prev) + " (" + k.since.slice(8, 10) + "." + k.since.slice(5, 7) + ")";
        if (k.next) {
            const days = Math.round((Date.UTC(+k.next.slice(0, 4), +k.next.slice(5, 7) - 1, +k.next.slice(8, 10))
                                     - Date.UTC(+mskDate(0).slice(0, 4), +mskDate(0).slice(5, 7) - 1, +mskDate(0).slice(8, 10))) / 86400e3);
            s += "  ·  заседание " + (+k.next.slice(8, 10)) + " " + months[+k.next.slice(5, 7) - 1]
               + (days === 0 ? ", сегодня" : days === 1 ? ", завтра" : ", через " + days + " " + plural(days, "день", "дня", "дней"));
        }
        return s;
    }
    function plural(n, one, few, many) {
        const a = n % 10, b = n % 100;
        return a === 1 && b !== 11 ? one : a >= 2 && a <= 4 && (b < 12 || b > 14) ? few : many;
    }

    function refreshDay() {
        lastDayFetch = Date.now();
        instruments.forEach(ins => {
            if (ins.asset && (!brentSecid || Date.now() - lastContractFetch > 3600e3))
                fetchContract(() => fetchInstrument(ins, "day"));
            else
                fetchInstrument(ins, "day");
        });
    }
    function refreshRange() {
        lastRangeFetch = Date.now();
        if (range !== "day")
            instruments.forEach(ins => fetchInstrument(ins, range));
    }

    // ---- sharp moves ----
    function alertFor(ins, s) {
        if (!ins.hourPct || !s || s.points.length < 2)
            return null;
        const p = s.points, last = p[p.length - 1];
        let j = p.length - 1;
        while (j > 0 && p[j - 1].t >= last.t - 3600e3)
            j--;
        const hour = (last.v - p[j].v) / p[j].v * 100;
        const day = (last.v - s.base) / s.base * 100;
        if (j < p.length - 1 && Math.abs(hour) >= ins.hourPct * sensitivity)
            return { dir: hour > 0 ? 1 : -1, kind: "hour", pct: hour, text: fmtPct(hour) + " за час" };
        if (Math.abs(day) >= ins.dayPct * sensitivity)
            return { dir: day > 0 ? 1 : -1, kind: "day", pct: day, text: fmtPct(day) + " за день" };
        return null;
    }

    function updateAlerts() {
        const a = {}, n = Object.assign({}, notified), fresh = [];
        instruments.forEach(ins => {
            const al = alertFor(ins, dayMarket[ins.key]);
            Object.keys(n).forEach(k => {
                if (k.startsWith(ins.key + ":") && (!al || k !== ins.key + ":" + al.kind + ":" + al.dir))
                    delete n[k];
            });
            if (!al)
                return;
            a[ins.key] = al;
            const id = ins.key + ":" + al.kind + ":" + al.dir;
            if (!n[id]) {
                n[id] = true;
                fresh.push({ ins: ins, al: al });
            }
        });
        alerts = a;
        notified = n;
        if (fresh.length && started && Plasmoid.configuration.notify)
            notify(fresh);
    }

    // One notification per update, even when several instruments jump at once.
    function notify(list) {
        const line = x => {
            const s = dayMarket[x.ins.key], last = s.points[s.points.length - 1].v;
            return (x.al.dir > 0 ? "▲ " : "▼ ") + x.ins.title + " " + x.al.text + " → "
                 + x.ins.prefix + last.toLocaleString(Qt.locale("ru_RU"), "f", x.ins.decimals);
        };
        const n = notificationComponent.createObject(root, list.length === 1
            ? { title: line(list[0]), text: "Мосбиржа, задержка 15 мин" }
            : { title: "Резкое движение: " + list.map(x => x.ins.title).join(", "), text: list.map(line).join("\n") });
        n.sendEvent();
    }

    Component {
        id: notificationComponent
        Notification {
            componentName: "plasma_workspace"
            eventId: "notification"
            iconName: "office-chart-line"
        }
    }

    // ---- Bank of Russia ----
    function fetchCbr() {
        lastCbrFetch = Date.now();
        get("https://www.cbr-xml-daily.ru/daily_json.js", function (txt) {
            const d = JSON.parse(txt), c = {};
            const published = d.Date.slice(0, 10);
            // After ~15:30 MSK the file already holds the rate for the next business day.
            const ahead = published > mskDate(0);
            ["USD", "EUR", "CNY"].forEach(code => {
                const v = d.Valute[code];
                c[code] = ahead ? { today: v.Previous / v.Nominal, next: v.Value / v.Nominal, nextDate: published }
                                : { today: v.Value / v.Nominal, next: NaN, nextDate: "" };
            });
            cbr = c;
            saveCache("day");
        });
        if (range !== "day")
            fetchCbrHist();
    }

    function fetchCbrHist() {
        const back = { week: -12, month: -40, year: -372 }[range];
        const from = cbrDate(mskDate(back)), to = cbrDate(mskDate(1));
        instruments.filter(ins => ins.cbrId).forEach(ins => {
            get("https://www.cbr.ru/scripts/XML_dynamic.asp?date_req1=" + from + "&date_req2=" + to
                    + "&VAL_NM_RQ=" + ins.cbrId, function (txt) {
                const re = /<Record Date="(\d\d)\.(\d\d)\.(\d{4})"[^>]*><Nominal>(\d+)<\/Nominal><Value>([\d,]+)</g;
                const arr = [];
                let m;
                while ((m = re.exec(txt)))
                    arr.push({ t: Date.UTC(+m[3], +m[2] - 1, +m[1], -3), v: parseFloat(m[5].replace(",", ".")) / +m[4] });
                if (!arr.length)
                    return;
                const h = Object.assign({}, cbrHist);
                h[ins.cbrCode] = arr;
                cbrHist = h;
            });
        });
    }

    // CBR rate aligned to each chart point (dashed line), or null.
    function refFor(ins, s) {
        if (!ins.cbrCode || !s || !s.points.length)
            return null;
        const today = cbr[ins.cbrCode] ? cbr[ins.cbrCode].today : NaN;
        const hist = cbrHist[ins.cbrCode];
        if (range === "day" || !hist || !hist.length)
            return isNaN(today) ? null : s.points.map(() => today);
        let j = 0;
        return s.points.map(p => {
            while (j + 1 < hist.length && hist[j + 1].t <= p.t)
                j++;
            return hist[j].t <= p.t ? hist[j].v : NaN;
        });
    }

    // ---- offline cache (LocalStorage, not the applet config: appletsrc writes wake other watchers) ----
    function db() {
        const d = LocalStorage.openDatabaseSync("plasmaglass-markets", "", "Markets cache", 5000000);
        d.transaction(tx => tx.executeSql("CREATE TABLE IF NOT EXISTS kv(k TEXT PRIMARY KEY, v TEXT)"));
        return d;
    }
    function saveCache(r) {
        const blob = r === "day" ? { market: dayMarket, cbr, notified, dataTime, brentSecid, brentExpiry }
                   : r === "urals" ? { urals, brentYear, lastBrentYearFetch }
                   : r === "keyrate" ? { keyRate, lastKeyRateFetch }
                   : { market, cbrHist };
        db().transaction(tx => tx.executeSql("INSERT OR REPLACE INTO kv VALUES(?, ?)", [r, JSON.stringify(blob)]));
    }
    function readCache(r) {
        let blob = null;
        db().readTransaction(tx => {
            const rs = tx.executeSql("SELECT v FROM kv WHERE k = ?", [r]);
            if (rs.rows.length)
                blob = JSON.parse(rs.rows.item(0).v);
        });
        return blob;
    }
    function loadRangeCache() {
        const blob = range === "day" ? null : readCache(range);
        market = blob ? blob.market : {};
        cbrHist = blob && blob.cbrHist ? blob.cbrHist : {};
    }

    // ---- schedule: day data every 2 min during MOEX hours (drives alerts), other ranges rarely ----
    function tick(force) {
        const now = Date.now();
        const dayPeriod = mskHour() >= 6.8 ? 120e3 : 1800e3;
        const rangePeriod = { day: Infinity, week: 600e3, month: 1800e3, year: 3600e3 }[range];
        if (force || now - lastDayFetch >= dayPeriod - 5e3)
            refreshDay();
        if (force || now - lastRangeFetch >= rangePeriod - 5e3)
            refreshRange();
        if (force || now - lastCbrFetch >= 900e3)
            fetchCbr();
        if (now - lastUralsFetch >= 6 * 3600e3)
            fetchUrals();
        if (now - lastKeyRateFetch >= 6 * 3600e3)
            fetchKeyRate();
        if (now - lastBrentYearFetch >= (brentYear ? 20 * 3600e3 : 1800e3)) {
            lastBrentYearFetch = now;
            fetchBrentYear(() => {});
        }
    }

    onRangeChanged: {
        if (!started)
            return;
        loadRangeCache();
        lastRangeFetch = 0;
        refreshRange();
        if (range !== "day")
            fetchCbrHist();
    }
    onSensitivityChanged: if (started) updateAlerts()

    Component.onCompleted: {
        const blob = readCache("day");
        if (blob) {
            dayMarket = blob.market || {};
            cbr = blob.cbr || {};
            notified = blob.notified || {};
            dataTime = blob.dataTime || 0;
            brentSecid = blob.brentSecid || "";
            brentExpiry = blob.brentExpiry || "";
        }
        const u = readCache("urals");
        if (u) {
            urals = u.urals || {};
            brentYear = u.brentYear || null;
            lastBrentYearFetch = u.lastBrentYearFetch || 0;
        }
        const k = readCache("keyrate");
        if (k) {
            keyRate = k.keyRate;
            lastKeyRateFetch = k.lastKeyRateFetch || 0;
        }
        loadRangeCache();
        updateAlerts();
        tick(true);
        started = true;
    }

    Timer {
        interval: 60000
        running: true
        repeat: true
        onTriggered: root.tick(false)
    }

    fullRepresentation: Item {
        Layout.preferredWidth: 600
        Layout.preferredHeight: 480
        Layout.minimumWidth: 480
        Layout.minimumHeight: 340

        GlassCard {
            anchors.fill: parent
        }

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 8
            spacing: 4

            Repeater {
                model: root.layoutRows

                RowLayout {
                    id: tileRow
                    required property var modelData
                    required property int index

                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    Layout.preferredHeight: 1
                    spacing: 0

                    Repeater {
                        model: tileRow.modelData

                        Tile {
                            required property var modelData
                            required property int index
                            readonly property var insData: root.instrument(modelData)

                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            Layout.preferredWidth: 1
                            ins: insData
                            compact: tileRow.modelData.length > 2
                            series: root.seriesFor(insData)
                            ref: insData.derived ? root.uralsRef(series) : root.refFor(insData, series)
                            cbrInfo: insData.cbrCode ? (root.cbr[insData.cbrCode] || null) : null
                            expiry: insData.asset ? root.brentExpiry : ""
                            customNote: insData.derived ? root.uralsNote() : ""
                            alert: root.alerts[modelData] || null
                            range: root.range
                            rightEdge: index < tileRow.modelData.length - 1
                            bottomEdge: tileRow.index < root.layoutRows.length - 1
                        }
                    }
                }
            }

            Text {
                Layout.fillWidth: true
                Layout.leftMargin: 10
                Layout.topMargin: 2
                visible: text !== ""
                text: root.keyRateText
                elide: Text.ElideRight
                font.pixelSize: 13
                font.features: { "tnum": 1 }
                color: Qt.rgba(1, 1, 1, 0.6)
            }

            RowLayout {
                Layout.fillWidth: true
                Layout.leftMargin: 6
                Layout.rightMargin: 6
                Layout.bottomMargin: 2

                Row {
                    spacing: 2

                    Repeater {
                        model: root.ranges

                        Rectangle {
                            required property var modelData
                            readonly property bool active: root.range === modelData.id

                            width: label.implicitWidth + 16
                            height: 24
                            radius: 7
                            color: active ? Qt.rgba(1, 1, 1, 0.14) : (area.containsMouse ? Qt.rgba(1, 1, 1, 0.06) : "transparent")

                            Text {
                                id: label
                                anchors.centerIn: parent
                                text: parent.modelData.label
                                font.pixelSize: 13
                                color: parent.active ? "white" : Qt.rgba(1, 1, 1, 0.55)
                            }
                            MouseArea {
                                id: area
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: Plasmoid.configuration.range = parent.modelData.id
                            }
                        }
                    }
                }

                Item { Layout.fillWidth: true }

                Text {
                    readonly property string at: root.dataTime ? Qt.formatTime(new Date(root.dataTime), "HH:mm") : "—"
                    text: root.offline ? "нет связи · данные на " + at : "Мосбиржа · задержка 15 мин · " + at
                    font.pixelSize: 13
                    font.features: { "tnum": 1 }
                    color: root.offline ? "#ff9f0a" : Qt.rgba(1, 1, 1, 0.45)
                }
            }
        }
    }
}
