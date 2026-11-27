// Offline test harness for apps-script.gs: stands in for Google's services.
// Run: node tools/waitlist/test-apps-script.js [preview-dir]
const fs = require("fs"), path = require("path"), vm = require("vm"), crypto = require("crypto"), assert = require("assert");

const sent = [], props = {}, fetches = [], cache = {};
let graphStatus = 202;
function makeSheet() {
  const rows = [];   // row 1 = headers
  const cell = (r, c) => (rows[r - 1] || [])[c - 1];
  const range = (r, c, nr = 1, nc = 1) => ({
    setValues(v) { v.forEach((row, i) => row.forEach((x, j) => { (rows[r - 1 + i] ||= [])[c - 1 + j] = x; })); return this; },
    setValue(v) { (rows[r - 1] ||= [])[c - 1] = v; return this; },
    getValue() { return cell(r, c); },
    getValues() { return Array.from({ length: nr }, (_, i) => Array.from({ length: nc }, (_, j) => cell(r + i, c + j) ?? "")); },
    setFontWeight() { return this; }, setFontColor() { return this; }, setBackground() { return this; }, setFontFamily() { return this; },
    setVerticalAlignment() { return this; }, setWrap() { return this; }, setNumberFormat() { return this; }, setDataValidation() { return this; },
    applyRowBanding() { return this; },
  });
  return { rows, getName: () => "Sign-ups", getLastRow: () => rows.length, getMaxRows: () => 1000, getRange: range,
    appendRow(v) { rows.push(v); }, setRowHeight() {}, setFrozenRows() {}, setColumnWidth() {}, setConditionalFormatRules() {}, getBandings: () => [1] };
}
const sheet = makeSheet();
const ctx = {
  console,
  Logger: { log() {} },
  PropertiesService: { getScriptProperties: () => ({ getProperty: k => props[k] || null, setProperty: (k, v) => { props[k] = v; } }) },
  SpreadsheetApp: {
    openById: id => ({ rename() {}, getSheetByName: () => sheet, insertSheet: () => sheet, getSheets: () => [sheet], deleteSheet() {} }),
    getActiveSpreadsheet: () => ({ rename() {}, getSheetByName: () => sheet, insertSheet: () => sheet, getSheets: () => [sheet], deleteSheet() {} }),
    newDataValidation: () => ({ requireValueInList() { return this; }, build() { return {}; } }),
    newConditionalFormatRule: () => ({ whenTextEqualTo() { return this; }, setFontColor() { return this; }, setBackground() { return this; }, setRanges() { return this; }, build() { return {}; } }),
    BandingTheme: { LIGHT_GREY: 1 },
  },
  Utilities: {
    getUuid: () => crypto.randomUUID(),
    computeHmacSha256Signature: (v, k) => Array.from(crypto.createHmac("sha256", k).update(v).digest()),
    base64EncodeWebSafe: b => Buffer.from(b).toString("base64").replace(/\+/g, "-").replace(/\//g, "_"),
  },
  MailApp: { sendEmail: o => sent.push(o), getRemainingDailyQuota: () => 99 },
  ScriptApp: { getService: () => ({ getUrl: () => "https://script.google.com/macros/s/TEST/exec" }) },
  LockService: { getScriptLock: () => ({ waitLock() {}, releaseLock() {} }) },
  CacheService: { getScriptCache: () => ({ get: k => cache[k] || null, put: (k, v) => { cache[k] = v; } }) },
  Session: { getEffectiveUser: () => ({ getEmail: () => "eglurtech@gmail.com" }) },
  UrlFetchApp: { fetch: (url, opts) => {
    fetches.push({ url, opts });
    if (url.includes("login.microsoftonline.com")) return { getResponseCode: () => 200, getContentText: () => JSON.stringify({ access_token: "tok123", expires_in: 3600 }) };
    return { getResponseCode: () => graphStatus, getContentText: () => (graphStatus === 202 ? "" : '{"error":{"code":"ErrorAccessDenied"}}') };
  } },
  ContentService: { createTextOutput: t => ({ text: t, setMimeType() { return this; } }), MimeType: { JSON: "json" } },
  HtmlService: { createHtmlOutput: h => ({ html: h, setTitle() { return this; } }) },
};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(path.join(__dirname, "apps-script.gs"), "utf8"), ctx);
const call = (fn, ...a) => ctx[fn](...a);
const out = r => JSON.parse(r.text);

