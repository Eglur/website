/**
 * Eglur Daily: sign-up record, welcome email, briefing sender and unsubscribe.
 * Also the website's contact form: each message is logged in the Messages sheet and emailed
 * to contact@eglurtech.com with Reply-To set to the sender, and the sender gets a short fixed confirmation.
 *
 * Lives on eglurtech@gmail.com: either inside the sheet (Extensions > Apps Script, SHEET_ID empty) or, as now,
 * as a standalone project with SHEET_ID set. When pasting a new version, keep the existing SHEET_ID line.
 * Setup: paste this file, run setup() once, then Deploy > New deployment > Web app
 * (Execute as: Me, Who has access: Anyone). See tools/waitlist/SETUP.md.
 * To send from monitor@eglurtech.com, add MS_TENANT_ID, MS_CLIENT_ID and MS_CLIENT_SECRET
 * as script properties (Project Settings) and run testSend(). Until then it sends from Gmail.
 *
 * Every request must carry the secret token that setup() creates, except the signed
 * unsubscribe links in emails.
 */

var SHEET_ID = '';   // set for a standalone script project; leave empty when the script lives inside the sheet
var SHEET_NAME = 'Sign-ups';
var HEADERS = ['Joined', 'Email', 'Postcode or area', 'Topics', 'Other topics', 'Places', 'People',
               'How often', 'Status', 'Welcome sent', 'Last briefing'];
var COL = {};
HEADERS.forEach(function (h, i) { COL[h] = i + 1; });
var REPLY_TO = 'monitor@eglurtech.com';
var SENDER = 'monitor@eglurtech.com';   // sends from this Microsoft 365 mailbox once MS_* script properties are set
var FROM_NAME = 'Eglur Daily';
var SITE = 'https://www.eglurtech.com';

// Contact form messages (from the Supabase webhook on public.contact_messages)
var MSG_SHEET = 'Messages';
var MSG_HEADERS = ['Received', 'Name', 'Email', 'Organisation', 'About', 'Message', 'Came from', 'Status',
                   'Emailed to you', 'Confirmation'];
var MCOL = {};
MSG_HEADERS.forEach(function (h, i) { MCOL[h] = i + 1; });
var CONTACT_TO = 'contact@eglurtech.com';   // where messages go (a shared mailbox); a CONTACT_TO script property overrides it
var TOPICS = { 'conversation': 'An early conversation', 'design-partner': 'Becoming a design partner', 'other': 'Something else' };
var NOTIFY_PER_DAY = 60;   // emails to you; past this, messages still land in the sheet
var ACKS_PER_DAY = 20;     // confirmations to senders, at most one per address every six hours

/* ------------------------------------------------------------------ setup */

function spreadsheet_() {
  return SHEET_ID ? SpreadsheetApp.openById(SHEET_ID) : SpreadsheetApp.getActiveSpreadsheet();
}

