// Offline test harness for apps-script.gs: stands in for Google's services.
// Run: node tools/waitlist/test-apps-script.js [preview-dir]
const fs = require("fs"), path = require("path"), vm = require("vm"), crypto = require("crypto"), assert = require("assert");

const sent = [], props = {}, fetches = [], cache = {};
let graphStatus = 202;
const denySenders = new Set();   // mailboxes the Microsoft app isn't allowed to send as
// Like Sheets: a leading apostrophe marks text and isn't part of the stored value. `raw` keeps what was written.
const kept = x => (typeof x === "string" && x[0] === "'" ? x.slice(1) : x);
function makeSheet(name) {
  const rows = [], raw = [];   // row 1 = headers
  const cell = (r, c) => (rows[r - 1] || [])[c - 1];
  const range = (r, c, nr = 1, nc = 1) => ({
    setValues(v) { v.forEach((row, i) => { raw.push(row); row.forEach((x, j) => { (rows[r - 1 + i] ||= [])[c - 1 + j] = kept(x); }); }); return this; },
    setValue(v) { (rows[r - 1] ||= [])[c - 1] = kept(v); return this; },
    getValue() { return cell(r, c); },
    getValues() { return Array.from({ length: nr }, (_, i) => Array.from({ length: nc }, (_, j) => cell(r + i, c + j) ?? "")); },
    setFontWeight() { return this; }, setFontColor() { return this; }, setBackground() { return this; }, setFontFamily() { return this; },
    setVerticalAlignment() { return this; }, setWrap() { return this; }, setNumberFormat() { return this; }, setDataValidation() { return this; },
    applyRowBanding() { return this; },
  });
  return { rows, raw, getName: () => name, getLastRow: () => rows.length, getMaxRows: () => 1000, getRange: range,
    appendRow(v) { raw.push(v); rows.push(v.map(kept)); }, setRowHeight() {}, setFrozenRows() {}, setColumnWidth() {},
    setConditionalFormatRules() {}, getBandings: () => [1] };
}
const sheets = { "Sign-ups": makeSheet("Sign-ups") };
const sheet = sheets["Sign-ups"];
const book = { rename() {}, getSheetByName: n => sheets[n] || null, insertSheet: n => (sheets[n] = makeSheet(n)),
               getSheets: () => Object.values(sheets), deleteSheet(sh) { delete sheets[sh.getName()]; } };
