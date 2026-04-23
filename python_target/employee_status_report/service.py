"""
Employee Status Report Service — migrated from HR_EMP_STATUS.

Original PeopleCode: Application Engine program reading from PS_JOB,
                     PS_PERSONAL_DATA, PS_EMPLOYMENT tables
Target:              FastAPI endpoint returning structured JSON with the same
                     business logic (status categorization, filtering, summary).

Migration notes:
- PeopleCode CreateRowset/Fill/SQLExec -> SQL query + dict rows
- PeopleCode Evaluate on EMPL_STATUS -> StatusCategory enum with same mapping
- CSV file output -> JSON response (consumed by frontend dashboard)
- Run Control record -> API query parameters / request body
"""

from datetime import UTC, date, datetime
from decimal import Decimal

from .models import (
    EmployeeRecord,
    EmployeeStatusReportResponse,
    ReportFilters,
    ReportSummary,
    StatusCategory,
)

# Maps PeopleSoft EMPL_STATUS codes to status categories.
# Matches PeopleCode Evaluate block exactly.
_STATUS_MAP: dict[str, StatusCategory] = {
    "A": StatusCategory.ACTIVE,
    "L": StatusCategory.LOA,
    "P": StatusCategory.LOA,
    "T": StatusCategory.TERMINATED,
    "D": StatusCategory.TERMINATED,
    "R": StatusCategory.RETIRED,
}


def determine_status_category(
    empl_status: str,
    hr_status: str,
) -> StatusCategory:
    """Determine employee status category from PeopleSoft status codes.

    Replicates PeopleCode Evaluate on &emplStatus:
    - A -> ACTIVE, L/P -> LOA, T/D -> TERMINATED, R -> RETIRED
    - Override: HR_STATUS='I' with ACTIVE -> TERMINATED (data inconsistency)
    - Unknown codes default to LOA (matches When-Other branch)
    """
    category = _STATUS_MAP.get(empl_status, StatusCategory.LOA)

    # PeopleCode: If &hrStatus = "I" And &statusCategory = "ACTIVE"
    if hr_status == "I" and category == StatusCategory.ACTIVE:
        return StatusCategory.TERMINATED

    return category


def calculate_years_of_service(hire_date: date | None, today: date) -> int:
    """Calculate years of service from hire date.

    Matches PeopleCode: DatePart(Year, &today) - DatePart(Year, &hireDate)
    """
    if hire_date is None:
        return 0
    return today.year - hire_date.year


def filter_by_status(
    items: list[EmployeeRecord], filters: ReportFilters
) -> list[EmployeeRecord]:
    """Apply status category filters — matches PeopleCode Step: Filter."""
    allowed: set[StatusCategory] = set()
    if filters.show_active:
        allowed.add(StatusCategory.ACTIVE)
    if filters.show_loa:
        allowed.add(StatusCategory.LOA)
    if filters.show_terminated:
        allowed.add(StatusCategory.TERMINATED)
    if filters.show_retired:
        allowed.add(StatusCategory.RETIRED)

    return [item for item in items if item.status_category in allowed]


def build_summary(items: list[EmployeeRecord]) -> ReportSummary:
    """Aggregate summary statistics — matches PeopleCode Step: Summary."""
    summary = ReportSummary()

    for item in items:
        if item.status_category == StatusCategory.ACTIVE:
            summary.active_count += 1
        elif item.status_category == StatusCategory.LOA:
            summary.loa_count += 1
        elif item.status_category == StatusCategory.TERMINATED:
            summary.terminated_count += 1
        elif item.status_category == StatusCategory.RETIRED:
            summary.retired_count += 1

        if item.is_headcount:
            summary.total_headcount += 1

        summary.total_annual_compensation += item.annual_rate

    return summary


def generate_employee_status_report(
    raw_data: list[dict],
    filters: ReportFilters,
) -> EmployeeStatusReportResponse:
    """Main orchestrator — replaces PeopleCode Application Engine steps.

    Args:
        raw_data: Rows from the data warehouse query (replaces PeopleCode SQLExec).
                  Each dict has keys matching the source table columns.
        filters:  Run control parameters from the API request.

    Returns:
        Complete report response with items, summary, and metadata.
    """
    today = filters.as_of_date or date.today()
    items: list[EmployeeRecord] = []

    for row in raw_data:
        empl_status = row.get("empl_status", "A")
        hr_status = row.get("hr_status", "A")
        category = determine_status_category(empl_status, hr_status)

        hire_date = row.get("hire_date")
        if isinstance(hire_date, str):
            hire_date = date.fromisoformat(hire_date)

        term_date = row.get("termination_date")
        if isinstance(term_date, str):
            term_date = date.fromisoformat(term_date)

        last_action_date = row.get("last_action_date")
        if isinstance(last_action_date, str):
            last_action_date = date.fromisoformat(last_action_date)

        years = calculate_years_of_service(hire_date, today)

        # Headcount: only Active and LOA — matches PeopleCode headcount flag
        is_headcount = category in (StatusCategory.ACTIVE, StatusCategory.LOA)

        # Recently actioned — matches PeopleCode stale threshold check
        recently_actioned = False
        if last_action_date is not None:
            days_since = (today - last_action_date).days
            recently_actioned = days_since <= filters.stale_days

        item = EmployeeRecord(
            employee_id=row["employee_id"],
            name=row.get("name", ""),
            business_unit=row.get("business_unit", filters.business_unit),
            department_id=row.get("department_id", ""),
            department_descr=row.get("department_descr", ""),
            job_code=row.get("job_code", ""),
            job_title=row.get("job_title", ""),
            empl_status=empl_status,
            hr_status=hr_status,
            status_category=category,
            hire_date=hire_date,
            termination_date=term_date,
            last_action_date=last_action_date,
            action=row.get("action", ""),
            action_reason=row.get("action_reason", ""),
            annual_rate=Decimal(str(row.get("annual_rate", 0))),
            currency=row.get("currency", "USD"),
            years_of_service=years,
            is_headcount=is_headcount,
            recently_actioned=recently_actioned,
        )
        items.append(item)

    # Filter by status category — matches PeopleCode Step: Filter
    items = filter_by_status(items, filters)

    # Sort: status category, then department — matches output ordering
    category_order = {
        StatusCategory.ACTIVE: 1,
        StatusCategory.LOA: 2,
        StatusCategory.TERMINATED: 3,
        StatusCategory.RETIRED: 4,
    }
    items.sort(key=lambda x: (category_order[x.status_category], x.department_id))

    summary = build_summary(items)

    return EmployeeStatusReportResponse(
        generated_at=datetime.now(UTC),
        filters_applied=filters,
        total_items=len(items),
        summary=summary,
        items=items,
    )