function setup() {
  var props = PropertiesService.getScriptProperties();
  if (!props.getProperty('TOKEN')) {
    props.setProperty('TOKEN', Utilities.getUuid().replace(/-/g, '') + Utilities.getUuid().replace(/-/g, ''));
  }
  var ss = spreadsheet_();
  ss.rename('Eglur Daily: sign-ups');
  var sh = ss.getSheetByName(SHEET_NAME) || ss.insertSheet(SHEET_NAME, 0);
  ss.getSheets().forEach(function (s) {
    if (s.getName() !== SHEET_NAME && s.getName() !== MSG_SHEET && s.getLastRow() === 0) ss.deleteSheet(s);
  });
  sh.getRange(1, 1, 1, HEADERS.length).setValues([HEADERS])
    .setFontWeight('bold').setFontColor('#FCFFFE').setBackground('#286A6C')
    .setFontFamily('Arial').setVerticalAlignment('middle');
  sh.setRowHeight(1, 34);
  sh.setFrozenRows(1);
  var widths = [150, 230, 150, 260, 200, 180, 200, 100, 110, 150, 150];
  widths.forEach(function (w, i) { sh.setColumnWidth(i + 1, w); });
  sh.getRange(2, 1, sh.getMaxRows() - 1, HEADERS.length).setFontFamily('Arial').setVerticalAlignment('top').setWrap(true);
  sh.getRange(2, COL['Joined'], sh.getMaxRows() - 1, 1).setNumberFormat('d mmm yyyy, hh:mm');
  sh.getRange(2, COL['Welcome sent'], sh.getMaxRows() - 1, 2).setNumberFormat('d mmm yyyy, hh:mm');
  var status = sh.getRange(2, COL['Status'], sh.getMaxRows() - 1, 1);
  status.setDataValidation(SpreadsheetApp.newDataValidation().requireValueInList(['Active', 'Unsubscribed', 'Paused'], true).build());
  var rules = [
    SpreadsheetApp.newConditionalFormatRule().whenTextEqualTo('Active').setFontColor('#1E5153').setBackground('#E6F1EF').setRanges([status]).build(),
    SpreadsheetApp.newConditionalFormatRule().whenTextEqualTo('Unsubscribed').setFontColor('#7D8B88').setBackground('#F1F3F2').setRanges([status]).build()
  ];
  sh.setConditionalFormatRules(rules);
  if (!sh.getBandings().length) sh.getRange(1, 1, sh.getMaxRows(), HEADERS.length).applyRowBanding(SpreadsheetApp.BandingTheme.LIGHT_GREY, true, false);
  Logger.log('Setup done. Your secret token (keep it private):\n' + props.getProperty('TOKEN'));
}

/* --------------------------------------------------------------- requests */

function doPost(e) {
  if (!authorised_(e)) return json_({ ok: false, error: 'unauthorised' });
  var body = {};
  try { body = JSON.parse((e.postData && e.postData.contents) || '{}'); } catch (err) { return json_({ ok: false, error: 'bad json' }); }
  if (body.type === 'INSERT' && body.record) {                                        // from a Supabase webhook
    if (body.table === 'contact_messages') return json_(addMessage_(body.record));
    if (!body.table || body.table === 'waitlist') return json_(addSignup_(body.record));
    return json_({ ok: false, error: 'unknown table' });
  }
  if (body.action === 'send') return json_(sendBriefing_(body));                     // from the daily job
  return json_({ ok: false, error: 'unknown request' });
}

function doGet(e) {
  var p = (e && e.parameter) || {};
  if (p.action === 'unsubscribe') return unsubscribePage_(p.e || '', p.s || '');
  if (!authorised_(e)) return json_({ ok: false, error: 'unauthorised' });
  if (p.action === 'list') return json_({ ok: true, subscribers: activeSubscribers_(), quota: quota_() });
  return json_({ ok: true });
}

function authorised_(e) {
  var t = PropertiesService.getScriptProperties().getProperty('TOKEN');
  return !!(t && e && e.parameter && e.parameter.token === t);
}

function json_(o) {
  return ContentService.createTextOutput(JSON.stringify(o)).setMimeType(ContentService.MimeType.JSON);
}

/* ---------------------------------------------------------------- sign-ups */

function addSignup_(r) {
  var email = String(r.email || '').trim().toLowerCase();
  if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) return { ok: false, error: 'bad email' };
  var lock = LockService.getScriptLock(); lock.waitLock(20000);
  try {
    var sh = sheet_(), row = findRow_(sh, email);
    if (row) return { ok: true, duplicate: true };
    var topics = (r.topics || []).join(', ');
    sh.appendRow([new Date(r.created_at || new Date()), cell_(email), cell_(r.area), cell_(topics), cell_(r.topics_other),
                  cell_(r.places), cell_(r.people), r.frequency === 'weekly' ? 'Weekly' : 'Daily', 'Active', '', '']);
    row = sh.getLastRow();
    try {
      sendWelcome_(email, r);
      sh.getRange(row, COL['Welcome sent']).setValue(new Date());
    } catch (err) {
      sh.getRange(row, COL['Welcome sent']).setValue('Failed: ' + err.message);
    }
    return { ok: true };
  } finally { lock.releaseLock(); }
}

