"""
Order Credit Check Service — migrated from ZCL_IM_ORDER_CREDIT_CHECK.

Original ABAP: BAdI implementation (ZBADI_ORDER_CREDIT~CHECK_CREDIT) run when
               a sales order is saved, reading KNKK/VBAK/VBAP/LIKP/LIPS/BSID.
Target:        Service layer module callable from the order save pipeline.

Migration notes:
- BAdI method → module-level function taking pre-fetched aggregates
- Private class methods → module-level helper functions
- AUTHORITY-CHECK → typed exception (auth middleware in production)
- SAP SELECT / SELECT SUM → data warehouse query or ORM aggregate
- ABAP `p LENGTH n DECIMALS 2` assignment → Decimal quantized to 2 places
"""

from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from .models import (
    CreditCheckRequest,
    CreditCheckResult,
    CreditMaster,
    CreditStatus,
    MessageType,
    OpenExposure,
    RiskCategory,
)

DELIVERY_BLOCK = "Z1"

# Tolerance granted above the credit limit, by risk category.
# Matches ABAP METHOD get_limit_tolerance.
LIMIT_TOLERANCE_PCT: dict[str, Decimal] = {
    RiskCategory.LOW: Decimal("10.00"),
    RiskCategory.MEDIUM: Decimal("5.00"),
    RiskCategory.HIGH: Decimal("0.00"),
}

# Overdue days tolerated before the order is blocked, by risk category.
# Matches ABAP METHOD get_overdue_tolerance.
OVERDUE_TOLERANCE_DAYS: dict[str, int] = {
    RiskCategory.LOW: 30,
    RiskCategory.MEDIUM: 15,
    RiskCategory.HIGH: 0,
}

WARNING_THRESHOLD_PCT = Decimal("90")


class AuthorizationError(Exception):
    """Replaces ABAP RAISE authorization_failed."""

    def __init__(self, sales_organization: str) -> None:
        self.sales_organization = sales_organization
        super().__init__(
            f"Authorization failed for sales organization {sales_organization}"
        )


def _to_amount(value: Decimal) -> Decimal:
    """Emulate assignment to an ABAP `p ... DECIMALS 2` field."""
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def get_limit_tolerance(risk_category: str) -> Decimal:
    """Tolerance percentage granted above the credit limit.

    ABAP: METHOD get_limit_tolerance — unknown categories are treated as
    high risk (no tolerance).
    """
    return LIMIT_TOLERANCE_PCT.get(risk_category, Decimal("0.00"))


def get_overdue_tolerance(risk_category: str) -> int:
    """Overdue days tolerated before blocking.

    ABAP: METHOD get_overdue_tolerance — unknown categories are treated as
    high risk (no tolerance).
    """
    return OVERDUE_TOLERANCE_DAYS.get(risk_category, 0)


def calculate_exposure(
    credit: CreditMaster,
    open_items: OpenExposure,
    order_value: Decimal,
) -> Decimal:
    """Total credit exposure including the order being saved.

    ABAP: METHOD calculate_exposure
      rv_total = skfor + ssobl + open_order_value + open_delivery_value
               + iv_order_value
    """
    return _to_amount(
        credit.open_receivables
        + credit.special_liability
        + open_items.open_order_value
        + open_items.open_delivery_value
        + order_value
    )


