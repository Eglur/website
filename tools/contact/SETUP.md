# Contact form: database, email and sheet

The form at **www.eglurtech.com/contact** saves each message in Supabase. Supabase then calls the
same Google Apps Script as the Eglur Daily waitlist, which:

- emails the message to **contact@eglurtech.com** (a shared mailbox in Microsoft 365), with Reply-To set to the sender, so pressing Reply answers them directly;
- sends the sender a short confirmation in fixed words (never their name or message, so nobody can use the form to send their own text to someone else's address);
- adds a row to a **Messages** tab in the "Eglur Daily: sign-ups" spreadsheet, with a Status column (New, Replied, Closed).

About 10 minutes. Do these **before** the website change goes live, in this order.

## 0. The mailbox (Microsoft 365 admin)
**admin.microsoft.com → Teams & groups → Shared mailboxes → Add a shared mailbox.** Name `Eglur`, email `contact@eglurtech.com`. Then add yourself under **Members**, which lets you read it and reply as contact@. Shared mailboxes are free.
In classic Outlook it appears on its own; in Outlook on the web or the new Outlook, right-click **Folders → Add shared folder or mailbox** once.

## 1. The database (Supabase, project **Eglur Daily**)
1. **SQL Editor → New query.** Paste everything from `tools/contact/supabase.sql`.
2. Optional dry run: add `begin;` as the first line and `rollback;` as the last, and click **Run**. "Success. No rows returned" means it works; nothing has changed yet. Remove those two lines.
3. Click **Run**. You should see "Success. No rows returned".

This creates the `contact_messages` table. The website's public key can only add a message to it; it can't read, change or delete any. There's also a brake: at most 3 messages an hour from one address, 30 an hour and 150 a day in total.

## 2. The script (signed in as eglurtech@gmail.com)
1. Go to **script.google.com** and open the **Eglur Daily** project. (It's a standalone project, so it isn't under the sheet's Extensions menu.)
2. Select all the code, delete it, paste in everything from `tools/waitlist/apps-script.gs`, then put back the original `var SHEET_ID = '…';` line near the top: it tells the script which sheet to use. Click **Save**.
3. Optional: choose **setupMessages** in the function menu and click **Run**, to create the Messages tab now. Otherwise it appears with the first message.
4. **Deploy → Manage deployments**, and for **each** active deployment: edit (pencil) **→ Version:** the newest (or **New version**) **→ Deploy.** The web addresses stay the same.

## 3. Connect them (Supabase, project **Eglur Daily**)
Only after step 2 is deployed: the old script would treat a message as a waitlist sign-up.

**Easiest, and the secret token is never copied:** SQL Editor → New query → paste everything from `tools/contact/webhook.sql` → **Run**. It gives `contact_messages` a webhook with the same address, headers and parameters as the waitlist's (the token sits in the parameters), all inside the database. It then shows up under **Database → Webhooks** as `send-message-to-inbox`.

Or by hand:
1. **Database → Webhooks.** Open the existing waitlist hook (`send_to_sheet`) and note its URL and its HTTP parameters (the `token`). Close it without changing anything.
2. **Create a new hook.** Name: `send-message-to-inbox`. Table: `contact_messages`. Events: **Insert** only.
3. Type: **HTTP Request**, method **POST**, the same URL, and add the same `token` HTTP parameter. Set **Timeout** to `5000`.
4. Click **Create webhook**.

## 4. Test it, once the website change is live
1. Send yourself a message at **www.eglurtech.com/contact**, using an address other than contact@eglurtech.com.
2. Check that the message arrives at contact@eglurtech.com, that pressing Reply addresses it to the sender, that the confirmation arrives at the address you used, and that a row appears in the Messages tab (and in Supabase under **Table Editor → contact_messages**).
3. Mark the test row Closed, or delete it.

## Good to know
- **Where to reply:** reply to the notification in the contact@ mailbox. Choose **From: contact@** or your own address, whichever you prefer.
- **If an email fails**, the message is still in the Messages tab and in Supabase, and the row says why.
- **Limits:** at most 60 notification emails and 20 confirmations a day, and one confirmation per address every six hours. Past that, messages still land in the sheet. Emails come from eglurtech@gmail.com until the Microsoft 365 step in `tools/waitlist/SETUP.md` is done, then from monitor@eglurtech.com.
- **Switches** (Apps Script → Project Settings → Script properties): `CONTACT_TO` sends messages to a different address; `CONTACT_ACK` set to `off` stops the confirmations.
- **Privacy:** messages are kept in Supabase and the sheet, and only you can see either. The website's data page says so. Delete a person's rows in both places if they ask.