const ctx = {
  console,
  Logger: { log() {} },
  PropertiesService: { getScriptProperties: () => ({ getProperty: k => props[k] || null, setProperty: (k, v) => { props[k] = v; } }) },
  SpreadsheetApp: {
    openById: id => book,
    getActiveSpreadsheet: () => book,
    newDataValidation: () => ({ requireValueInList() { return this; }, build() { return {}; } }),
    newConditionalFormatRule: () => ({ whenTextEqualTo() { return this; }, setFontColor() { return this; }, setBackground() { return this; }, setRanges() { return this; }, build() { return {}; } }),
    BandingTheme: { LIGHT_GREY: 1 },
  },
  Utilities: {
    getUuid: () => crypto.randomUUID(),
    computeHmacSha256Signature: (v, k) => Array.from(crypto.createHmac("sha256", k).update(v).digest()),
    base64EncodeWebSafe: b => Buffer.from(b).toString("base64").replace(/\+/g, "-").replace(/\//g, "_"),
    formatDate: (d, tz, f) => (f === "yyyy-MM-dd" ? new Date(d).toISOString().slice(0, 10) : "Sat 28 Nov 2026, 10:15"),
  },
  MailApp: { sendEmail: o => sent.push(o), getRemainingDailyQuota: () => 99 },
  ScriptApp: { getService: () => ({ getUrl: () => "https://script.google.com/macros/s/TEST/exec" }) },
  LockService: { getScriptLock: () => ({ waitLock() {}, releaseLock() {} }) },
  CacheService: { getScriptCache: () => ({ get: k => cache[k] || null, put: (k, v) => { cache[k] = v; } }) },
  Session: { getEffectiveUser: () => ({ getEmail: () => "eglurtech@gmail.com" }) },
  UrlFetchApp: { fetch: (url, opts) => {
    fetches.push({ url, opts });
    if (url.includes("login.microsoftonline.com")) return { getResponseCode: () => 200, getContentText: () => JSON.stringify({ access_token: "tok123", expires_in: 3600 }) };
    const sender = decodeURIComponent((url.match(/\/users\/([^/]+)\/sendMail/) || [])[1] || "");
    const status = denySenders.has(sender) ? 403 : graphStatus;
    return { getResponseCode: () => status, getContentText: () => (status === 202 ? "" : '{"error":{"code":"ErrorAccessDenied"}}') };
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

// ---- contact form: a message is logged, emailed to Toby with Reply-To the sender, and confirmed to the sender
const isDate = v => Object.prototype.toString.call(v) === "[object Date]";
const today = new Date().toISOString().slice(0, 10);
const msg = { id: 1, created_at: "2026-11-28T10:15:00Z", name: "Jane Smith", email: "jane@office.example",
              organisation: "Office of Jane Smith MS", topic: "conversation",
              message: "Hello.\nCould we talk about <your> tool?", from_page: "product" };
const contact = (rec, token) => post({ type: "INSERT", table: "contact_messages", schema: "public", record: rec, old_record: null }, token);
let n0 = sent.length;
assert.deepStrictEqual(contact(msg), { ok: true, logged: true, emailed: true });
const ms = sheets["Messages"];
assert.ok(ms, "Messages sheet created on the first message");
assert.deepStrictEqual(ms.rows[0], ["Received", "Name", "Email", "Organisation", "About", "Message", "Came from", "Status", "Emailed to you", "Confirmation"]);
let mr = ms.rows[1];
assert.ok(isDate(mr[0]));
assert.deepStrictEqual(mr.slice(1, 8), ["Jane Smith", "jane@office.example", "Office of Jane Smith MS", "An early conversation",
                                        "Hello.\nCould we talk about <your> tool?", "product", "New"]);
assert.ok(isDate(mr[8]) && isDate(mr[9]), "email and confirmation times recorded");
assert.strictEqual(sent.length, n0 + 2);
const note = sent[n0], ack = sent[n0 + 1];
assert.strictEqual(note.to, "contact@eglurtech.com");
assert.strictEqual(note.replyTo, "jane@office.example", "replying answers the sender");
assert.strictEqual(note.name, "Eglur website");
assert.strictEqual(note.subject, "Website message from Jane Smith (Office of Jane Smith MS)");
assert.ok(note.htmlBody.includes("Hello.<br>Could we talk about &lt;your&gt; tool?"), "message escaped, line breaks kept");
assert.ok(note.htmlBody.includes("eglurtech.com/product") && note.htmlBody.includes("An early conversation"));
assert.ok(note.htmlBody.includes('href="mailto:jane@office.example"'));
assert.ok(!note.htmlBody.includes("Unsubscribe") && note.htmlBody.includes("Sent by the contact form"));
assert.ok(note.body.includes("Could we talk about <your> tool?") && note.body.includes("Organisation: Office of Jane Smith MS"));
assert.strictEqual(ack.to, "jane@office.example");
assert.strictEqual(ack.replyTo, "contact@eglurtech.com");
assert.strictEqual(ack.name, "Eglur");
assert.strictEqual(ack.subject, "We got your message");
assert.ok(ack.htmlBody.includes("Thanks for getting in touch") && ack.htmlBody.includes("If that wasn't you"));
for (const bit of ["Jane", "Smith", "Could we talk", "Office of"]) {
  assert.ok(!ack.htmlBody.includes(bit) && !ack.body.includes(bit), `the confirmation carries none of the sender's words (${bit})`);
}

// a second message from the same address: Toby still gets it; no second confirmation within six hours
n0 = sent.length;
contact({ ...msg, message: "One more thing." });
assert.strictEqual(sent.length, n0 + 1);
assert.strictEqual(sent[n0].to, "contact@eglurtech.com");
assert.strictEqual(ms.rows[2][9], "Not sent: one already went to this address in the last six hours");

// text that looks like a formula is kept as text, in messages and in sign-ups
contact({ ...msg, email: "f@x.example", name: '=HYPERLINK("http://evil.example","x")', organisation: "+44 1234", message: "=IMPORTXML(A1)" });
let fr = ms.raw[ms.raw.length - 1];
assert.ok(fr[1].startsWith("'=") && fr[3].startsWith("'+") && fr[5].startsWith("'="), "formulas neutralised");
assert.strictEqual(ms.rows[ms.rows.length - 1][5], "=IMPORTXML(A1)", "and shown exactly as written");
post({ type: "INSERT", table: "waitlist", record: { email: "g@x.example", area: "=1+1", topics: [], places: "@x", frequency: "daily" } });
fr = sheet.raw[sheet.raw.length - 1];
assert.ok(fr[2] === "'=1+1" && fr[5] === "'@x", "sign-ups get the same protection");

// bad or incomplete records are refused, and nothing is sent
n0 = sent.length;
const rowsBefore = ms.rows.length;
for (const bad of [{ email: "a@b.co\nBcc: x@y.z" }, { email: "x@y.co, z@w.co" }, { email: "<x@y.co>" }, { name: "  " }, { message: "" }]) {
  assert.deepStrictEqual(contact({ ...msg, ...bad }), { ok: false, error: "incomplete message" }, JSON.stringify(bad));
}
assert.strictEqual(sent.length, n0); assert.strictEqual(ms.rows.length, rowsBefore);
// a line break in a name can't reach the subject line
contact({ ...msg, email: "h@x.example", name: "Bob\r\nBcc: x@y.z" });
assert.strictEqual(sent[sent.length - 2].subject, "Website message from Bob Bcc: x@y.z (Office of Jane Smith MS)");
// unauthorised posts are refused
assert.deepStrictEqual(contact(msg, "wrong"), { ok: false, error: "unauthorised" });
// a webhook from any other table is refused rather than treated as a sign-up
n0 = sent.length;
assert.deepStrictEqual(post({ type: "INSERT", table: "something_else", record: { email: "z@x.example", area: "x" } }), { ok: false, error: "unknown table" });
assert.strictEqual(sent.length, n0);

// switches and limits
props.CONTACT_ACK = "off";
contact({ ...msg, email: "i@x.example" });
assert.strictEqual(ms.rows[ms.rows.length - 1][9], "Not sent: switched off");
delete props.CONTACT_ACK;
props.CONTACT_ACKS = JSON.stringify({ day: today, n: 20 });
contact({ ...msg, email: "j@x.example" });
assert.strictEqual(ms.rows[ms.rows.length - 1][9], "Not sent: daily limit reached");
delete props.CONTACT_ACKS;
props.CONTACT_NOTIFIED = JSON.stringify({ day: today, n: 60 });
n0 = sent.length;
assert.deepStrictEqual(contact({ ...msg, email: "k@x.example" }), { ok: true, logged: true, emailed: false });
assert.ok(String(ms.rows[ms.rows.length - 1][8]).startsWith("Failed: not emailed"), "kept in the sheet when the day's limit is used");
assert.ok(!sent.slice(n0).some(e => e.to === "contact@eglurtech.com"));
props.CONTACT_NOTIFIED = JSON.stringify({ day: "2000-01-01", n: 60 });   // a new day resets the count
contact({ ...msg, email: "l@x.example" });
assert.ok(isDate(ms.rows[ms.rows.length - 1][8]));
props.CONTACT_TO = "hello@eglurtech.com";
contact({ ...msg, email: "m@x.example" });
assert.ok(sent.some(e => e.to === "hello@eglurtech.com" && e.replyTo === "m@x.example"), "CONTACT_TO changes where messages go");
delete props.CONTACT_TO;
// re-running setup keeps the Messages sheet
call("setup");
assert.ok(sheets["Messages"] && sheets["Messages"].rows.length > 5);

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
// contact messages go the same way, sent FROM contact@ (not monitor@), with Reply-To the sender
contact({ ...msg, email: "graph@x.example" });
let gf = fetches.filter(f => f.url.includes("graph.microsoft.com")).slice(-2);
const gm = gf.map(f => JSON.parse(f.opts.payload).message);
assert.deepStrictEqual(gf.map(f => f.url), Array(2).fill("https://graph.microsoft.com/v1.0/users/contact%40eglurtech.com/sendMail"));
assert.strictEqual(gm[0].toRecipients[0].emailAddress.address, "contact@eglurtech.com");
assert.strictEqual(gm[0].replyTo[0].emailAddress.address, "graph@x.example");
assert.strictEqual(gm[1].toRecipients[0].emailAddress.address, "graph@x.example");
assert.strictEqual(gm[1].replyTo[0].emailAddress.address, "contact@eglurtech.com");
assert.ok(isDate(ms.rows[ms.rows.length - 1][8]) && isDate(ms.rows[ms.rows.length - 1][9]));
// if Microsoft won't let the app send as contact@, the emails still go, from monitor@, and the row says so
denySenders.add("contact@eglurtech.com");
let before = fetches.length;
contact({ ...msg, email: "deny@x.example" });
gf = fetches.slice(before).filter(f => f.url.includes("/sendMail"));
assert.deepStrictEqual(gf.map(f => f.url.split("/users/")[1]), ["contact%40eglurtech.com/sendMail", "monitor%40eglurtech.com/sendMail",
                                                                 "contact%40eglurtech.com/sendMail", "monitor%40eglurtech.com/sendMail"]);
assert.strictEqual(ms.rows[ms.rows.length - 1][8], "Sent from monitor@eglurtech.com (not allowed to send as contact@eglurtech.com)");
assert.strictEqual(ms.rows[ms.rows.length - 1][9], "Sent from monitor@eglurtech.com (not allowed to send as contact@eglurtech.com)");
denySenders.clear();
// Daily emails still come from monitor@
before = fetches.length;
post({ action: "send", to: "ms@example.com", subject: "Again", html: "x", text: "x" });
assert.strictEqual(fetches.slice(before).find(f => f.url.includes("/sendMail")).url, "https://graph.microsoft.com/v1.0/users/monitor%40eglurtech.com/sendMail");
// testSend works from the editor
call("testSend");
assert.strictEqual(JSON.parse(fetches[fetches.length - 1].opts.payload).message.toRecipients[0].emailAddress.address, "eglurtech@gmail.com");

if (process.argv[2]) {
  fs.mkdirSync(process.argv[2], { recursive: true });
  fs.writeFileSync(path.join(process.argv[2], "welcome.html"), w.htmlBody);
  fs.writeFileSync(path.join(process.argv[2], "contact-to-you.html"), note.htmlBody);
  fs.writeFileSync(path.join(process.argv[2], "contact-confirmation.html"), ack.htmlBody);
}
console.log("apps-script: all checks passed");
