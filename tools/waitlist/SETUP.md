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

## Good to know
- **Gmail's limit:** an ordinary Gmail account can email about 100 people a day. The job checks the remaining quota and stops before it. Beyond that, switch to a sending service such as Resend.
- **Changing what someone follows:** edit their row in the sheet. Changes apply from the next morning.
- **Unsubscribing:** every email has a link. It sets their Status to Unsubscribed, and nothing more is sent to them. You can also change Status by hand.
- **Privacy:** sign-ups are stored in Supabase (EU) and in this sheet. Only you can see either.
- **Councils covered:** Pembrokeshire and Ceredigion for now. Others get a "coming soon" line. Add a council by putting its ModernGov address in `COUNCIL_SITES` in `tools/monitor/subscribers.py`.
