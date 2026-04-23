"""
Data models for the Employee Status Report service.

Migrated from: HR_EMP_STATUS (Application Engine PeopleCode)
Source tables:  PS_JOB, PS_PERSONAL_DATA, PS_EMPLOYMENT, PS_DEPT_TBL, PS_JOBCODE_TBL
"""

from datetime import date, datetime
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, Field


class StatusCategory(str, Enum):
    """Employee status category.

    Maps to PeopleCode Evaluate on EMPL_STATUS:
      'A'       -> ACTIVE
      'L', 'P'  -> LOA
      'T', 'D'  -> TERMINATED
      'R'       -> RETIRED
    """

    ACTIVE = "active"
    LOA = "loa"
    TERMINATED = "terminated"
    RETIRED = "retired"


class ReportFilters(BaseModel):
    """Run control parameters — maps to PeopleCode Record.RUN_CNTL_HR fields."""

    business_unit: str = Field(description="Business unit (BUSINESS_UNIT)")
    department_id: str | None = Field(
        default=None, description="Department filter (DEPTID)"
    )
    as_of_date: date | None = Field(
        default=None, description="Effective date for job data (ASOFDATE)"
    )
    stale_days: int = Field(
        default=180,
        ge=1,
        description="Days since last action to flag as stale (STALE_DAYS)",
    )
    show_active: bool = Field(default=True, description="Include active (SHOW_ACTIVE)")
    show_loa: bool = Field(default=True, description="Include LOA (SHOW_LOA)")
    show_terminated: bool = Field(
        default=False, description="Include terminated (SHOW_TERMINATED)"
    )
    show_retired: bool = Field(
        default=False, description="Include retired (SHOW_RETIRED)"
    )


class EmployeeRecord(BaseModel):
    """Single employee line item — maps to PeopleCode result rowset record."""

    employee_id: str = Field(description="Employee ID (PS_JOB.EMPLID)")
    name: str = Field(description="Display name (PS_PERSONAL_DATA.NAME_DISPLAY)")
    business_unit: str = Field(description="Business unit (PS_JOB.BUSINESS_UNIT)")
    department_id: str = Field(description="Department (PS_JOB.DEPTID)")
    department_descr: str = Field(
        default="", description="Department description (PS_DEPT_TBL.DESCR)"
    )
    job_code: str = Field(description="Job code (PS_JOB.JOBCODE)")
    job_title: str = Field(
        default="", description="Job title (PS_JOBCODE_TBL.DESCR)"
    )
    empl_status: str = Field(
        description="PeopleSoft employee status code (PS_JOB.EMPL_STATUS)"
    )
    hr_status: str = Field(
        default="A", description="HR status A=Active I=Inactive (PS_JOB.HR_STATUS)"
    )
    status_category: StatusCategory = Field(description="Derived status category")
    hire_date: date | None = Field(
        default=None, description="Original hire date (PS_EMPLOYMENT.HIRE_DT)"
    )
    termination_date: date | None = Field(
        default=None, description="Termination date (PS_EMPLOYMENT.TERMINATION_DT)"
    )
    last_action_date: date | None = Field(
        default=None, description="Last effective date (PS_JOB.EFFDT)"
    )
    action: str = Field(default="", description="Last action code (PS_JOB.ACTION)")
    action_reason: str = Field(
        default="", description="Last action reason (PS_JOB.ACTION_REASON)"
    )
    annual_rate: Decimal = Field(
        default=Decimal("0"), description="Annual compensation (PS_JOB.ANNUAL_RT)"
    )
    currency: str = Field(
        default="USD", description="Currency code (PS_JOB.CURRENCY_CD)"
    )
    years_of_service: int = Field(
        default=0, description="Calculated years since hire"
    )
    is_headcount: bool = Field(
        default=True, description="Counts toward headcount (Active + LOA only)"
    )
    recently_actioned: bool = Field(
        default=False,
        description="Action within stale_days threshold",
    )


class ReportSummary(BaseModel):
    """Aggregated summary — added value beyond the original CSV output."""

    active_count: int = 0
    loa_count: int = 0
    terminated_count: int = 0
    retired_count: int = 0
    total_headcount: int = 0
    total_annual_compensation: Decimal = Decimal("0")


class EmployeeStatusReportResponse(BaseModel):
    """Full report response — replaces Application Engine CSV file output."""

    generated_at: datetime
    filters_applied: ReportFilters
    total_items: int
    summary: ReportSummary
    items: list[EmployeeRecord]
