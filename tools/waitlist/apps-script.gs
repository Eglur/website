/**
 * Eglur Daily: sign-up record, welcome email, briefing sender and unsubscribe.
 *
 * Lives in a Google Sheet on eglurtech@gmail.com (Extensions > Apps Script).
 * Setup: paste this file, run setup() once, then Deploy > New deployment > Web app
 * (Execute as: Me, Who has access: Anyone). See tools/waitlist/SETUP.md.
 *
 * Every request must carry the secret token that setup() creates, except the signed
 * unsubscribe links in emails.
 */

var SHEET_NAME = 'Sign-ups';
var HEADERS = ['Joined', 'Email', 'Postcode or area', 'Topics', 'Other topics', 'Places', 'People',
               'How often', 'Status', 'Welcome sent', 'Last briefing'];
var COL = {};
HEADERS.forEach(function (h, i) { COL[h] = i + 1; });
var REPLY_TO = 'monitor@eglurtech.com';
var FROM_NAME = 'Eglur Daily';
var SITE = 'https://www.eglurtech.com';

/* ------------------------------------------------------------------ setup */

function setup() {
  var props = PropertiesService.getScriptProperties();
  if (!props.getProperty('TOKEN')) {
    props.setProperty('TOKEN', Utilities.getUuid().replace(/-/g, '') + Utilities.getUuid().replace(/-/g, ''));
  }
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  ss.rename('Eglur Daily: sign-ups');
  var sh = ss.getSheetByName(SHEET_NAME) || ss.insertSheet(SHEET_NAME, 0);
  ss.getSheets().forEach(function (s) { if (s.getName() !== SHEET_NAME && s.getLastRow() === 0) ss.deleteSheet(s); });
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
  if (body.type === 'INSERT' && body.record) return json_(addSignup_(body.record));   // from the Supabase webhook
  if (body.action === 'send') return json_(sendBriefing_(body));                     // from the daily job
  return json_({ ok: false, error: 'unknown request' });
}

function doGet(e) {
  var p = (e && e.parameter) || {};
  if (p.action === 'unsubscribe') return unsubscribePage_(p.e || '', p.s || '');
  if (!authorised_(e)) return json_({ ok: false, error: 'unauthorised' });
  if (p.action === 'list') return json_({ ok: true, subscribers: activeSubscribers_(), quota: MailApp.getRemainingDailyQuota() });
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
    sh.appendRow([new Date(r.created_at || new Date()), email, r.area || '', topics, r.topics_other || '', r.places || '',
                  r.people || '', r.frequency === 'weekly' ? 'Weekly' : 'Daily', 'Active', '', '']);
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
  if (MailApp.getRemainingDailyQuota() < 1) return { ok: false, error: 'daily email quota used up' };
  var unsub = unsubscribeUrl_(email);
  MailApp.sendEmail({
    to: email, name: FROM_NAME, replyTo: REPLY_TO, subject: String(b.subject || 'Your Eglur Daily briefing'),
    htmlBody: String(b.html || '').split('{{UNSUBSCRIBE}}').join(unsub),
    body: String(b.text || '').split('{{UNSUBSCRIBE}}').join(unsub)
  });
  sh.getRange(row, COL['Last briefing']).setValue(new Date());
  return { ok: true };
}

function sheet_() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
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
    (daily ? 'every weekday morning' : 'every Friday') + ' covering your council, the Senedd and Westminster, with only the things that touch what you follow.</p>' +
    '<p style="margin:0 0 8px;font-size:14px;font-weight:bold;color:#101A1A">What we\'ll watch for you</p>' +
    '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;margin:0 0 28px">' + table +
    '<tr><td colspan="2" style="border-top:1px solid #E3E8E6"></td></tr></table>' +
    '<p style="margin:0 0 30px;font-size:15px;line-height:1.6;color:#3D4A49">Want to change anything? Just reply to this email.</p>' +
    button_(SITE + '/monitor/', 'See a live example');
  var text = "You're on the list.\n\nThanks for joining Eglur Daily. When it launches, you'll get a short email " +
    (daily ? 'every weekday morning' : 'every Friday') + ' covering your council, the Senedd and Westminster.\n\n' +
    rows.map(function (x) { return x[0] + ': ' + x[1]; }).join('\n') +
    '\n\nWant to change anything? Just reply to this email.\n\nSee a live example: ' + SITE + '/monitor/\n\nUnsubscribe: ' + unsubscribeUrl_(email);
  MailApp.sendEmail({
    to: email, name: FROM_NAME, replyTo: REPLY_TO, subject: "You're on the list for Eglur Daily",
    htmlBody: frame_(inner, "We'll set up your briefing when Eglur Daily launches.", unsubscribeUrl_(email)), body: text
  });
}

/* ---------------------------------------------------------- email pieces */

function wordmark_(size) {
  return '<span style="font-family:\'DM Serif Display\',Georgia,serif;font-size:' + size + 'px;line-height:1;color:#101A1A;letter-spacing:-.02em">eglur<span style="color:#286A6C">.</span></span>';
}

function button_(href, label) {
  return '<table role="presentation" cellpadding="0" cellspacing="0"><tr><td style="border-radius:999px;background:#286A6C">' +
    '<a href="' + href + '" style="display:inline-block;padding:13px 24px;font-family:Arial,Helvetica,sans-serif;font-size:15px;font-weight:bold;color:#FCFFFE;text-decoration:none;border-radius:999px">' +
    esc_(label) + '</a></td></tr></table>';
}

function frame_(inner, preheader, unsub) {
  return '<!doctype html><html lang="en-GB"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">' +
    '<meta name="color-scheme" content="light"><link href="https://fonts.googleapis.com/css2?family=DM+Serif+Display&display=swap" rel="stylesheet"></head>' +
    '<body style="margin:0;padding:0;background:#F1F6F5">' +
    '<div style="display:none;max-height:0;overflow:hidden;opacity:0">' + esc_(preheader) + '</div>' +
    '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#F1F6F5"><tr><td align="center" style="padding:32px 14px">' +
    '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:600px">' +
    '<tr><td style="padding:0 6px 22px">' + wordmark_(26) + '</td></tr>' +
    '<tr><td style="background:#FFFFFF;border-radius:16px;padding:40px 36px;font-family:Arial,Helvetica,sans-serif">' + inner + '</td></tr>' +
    '<tr><td style="padding:22px 6px;font-family:Arial,Helvetica,sans-serif;font-size:12px;line-height:1.6;color:#5F6B6A">' +
    'Eglur Technologies. Eglur is Welsh for clear.<br>You signed up at eglurtech.com/daily. ' +
    '<a href="' + unsub + '" style="color:#5F6B6A">Unsubscribe</a></td></tr>' +
    '</table></td></tr></table></body></html>';
}

function esc_(s) {
  return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}