// setup creates headers and a token
call("setup");
assert.ok(props.TOKEN && props.TOKEN.length >= 32, "token created");
assert.strictEqual(sheet.rows[0][1], "Email");
const T = props.TOKEN;
const post = (body, token = T) => out(call("doPost", { parameter: { token }, postData: { contents: JSON.stringify(body) } }));
const get = (p) => call("doGet", { parameter: p });

// unauthorised requests are refused
assert.deepStrictEqual(post({ type: "INSERT", record: { email: "a@b.co" } }, "wrong"), { ok: false, error: "unauthorised" });
assert.strictEqual(out(get({ action: "list" })).ok, false);

// a Supabase insert adds a row and sends the welcome email
const record = { email: "Jane@Example.com", area: "SA43 1AB", topics: ["Planning", "Farming"], topics_other: "bus routes",
                 places: "Cardigan", people: "Cllr Jane Smith", frequency: "daily", created_at: "2026-11-27T02:30:00Z" };
assert.deepStrictEqual(post({ type: "INSERT", table: "waitlist", record }), { ok: true });
assert.strictEqual(sheet.rows.length, 2);
assert.strictEqual(sheet.rows[1][1], "jane@example.com");
assert.strictEqual(sheet.rows[1][3], "Planning, Farming");
assert.strictEqual(sheet.rows[1][8], "Active");
assert.strictEqual(Object.prototype.toString.call(sheet.rows[1][9]), "[object Date]", "welcome sent time recorded");
assert.strictEqual(sent.length, 1);
const w = sent[0];
assert.strictEqual(w.to, "jane@example.com"); assert.strictEqual(w.name, "Eglur Daily"); assert.strictEqual(w.replyTo, "monitor@eglurtech.com");
assert.ok(w.htmlBody.includes("You're on the list") && w.htmlBody.includes("Planning, Farming; bus routes") && w.htmlBody.includes("Every weekday morning"));
assert.ok(w.htmlBody.includes("action=unsubscribe&e=jane%40example.com&s="), "signed unsubscribe link");

// duplicates don't add rows or emails
assert.deepStrictEqual(post({ type: "INSERT", record }), { ok: true, duplicate: true });
assert.strictEqual(sheet.rows.length, 2); assert.strictEqual(sent.length, 1);

// the list shows active subscribers
const list = out(get({ action: "list", token: T }));
assert.strictEqual(list.subscribers.length, 1); assert.strictEqual(list.subscribers[0].frequency, "daily");

// sending a briefing: only to active subscribers, with the unsubscribe link filled in
assert.strictEqual(post({ action: "send", to: "stranger@example.com", subject: "x", html: "x" }).ok, false, "not an open relay");
assert.deepStrictEqual(post({ action: "send", to: "jane@example.com", subject: "Hi", html: '<a href="{{UNSUBSCRIBE}}">u</a>', text: "u {{UNSUBSCRIBE}}" }), { ok: true });
assert.ok(sent[1].htmlBody.includes("https://script.google.com/macros/s/TEST/exec?action=unsubscribe&e=jane%40example.com&s="));
assert.ok(!sent[1].htmlBody.includes("{{UNSUBSCRIBE}}"));

