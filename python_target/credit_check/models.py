"""
Data models for the Order Credit Check service.

Migrated from: ZCL_IM_ORDER_CREDIT_CHECK (BAdI implementation)
Source tables:  KNKK, VBAK, VBAP, LIKP, LIPS, BSID
"""

from decimal import Decimal
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class CreditStatus(str, Enum):
    """Check outcome — maps to ABAP ty_check_result-status (P/W/B)."""

    PASS = "P"
    WARN = "W"
    BLOCK = "B"


class MessageType(str, Enum):
    """SAP message type — maps to ABAP ty_check_result-message_type."""

    SUCCESS = "S"
    WARNING = "W"
    ERROR = "E"


class RiskCategory(str, Enum):
    """Credit risk category — maps to KNKK-CTLPC."""

    LOW = "001"
    MEDIUM = "002"
    HIGH = "003"


class CreditMaster(BaseModel):
    """Customer credit master data — maps to ABAP ty_credit_master (KNKK)."""

    customer_number: str = Field(description="Customer number (KUNNR)")
    credit_control_area: str = Field(description="Credit control area (KKBER)")
    credit_limit: Decimal = Field(description="Credit limit (KLIMK)")
    open_receivables: Decimal = Field(
        default=Decimal("0"), description="Open receivables (SKFOR)"
    )
    special_liability: Decimal = Field(
        default=Decimal("0"), description="Special liability (SSOBL)"
    )
    risk_category: str = Field(default="003", description="Risk category (CTLPC)")
    is_blocked: bool = Field(default=False, description="Credit block flag (CRBLB)")
    currency: str = Field(default="USD", description="Credit limit currency (WAERS)")


class OpenExposure(BaseModel):
    """Aggregated open items — maps to ABAP ty_exposure.

    Source: VBAK/VBAP (open orders), LIKP/LIPS (open deliveries),
    BSID (overdue receivables).
    """

    open_order_value: Decimal = Field(
        default=Decimal("0"), description="Sum of open sales order values (VBAP-NETWR)"
    )
    open_delivery_value: Decimal = Field(
        default=Decimal("0"), description="Sum of open delivery values (LIPS-NETWR)"
    )
    overdue_amount: Decimal = Field(
        default=Decimal("0"), description="Sum of uncleared overdue items (BSID-WRBTR)"
    )
    overdue_days: int = Field(
        default=0, description="Days overdue of the oldest open item (SY-DATUM - ZFBDT)"
    )


class CreditCheckRequest(BaseModel):
    """Input parameters — maps to the BAdI method IMPORTING parameters."""

    customer_number: str = Field(description="Customer number (IV_KUNNR)")
    credit_control_area: str = Field(
        default="1000", description="Credit control area (IV_KKBER)"
    )
    sales_organization: str = Field(
        default="1000", description="Sales organization (IV_VKORG)"
    )
    order_value: Decimal = Field(
        description="Net value of the order being saved (IV_ORDER_VALUE)"
    )


class CreditCheckResult(BaseModel):
    """Output — maps to ABAP ty_check_result / ZS_CREDIT_CHECK_RESULT."""

    status: CreditStatus
    reason_code: str = Field(description="Reason code (ty_check_result-reason_code)")
    message_type: MessageType
    message_text: str
    total_exposure: Decimal = Field(
        default=Decimal("0"), description="Receivables + liability + open + current order"
    )
    effective_limit: Decimal = Field(
        default=Decimal("0"), description="Credit limit including risk tolerance"
    )
    utilization_pct: Decimal = Field(
        default=Decimal("0"), description="Exposure as a percentage of the credit limit"
    )
    delivery_block: Optional[str] = Field(
        default=None, description="Delivery block to set on the order (VBAK-LIFSK)"
    )