function activeSubscribers_() {
  var sh = sheet_(), last = sh.getLastRow();
  if (last < 2) return [];
  return sh.getRange(2, 1, last - 1, HEADERS.length).getValues()
    .filter(function (v) { return v[COL['Status'] - 1] === 'Active' && v[COL['Email'] - 1]; })
    .map(function (v) {
      return { email: v[COL['Email'] - 1], area: v[COL['Postcode or area'] - 1], topics: v[COL['Topics'] - 1],
               topics_other: v[COL['Other topics'] - 1], places: v[COL['Places'] - 1], people: v[COL['People'] - 1],
               frequency: String(v[COL['How often'] - 1]).toLowerCase() };
    });
}

function sendBriefing_(b) {
  var email = String(b.to || '').trim().toLowerCase(), sh = sheet_(), row = findRow_(sh, email);
  if (!row || sh.getRange(row, COL['Status']).getValue() !== 'Active') return { ok: false, error: 'not an active subscriber' };
  if (quota_() < 1) return { ok: false, error: 'daily email quota used up' };
  var unsub = unsubscribeUrl_(email);
  sendMail_({
    to: email, subject: String(b.subject || 'Your Eglur Daily briefing'),
    html: String(b.html || '').split('{{UNSUBSCRIBE}}').join(unsub),
    text: String(b.text || '').split('{{UNSUBSCRIBE}}').join(unsub)
  });
  sh.getRange(row, COL['Last briefing']).setValue(new Date());
  return { ok: true };
}

function sheet_() {
  var ss = spreadsheet_();
  return ss.getSheetByName(SHEET_NAME) || (setup(), ss.getSheetByName(SHEET_NAME));
}

function findRow_(sh, email) {
  var last = sh.getLastRow();
  if (last < 2) return 0;
  var emails = sh.getRange(2, COL['Email'], last - 1, 1).getValues();
  for (var i = 0; i < emails.length; i++) if (String(emails[i][0]).toLowerCase() === email) return i + 2;
  return 0;
}

/* ------------------------------------------------------------- unsubscribe */

function signature_(email) {
  var key = PropertiesService.getScriptProperties().getProperty('TOKEN');
  return Utilities.base64EncodeWebSafe(Utilities.computeHmacSha256Signature(email, key)).replace(/=+$/, '');
}

function unsubscribeUrl_(email) {
  return ScriptApp.getService().getUrl() + '?action=unsubscribe&e=' + encodeURIComponent(email) + '&s=' + signature_(email);
}

function unsubscribePage_(email, sig) {
  email = String(email).trim().toLowerCase();
  var ok = email && sig === signature_(email);
  if (ok) {
    var sh = sheet_(), row = findRow_(sh, email);
    if (row) sh.getRange(row, COL['Status']).setValue('Unsubscribed');
  }
  var title = ok ? "You're unsubscribed" : 'That link has expired';
  var text = ok ? "You won't get any more emails from Eglur Daily. Changed your mind? Join again any time."
                : 'Reply to any Eglur Daily email and we will remove you straight away.';
  var html = '<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>' + title +
    '</title></head><body style="margin:0;background:#FCFFFE;font-family:Arial,Helvetica,sans-serif;color:#101A1A">' +
    '<div style="max-width:520px;margin:80px auto;padding:0 24px">' + wordmark_(28) +
    '<h1 style="font-family:Georgia,serif;font-weight:400;font-size:40px;line-height:1.05;margin:40px 0 16px">' + title +
    '<span style="color:#286A6C">.</span></h1><p style="font-size:17px;line-height:1.6;color:#3D4A49">' + text + '</p>' +
    '<p><a href="' + SITE + '/daily/" style="color:#1E5153">Back to Eglur Daily</a></p></div></body></html>';
  return HtmlService.createHtmlOutput(html).setTitle(title);
}

