# Sparkles Operations Manager

Sparkles Operations Manager is a read-only operational layer inside the existing
Sparkles Owner Command Centre. It does not create a separate application and
does not change booking, payment, cleaner, customer, recruitment, email or
automation workflows.

## Architecture

- `operations_manager.py` contains the reusable `OperationsIssue` and
  `HealthSummary` models.
- The existing `owner_dashboard_payload()` remains the authoritative source for
  revenue, booking, assignment and outstanding-balance totals.
- Operations Manager receives that dashboard payload and performs bounded
  `SELECT` queries for exception detection and recent activity.
- The existing authenticated `/api/admin/dashboard` response now includes an
  `operations_manager` object.
- `owner-dashboard.js` renders that object inside the existing Owner Command
  Centre.

No database table or environment variable was added.

## Data inspected

- `bookings`
- `customers`
- `cleaners`
- `cleaner_applicants`
- `payments`
- `automation_jobs`
- `automation_alerts`
- `automation_logs`
- `email_log`
- `booking_timeline`
- `cleaner_applicant_timeline`

All database statements in `operations_manager.py` are reads.

## Payload

`operations_manager` contains:

- `business_health`: status, score, message and issue counts.
- `summary`: today's revenue, bookings today, estimated available cleaners,
  jobs awaiting assignment and outstanding balances.
- `groups.critical`
- `groups.needs_attention`
- `groups.suggested_actions`
- `groups.recent_activity`
- `read_only`: always `true`.

Every issue contains:

- `title`
- `severity`
- `category`
- `related_record`
- `recommended_action`
- `admin_url`
- `detail`
- `occurred_at`

## Health rules

Critical examples:

- A deposit-confirmed booking due today or earlier has no cleaner.
- An in-progress booking has no cleaner.
- An automation exhausted its retries.
- An unresolved automation alert is marked Error or Critical.
- A required Operations Manager data source cannot be inspected.

Needs Attention examples:

- A future paid booking needs assignment.
- A completed job still has a final balance.
- An automation is retrying.
- A recent email delivery failed.
- No activated cleaner appears available for today's work.

Suggested Actions include strong cleaner applicants awaiting owner review and
limited cleaner capacity. Cleaner approval is never automated.

Available cleaners is an operational estimate based on active, activated
accounts, saved availability and current jobs scheduled for today. It is not a
replacement for the existing cleaner eligibility or assignment logic.

## Failure isolation

The Operations Manager catches read failures and reports one system issue rather
than changing or retrying business workflows. The existing dashboard cards
remain the source of truth.

## Railway

No new Railway variables or migration steps are required. Deploy the commit
normally and log back into the Owner Command Centre.
