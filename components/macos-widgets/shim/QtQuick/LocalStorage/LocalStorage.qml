pragma Singleton
import QtQuick

// Qt's LocalStorage API (openDatabaseSync / transaction / executeSql) on SQLite
// through the host. PyQt6 wheels don't include the real module.
QtObject {
    function openDatabaseSync(name, version, description, size) {
        const tx = {
            executeSql: function (sql, args) {
                const rows = host.sql(name, sql, args || []);
                return { rowsAffected: 0, insertId: "", rows: { length: rows.length, item: i => rows[i] } };
            }
        };
        // the callback is run by the host, as Qt's own LocalStorage runs it from C++:
        // called from here it would lose the widget's scope (writes to its properties
        // would become "invalid writes to a global property")
        return {
            transaction: function (fn) { host.invoke(fn, tx); },
            readTransaction: function (fn) { host.invoke(fn, tx); }
        };
    }
}