// unsubscribe: a forged link changes nothing; a real one marks them unsubscribed
assert.ok(get({ action: "unsubscribe", e: "jane@example.com", s: "forged" }).html.includes("That link has expired"));
assert.strictEqual(sheet.rows[1][8], "Active");
const sig = decodeURIComponent(sent[1].htmlBody.match(/&s=([^"&]+)/)[1]);
assert.ok(get({ action: "unsubscribe", e: "jane@example.com", s: sig }).html.includes("You're unsubscribed"));
assert.strictEqual(sheet.rows[1][8], "Unsubscribed");
assert.strictEqual(out(get({ action: "list", token: T })).subscribers.length, 0);
assert.strictEqual(post({ action: "send", to: "jane@example.com", subject: "x", html: "x" }).ok, false, "no emails after unsubscribing");

// HTML in sign-up answers is escaped in the welcome email
post({ type: "INSERT", record: { email: "x@y.co", area: "<b>Hi</b>", topics: [], frequency: "weekly" } });
assert.ok(sent[2].htmlBody.includes("&lt;b&gt;Hi&lt;/b&gt;") && sent[2].htmlBody.includes("Fridays"));

// ---- Microsoft 365: once the MS_* properties are set, mail goes from monitor@eglurtech.com via Graph
Object.assign(props, { MS_TENANT_ID: "tenant-1", MS_CLIENT_ID: "client-1", MS_CLIENT_SECRET: "secret-1" });
const gmailBefore = sent.length;
assert.deepStrictEqual(post({ type: "INSERT", record: { email: "ms@example.com", area: "SA65", topics: ["Housing"], frequency: "daily" } }), { ok: true });
assert.strictEqual(sent.length, gmailBefore, "no Gmail send once Microsoft is configured");
const tokenCalls = fetches.filter(f => f.url.includes("login.microsoftonline.com"));
assert.strictEqual(tokenCalls.length, 1);
assert.strictEqual(tokenCalls[0].opts.payload.grant_type, "client_credentials");
assert.strictEqual(tokenCalls[0].opts.payload.scope, "https://graph.microsoft.com/.default");
const g = fetches.filter(f => f.url.includes("graph.microsoft.com")).pop();
assert.strictEqual(g.url, "https://graph.microsoft.com/v1.0/users/monitor%40eglurtech.com/sendMail");
assert.strictEqual(g.opts.headers.Authorization, "Bearer tok123");
const m = JSON.parse(g.opts.payload).message;
assert.strictEqual(m.toRecipients[0].emailAddress.address, "ms@example.com");
assert.strictEqual(m.replyTo[0].emailAddress.address, "monitor@eglurtech.com");
assert.strictEqual(m.body.contentType, "HTML");
assert.ok(m.subject === "You're on the list for Eglur Daily" && m.body.content.includes("You're on the list"));
assert.ok(Object.prototype.toString.call(sheet.rows[sheet.rows.length - 1][9]) === "[object Date]", "welcome recorded as sent");
// briefings go the same way, reusing the cached sign-in
assert.deepStrictEqual(post({ action: "send", to: "ms@example.com", subject: "Today", html: "<a href='{{UNSUBSCRIBE}}'>u</a>", text: "" }), { ok: true });
assert.strictEqual(fetches.filter(f => f.url.includes("login.microsoftonline.com")).length, 1, "sign-in token reused");
assert.ok(JSON.parse(fetches[fetches.length - 1].opts.payload).message.body.content.includes("action=unsubscribe&e=ms%40example.com"));
assert.strictEqual(out(get({ action: "list", token: T })).quota, 5000);
// if Microsoft refuses, the failure is recorded on the row rather than lost
graphStatus = 403;
post({ type: "INSERT", record: { email: "fail@example.com", area: "SA65", topics: [], frequency: "daily" } });
assert.ok(String(sheet.rows[sheet.rows.length - 1][9]).startsWith("Failed: Microsoft send failed (403)"));
graphStatus = 202;
// testSend works from the editor
call("testSend");
assert.strictEqual(JSON.parse(fetches[fetches.length - 1].opts.payload).message.toRecipients[0].emailAddress.address, "eglurtech@gmail.com");

if (process.argv[2]) {
  fs.mkdirSync(process.argv[2], { recursive: true });
  fs.writeFileSync(path.join(process.argv[2], "welcome.html"), w.htmlBody);
}
console.log("apps-script: all checks passed");
