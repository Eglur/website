# Eglur Daily: sign-up sheet, welcome email and daily emails

About 15 minutes. Do these in order.

## 1. The Google Sheet (signed in as eglurtech@gmail.com)
1. Go to **sheets.new** while signed in as **eglurtech@gmail.com**. A blank sheet opens.
2. **Extensions → Apps Script.** Delete the starter code, paste in everything from `tools/waitlist/apps-script.gs`, and click **Save**.
3. In the function menu at the top, choose **setup**, then click **Run**.
   - Google asks for permission. Because this is your own script, it shows a warning: click **Advanced → Go to (project name)** and **Allow**. The script needs access to this sheet and to send email as you.
4. Open **Execution log** at the bottom. Copy the **secret token** it shows and keep it private.
5. **Deploy → New deployment**. Click the gear and choose **Web app**. Set **Execute as: Me** and **Who has access: Anyone**, then click **Deploy**. Copy the **Web app URL** (it ends in `/exec`).

The sheet is now called "Eglur Daily: sign-ups", with headings, formatting and a Status column (Active, Unsubscribed or Paused).

## 2. Connect Supabase to the sheet
In Supabase (project **Eglur Daily**):
1. **Database → Webhooks** (enable webhooks if it asks), then **Create a new hook**.
2. Name: `send-to-sheet`. Table: `waitlist`. Events: **Insert** only.
3. Type: **HTTP Request**, method **POST**. URL: your Web app URL followed by `?token=` and your secret token, e.g.
   `https://script.google.com/macros/s/AKfy…/exec?token=abc123…`
4. Click **Create webhook**.

From now on, every sign-up appears in the sheet within seconds and gets the welcome email.

## 3. Let the daily job use the sheet
Add two repository secrets at https://github.com/Eglur/website/settings/secrets/actions/new:
- `SUBSCRIBERS_URL`: the Web app URL
- `SUBSCRIBERS_TOKEN`: the secret token

## 4. Test it
1. Sign up at **www.eglurtech.com/daily/** with your own email. Check that a row appears in the sheet and the welcome email arrives (look in spam the first time, and mark it "not spam").
2. Open https://github.com/Eglur/website/actions/workflows/daily-email.yml and click **Run workflow** with **dry run** ticked. The run's **email-previews** download shows what each person would get.
3. To send yourself a real one: run it again, untick **dry run**, and put your email in **only**.

After that it runs on its own every weekday at 06:10 UTC. Weekly subscribers get theirs on Fridays. Daily subscribers with nothing relevant that day get no email rather than an empty one.

## 5. Send from monitor@eglurtech.com (Microsoft 365)
Until this is done, emails come from eglurtech@gmail.com. Afterwards they come from **monitor@eglurtech.com** through your Microsoft 365, signed with your domain, so they're far less likely to land in spam, and the limit rises to thousands a day.

**a. Make monitor@ a mailbox of its own** (Microsoft's sending service needs a real mailbox, not an alias). Shared mailboxes are free.
1. Go to **admin.exchange.microsoft.com → Recipients → Mailboxes**, open your own mailbox, then **Email addresses** (or "Manage email address types"). Remove `monitor@eglurtech.com` and save.
2. Back in **Mailboxes**, choose **Add a shared mailbox**. Display name **Eglur Daily**, email **monitor@eglurtech.com**. Then add yourself as a member, so replies appear in your Outlook.

**b. Give the sheet permission to send** (about 5 minutes, at **entra.microsoft.com**):
1. **App registrations → New registration.** Name it `Eglur Daily mailer`, choose *Accounts in this organizational directory only*, and click **Register**.
2. Copy the **Application (client) ID** and **Directory (tenant) ID** from the overview page.
3. **API permissions → Add a permission → Microsoft Graph → Application permissions →** tick **Mail.Send → Add permissions**, then click **Grant admin consent for Eglur Technologies**.
4. **Certificates & secrets → New client secret** (24 months). Copy the **Value** straight away; Microsoft only shows it once.

**c. Tell the script** (in the sheet's **Extensions → Apps Script**):
1. Paste in the updated `apps-script.gs` and **Save**.
2. Click the **gear (Project Settings) → Script properties → Add**, and add three properties:
   - `MS_TENANT_ID`: the Directory (tenant) ID
   - `MS_CLIENT_ID`: the Application (client) ID
   - `MS_CLIENT_SECRET`: the secret's Value
3. Choose **testSend** in the function menu and click **Run**. Allow the new permission ("connect to an external service") when asked. A test email arrives in eglurtech@gmail.com **from monitor@eglurtech.com**.
4. **Deploy → Manage deployments → edit (pencil) → Version: New version → Deploy**, so the live web app uses the new code. The URL stays the same.

Optional hardening: as set up, the Mail.Send permission could send as any mailbox in your organisation. Microsoft's "RBAC for Applications" can limit it to monitor@ only; worth doing before anyone else joins your Microsoft 365.

## Good to know
- **The website's contact form** uses this same script and sheet (a Messages tab). Setup: `tools/contact/SETUP.md`.
- **Limits:** from Gmail, about 100 emails a day (the job stops before that). From Microsoft 365, thousands a day.
- **Changing what someone follows:** edit their row in the sheet. Changes apply from the next morning.
- **Unsubscribing:** every email has a link. It sets their Status to Unsubscribed, and nothing more is sent to them. You can also change Status by hand.
- **Privacy:** sign-ups are stored in Supabase (EU) and in this sheet. Only you can see either.
- **Councils covered:** Pembrokeshire and Ceredigion for now. Others get a "coming soon" line. Add a council by putting its ModernGov address in `COUNCIL_SITES` in `tools/monitor/subscribers.py`.
