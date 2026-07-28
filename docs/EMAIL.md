# JBHNTR, Email (Resend over SMTP)

The app sends a few transactional emails: **password reset**, **premium
confirmation**, and the optional **"email me when the search is ready"** notice.
They all go through one provider-agnostic SMTP sender
(`web/app/services/email.py`). Until SMTP is configured the sender is a **safe
no-op** that logs the message it *would* have sent, so nothing breaks before you
turn it on.

Recommended provider: **Resend**. Free tier (3,000/month, 100/day) covers this
comfortably, domain verification is just DNS, and it exposes SMTP, so no code
changes are needed, only environment variables.

---

## 1. Create the Resend account and verify the domain

1. Sign up at <https://resend.com> (the free plan is enough).
2. **Domains → Add Domain →** `jbhntr.app`.
3. Resend shows a set of DNS records (an MX/SPF `TXT`, a DKIM `TXT`, and usually
   a return-path `CNAME`). Add each one in **Cloudflare → DNS** for `jbhntr.app`,
   exactly as shown.
   - Leave the Cloudflare proxy **off** (grey cloud) for these records.
   - This is **outbound sending only**. It does **not** touch your existing
     Cloudflare **Email Routing** (that forwards inbound mail to `hello@`), so
     the two coexist.
4. Back in Resend, click **Verify**. DNS can take a few minutes to an hour.
   Wait until the domain shows **Verified** before sending.

## 2. Create an API key

**Resend → API Keys → Create API Key** (sending permission is enough). Copy it
now, it is shown only once. This value is the SMTP password below.

## 3. Set the environment variables on Railway

**Railway → your web service → Variables.** Add:

```bash
SMTP_HOST=smtp.resend.com
SMTP_PORT=587
SMTP_USER=resend            # literally the word "resend"
SMTP_PASSWORD=<your Resend API key>
SMTP_FROM=hello@jbhntr.app  # must be on the verified domain
SMTP_TLS=true
```

Also make sure the base URL is your real domain, because it builds the reset
link in the email:

```bash
BASE_URL=https://jbhntr.app
```

Optional, defaults to 60 if unset:

```bash
RESET_TOKEN_MINUTES=60      # how long a reset link stays valid
```

> Confirm the exact host/port/username in **Resend → SMTP** if anything above
> looks different, those are the values the panel gives you. Port 587 uses
> STARTTLS, which is what `SMTP_TLS=true` selects.

Railway redeploys on save. The sender reads these at startup.

## 4. Test the loop

1. Go to `https://jbhntr.app/forgot` and enter an email that has a
   password account.
2. The reset email should arrive within a few seconds. Follow the link, set a
   new password, and confirm you land signed in.

If nothing arrives:

- **Check the Railway logs.** If you see `email not configured — would send…`,
  the vars are not being read (typo or not redeployed).
- If you see `email send to … failed`, it reached SMTP but was rejected, usually
  the domain is not verified yet, or `SMTP_FROM` is not on the verified domain.
- Check the Resend dashboard's **Emails** log, it shows delivered/bounced.

---

## What sends, and when

| Email | Trigger | Code |
| --- | --- | --- |
| Welcome (HTML + text) | successful signup (email or new Google account) | `send_welcome` |
| Password reset (HTML + text) | `/forgot` for a real password account | `send_password_reset` |
| Daily/weekly digest (HTML + text) | the nightly cron, premium users, non-empty days only | `send_digest` |
| Premium waiting-list confirmation | user taps "Tell me when premium opens" | `send_premium_confirmation` |

Bodies live in `web/app/templates/email/` (`_shell.html` + one `.html` and
`.txt` per email). The digest never sends on a zero-match day, caps at eight
roles, never repeats one, honours each user's frequency (Account → Email), and
carries a one-click unsubscribe (`/unsubscribe?t=...` + `List-Unsubscribe`
headers).

## From-address and deliverability

- Always send **from an address on the verified domain** (`hello@jbhntr.app` or
  `noreply@jbhntr.app`), never a Gmail address, that is the single biggest
  deliverability factor.
- Keep the DKIM/SPF records in place; removing them will send mail to spam.

## Switching providers later

Everything is plain SMTP, so **Postmark**, **Amazon SES**, **Brevo**, etc. work
by changing the same six variables, no code change:

- **Postmark**: `SMTP_HOST=smtp.postmarkapp.com`, `SMTP_PORT=587`, and
  `SMTP_USER` = `SMTP_PASSWORD` = your Server API token.
- **Amazon SES**: the region SMTP host (e.g.
  `email-smtp.eu-west-1.amazonaws.com`), port `587`, and the generated SMTP
  credentials.

If you ever move to a provider's HTTP API instead of SMTP, that is a change to
`web/app/services/email.py` alone.
