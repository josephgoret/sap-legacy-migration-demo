"""
Tests for the Employee Sync service.

Validates functional equivalence between the PeopleCode EMP_SYNC_SUB
Integration Broker handler and the migrated Python implementation.
"""

from datetime import date
from decimal import Decimal

import pytest

from python_target.employee_sync.models import (
    CompensationData,
    EmployeeSyncMessage,
    JobData,
    ProcessingStatus,
    SyncResult,
    TransactionType,
)
from python_target.employee_sync.service import (
    build_target_payload,
    process_message_batch,
    process_single_message,
    validate_message,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def hire_message() -> EmployeeSyncMessage:
    """A valid HIRE message matching a typical Integration Broker message."""
    return EmployeeSyncMessage(
        message_id="MSG-001",
        message_type="EMP_SYNC",
        sender_system="PS-PROD",
        transaction_type=TransactionType.HIRE,
        employee_id="EMP100",
        first_name="Jane",
        last_name="Smith",
        job=JobData(
            business_unit="US001",
            department_id="10100",
            job_code="DEV02",
            position_number="00012345",
            empl_status="A",
            action="HIR",
            action_reason="NEW",
            effective_date=date(2024, 7, 1),
        ),
        compensation=CompensationData(
            annual_rate=Decimal("95000"),
            currency="USD",
        ),
    )


@pytest.fixture()
def transfer_message() -> EmployeeSyncMessage:
    return EmployeeSyncMessage(
        message_id="MSG-002",
        transaction_type=TransactionType.TRANSFER,
        employee_id="EMP200",
        first_name="Bob",
        last_name="Jones",
        job=JobData(
            business_unit="US001",
            department_id="10200",
            job_code="MGR01",
            effective_date=date(2024, 8, 1),
            action="XFR",
            action_reason="PROMO",
        ),
    )


@pytest.fixture()
def termination_message() -> EmployeeSyncMessage:
    return EmployeeSyncMessage(
        message_id="MSG-003",
        transaction_type=TransactionType.TERMINATION,
        employee_id="EMP300",
        first_name="Alice",
        last_name="Davis",
        job=JobData(
            business_unit="US001",
            empl_status="T",
            action="TER",
            action_reason="RES",
            effective_date=date(2024, 9, 15),
        ),
    )


# ---------------------------------------------------------------------------
# validate_message — mirrors PeopleCode validation checks
# ---------------------------------------------------------------------------


class TestValidateMessage:

    def test_valid_hire_passes(self, hire_message):
        errors = validate_message(hire_message)
        assert errors == []

    def test_missing_employee_id(self, hire_message):
        """PeopleCode: If None(&emplId) -> &errorMessages = "Missing EMPLID"."""
        hire_message.employee_id = ""
        errors = validate_message(hire_message)
        assert any("EMPLID" in e for e in errors)

    def test_missing_business_unit(self, hire_message):
        """PeopleCode: If None(&businessUnit) -> error."""
        hire_message.job.business_unit = ""
        errors = validate_message(hire_message)
        assert any("BUSINESS_UNIT" in e for e in errors)

    def test_hire_requires_name(self, hire_message):
        """PeopleCode: HIRE requires FIRST_NAME and LAST_NAME."""
        hire_message.first_name = ""
        errors = validate_message(hire_message)
        assert any("FIRST_NAME" in e for e in errors)

    def test_hire_requires_job_code(self, hire_message):
        """PeopleCode: HIRE requires JOBCODE."""
        hire_message.job.job_code = ""
        errors = validate_message(hire_message)
        assert any("JOBCODE" in e for e in errors)

    def test_transfer_requires_at_least_one_change(self):
        """PeopleCode: TRANSFER requires DEPTID, JOBCODE, or POSITION_NBR."""
        msg = EmployeeSyncMessage(
            message_id="MSG-X",
            transaction_type=TransactionType.TRANSFER,
            employee_id="EMP999",
            job=JobData(
                business_unit="US001",
                department_id="",
                job_code="",
                position_number="",
                effective_date=date(2024, 8, 1),
            ),
        )
        errors = validate_message(msg)
        assert any("TRANSFER" in e for e in errors)

    def test_termination_requires_action(self):
        """PeopleCode: TERMINATION requires ACTION."""
        msg = EmployeeSyncMessage(
            message_id="MSG-X",
            transaction_type=TransactionType.TERMINATION,
            employee_id="EMP999",
            job=JobData(
                business_unit="US001",
                action="",
                effective_date=date(2024, 9, 1),
            ),
        )
        errors = validate_message(msg)
        assert any("ACTION" in e for e in errors)

    def test_valid_transfer_passes(self, transfer_message):
        errors = validate_message(transfer_message)
        assert errors == []

    def test_valid_termination_passes(self, termination_message):
        errors = validate_message(termination_message)
        assert errors == []


# ---------------------------------------------------------------------------
# build_target_payload — mirrors PeopleCode target XML building
# ---------------------------------------------------------------------------


class TestBuildTargetPayload:

    def test_hire_payload(self, hire_message):
        """PeopleCode: Hire -> Workday Hire_Employee operation."""
        payload = build_target_payload(hire_message)
        assert payload["operation"] == "Hire_Employee"
        assert payload["employee_id"] == "EMP100"
        assert payload["legal_name_first"] == "Jane"
        assert payload["legal_name_last"] == "Smith"
        assert payload["business_unit"] == "US001"
        assert payload["job_profile"] == "DEV02"

    def test_rehire_payload(self):
        """PeopleCode: Rehire -> Hire_Employee with rehire_flag."""
        msg = EmployeeSyncMessage(
            message_id="MSG-R",
            transaction_type=TransactionType.REHIRE,
            employee_id="EMP400",
            first_name="Carol",
            last_name="White",
            job=JobData(
                business_unit="US001",
                department_id="10100",
                job_code="DEV02",
                effective_date=date(2024, 10, 1),
            ),
        )
        payload = build_target_payload(msg)
        assert payload["operation"] == "Hire_Employee"
        assert payload["rehire_flag"] is True

    def test_transfer_payload(self, transfer_message):
        """PeopleCode: Transfer -> Workday Change_Job operation."""
        payload = build_target_payload(transfer_message)
        assert payload["operation"] == "Change_Job"
        assert payload["department"] == "10200"
        assert payload["reason"] == "PROMO"

    def test_termination_payload(self, termination_message):
        """PeopleCode: Termination -> Workday Terminate_Employee."""
        payload = build_target_payload(termination_message)
        assert payload["operation"] == "Terminate_Employee"
        assert payload["termination_action"] == "TER"
        assert payload["termination_reason"] == "RES"


# ---------------------------------------------------------------------------
# process_single_message — mirrors PeopleCode per-message processing
# ---------------------------------------------------------------------------


class TestProcessSingleMessage:

    def test_successful_hire(self, hire_message):
        """PeopleCode: CommitWork() -> &processingStatus = "SUCCESS"."""
        result = process_single_message(hire_message)

        assert result.status == ProcessingStatus.SUCCESS
        assert result.target_employee_id == "EMP100"
        assert result.error_messages == []

    def test_validation_failure(self, hire_message):
        """PeopleCode: Validation fails -> &processingStatus = "ERROR"."""
        hire_message.employee_id = ""
        result = process_single_message(hire_message)

        assert result.status == ProcessingStatus.ERROR
        assert len(result.error_messages) > 0


# ---------------------------------------------------------------------------
# process_message_batch — mirrors processing multiple IB messages
# ---------------------------------------------------------------------------


class TestProcessMessageBatch:

    def test_mixed_batch(self, hire_message, termination_message):
        """Process batch with mix of valid and invalid messages."""
        invalid_msg = EmployeeSyncMessage(
            message_id="MSG-BAD",
            transaction_type=TransactionType.HIRE,
            employee_id="",  # Invalid: missing EMPLID
            job=JobData(
                business_unit="US001",
                job_code="DEV02",
                effective_date=date(2024, 7, 1),
            ),
        )

        messages = [hire_message, invalid_msg, termination_message]
        batch_result = process_message_batch(messages)

        assert batch_result.total_processed == 3
        assert batch_result.successful == 2
        assert batch_result.failed == 1
        assert batch_result.results[1].status == ProcessingStatus.ERROR

    def test_empty_batch(self):
        batch_result = process_message_batch([])
        assert batch_result.total_processed == 0
        assert batch_result.successful == 0
        assert batch_result.failed == 0
