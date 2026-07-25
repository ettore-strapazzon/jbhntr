# JBHNTR, Security & Data Protection

> ⚠️ **Not legal advice.** This documents what the code does and what the law
> broadly requires. Before taking payment or launching publicly, have a lawyer
> review your Terms, Privacy Policy and processor agreements.

## Why this deserves real care

Users upload **CVs**. A CV is among the most sensitive documents a person has:
full name, address, phone, employment history, and it frequently *implies*
special-category data under **GDPR Article 9** (health, via gaps or
accommodations; ethnicity or religion, via names, languages, schools,
volunteering). Treat the whole store as sensitive by default.

## Threat model

| Threat | Mitigation |
|---|---|
| Database dump leaks CVs | Files encrypted at rest (Fernet/AES-128-CBC+HMAC); key held in env, never in DB |
| Stolen session cookie | `HttpOnly`, `Secure`, `SameSite=Lax`, signed, 14-day expiry, rotated on login |
| Password database leak | **bcrypt** hashes (cost 12); never reversible, never logged |
| Malicious upload (RCE/XSS) | Extension **and** magic-byte check, ≤1 MB, stored as opaque bytes, never executed, never served inline |
| CSRF | Signed per-session token on every state-changing form |
| SQL injection | SQLAlchemy parameterised queries only; no string SQL |
| XSS | Jinja2 autoescaping on; user text never marked `\|safe` |
| Brute force | Per-IP + per-account login throttling, plus Cloudflare rate limiting |
| Enumeration of accounts | Identical response for "wrong password" and "no such user" |
| Cost abuse (paid AI) | Hard per-user search quotas checked server-side before enqueue |
| Another user's data | Every query filtered by `user_id`; ownership re-checked on every object |

## Encryption of uploads

```
upload → validate (size, extension, magic bytes)
       → extract text for the AI
       → Fernet.encrypt(bytes) with FILE_ENCRYPTION_KEY
       → store ciphertext in Postgres (bytea)
```

Rationale for storing in Postgres rather than object storage: at this scale
(≤1 MB × a few files per user) it keeps backups, deletion and access control in
**one** place, which is exactly what makes GDPR erasure reliable.

**Key management:** `FILE_ENCRYPTION_KEY` is a Railway secret. If it is lost,
files are unrecoverable by design. Rotating it requires decrypt-and-re-encrypt;
a helper is provided in `web/app/security.py`.

## GDPR obligations and how they're met

| Requirement | Implementation |
|---|---|
| **Lawful basis** (Art. 6) | Contract performance, you can't run a job search without a profile. Marketing email is separate opt-in (consent). |
| **Art. 9 special categories** | Not solicited. Terms instruct users not to include health/political/religious data. Encryption + minimisation reduce exposure. |
| **Transparency** (Art. 13) | Privacy Policy lists every sub-processor and purpose |
| **Right of access** (Art. 15) | `GET /account/export` → JSON of everything held |
| **Right to erasure** (Art. 17) | `POST /account/delete` → hard-deletes rows and ciphertext, not a soft flag |
| **Data minimisation** (Art. 5) | Only the listed fields; no tracking cookies; IPs not stored with page views |
| **Storage limitation** | Searches/results purged after 12 months; deleted accounts purged immediately |
| **Security** (Art. 32) | Encryption at rest and in transit, hashed passwords, access controls |
| **Records of processing** (Art. 30) | This document + the sub-processor table |
| **Breach notification** (Art. 33) | Runbook below; 72-hour clock |

### Sub-processors (must be listed in the Privacy Policy)

| Processor | Data sent | Purpose | Where |
|---|---|---|---|
| Railway | All application data | Hosting | US/EU region |
| OpenRouter → model provider | **CV text, about-me, job adverts** | Matching & document generation | US |
| Cloudflare | IP, request metadata | DNS, TLS, WAF | Global |
| Plausible | Page URL, country | Analytics (cookieless) | EU |
| *(Later)* Stripe | Email, payment data | Billing | US/EU |

> The OpenRouter row is the significant one: **user CV text leaves the EU**.
> Your Privacy Policy must say so plainly, and you need Standard Contractual
> Clauses or an equivalent transfer mechanism. An EU-hosted model provider
> removes this issue entirely if it becomes a blocker.

## Cookies

Only **one** cookie: the session. It is strictly necessary, so under the EU
ePrivacy Directive it does **not** require consent. Analytics is cookieless
(Plausible). Therefore the banner is an **informational notice**, not a consent
gate, no "Accept/Reject" dance, which is both more honest and better UX. If
you later add advertising or profiling cookies, you must switch to real consent
with granular opt-in.

## Incident runbook

1. Contain, revoke keys, take the service offline if data is actively exposed.
2. Assess, what data, how many users, is it encrypted?
3. **Notify the supervisory authority within 72 hours** if a risk to individuals
   exists (Art. 33). In Italy this is the Garante.
4. Notify affected users without undue delay if the risk is high (Art. 34).
5. Write a post-mortem; fix the root cause.

## Pre-launch checklist

- [ ] `FILE_ENCRYPTION_KEY` and `SECRET_KEY` are strong, unique, and only in Railway secrets
- [ ] `DEBUG=false` in production
- [ ] HTTPS enforced; HSTS on (automatic with a `.app` domain)
- [ ] Security headers present (CSP, X-Frame-Options, X-Content-Type-Options)
- [ ] Password reset works and doesn't leak whether an account exists
- [ ] Account deletion genuinely removes rows and ciphertext (verify in the DB)
- [ ] Data export returns everything held about the user
- [ ] Terms + Privacy reviewed by a lawyer
- [ ] Backups enabled **and a restore tested**
- [ ] Rate limits verified with a real load test
- [ ] No secrets in git (`git log -p | grep -i "sk-"`)