def check_credit(
    request: CreditCheckRequest,
    credit: Optional[CreditMaster],
    open_items: OpenExposure,
) -> CreditCheckResult:
    """Main credit check — replaces the BAdI method body.

    Args:
        request:    Customer, credit control area, sales org, order value.
        credit:     Credit master record (KNKK). None if no record exists.
        open_items: Pre-aggregated open orders, deliveries and overdue items.

    Returns:
        CreditCheckResult with status, reason code and exposure figures.

    Raises:
        AuthorizationError: Replaces ABAP RAISE authorization_failed. The
            caller (auth middleware) performs the check; kept here so the
            service contract matches the ABAP interface.
    """
    # No credit master record — maps to ABAP: IF sy-subrc <> 0 after SELECT knkk
    if credit is None:
        return CreditCheckResult(
            status=CreditStatus.BLOCK,
            reason_code="NO_CREDIT_MASTER",
            message_type=MessageType.ERROR,
            message_text=(
                f"No credit master record for customer {request.customer_number} "
                f"in area {request.credit_control_area}"
            ),
            delivery_block=DELIVERY_BLOCK,
        )

    # Central credit block — maps to ABAP: IF ls_credit-crblb = 'X'.
    if credit.is_blocked:
        return CreditCheckResult(
            status=CreditStatus.BLOCK,
            reason_code="CUSTOMER_BLOCKED",
            message_type=MessageType.ERROR,
            message_text=(
                f"Customer {request.customer_number} is blocked for credit reasons"
            ),
            delivery_block=DELIVERY_BLOCK,
        )

    total_exposure = calculate_exposure(credit, open_items, request.order_value)

    # No limit maintained — maps to ABAP: IF ls_credit-klimk <= 0.
    if credit.credit_limit <= 0:
        if credit.risk_category == RiskCategory.LOW:
            return CreditCheckResult(
                status=CreditStatus.PASS,
                reason_code="NO_LIMIT_CHECK",
                message_type=MessageType.SUCCESS,
                message_text=(
                    f"No credit limit maintained for {request.customer_number}; "
                    "check skipped"
                ),
                total_exposure=total_exposure,
            )
        return CreditCheckResult(
            status=CreditStatus.BLOCK,
            reason_code="ZERO_CREDIT_LIMIT",
            message_type=MessageType.ERROR,
            message_text=(
                f"Credit limit is zero for customer {request.customer_number}"
            ),
            total_exposure=total_exposure,
            delivery_block=DELIVERY_BLOCK,
        )

    # Limit evaluation — maps to ABAP effective limit / utilization calculation
    tolerance_pct = get_limit_tolerance(credit.risk_category)
    effective_limit = _to_amount(
        credit.credit_limit * (1 + tolerance_pct / Decimal("100"))
    )
    utilization_pct = _to_amount(total_exposure / credit.credit_limit * Decimal("100"))

    if total_exposure > effective_limit:
        result = CreditCheckResult(
            status=CreditStatus.BLOCK,
            reason_code="LIMIT_EXCEEDED",
            message_type=MessageType.ERROR,
            message_text=(
                f"Credit limit exceeded: exposure {total_exposure} "
                f"above effective limit {effective_limit}"
            ),
            total_exposure=total_exposure,
            effective_limit=effective_limit,
            utilization_pct=utilization_pct,
            delivery_block=DELIVERY_BLOCK,
        )
    elif utilization_pct >= WARNING_THRESHOLD_PCT:
        result = CreditCheckResult(
            status=CreditStatus.WARN,
            reason_code="LIMIT_NEARLY_EXCEEDED",
            message_type=MessageType.WARNING,
            message_text=(
                f"Credit limit {utilization_pct}% utilized for customer "
                f"{request.customer_number}"
            ),
            total_exposure=total_exposure,
            effective_limit=effective_limit,
            utilization_pct=utilization_pct,
        )
    else:
        result = CreditCheckResult(
            status=CreditStatus.PASS,
            reason_code="OK",
            message_type=MessageType.SUCCESS,
            message_text=f"Credit check passed for customer {request.customer_number}",
            total_exposure=total_exposure,
            effective_limit=effective_limit,
            utilization_pct=utilization_pct,
        )

    # Overdue items override a passing or warning result
    # (matches ABAP: IF ls_result-status <> 'B'.)
    if result.status != CreditStatus.BLOCK:
        tolerance_days = get_overdue_tolerance(credit.risk_category)
        if open_items.overdue_amount > 0 and open_items.overdue_days > tolerance_days:
            result.status = CreditStatus.BLOCK
            result.reason_code = "OVERDUE_ITEMS"
            result.message_type = MessageType.ERROR
            result.message_text = (
                f"Overdue items {open_items.overdue_amount} "
                f"({open_items.overdue_days} days) exceed tolerance of "
                f"{tolerance_days} days"
            )
            result.delivery_block = DELIVERY_BLOCK

    return result
