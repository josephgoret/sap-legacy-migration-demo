"""
Tests for the Employee Status Report service.

Validates functional equivalence between the PeopleCode HR_EMP_STATUS
Application Engine and the migrated Python implementation. Each test maps
to a specific piece of PeopleCode logic with comments referencing the original code.
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from python_target.employee_status_report.models import (
    EmployeeRecord,
    ReportFilters,
    StatusCategory,
)
from python_target.employee_status_report.service import (
    build_summary,
    calculate_years_of_service,
    determine_status_category,
    filter_by_status,
    generate_employee_status_report,
)


# ---------------------------------------------------------------------------
# determine_status_category — mirrors PeopleCode Evaluate on &emplStatus
# ---------------------------------------------------------------------------


class TestDetermineStatusCategory:
    """Tests for status categorization matching PeopleCode Evaluate block."""

    def test_active_employee(self):
        """PeopleCode: When = "A" -> &statusCategory = "ACTIVE"."""
        assert determine_status_category("A", "A") == StatusCategory.ACTIVE

    def test_leave_of_absence(self):
        """PeopleCode: When = "L" -> &statusCategory = "LOA"."""
        assert determine_status_category("L", "A") == StatusCategory.LOA

    def test_paid_leave(self):
        """PeopleCode: When = "P" -> &statusCategory = "LOA"."""
        assert determine_status_category("P", "A") == StatusCategory.LOA

    def test_terminated(self):
        """PeopleCode: When = "T" -> &statusCategory = "TERMINATED"."""
        assert determine_status_category("T", "I") == StatusCategory.TERMINATED

    def test_deceased(self):
        """PeopleCode: When = "D" -> &statusCategory = "TERMINATED"."""
        assert determine_status_category("D", "I") == StatusCategory.TERMINATED

    def test_retired(self):
        """PeopleCode: When = "R" -> &statusCategory = "RETIRED"."""
        assert determine_status_category("R", "I") == StatusCategory.RETIRED

    def test_unknown_status_defaults_to_loa(self):
        """PeopleCode: When-Other -> &statusCategory = "LOA"."""
        assert determine_status_category("S", "A") == StatusCategory.LOA
        assert determine_status_category("X", "A") == StatusCategory.LOA

    def test_inactive_hr_status_overrides_active_to_terminated(self):
        """PeopleCode: If &hrStatus = "I" And &statusCategory = "ACTIVE"."""
        assert determine_status_category("A", "I") == StatusCategory.TERMINATED

    def test_inactive_hr_status_does_not_override_loa(self):
        """Override only applies when category would be ACTIVE."""
        assert determine_status_category("L", "I") == StatusCategory.LOA

    def test_inactive_hr_status_does_not_override_retired(self):
        """Override only applies when category would be ACTIVE."""
        assert determine_status_category("R", "I") == StatusCategory.RETIRED


# ---------------------------------------------------------------------------
# calculate_years_of_service — mirrors PeopleCode year calculation
# ---------------------------------------------------------------------------


class TestCalculateYearsOfService:

    def test_normal_calculation(self):
        """PeopleCode: DatePart(Year, &today) - DatePart(Year, &hireDate)."""
        result = calculate_years_of_service(date(2015, 6, 1), date(2024, 1, 1))
        assert result == 9

    def test_no_hire_date_returns_zero(self):
        """PeopleCode: If None(&hireDate) -> &yearsOfService = 0."""
        assert calculate_years_of_service(None, date(2024, 1, 1)) == 0

    def test_same_year(self):
        result = calculate_years_of_service(date(2024, 3, 15), date(2024, 12, 1))
        assert result == 0


# ---------------------------------------------------------------------------
# filter_by_status — mirrors PeopleCode Step: Filter
# ---------------------------------------------------------------------------


class TestFilterByStatus:

    @pytest.fixture()
    def sample_items(self) -> list[EmployeeRecord]:
        def make_item(category: StatusCategory) -> EmployeeRecord:
            return EmployeeRecord(
                employee_id="EMP001",
                name="Test Employee",
                business_unit="US001",
                department_id="10100",
                job_code="MGR01",
                empl_status="A",
                status_category=category,
                annual_rate=Decimal("75000"),
                years_of_service=5,
            )

        return [
            make_item(StatusCategory.ACTIVE),
            make_item(StatusCategory.LOA),
            make_item(StatusCategory.TERMINATED),
            make_item(StatusCategory.RETIRED),
        ]

    def test_default_filters_show_active_and_loa(self, sample_items):
        """Default run control: SHOW_ACTIVE=Y, SHOW_LOA=Y, others=N."""
        filters = ReportFilters(business_unit="US001")
        result = filter_by_status(sample_items, filters)
        assert len(result) == 2
        categories = {r.status_category for r in result}
        assert categories == {StatusCategory.ACTIVE, StatusCategory.LOA}

    def test_show_only_terminated(self, sample_items):
        """PeopleCode: When = "TERMINATED" If &showTerminated = "Y"."""
        filters = ReportFilters(
            business_unit="US001",
            show_active=False,
            show_loa=False,
            show_terminated=True,
            show_retired=False,
        )
        result = filter_by_status(sample_items, filters)
        assert len(result) == 1
        assert result[0].status_category == StatusCategory.TERMINATED

    def test_show_all(self, sample_items):
        filters = ReportFilters(
            business_unit="US001",
            show_active=True,
            show_loa=True,
            show_terminated=True,
            show_retired=True,
        )
        result = filter_by_status(sample_items, filters)
        assert len(result) == 4


# ---------------------------------------------------------------------------
# build_summary — mirrors PeopleCode Step: Summary
# ---------------------------------------------------------------------------


class TestBuildSummary:

    def test_summary_counts(self):
        """Verify aggregate counts match PeopleCode summary loop."""
        items = [
            EmployeeRecord(
                employee_id="E001",
                name="Active Employee",
                business_unit="US001",
                department_id="10100",
                job_code="MGR01",
                empl_status="A",
                status_category=StatusCategory.ACTIVE,
                annual_rate=Decimal("80000"),
                is_headcount=True,
            ),
            EmployeeRecord(
                employee_id="E002",
                name="LOA Employee",
                business_unit="US001",
                department_id="10200",
                job_code="ANL01",
                empl_status="L",
                status_category=StatusCategory.LOA,
                annual_rate=Decimal("65000"),
                is_headcount=True,
            ),
            EmployeeRecord(
                employee_id="E003",
                name="Terminated Employee",
                business_unit="US001",
                department_id="10100",
                job_code="MGR01",
                empl_status="T",
                status_category=StatusCategory.TERMINATED,
                annual_rate=Decimal("90000"),
                is_headcount=False,
            ),
        ]

        summary = build_summary(items)

        assert summary.active_count == 1
        assert summary.loa_count == 1
        assert summary.terminated_count == 1
        assert summary.retired_count == 0
        assert summary.total_headcount == 2
        assert summary.total_annual_compensation == Decimal("235000")


# ---------------------------------------------------------------------------
# generate_employee_status_report — end-to-end integration test
# ---------------------------------------------------------------------------


class TestGenerateEmployeeStatusReport:

    def test_full_report_generation(self):
        """End-to-end test matching the full Application Engine flow."""
        raw_data = [
            {
                "employee_id": "EMP001",
                "name": "Smith, John",
                "business_unit": "US001",
                "department_id": "10100",
                "department_descr": "Engineering",
                "job_code": "MGR01",
                "job_title": "Manager",
                "empl_status": "A",
                "hr_status": "A",
                "hire_date": "2015-03-15",
                "last_action_date": date.today().isoformat(),
                "annual_rate": 95000,
            },
            {
                "employee_id": "EMP002",
                "name": "Jones, Sarah",
                "business_unit": "US001",
                "department_id": "10200",
                "department_descr": "Finance",
                "job_code": "ANL01",
                "job_title": "Analyst",
                "empl_status": "L",
                "hr_status": "A",
                "hire_date": "2018-07-01",
                "last_action_date": date.today().isoformat(),
                "annual_rate": 72000,
            },
            {
                "employee_id": "EMP003",
                "name": "Davis, Mike",
                "business_unit": "US001",
                "department_id": "10100",
                "department_descr": "Engineering",
                "job_code": "DEV02",
                "job_title": "Developer",
                "empl_status": "T",
                "hr_status": "I",
                "hire_date": "2010-01-10",
                "termination_date": "2023-06-30",
                "last_action_date": "2023-06-30",
                "annual_rate": 85000,
                "action": "TER",
                "action_reason": "RES",
            },
        ]

        filters = ReportFilters(
            business_unit="US001",
            show_active=True,
            show_loa=True,
            show_terminated=True,
            show_retired=True,
        )

        report = generate_employee_status_report(raw_data, filters)

        assert report.total_items == 3
        assert report.summary.active_count == 1
        assert report.summary.loa_count == 1
        assert report.summary.terminated_count == 1
        # Items sorted: active first, then LOA, then terminated
        assert report.items[0].status_category == StatusCategory.ACTIVE

    def test_default_filters_exclude_terminated(self):
        """Default filters show Active + LOA only — matches PeopleCode defaults."""
        raw_data = [
            {
                "employee_id": "EMP001",
                "name": "Active Employee",
                "business_unit": "US001",
                "department_id": "10100",
                "job_code": "MGR01",
                "empl_status": "A",
                "hr_status": "A",
                "annual_rate": 80000,
            },
            {
                "employee_id": "EMP002",
                "name": "Terminated Employee",
                "business_unit": "US001",
                "department_id": "10100",
                "job_code": "MGR01",
                "empl_status": "T",
                "hr_status": "I",
                "annual_rate": 70000,
            },
        ]

        filters = ReportFilters(business_unit="US001")
        report = generate_employee_status_report(raw_data, filters)

        assert report.total_items == 1
        assert report.items[0].employee_id == "EMP001"

    def test_report_with_empty_data(self):
        """Matches PeopleCode: If &rsEmployees.ActiveRowCount = 0."""
        filters = ReportFilters(
            business_unit="US001",
            show_active=True,
            show_loa=True,
            show_terminated=True,
            show_retired=True,
        )
        report = generate_employee_status_report([], filters)
        assert report.total_items == 0
        assert report.items == []

    def test_recently_actioned_flag(self):
        """PeopleCode: &daysSinceAction <= &staleDays -> &recentlyActioned = "Y"."""
        raw_data = [
            {
                "employee_id": "EMP001",
                "name": "Recent Action",
                "business_unit": "US001",
                "department_id": "10100",
                "job_code": "MGR01",
                "empl_status": "A",
                "hr_status": "A",
                "last_action_date": date.today().isoformat(),
                "annual_rate": 80000,
            },
            {
                "employee_id": "EMP002",
                "name": "Stale Action",
                "business_unit": "US001",
                "department_id": "10100",
                "job_code": "MGR01",
                "empl_status": "A",
                "hr_status": "A",
                "last_action_date": (date.today() - timedelta(days=200)).isoformat(),
                "annual_rate": 75000,
            },
        ]

        filters = ReportFilters(business_unit="US001", stale_days=180)
        report = generate_employee_status_report(raw_data, filters)

        assert report.items[0].recently_actioned is True
        assert report.items[1].recently_actioned is False