/* -------------------------------------------------------- contact form */

function addMessage_(r) {
  var email = String(r.email || '').trim();
  var m = {
    when: new Date(r.created_at || new Date()),
    name: oneLine_(r.name, 120),
    email: email.length <= 254 && /^[^@\s,;<>"]+@[^@\s,;<>"]+\.[^@\s,;<>"]+$/.test(email) ? email : '',
    organisation: oneLine_(r.organisation, 160),
    about: TOPICS[r.topic] || '',
    message: String(r.message || '').replace(/\r\n?/g, '\n').slice(0, 5000).trim(),
    page: oneLine_(r.from_page, 40).replace(/[^a-z0-9-]/g, '')
  };
  if (!m.name || !m.email || !m.message) return { ok: false, error: 'incomplete message' };

  var lock = LockService.getScriptLock(); lock.waitLock(20000);
  var sh = null, row = 0, notify, ackSkip;
  try {
    try {   // a problem with the sheet mustn't stop the email reaching you
      sh = msgSheet_();
      row = sh.getLastRow() + 1;
      sh.getRange(row, 1, 1, MSG_HEADERS.length).setValues([[m.when, cell_(m.name), cell_(m.email), cell_(m.organisation),
        m.about, cell_(m.message), cell_(m.page), 'New', '', '']]);
    } catch (err) { sh = null; row = 0; }
    notify = quota_() >= 1 && countToday_('CONTACT_NOTIFIED', NOTIFY_PER_DAY);
    ackSkip = ackSkip_(m.email);
  } finally { lock.releaseLock(); }
  function mark(col, v) { if (sh && row) try { sh.getRange(row, MCOL[col]).setValue(v); } catch (err) {} }

  // 1. To you. Reply-To is the sender, so replying answers them directly.
  var emailed = false;
  try {
    if (!notify) throw new Error("not emailed: today's email limit is used up, so read it here");
    sendMail_(notifyEmail_(m));
    emailed = true;
    mark('Emailed to you', new Date());
  } catch (err) { mark('Emailed to you', 'Failed: ' + err.message); }

  // 2. To the sender: fixed words only, never their name or message, so nobody can use
  //    the form to send their own text to someone else's address.
  try {
    if (ackSkip) mark('Confirmation', 'Not sent: ' + ackSkip);
    else { sendMail_(ackEmail_(m)); mark('Confirmation', new Date()); }
  } catch (err) { mark('Confirmation', 'Failed: ' + err.message); }
  return { ok: true, logged: !!row, emailed: emailed };
}

function ackSkip_(email) {
  if (String(prop_('CONTACT_ACK') || '').toLowerCase() === 'off') return 'switched off';
  var cache = CacheService.getScriptCache(), key = 'ack:' + email.toLowerCase().slice(0, 240);
  if (cache.get(key)) return 'one already went to this address in the last six hours';
  if (quota_() < 10) return 'saving the day\'s remaining email allowance';
  if (!countToday_('CONTACT_ACKS', ACKS_PER_DAY)) return 'daily limit reached';
  cache.put(key, '1', 21600);   // six hours, the longest the cache keeps anything
  return '';
}

/** Counts one more use today, if today's limit allows it. */
function countToday_(name, max) {
  var props = PropertiesService.getScriptProperties();
  var today = Utilities.formatDate(new Date(), 'Europe/London', 'yyyy-MM-dd'), c = {};
  try { c = JSON.parse(props.getProperty(name) || '{}'); } catch (err) { c = {}; }
  if (c.day !== today) c = { day: today, n: 0 };
  if (c.n >= max) return false;
  c.n++;
  props.setProperty(name, JSON.stringify(c));
  return true;
}

function notifyEmail_(m) {
  var where = m.page ? 'eglurtech.com/' + (m.page === 'home' ? '' : m.page) : '';
  var rows = [['Name', esc_(m.name)], ['Email', '<a href="mailto:' + esc_(m.email) + '" style="color:#1E5153">' + esc_(m.email) + '</a>'],
              ['Organisation', esc_(m.organisation)], ['About', esc_(m.about)], ['Came from', esc_(where)],
              ['Received', esc_(when_(m.when))]].filter(function (x) { return x[1]; });
  var table = rows.map(function (x) {
    return '<tr><td style="padding:10px 0;border-top:1px solid #E3E8E6;width:120px;vertical-align:top;font-size:14px;color:#5F6B6A">' +
      x[0] + '</td><td style="padding:10px 0;border-top:1px solid #E3E8E6;font-size:15px;line-height:1.5;color:#101A1A">' + x[1] + '</td></tr>';
  }).join('');
  var inner =
    '<h1 style="margin:0 0 14px;font-family:\'DM Serif Display\',Georgia,serif;font-weight:400;font-size:34px;line-height:1.1;color:#101A1A">' +
    'New message<span style="color:#286A6C">.</span></h1>' +
    '<p style="margin:0 0 24px;font-size:16px;line-height:1.6;color:#3D4A49">From the contact form on eglurtech.com. ' +
    'Reply to this email to answer ' + esc_(m.name) + ' directly.</p>' +
    '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;margin:0 0 4px">' + table +
    '<tr><td colspan="2" style="border-top:1px solid #E3E8E6"></td></tr></table>' +
    '<p style="margin:20px 0 0;font-size:16px;line-height:1.65;color:#101A1A">' + esc_(m.message).replace(/\n/g, '<br>') + '</p>';
  var text = 'New message from the contact form on eglurtech.com. Reply to this email to answer ' + m.name + ' directly.\n\n' +
    [['Name', m.name], ['Email', m.email], ['Organisation', m.organisation], ['About', m.about], ['Came from', where],
     ['Received', when_(m.when)]].filter(function (x) { return x[1]; }).map(function (x) { return x[0] + ': ' + x[1]; }).join('\n') +
    '\n\n' + m.message + '\n';
  var subject = ('Website message from ' + m.name + (m.organisation ? ' (' + m.organisation + ')' : '')).slice(0, 160);
  return { to: prop_('CONTACT_TO') || CONTACT_TO, name: 'Eglur website', replyTo: m.email, subject: subject, text: text,
           html: frame_(inner, m.name + ' sent a message from eglurtech.com', '', 'Sent by the contact form at eglurtech.com/contact.') };
}

function ackEmail_(m) {
  var inner =
    '<h1 style="margin:0 0 18px;font-family:\'DM Serif Display\',Georgia,serif;font-weight:400;font-size:38px;line-height:1.05;color:#101A1A">' +
    'Thanks for getting in touch<span style="color:#286A6C">.</span></h1>' +
    '<p style="margin:0 0 16px;font-size:17px;line-height:1.6;color:#3D4A49">Your message has reached us. We read every message, ' +
    'and we\'ll reply to you personally.</p>' +
    '<p style="margin:0;font-size:17px;line-height:1.6;color:#3D4A49">Need to add something? Just reply to this email.</p>';
  var text = "Thanks for getting in touch.\n\nYour message has reached us. We read every message, and we'll reply to you personally.\n\n" +
    'Need to add something? Just reply to this email.\n\nEglur Technologies. Eglur is Welsh for clear.\n' +
    "You're getting this because this address was entered on the contact form at eglurtech.com. If that wasn't you, " +
    "ignore this email and you won't hear from us again.";
  return { to: m.email, name: 'Eglur', replyTo: prop_('CONTACT_TO') || CONTACT_TO, subject: 'We got your message', text: text,
           html: frame_(inner, "We'll reply to you personally.", '',
             "You're getting this because this address was entered on the contact form at eglurtech.com. " +
             "If that wasn't you, ignore this email and you won't hear from us again.") };
}

function msgSheet_() {
  var ss = spreadsheet_(), sh = ss.getSheetByName(MSG_SHEET);
  if (!sh) { sh = ss.insertSheet(MSG_SHEET); formatMessages_(sh); }
  return sh;
}

/** Optional: run from the editor to create (or re-format) the Messages sheet before the first message. */
function setupMessages() {
  formatMessages_(msgSheet_());
  Logger.log('The Messages sheet is ready.');
}

function formatMessages_(sh) {
  sh.getRange(1, 1, 1, MSG_HEADERS.length).setValues([MSG_HEADERS])
    .setFontWeight('bold').setFontColor('#FCFFFE').setBackground('#286A6C')
    .setFontFamily('Arial').setVerticalAlignment('middle');
  sh.setRowHeight(1, 34);
  sh.setFrozenRows(1);
  [150, 170, 220, 200, 190, 420, 110, 100, 150, 150].forEach(function (w, i) { sh.setColumnWidth(i + 1, w); });
  var body = sh.getRange(2, 1, sh.getMaxRows() - 1, MSG_HEADERS.length);
  body.setFontFamily('Arial').setVerticalAlignment('top').setWrap(true);
  sh.getRange(2, MCOL['Received'], sh.getMaxRows() - 1, 1).setNumberFormat('d mmm yyyy, hh:mm');
  sh.getRange(2, MCOL['Emailed to you'], sh.getMaxRows() - 1, 2).setNumberFormat('d mmm yyyy, hh:mm');
  var status = sh.getRange(2, MCOL['Status'], sh.getMaxRows() - 1, 1);
  status.setDataValidation(SpreadsheetApp.newDataValidation().requireValueInList(['New', 'Replied', 'Closed'], true).build());
  sh.setConditionalFormatRules([
    SpreadsheetApp.newConditionalFormatRule().whenTextEqualTo('New').setFontColor('#1E5153').setBackground('#E6F1EF').setRanges([status]).build(),
    SpreadsheetApp.newConditionalFormatRule().whenTextEqualTo('Closed').setFontColor('#7D8B88').setBackground('#F1F3F2').setRanges([status]).build()
  ]);
}

/* ----------------------------------------------------------- welcome email */

function sendWelcome_(email, r) {
  var daily = r.frequency !== 'weekly';
  var rows = [
    ['Area', r.area],
    ['Topics', [(r.topics || []).join(', '), r.topics_other].filter(String).join('; ')],
    ['Places', r.places],
    ['People', r.people],
    ['How often', daily ? 'Every weekday morning' : 'Fridays']
  ].filter(function (x) { return x[1]; });
  var table = rows.map(function (x) {
    return '<tr><td style="padding:12px 0;border-top:1px solid #E3E8E6;width:110px;vertical-align:top;font-size:14px;color:#5F6B6A">' +
      esc_(x[0]) + '</td><td style="padding:12px 0;border-top:1px solid #E3E8E6;font-size:15px;line-height:1.5;color:#101A1A">' +
      esc_(x[1]) + '</td></tr>';
  }).join('');
  var inner =
    '<h1 style="margin:0 0 18px;font-family:\'DM Serif Display\',Georgia,serif;font-weight:400;font-size:38px;line-height:1.05;color:#101A1A">' +
    "You're on the list<span style=\"color:#286A6C\">.</span></h1>" +
    '<p style="margin:0 0 28px;font-size:17px;line-height:1.6;color:#3D4A49">Thanks for joining Eglur Daily. When it launches, you\'ll get a short email ' +
    (daily ? 'every weekday morning' : 'every Friday') + ' covering your council, your parliament and Westminster, with only the things that touch what you follow.</p>' +
    '<p style="margin:0 0 8px;font-size:14px;font-weight:bold;color:#101A1A">What we\'ll watch for you</p>' +
    '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;margin:0 0 28px">' + table +
    '<tr><td colspan="2" style="border-top:1px solid #E3E8E6"></td></tr></table>' +
    '<p style="margin:0 0 30px;font-size:15px;line-height:1.6;color:#3D4A49">Want to change anything? Just reply to this email.</p>' +
    button_(SITE + '/monitor/', 'See a live example');
  var text = "You're on the list.\n\nThanks for joining Eglur Daily. When it launches, you'll get a short email " +
    (daily ? 'every weekday morning' : 'every Friday') + ' covering your council, your parliament and Westminster.\n\n' +
    rows.map(function (x) { return x[0] + ': ' + x[1]; }).join('\n') +
    '\n\nWant to change anything? Just reply to this email.\n\nSee a live example: ' + SITE + '/monitor/\n\nUnsubscribe: ' + unsubscribeUrl_(email);
  sendMail_({
    to: email, subject: "You're on the list for Eglur Daily",
    html: frame_(inner, "We'll set up your briefing when Eglur Daily launches.", unsubscribeUrl_(email)), text: text
  });
}

/* ------------------------------------------------------------- sending */

// Microsoft 365 (Graph) when configured, so email comes from monitor@eglurtech.com; Gmail otherwise.
function msConfig_() {
  var p = PropertiesService.getScriptProperties();
  var c = { tenant: p.getProperty('MS_TENANT_ID'), client: p.getProperty('MS_CLIENT_ID'),
            secret: p.getProperty('MS_CLIENT_SECRET'), sender: p.getProperty('MS_SENDER') || SENDER };
  return c.tenant && c.client && c.secret ? c : null;
}

function msToken_(c) {
  var cache = CacheService.getScriptCache(), hit = cache.get('ms_token');
  if (hit) return hit;
  var res = UrlFetchApp.fetch('https://login.microsoftonline.com/' + encodeURIComponent(c.tenant) + '/oauth2/v2.0/token', {
    method: 'post', muteHttpExceptions: true,
    payload: { client_id: c.client, client_secret: c.secret, grant_type: 'client_credentials', scope: 'https://graph.microsoft.com/.default' }
  });
  var body = JSON.parse(res.getContentText() || '{}');
  if (!body.access_token) throw new Error('Microsoft sign-in failed: ' + (body.error_description || body.error || res.getResponseCode()));
  cache.put('ms_token', body.access_token, Math.max(60, Math.min(3000, (body.expires_in || 3600) - 300)));
  return body.access_token;
}

function sendMail_(o) {
  var c = msConfig_();
  if (!c) {
    MailApp.sendEmail({ to: o.to, name: o.name || FROM_NAME, replyTo: o.replyTo || REPLY_TO, subject: o.subject, htmlBody: o.html, body: o.text });
    return 'gmail';
  }
  var res = UrlFetchApp.fetch('https://graph.microsoft.com/v1.0/users/' + encodeURIComponent(c.sender) + '/sendMail', {
    method: 'post', contentType: 'application/json', muteHttpExceptions: true,
    headers: { Authorization: 'Bearer ' + msToken_(c) },
    payload: JSON.stringify({
      message: {
        subject: o.subject,
        body: { contentType: 'HTML', content: o.html },
        toRecipients: [{ emailAddress: { address: o.to } }],
        replyTo: [{ emailAddress: { address: o.replyTo || REPLY_TO } }]
      },
      saveToSentItems: false
    })
  });
  if (res.getResponseCode() !== 202) throw new Error('Microsoft send failed (' + res.getResponseCode() + '): ' + res.getContentText().slice(0, 200));
  return 'microsoft';
}

function quota_() {
  return msConfig_() ? 5000 : MailApp.getRemainingDailyQuota();   // Microsoft 365 allows thousands a day
}

/** Run this from the editor after adding the MS_* script properties: sends a test email to this Google account. */
function testSend() {
  var to = Session.getEffectiveUser().getEmail();
  var via = sendMail_({ to: to, subject: 'Eglur Daily test', text: 'It works.',
    html: frame_('<h1 style="margin:0 0 12px;font-family:Georgia,serif;font-weight:400;font-size:32px">It works<span style="color:#286A6C">.</span></h1>' +
                 '<p style="margin:0;font-size:16px;color:#3D4A49">This came from ' + esc_(msConfig_() ? msConfig_().sender : 'Gmail') + '.</p>', 'Test', '#') });
  Logger.log('Sent a test to ' + to + ' via ' + via);
}

/* ---------------------------------------------------------- email pieces */

function wordmark_(size) {
  var h = Math.round(size * 1.5), w = Math.round(h * 330 / 134);   // the real wordmark as an image: email clients won't load the font
  return '<a href="' + SITE + '/"><img src="' + SITE + '/img/email-wordmark.png" width="' + w + '" height="' + h + '" alt="eglur." ' +
         'style="display:block;border:0;outline:none;width:' + w + 'px;height:' + h + 'px"></a>';
}

function button_(href, label) {
  return '<table role="presentation" cellpadding="0" cellspacing="0"><tr><td style="border-radius:999px;background:#286A6C">' +
    '<a href="' + href + '" style="display:inline-block;padding:13px 24px;font-family:Arial,Helvetica,sans-serif;font-size:15px;font-weight:bold;color:#FCFFFE;text-decoration:none;border-radius:999px">' +
    esc_(label) + '</a></td></tr></table>';
}

function frame_(inner, preheader, unsub, foot) {
  return '<!doctype html><html lang="en-GB"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">' +
    '<meta name="color-scheme" content="light"><link href="https://fonts.googleapis.com/css2?family=DM+Serif+Display&display=swap" rel="stylesheet"></head>' +
    '<body style="margin:0;padding:0;background:#F1F6F5">' +
    '<div style="display:none;max-height:0;overflow:hidden;opacity:0">' + esc_(preheader) + '</div>' +
    '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#F1F6F5"><tr><td align="center" style="padding:32px 14px">' +
    '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:600px">' +
    '<tr><td style="padding:0 6px 22px">' + wordmark_(26) + '</td></tr>' +
    '<tr><td style="background:#FFFFFF;border-radius:16px;padding:40px 36px;font-family:Arial,Helvetica,sans-serif">' + inner + '</td></tr>' +
    '<tr><td style="padding:22px 6px;font-family:Arial,Helvetica,sans-serif;font-size:12px;line-height:1.6;color:#5F6B6A">' +
    'Eglur Technologies. Eglur is Welsh for clear.<br>' +
    (foot ? esc_(foot) : 'You signed up at eglurtech.com/daily. <a href="' + unsub + '" style="color:#5F6B6A">Unsubscribe</a>') +
    '</td></tr>' +
    '</table></td></tr></table></body></html>';
}

function prop_(k) {
  return PropertiesService.getScriptProperties().getProperty(k);
}

/** One line of plain text: no line breaks or control characters, at most max characters. */
function oneLine_(s, max) {
  return String(s == null ? '' : s).replace(/[\u0000-\u001f\u007f\s]+/g, ' ').trim().slice(0, max);
}

/** Sheets runs text that starts with = + - or @ as a formula; a leading apostrophe keeps it as text. */
function cell_(v) {
  var s = String(v == null ? '' : v);
  return /^[=+\-@]/.test(s) ? "'" + s : s;
}

function when_(d) {
  return Utilities.formatDate(d, 'Europe/London', 'EEE d MMM yyyy, HH:mm');
}

function esc_(s) {
  return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}
