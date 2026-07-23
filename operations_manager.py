"""Read-only operational intelligence for the Sparkles Owner Command Centre.

This module deliberately contains no workflow mutations. It consumes the
authoritative dashboard summary and performs bounded SELECT queries to surface
records that may require the owner's attention.
"""

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import json
import re
from typing import Any, Callable


@dataclass(frozen=True)
class OperationsIssue:
    """A reusable issue presented by the Operations Manager."""

    title: str
    severity: str
    category: str
    related_record: dict[str, Any]
    recommended_action: str
    admin_url: str
    detail: str = ""
    occurred_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class HealthSummary:
    """A reusable summary of the business's current operational health."""

    status: str
    score: int
    message: str
    critical_count: int
    needs_attention_count: int
    suggested_action_count: int
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _normalise(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def _truthy(value: Any) -> bool:
    return _normalise(value) in {"1", "true", "yes", "y", "on", "active", "enabled"}


def _as_int(value: Any) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


def _parse_json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    try:
        parsed = json.loads(value or "[]")
        return parsed if isinstance(parsed, list) else []
    except (TypeError, json.JSONDecodeError):
        return []


def _record(record_type: str, row: dict[str, Any], fallback: str = "") -> dict[str, Any]:
    identifier = row.get("id")
    reference = (
        row.get("reference")
        or row.get("provider_payment_id")
        or row.get("automation_key")
        or fallback
    )
    return {"type": record_type, "id": identifier, "reference": str(reference or identifier or "")}


def _issue(
    title: str,
    severity: str,
    category: str,
    record_type: str,
    row: dict[str, Any],
    recommended_action: str,
    admin_url: str,
    detail: str = "",
    occurred_at: str = "",
) -> OperationsIssue:
    return OperationsIssue(
        title=title,
        severity=severity,
        category=category,
        related_record=_record(record_type, row),
        recommended_action=recommended_action,
        admin_url=admin_url,
        detail=detail,
        occurred_at=occurred_at,
    )


def _dedupe(issues: list[OperationsIssue]) -> list[OperationsIssue]:
    seen: set[tuple[str, str, str]] = set()
    unique: list[OperationsIssue] = []
    for issue in issues:
        key = (
            issue.title,
            issue.category,
            str(issue.related_record.get("reference") or issue.related_record.get("id") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(issue)
    return unique


def _active_booking(row: dict[str, Any]) -> bool:
    return not row.get("archived_at") and not _truthy(row.get("is_test"))


def _successful_payment(row: dict[str, Any]) -> bool:
    return _normalise(row.get("status")) in {
        "paid",
        "succeeded",
        "success",
        "complete",
        "completed",
        "paid in full",
    }


def _booking_has_deposit(booking: dict[str, Any], paid_booking_ids: set[str]) -> bool:
    return (
        str(booking.get("id")) in paid_booking_ids
        or _normalise(booking.get("payment_status")) in {"deposit paid", "balance due", "paid in full"}
        or _normalise(booking.get("status")) == "deposit paid"
    )


def _cleaner_available_today(
    cleaner: dict[str, Any],
    today_name: str,
    busy_cleaner_ids: set[int],
) -> bool:
    cleaner_id = _as_int(cleaner.get("id"))
    if not _truthy(cleaner.get("active")) or not cleaner.get("password_hash"):
        return False
    if cleaner_id in busy_cleaner_ids:
        return False
    availability = [str(item).strip().lower() for item in _parse_json_list(cleaner.get("availability"))]
    if not availability:
        availability = [
            item.strip().lower()
            for item in str(cleaner.get("availability") or "").split(",")
            if item.strip()
        ]
    return today_name.lower() in availability or any(
        item in {"any", "any day", "all", "every day", "fully flexible", "flexible"}
        for item in availability
    )


def build_operations_summary(
    connector: Callable[[], Any],
    dashboard_payload: dict[str, Any],
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return the read-only Operations Manager payload.

    ``dashboard_payload`` is the already-computed Owner Command Centre payload,
    ensuring financial and booking totals have one authoritative calculation.
    """

    local_now = now or datetime.now().astimezone()
    if local_now.tzinfo is None:
        local_now = local_now.replace(tzinfo=timezone.utc)
    today = local_now.date()
    today_s = today.isoformat()
    today_name = today.strftime("%A")
    seven_days_ago = (local_now - timedelta(days=7)).astimezone(timezone.utc).isoformat()
    cards = dict(dashboard_payload.get("cards") or {})
    inspection_errors: list[str] = []

    with connector() as conn:
        def rows(sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
            try:
                return [dict(row) for row in conn.execute(sql, params).fetchall()]
            except Exception as error:  # The panel must never break the proven dashboard.
                inspection_errors.append(str(error))
                return []

        bookings = rows(
            """SELECT id,reference,name,preferred_date,preferred_time,status,payment_status,
                      cleaner_id,balance_amount,created_at,archived_at,is_test
               FROM bookings ORDER BY id DESC"""
        )
        customers = rows(
            "SELECT id,name,email,created_at FROM customers ORDER BY id DESC LIMIT 50"
        )
        cleaners = rows(
            """SELECT id,name,email,active,password_hash,availability,services,postcode,
                      travel_radius,identity_verified,right_to_work_verified,created_at
               FROM cleaners ORDER BY id DESC"""
        )
        applicants = rows(
            """SELECT id,name,status,ai_recommendation,ai_score,created_at,updated_at
               FROM cleaner_applicants ORDER BY id DESC LIMIT 100"""
        )
        payments = rows(
            """SELECT id,booking_id,payment_type,amount,status,provider_payment_id,created_at
               FROM payments ORDER BY id DESC LIMIT 100"""
        )
        automation_jobs = rows(
            """SELECT id,booking_id,step,status,attempts,max_attempts,last_error,updated_at
               FROM automation_jobs ORDER BY id DESC LIMIT 100"""
        )
        automation_alerts = rows(
            """SELECT id,automation_key,title,detail,level,created_at
               FROM automation_alerts WHERE resolved_at IS NULL ORDER BY id DESC LIMIT 50"""
        )
        automation_logs = rows(
            """SELECT id,automation_key,event,detail,level,created_at
               FROM automation_logs ORDER BY id DESC LIMIT 50"""
        )
        email_logs = rows(
            """SELECT id,booking_id,recipient,subject,status,error,created_at
               FROM email_log ORDER BY id DESC LIMIT 100"""
        )
        booking_timeline = rows(
            """SELECT id,booking_id,event,detail,level,created_at
               FROM booking_timeline ORDER BY id DESC LIMIT 50"""
        )
        applicant_timeline = rows(
            """SELECT id,applicant_id,event,detail,level,created_at
               FROM cleaner_applicant_timeline ORDER BY id DESC LIMIT 30"""
        )

    active_bookings = [booking for booking in bookings if _active_booking(booking)]
    successful_payments = [payment for payment in payments if _successful_payment(payment)]
    paid_booking_ids = {str(payment.get("booking_id")) for payment in successful_payments}
    busy_statuses = {"assigned", "accepted", "on my way", "in progress"}
    busy_cleaner_ids = {
        _as_int(booking.get("cleaner_id"))
        for booking in active_bookings
        if booking.get("cleaner_id")
        and str(booking.get("preferred_date") or "")[:10] == today_s
        and _normalise(booking.get("status")) in busy_statuses
    }
    available_cleaners = sum(
        1 for cleaner in cleaners if _cleaner_available_today(cleaner, today_name, busy_cleaner_ids)
    )

    critical: list[OperationsIssue] = []
    attention: list[OperationsIssue] = []
    suggestions: list[OperationsIssue] = []
    activity: list[OperationsIssue] = []

    for booking in active_bookings:
        status = _normalise(booking.get("status"))
        booking_date = str(booking.get("preferred_date") or "")[:10]
        has_deposit = _booking_has_deposit(booking, paid_booking_ids)
        unassigned = not booking.get("cleaner_id")
        reference = str(booking.get("reference") or f"Booking #{booking.get('id')}")
        if has_deposit and unassigned and status not in {"completed", "cancelled", "canceled"}:
            target = critical if booking_date and booking_date <= today_s else attention
            severity = "Critical" if target is critical else "Needs Attention"
            target.append(
                _issue(
                    f"{reference} has no cleaner assigned",
                    severity,
                    "Booking",
                    "booking",
                    booking,
                    "Open the booking and assign an eligible cleaner.",
                    "/admin/bookings",
                    f"Deposit is confirmed and the clean is scheduled for {booking_date or 'an unknown date'}.",
                    booking.get("created_at") or "",
                )
            )
        if status == "in progress" and unassigned:
            critical.append(
                _issue(
                    f"{reference} is in progress without an assigned cleaner",
                    "Critical",
                    "Booking",
                    "booking",
                    booking,
                    "Review the booking immediately and correct its cleaner assignment.",
                    "/admin/bookings",
                    "An in-progress job must remain linked to the cleaner performing it.",
                    booking.get("created_at") or "",
                )
            )
        if (
            status == "completed"
            and _normalise(booking.get("payment_status")) != "paid in full"
            and _as_int(booking.get("balance_amount")) > 0
        ):
            attention.append(
                _issue(
                    f"{reference} has an outstanding final balance",
                    "Needs Attention",
                    "Payment",
                    "booking",
                    booking,
                    "Open the booking and confirm the final invoice workflow is progressing.",
                    "/admin/bookings",
                    f"Remaining balance: £{_as_int(booking.get('balance_amount')) / 100:.2f}.",
                    booking.get("created_at") or "",
                )
            )

    for job in automation_jobs:
        status = _normalise(job.get("status"))
        if status == "failed":
            critical.append(
                _issue(
                    f"Automation failed: {job.get('step') or 'unknown step'}",
                    "Critical",
                    "Automation",
                    "automation_job",
                    job,
                    "Open Sparkles Autopilot, review the error and retry only after the cause is understood.",
                    "/admin/autopilot",
                    str(job.get("last_error") or "The workflow exhausted its retries."),
                    job.get("updated_at") or "",
                )
            )
        elif status == "retrying":
            attention.append(
                _issue(
                    f"Automation is retrying: {job.get('step') or 'unknown step'}",
                    "Needs Attention",
                    "Automation",
                    "automation_job",
                    job,
                    "Monitor the retry in Sparkles Autopilot; intervene only if it fails.",
                    "/admin/autopilot",
                    f"Attempt {job.get('attempts') or 0} of {job.get('max_attempts') or 0}.",
                    job.get("updated_at") or "",
                )
            )

    for alert in automation_alerts:
        is_critical = _normalise(alert.get("level")) in {"critical", "error", "failed"}
        target = critical if is_critical else attention
        target.append(
            _issue(
                str(alert.get("title") or "Automation needs attention"),
                "Critical" if is_critical else "Needs Attention",
                "Automation",
                "automation_alert",
                alert,
                "Open Sparkles Autopilot and follow the recommended action in the alert.",
                "/admin/autopilot",
                str(alert.get("detail") or ""),
                alert.get("created_at") or "",
            )
        )

    for email in email_logs:
        if _normalise(email.get("status")) not in {"failed", "error", "rejected", "bounced"}:
            continue
        if email.get("created_at") and str(email.get("created_at")) < seven_days_ago:
            continue
        attention.append(
            _issue(
                f"Email delivery failed: {email.get('subject') or 'Sparkles email'}",
                "Needs Attention",
                "Email",
                "email",
                email,
                "Open Automations, review the provider error and retry the related workflow if required.",
                "/admin/automations",
                str(email.get("error") or "The email provider did not confirm delivery."),
                email.get("created_at") or "",
            )
        )

    new_applicants = [
        applicant
        for applicant in applicants
        if _normalise(applicant.get("status")) in {"new", "applied", "review"}
    ]
    strong_applicants = [
        applicant
        for applicant in new_applicants
        if _normalise(applicant.get("ai_recommendation")) in {"excellent", "good"}
    ]
    if strong_applicants:
        suggestions.append(
            _issue(
                f"Review {len(strong_applicants)} recommended cleaner applicant(s)",
                "Suggested Action",
                "Recruitment",
                "cleaner_applicant",
                strong_applicants[0],
                "Review each applicant manually before approving or rejecting them.",
                "/admin/cleaner-applicants",
                "Sparkles AI marked these applicants Excellent or Good; no decision has been automated.",
                strong_applicants[0].get("updated_at") or strong_applicants[0].get("created_at") or "",
            )
        )
    elif new_applicants:
        suggestions.append(
            _issue(
                f"{len(new_applicants)} cleaner applicant(s) await review",
                "Suggested Action",
                "Recruitment",
                "cleaner_applicant",
                new_applicants[0],
                "Review applicants when capacity allows; approval remains an owner decision.",
                "/admin/cleaner-applicants",
                "No cleaner account will be created until the owner approves an applicant.",
                new_applicants[0].get("updated_at") or new_applicants[0].get("created_at") or "",
            )
        )
    if available_cleaners == 0 and _as_int(cards.get("today_bookings")) > 0:
        attention.append(
            OperationsIssue(
                title="No activated cleaner appears available today",
                severity="Needs Attention",
                category="Cleaner",
                related_record={"type": "cleaner", "id": None, "reference": today_s},
                recommended_action="Check today's cleaner availability and assigned jobs.",
                admin_url="/admin/cleaners",
                detail="Availability is estimated from active accounts, saved availability and today's active jobs.",
                occurred_at=local_now.isoformat(),
            )
        )
    elif available_cleaners < 2:
        suggestions.append(
            OperationsIssue(
                title="Cleaner capacity is currently limited",
                severity="Suggested Action",
                category="Cleaner",
                related_record={"type": "cleaner", "id": None, "reference": str(available_cleaners)},
                recommended_action="Continue reviewing suitable cleaner applicants to protect booking capacity.",
                admin_url="/admin/cleaner-applicants",
                detail=f"{available_cleaners} activated cleaner(s) appear available today.",
                occurred_at=local_now.isoformat(),
            )
        )

    for event in booking_timeline:
        activity.append(
            _issue(
                str(event.get("event") or "Booking updated"),
                "Informational",
                "Booking",
                "booking",
                {"id": event.get("booking_id"), "reference": f"Booking #{event.get('booking_id')}"},
                "No action required unless the timeline entry indicates a problem.",
                "/admin/bookings",
                str(event.get("detail") or ""),
                event.get("created_at") or "",
            )
        )
    for payment in successful_payments:
        activity.append(
            _issue(
                f"{str(payment.get('payment_type') or 'Payment').title()} payment received",
                "Informational",
                "Payment",
                "payment",
                payment,
                "No action required.",
                "/admin/bookings",
                f"£{_as_int(payment.get('amount')) / 100:.2f} recorded successfully.",
                payment.get("created_at") or "",
            )
        )
    for event in applicant_timeline:
        activity.append(
            _issue(
                str(event.get("event") or "Cleaner applicant updated"),
                "Informational",
                "Recruitment",
                "cleaner_applicant",
                {"id": event.get("applicant_id"), "reference": f"Applicant #{event.get('applicant_id')}"},
                "No action required unless the applicant now needs review.",
                "/admin/cleaner-applicants",
                str(event.get("detail") or ""),
                event.get("created_at") or "",
            )
        )
    for log in automation_logs:
        activity.append(
            _issue(
                str(log.get("event") or "Automation activity"),
                "Informational",
                "Automation",
                "automation_log",
                log,
                "No action required unless Sparkles Autopilot shows an unresolved alert.",
                "/admin/autopilot",
                str(log.get("detail") or ""),
                log.get("created_at") or "",
            )
        )

    if inspection_errors:
        critical.append(
            OperationsIssue(
                title="Operations Manager could not inspect all business records",
                severity="Critical",
                category="System",
                related_record={"type": "system", "id": None, "reference": "operations-manager"},
                recommended_action="Open Diagnostics and confirm all required PostgreSQL tables are available.",
                admin_url="/admin/diagnostics",
                detail=f"{len(inspection_errors)} read-only data source(s) could not be inspected.",
                occurred_at=local_now.isoformat(),
            )
        )

    critical = _dedupe(critical)[:12]
    attention = _dedupe(attention)[:12]
    suggestions = _dedupe(suggestions)[:8]
    activity = sorted(
        _dedupe(activity),
        key=lambda item: item.occurred_at or "",
        reverse=True,
    )[:12]

    if critical:
        health_status = "Critical"
        health_message = "Immediate owner attention is required."
    elif attention:
        health_status = "Needs Attention"
        health_message = "The business is running, with a small number of items to review."
    else:
        health_status = "Healthy"
        health_message = "No urgent action required."
    health_score = max(0, 100 - len(critical) * 25 - len(attention) * 7)
    health = HealthSummary(
        status=health_status,
        score=health_score,
        message=health_message,
        critical_count=len(critical),
        needs_attention_count=len(attention),
        suggested_action_count=len(suggestions),
        updated_at=local_now.isoformat(),
    )

    return {
        "business_health": health.to_dict(),
        "summary": {
            "today_revenue": _as_int(cards.get("revenue_today")),
            "bookings_today": _as_int(cards.get("today_bookings")),
            "available_cleaners": available_cleaners,
            "jobs_awaiting_assignment": _as_int(cards.get("waiting_assignment")),
            "outstanding_balances": _as_int(cards.get("outstanding_balances")),
            "customers_inspected": len(customers),
        },
        "groups": {
            "critical": [issue.to_dict() for issue in critical],
            "needs_attention": [issue.to_dict() for issue in attention],
            "suggested_actions": [issue.to_dict() for issue in suggestions],
            "recent_activity": [issue.to_dict() for issue in activity],
        },
        "read_only": True,
        "as_of": local_now.isoformat(),
    }
