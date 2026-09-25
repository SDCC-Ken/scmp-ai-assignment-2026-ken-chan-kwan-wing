# Limits and routing: what the numbers mean and how to change them

All data is fictional. There is no admin screen in the PoC: leave entitlements, department claim
limits and approvers are plain database values that you change with a few CLI commands. They are
**shown, never blocking**: a request may exceed a balance or a limit, and the approver decides.

## 1. What each value means

| Value | Meaning | Where it lives |
| --- | --- | --- |
| Leave entitlement | Days a person may take in a calendar year, for `annual` and `sick` leave only (half-day steps). `personal` and `unpaid` have none. | table `leave_entitlements` (`user_id`, `year`, `leave_type`, `entitled_days`; one row per user, year and type) |
| Department claim limit | Yearly budget of a department for staff claims, in HKD. | column `departments.claim_limit_amount` |
| Leave approver | The one person who decides this user's leave requests (must be an active `hr_approver`, not the user). | column `users.leave_approver_user_id` |
| Claim approver | The one person who decides this user's claims (must be an active `finance_approver`, not the user). | column `users.claim_approver_user_id` |
| Assigned approver of a request | The approver copied from the user when the request is created; only this person sees it in their queue and gets notified. | columns `leave_requests.approver_user_id`, `claim_requests.approver_user_id` |
| Department, job title | Department is used for the claim limit and the "same team" overlap only (not for routing). Job title is display only. | columns `users.department_id`, `users.job_title` |
| `can_request` | Derived: true when at least one approver is configured. A user without any (Helen and Eva in the seed) cannot file requests and has no balance screen; approvers can still use the chat page for the bell inbox. | computed from the two approver columns |

## 2. The seed (a fresh database)

| Person | Department | Role | Leave approver | Claim approver | Annual / sick (2026 and 2027) |
| --- | --- | --- | --- | --- | --- |
| Amy Lau, Software Engineer | IT | employee | Cathy Ng | Eva Cheung | 15 / 10 |
| Ben Chow, Software Engineer | IT | employee | Cathy Ng | Eva Cheung | 18 / 10 |
| Cathy Ng, HR Business Partner (IT) | HR | hr_approver | Helen Yeung | Eva Cheung | 15 / 10 |
| Daniel Wong, HR Officer | HR | employee | Helen Yeung | Eva Cheung | 15 / 12 |
| Helen Yeung, HR Manager | HR | hr_approver | none | none | none |
| Eva Cheung, Finance Manager | Finance | finance_approver | none | none | none |

Claim limits: IT HKD 60,000.00, HR HKD 30,000.00, Finance HKD 30,000.00. Helen's and Eva's
approvers are "out of the PoC scope"; giving them one later is a data change (section 4).

The pending demo requests show the limits: Amy's pending annual leave overlaps Ben's approved
leave (team overlap), Daniel's pending annual leave is above his annual balance, and Daniel's
pending claim pushes the HR department above its limit.

## 3. Counting rules

- **Only approved requests are deducted.** `pending_approval` requests are shown separately
  ("pending, not deducted"). Draft, failed, rejected and cancelled requests never count.
- **Leave** counts in the calendar year of its **start date** (a leave from 30 Dec to 5 Jan counts
  fully in the first year; there is no splitting). It uses the request's working days (weekends
  and public holidays already excluded, half days as 0.5).
  `remaining = entitled - approved` and can be negative.
- **Claims** count in the calendar year of the **receipt date**, per department (the sum of the
  approved claims of the department's users). `remaining = limit - approved`.
- When an approver looks at a request, that request is left out of the totals and shown as
  "requested": `remaining after = entitled (or limit) - approved - requested`. Over the limit
  means that value is below zero (exactly zero is fine). Other pending requests are listed as
  "pending elsewhere" and not deducted.
- **Team overlap:** active colleagues of the requester's department (the requester excluded) whose
  approved or pending leave shares at least one calendar day with the request.
- The numbers are informational. A request over the balance or the limit can still be submitted
  and approved.

## 4. Changing the data

Run the commands from `backend/` (`uv run python -m app.cli ...`) or, in Docker Compose:

```bash
docker compose exec api python -m app.cli show-org

# yearly entitlement of one person (annual or sick, half-day steps, creates the row if missing)
docker compose exec api python -m app.cli set-entitlement \
    --email amy.lau@example.com --year 2026 --type annual --days 18
docker compose exec api python -m app.cli set-entitlement \
    --email daniel.wong@example.com --year 2027 --type sick --days 12.5

# department claim limit in HKD (at most 2 decimals)
docker compose exec api python -m app.cli set-claim-limit --department IT --amount 80000

# who approves whom; an e-mail, or "none" to remove it. Only what you pass is changed.
docker compose exec api python -m app.cli set-approvers \
    --email amy.lau@example.com --leave-approver helen.yeung@example.com
docker compose exec api python -m app.cli set-approvers \
    --email helen.yeung@example.com --leave-approver cathy.ng@example.com \
    --claim-approver eva.cheung@example.com
docker compose exec api python -m app.cli set-approvers \
    --email daniel.wong@example.com --claim-approver none
```

`set-approvers` checks everything before it changes anything: the approver must exist, be active,
have the right role (`hr_approver` for leave, `finance_approver` for claims) and not be the user.
A mistake (unknown e-mail, wrong role, negative days, 3 decimals, unknown department) prints
`Error: ...` and changes nothing. `show-org` prints the departments with their limits, every user
with department, role, title and approvers, and the entitlements per year.

Changes apply to **new** requests. A request that is already pending keeps the approver it was
assigned when it was created.

## 5. Reset the database once for Phase 3

Phase 3 removed the database rule "a rejected request needs a note" and added new tables and
columns. SQLite cannot drop a rule in place, so a database created by an earlier phase must be
recreated (this also reseeds the demo data):

```bash
docker compose down -v                                   # deletes the Docker volume
docker compose up --build
# or, without Docker, from backend/:
uv run python -m app.cli seed --reset --yes
```

If you start the API on an old database it does not crash and does not modify the file: it logs
one clear error with the instruction above and answers `503` (with the same text) to the endpoints
that use the database, until you reset it. New databases store `schema_version = 3` in the
`schema_meta` table.
