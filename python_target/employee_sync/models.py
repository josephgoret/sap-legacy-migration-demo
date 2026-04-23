"""
Data models for the Employee Sync service.

Migrated from: EMP_SYNC_SUB (Integration Broker Subscription PeopleCode)
Message types: HIRE, TRANSFER, TERMINATION, REHIRE
Source XML:    Header, EmployeeData, JobData, CompensationData, AddressData nodes
"""

from datetime import date
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, Field


class TransactionType(str, Enum):
    """Employee sync transaction types — maps to PeopleCode TransactionType values."""

    HIRE = "HIRE"
    REHIRE = "REHIRE"
    TRANSFER = "TRANSFER"
    TERMINATION = "TERMINATION"


class ProcessingStatus(str, Enum):
    """Processing result for each message."""

    SUCCESS = "success"
    ERROR = "error"


class JobData(BaseModel):
    """Job data from the inbound message — maps to PeopleCode JobData XML node."""

    business_unit: str = Field(description="Business unit (BUSINESS_UNIT)")
    department_id: str = Field(default="", description="Department (DEPTID)")
    job_code: str = Field(default="", description="Job code (JOBCODE)")
    position_number: str = Field(default="", description="Position (POSITION_NBR)")
    empl_status: str = Field(default="A", description="Employee status (EMPL_STATUS)")
    action: str = Field(default="", description="Action code (ACTION)")
    action_reason: str = Field(default="", description="Action reason (ACTION_REASON)")
    effective_date: date = Field(description="Effective date (EFFDT)")


class CompensationData(BaseModel):
    """Compensation data — maps to PeopleCode CompensationData XML node."""

    annual_rate: Decimal = Field(
        default=Decimal("0"), description="Annual rate (ANNUAL_RT)"
    )
    currency: str = Field(default="USD", description="Currency (CURRENCY_CD)")


class AddressData(BaseModel):
    """Address data — maps to PeopleCode AddressData XML node."""

    address1: str = Field(default="", description="Street address (ADDRESS1)")
    city: str = Field(default="", description="City (CITY)")
    state: str = Field(default="", description="State (STATE)")
    postal: str = Field(default="", description="Postal code (POSTAL)")
    country: str = Field(default="", description="Country (COUNTRY)")
    email: str = Field(default="", description="Email address (EMAILID)")
    phone: str = Field(default="", description="Phone number (PHONE)")


class EmployeeSyncMessage(BaseModel):
    """Top-level inbound message — replaces Integration Broker XML message.

    In the original PeopleCode, this was an XML document received via
    %IntBroker.GetMessage() / &MSG.GetXmlDoc(). In the migrated system,
    this is a JSON message received from a message queue.
    """

    message_id: str = Field(
        description="Unique message ID (replaces &MSG.TransactionId)"
    )
    message_type: str = Field(
        default="EMP_SYNC", description="Message type (replaces Header/MessageType)"
    )
    sender_system: str = Field(
        default="UNKNOWN", description="Source system identifier"
    )
    transaction_type: TransactionType = Field(
        description="HIRE, REHIRE, TRANSFER, or TERMINATION"
    )
    employee_id: str = Field(description="Employee ID (EMPLID)")
    first_name: str = Field(default="", description="First name (FIRST_NAME)")
    last_name: str = Field(default="", description="Last name (LAST_NAME)")
    job: JobData = Field(description="Job data")
    compensation: CompensationData = Field(
        default_factory=CompensationData, description="Compensation data"
    )
    address: AddressData | None = Field(
        default=None, description="Address data (optional)"
    )


class SyncResult(BaseModel):
    """Processing result for a single message — replaces IB response XML."""

    message_id: str
    status: ProcessingStatus
    transaction_type: TransactionType
    employee_id: str
    target_employee_id: str | None = Field(
        default=None, description="Employee ID in target system"
    )
    error_messages: list[str] = Field(default_factory=list)


class SyncBatchResult(BaseModel):
    """Batch result — replaces processing multiple IB messages."""

    total_processed: int
    successful: int
    failed: int
    results: list[SyncResult]
