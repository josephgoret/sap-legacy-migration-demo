"""
Employee Sync Service — migrated from EMP_SYNC_SUB.

Original PeopleCode: Integration Broker subscription handler parsing XML messages
                     for employee hire/transfer/termination, validating, and
                     mapping to target system (Workday) API calls.
Target:              Event-driven Python service consuming JSON messages
                     from a queue and calling the target system.

Migration notes:
- %IntBroker.GetMessage() / &MSG.GetXmlDoc() -> JSON deserialization
- PeopleCode XmlNode.FindNode() -> Pydantic model field access
- PeopleCode Evaluate on &transactionType -> match/case on TransactionType enum
- PeopleCode CommitWork/RollbackWork -> transaction management
- PeopleCode %IntBroker.Publish(response) -> SyncResult return
"""

import logging

from .models import (
    EmployeeSyncMessage,
    ProcessingStatus,
    SyncBatchResult,
    SyncResult,
    TransactionType,
)

logger = logging.getLogger(__name__)


def validate_message(message: EmployeeSyncMessage) -> list[str]:
    """Validate inbound employee sync message.

    Replicates PeopleCode validation checks:
    - EMPLID is required
    - TransactionType must be known
    - BUSINESS_UNIT is required
    - EFFDT is required (enforced by Pydantic)
    - HIRE requires FIRST_NAME, LAST_NAME, JOBCODE
    - TRANSFER requires at least one of DEPTID, JOBCODE, POSITION_NBR
    - TERMINATION requires ACTION
    """
    errors: list[str] = []

    if not message.employee_id:
        errors.append("Missing EMPLID")

    if not message.job.business_unit:
        errors.append("Missing BUSINESS_UNIT")

    if message.transaction_type == TransactionType.HIRE:
        if not message.first_name or not message.last_name:
            errors.append("HIRE requires FIRST_NAME and LAST_NAME")
        if not message.job.job_code:
            errors.append("HIRE requires JOBCODE")

    elif message.transaction_type == TransactionType.REHIRE:
        if not message.first_name or not message.last_name:
            errors.append("REHIRE requires FIRST_NAME and LAST_NAME")

    elif message.transaction_type == TransactionType.TRANSFER:
        has_change = (
            message.job.department_id
            or message.job.job_code
            or message.job.position_number
        )
        if not has_change:
            errors.append(
                "TRANSFER requires at least one of DEPTID, JOBCODE, or POSITION_NBR"
            )

    elif message.transaction_type == TransactionType.TERMINATION:
        if not message.job.action:
            errors.append("TERMINATION requires ACTION")

    return errors


def build_target_payload(message: EmployeeSyncMessage) -> dict:
    """Build target system (Workday) payload from the parsed message.

    Replaces PeopleCode Evaluate block that builds &targetXml for each
    transaction type: Hire_Employee, Change_Job, Terminate_Employee.
    """
    job = message.job

    # Common fields across all transaction types
    payload: dict = {
        "employee_id": message.employee_id,
        "effective_date": job.effective_date.isoformat(),
    }

    if message.transaction_type == TransactionType.HIRE:
        payload["operation"] = "Hire_Employee"
        payload["legal_name_first"] = message.first_name
        payload["legal_name_last"] = message.last_name
        payload["hire_date"] = job.effective_date.isoformat()
        payload["business_unit"] = job.business_unit
        payload["department"] = job.department_id
        payload["job_profile"] = job.job_code
        payload["position"] = job.position_number
        payload["annual_rate"] = str(message.compensation.annual_rate)
        payload["currency"] = message.compensation.currency

    elif message.transaction_type == TransactionType.REHIRE:
        payload["operation"] = "Hire_Employee"
        payload["rehire_flag"] = True
        payload["legal_name_first"] = message.first_name
        payload["legal_name_last"] = message.last_name
        payload["hire_date"] = job.effective_date.isoformat()
        payload["business_unit"] = job.business_unit
        payload["department"] = job.department_id
        payload["job_profile"] = job.job_code

    elif message.transaction_type == TransactionType.TRANSFER:
        payload["operation"] = "Change_Job"
        payload["department"] = job.department_id
        payload["job_profile"] = job.job_code
        payload["position"] = job.position_number
        payload["reason"] = job.action_reason

    elif message.transaction_type == TransactionType.TERMINATION:
        payload["operation"] = "Terminate_Employee"
        payload["termination_date"] = job.effective_date.isoformat()
        payload["termination_action"] = job.action
        payload["termination_reason"] = job.action_reason

    return payload


def process_single_message(message: EmployeeSyncMessage) -> SyncResult:
    """Process a single inbound employee sync message.

    Replaces the main body of PeopleCode EMP_SYNC.OnNotify handler.
    Validates, builds target payload, and simulates target system call.
    """
    errors = validate_message(message)
    if errors:
        logger.warning(
            "Validation failed for message %s: %s", message.message_id, errors
        )
        return SyncResult(
            message_id=message.message_id,
            status=ProcessingStatus.ERROR,
            transaction_type=message.transaction_type,
            employee_id=message.employee_id,
            error_messages=errors,
        )

    try:
        payload = build_target_payload(message)
        # In production: call Workday API with payload
        # Replaces PeopleCode: CallTargetSystem(&targetXml) + CommitWork()
        target_emp_id = _call_target_system(payload)

        logger.info(
            "Employee %s %s processed (message %s). Target ID: %s",
            message.employee_id,
            message.transaction_type.value.lower(),
            message.message_id,
            target_emp_id,
        )

        return SyncResult(
            message_id=message.message_id,
            status=ProcessingStatus.SUCCESS,
            transaction_type=message.transaction_type,
            employee_id=message.employee_id,
            target_employee_id=target_emp_id,
        )

    except Exception as exc:
        # Replaces PeopleCode: RollbackWork() in catch block
        logger.error(
            "Target system error for message %s: %s", message.message_id, exc
        )
        return SyncResult(
            message_id=message.message_id,
            status=ProcessingStatus.ERROR,
            transaction_type=message.transaction_type,
            employee_id=message.employee_id,
            error_messages=[str(exc)],
        )


def process_message_batch(
    messages: list[EmployeeSyncMessage],
) -> SyncBatchResult:
    """Process a batch of inbound messages.

    Each message is processed independently, matching the PeopleCode pattern
    where each Integration Broker message is handled in its own transaction.
    """
    results = [process_single_message(msg) for msg in messages]
    successful = sum(1 for r in results if r.status == ProcessingStatus.SUCCESS)
    failed = sum(1 for r in results if r.status == ProcessingStatus.ERROR)

    return SyncBatchResult(
        total_processed=len(results),
        successful=successful,
        failed=failed,
        results=results,
    )


def _call_target_system(payload: dict) -> str:
    """Simulate calling the target system (Workday) API.

    In production, this would POST to the Workday SOAP/REST endpoint.
    For the demo, returns the employee_id as the target system ID.

    Replaces PeopleCode: &targetEmpId = CallTargetSystem(&targetXml)
    """
    return payload["employee_id"]
