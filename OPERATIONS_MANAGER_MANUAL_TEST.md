# Sparkles Operations Manager manual test checklist

Use safe test data locally or an already-labelled production test record.

## Access and regression

- [ ] Start the application using the existing README command.
- [ ] Log in as an admin.
- [ ] Confirm `/admin/dashboard` still loads.
- [ ] Confirm existing KPI cards, charts, upcoming jobs and reviews still load.
- [ ] Confirm a logged-out request is still redirected to `/admin/login`.

## Operations Manager panel

- [ ] Confirm the panel appears inside the Owner Command Centre.
- [ ] Confirm Business Health shows Healthy, Needs Attention or Critical.
- [ ] Confirm Today's Revenue matches the existing Revenue Today card.
- [ ] Confirm Bookings Today matches the existing Today's Jobs card.
- [ ] Confirm Jobs Awaiting Assignment matches the existing Bookings Waiting card.
- [ ] Confirm Outstanding Balances matches the existing dashboard value.
- [ ] Confirm Available Cleaners is described as today's availability estimate.

## Issues

- [ ] Confirm every displayed issue has a title and category.
- [ ] Confirm every issue explains the recommended action.
- [ ] Confirm each Open link reaches the relevant existing admin page.
- [ ] Confirm no issue action changes data automatically.
- [ ] Confirm a paid, unassigned booking appears under Critical when due today.
- [ ] Confirm a future paid, unassigned booking appears under Needs Attention.
- [ ] Confirm a completed booking with Balance Due appears under Needs Attention.
- [ ] Confirm a failed automation appears under Critical.
- [ ] Confirm a retrying automation appears under Needs Attention.
- [ ] Confirm a failed email from the last seven days appears under Needs Attention.
- [ ] Confirm a recommended applicant appears under Suggested Actions.
- [ ] Confirm timeline, payment, recruitment and automation events appear under Recent Activity.

## Mobile

- [ ] Test at approximately 390px width.
- [ ] Confirm there is no horizontal scrolling.
- [ ] Confirm summary cards stack into one column.
- [ ] Confirm issue groups stack into one column.
- [ ] Confirm issue Open links remain usable.

## Read-only assurance

- [ ] Record table row counts before loading the dashboard.
- [ ] Refresh the dashboard twice.
- [ ] Confirm no booking, payment, cleaner, applicant, email or automation row was created or changed.
- [ ] Confirm Stripe, customer email and cleaner workflows continue unchanged.
