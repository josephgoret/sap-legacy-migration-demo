"""
Tests for the Order Credit Check service.

Validates functional equivalence between the ABAP ZCL_IM_ORDER_CREDIT_CHECK
BAdI implementation and the migrated Python implementation.
"""

from decimal import Decimal

import pytest

from python_target.credit_check.models import (
    CreditCheckRequest,
    CreditMaster,
    CreditStatus,
    MessageType,
    OpenExposure,
    RiskCategory,
)
from python_target.credit_check.service import (
    calculate_exposure,
    check_credit,
    get_limit_tolerance,
    get_overdue_tolerance,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def credit_master() -> CreditMaster:
    """Credit master record — represents KNKK for a medium risk customer."""
    return CreditMaster(
        customer_number="0000012345",
        credit_control_area="1000",
        credit_limit=Decimal("100000.00"),
        open_receivables=Decimal("20000.00"),
        special_liability=Decimal("0.00"),
        risk_category=RiskCategory.MEDIUM,
        is_blocked=False,
        currency="USD",
    )


@pytest.fixture()
def open_items() -> OpenExposure:
    """Open orders/deliveries with no overdue items."""
    return OpenExposure(
        open_order_value=Decimal("10000.00"),
        open_delivery_value=Decimal("5000.00"),
        overdue_amount=Decimal("0.00"),
        overdue_days=0,
    )


def make_request(order_value: str) -> CreditCheckRequest:
    return CreditCheckRequest(
        customer_number="0000012345",
        credit_control_area="1000",
        sales_organization="1000",
        order_value=Decimal(order_value),
    )


# ---------------------------------------------------------------------------
# Tolerance tables
# ---------------------------------------------------------------------------

def test_get_limit_tolerance_by_risk_category():
    """ABAP: METHOD get_limit_tolerance CASE iv_ctlpc."""
    assert get_limit_tolerance("001") == Decimal("10.00")
    assert get_limit_tolerance("002") == Decimal("5.00")
    assert get_limit_tolerance("003") == Decimal("0.00")


def test_get_limit_tolerance_unknown_category_is_high_risk():
    """ABAP: WHEN OTHERS. rv_pct = '0.00'."""
    assert get_limit_tolerance("999") == Decimal("0.00")
    assert get_limit_tolerance("") == Decimal("0.00")


def test_get_overdue_tolerance_by_risk_category():
    """ABAP: METHOD get_overdue_tolerance CASE iv_ctlpc."""
    assert get_overdue_tolerance("001") == 30
    assert get_overdue_tolerance("002") == 15
    assert get_overdue_tolerance("003") == 0


def test_get_overdue_tolerance_unknown_category_is_high_risk():
    """ABAP: WHEN OTHERS. rv_days = 0."""
    assert get_overdue_tolerance("999") == 0


# ---------------------------------------------------------------------------
# Exposure calculation
# ---------------------------------------------------------------------------

def test_calculate_exposure_sums_all_components(credit_master, open_items):
    """ABAP: rv_total = skfor + ssobl + open orders + open deliveries + order."""
    total = calculate_exposure(credit_master, open_items, Decimal("2500.00"))
    assert total == Decimal("37500.00")


def test_calculate_exposure_with_special_liability(credit_master, open_items):
    """ABAP: ssobl is part of the exposure sum."""
    credit_master.special_liability = Decimal("1500.50")
    total = calculate_exposure(credit_master, open_items, Decimal("0"))
    assert total == Decimal("36500.50")


def test_calculate_exposure_zero_when_nothing_open():
    """ABAP: all summands initial → exposure 0."""
    credit = CreditMaster(
        customer_number="0000012345",
        credit_control_area="1000",
        credit_limit=Decimal("100000.00"),
    )
    total = calculate_exposure(credit, OpenExposure(), Decimal("0"))
    assert total == Decimal("0.00")


# ---------------------------------------------------------------------------
# Blocking paths that skip the limit evaluation
# ---------------------------------------------------------------------------

def test_check_credit_no_credit_master_blocks(open_items):
    """ABAP: SELECT SINGLE knkk sy-subrc <> 0 → NO_CREDIT_MASTER."""
    result = check_credit(make_request("1000.00"), None, open_items)

    assert result.status == CreditStatus.BLOCK
    assert result.reason_code == "NO_CREDIT_MASTER"
    assert result.message_type == MessageType.ERROR
    assert result.delivery_block == "Z1"
    assert "0000012345" in result.message_text


def test_check_credit_blocked_customer_blocks(credit_master, open_items):
    """ABAP: IF ls_credit-crblb = 'X' → CUSTOMER_BLOCKED."""
    credit_master.is_blocked = True
    result = check_credit(make_request("1000.00"), credit_master, open_items)

    assert result.status == CreditStatus.BLOCK
    assert result.reason_code == "CUSTOMER_BLOCKED"
    assert result.delivery_block == "Z1"
    # Exposure is not calculated on this path (ABAP RETURNs before it)
    assert result.total_exposure == Decimal("0")


def test_check_credit_blocked_customer_checked_before_limit(credit_master, open_items):
    """ABAP: crblb check precedes klimk evaluation, so the block wins."""
    credit_master.is_blocked = True
    credit_master.credit_limit = Decimal("999999.00")
    result = check_credit(make_request("1.00"), credit_master, open_items)

    assert result.reason_code == "CUSTOMER_BLOCKED"


# ---------------------------------------------------------------------------
# Zero / missing credit limit
# ---------------------------------------------------------------------------

def test_check_credit_zero_limit_low_risk_passes(credit_master, open_items):
    """ABAP: klimk <= 0 AND ctlpc = '001' → NO_LIMIT_CHECK."""
    credit_master.credit_limit = Decimal("0.00")
    credit_master.risk_category = RiskCategory.LOW
    result = check_credit(make_request("1000.00"), credit_master, open_items)

    assert result.status == CreditStatus.PASS
    assert result.reason_code == "NO_LIMIT_CHECK"
    assert result.message_type == MessageType.SUCCESS
    assert result.delivery_block is None
    assert result.total_exposure == Decimal("36000.00")


def test_check_credit_zero_limit_other_risk_blocks(credit_master, open_items):
    """ABAP: klimk <= 0 AND ctlpc <> '001' → ZERO_CREDIT_LIMIT."""
    credit_master.credit_limit = Decimal("0.00")
    result = check_credit(make_request("1000.00"), credit_master, open_items)

    assert result.status == CreditStatus.BLOCK
    assert result.reason_code == "ZERO_CREDIT_LIMIT"
    assert result.delivery_block == "Z1"


def test_check_credit_negative_limit_blocks(credit_master, open_items):
    """ABAP: klimk <= 0 covers negative limits too."""
    credit_master.credit_limit = Decimal("-500.00")
    result = check_credit(make_request("0.00"), credit_master, open_items)

    assert result.reason_code == "ZERO_CREDIT_LIMIT"


def test_check_credit_zero_limit_skips_overdue_override(credit_master, open_items):
    """ABAP: the klimk <= 0 branch RETURNs before the overdue check."""
    credit_master.credit_limit = Decimal("0.00")
    credit_master.risk_category = RiskCategory.LOW
    open_items.overdue_amount = Decimal("5000.00")
    open_items.overdue_days = 90
    result = check_credit(make_request("1000.00"), credit_master, open_items)

    assert result.status == CreditStatus.PASS
    assert result.reason_code == "NO_LIMIT_CHECK"


# ---------------------------------------------------------------------------
# Limit evaluation and boundaries
# ---------------------------------------------------------------------------

def test_check_credit_within_limit_passes(credit_master, open_items):
    """ABAP: exposure below limit and utilization < 90 → OK."""
    result = check_credit(make_request("2500.00"), credit_master, open_items)

    assert result.status == CreditStatus.PASS
    assert result.reason_code == "OK"
    assert result.total_exposure == Decimal("37500.00")
    assert result.effective_limit == Decimal("105000.00")
    assert result.utilization_pct == Decimal("37.50")


def test_check_credit_utilization_exactly_90_warns(credit_master, open_items):
    """ABAP: ELSEIF utilization_pct >= 90 — boundary is inclusive."""
    # 20000 + 10000 + 5000 + 55000 = 90000 → 90.00% of 100000
    result = check_credit(make_request("55000.00"), credit_master, open_items)

    assert result.status == CreditStatus.WARN
    assert result.reason_code == "LIMIT_NEARLY_EXCEEDED"
    assert result.message_type == MessageType.WARNING
    assert result.utilization_pct == Decimal("90.00")
    assert result.delivery_block is None


def test_check_credit_just_below_warning_threshold_passes(credit_master, open_items):
    """ABAP: utilization 89.99 stays below the >= 90 branch."""
    result = check_credit(make_request("54990.00"), credit_master, open_items)

    assert result.status == CreditStatus.PASS
    assert result.utilization_pct == Decimal("89.99")


def test_check_credit_exposure_equal_to_effective_limit_warns(
    credit_master, open_items
):
    """ABAP: IF exposure > effective_limit — equality does not block."""
    # Medium risk: effective limit = 100000 * 1.05 = 105000
    result = check_credit(make_request("70000.00"), credit_master, open_items)

    assert result.status == CreditStatus.WARN
    assert result.total_exposure == Decimal("105000.00")
    assert result.effective_limit == Decimal("105000.00")
    assert result.utilization_pct == Decimal("105.00")


def test_check_credit_above_effective_limit_blocks(credit_master, open_items):
    """ABAP: exposure > effective_limit → LIMIT_EXCEEDED."""
    result = check_credit(make_request("70000.01"), credit_master, open_items)

    assert result.status == CreditStatus.BLOCK
    assert result.reason_code == "LIMIT_EXCEEDED"
    assert result.message_type == MessageType.ERROR
    assert result.delivery_block == "Z1"


def test_check_credit_high_risk_gets_no_tolerance(credit_master, open_items):
    """ABAP: ctlpc '003' → tolerance 0, so effective limit = klimk."""
    credit_master.risk_category = RiskCategory.HIGH
    result = check_credit(make_request("65000.01"), credit_master, open_items)

    assert result.effective_limit == Decimal("100000.00")
    assert result.status == CreditStatus.BLOCK
    assert result.reason_code == "LIMIT_EXCEEDED"


def test_check_credit_low_risk_gets_ten_percent_tolerance(credit_master, open_items):
    """ABAP: ctlpc '001' → 10% tolerance, exposure 110000 still allowed."""
    credit_master.risk_category = RiskCategory.LOW
    result = check_credit(make_request("75000.00"), credit_master, open_items)

    assert result.effective_limit == Decimal("110000.00")
    assert result.total_exposure == Decimal("110000.00")
    assert result.status == CreditStatus.WARN


def test_check_credit_unknown_risk_category_gets_no_tolerance(
    credit_master, open_items
):
    """ABAP: WHEN OTHERS in get_limit_tolerance → 0% tolerance."""
    credit_master.risk_category = "007"
    result = check_credit(make_request("65000.01"), credit_master, open_items)

    assert result.effective_limit == Decimal("100000.00")
    assert result.reason_code == "LIMIT_EXCEEDED"


# ---------------------------------------------------------------------------
# Overdue override
# ---------------------------------------------------------------------------

def test_check_credit_overdue_beyond_tolerance_blocks_passing_order(
    credit_master, open_items
):
    """ABAP: overdue override applies when status <> 'B'."""
    open_items.overdue_amount = Decimal("2500.00")
    open_items.overdue_days = 16  # Medium risk tolerates 15
    result = check_credit(make_request("2500.00"), credit_master, open_items)

    assert result.status == CreditStatus.BLOCK
    assert result.reason_code == "OVERDUE_ITEMS"
    assert result.delivery_block == "Z1"
    assert "16 days" in result.message_text


def test_check_credit_overdue_at_tolerance_does_not_block(credit_master, open_items):
    """ABAP: IF overdue_days > lv_tol_days — equality does not block."""
    open_items.overdue_amount = Decimal("2500.00")
    open_items.overdue_days = 15
    result = check_credit(make_request("2500.00"), credit_master, open_items)

    assert result.status == CreditStatus.PASS
    assert result.reason_code == "OK"


def test_check_credit_overdue_days_without_amount_does_not_block(
    credit_master, open_items
):
    """ABAP: IF overdue_amount > 0 AND overdue_days > tolerance."""
    open_items.overdue_amount = Decimal("0.00")
    open_items.overdue_days = 120
    result = check_credit(make_request("2500.00"), credit_master, open_items)

    assert result.status == CreditStatus.PASS


def test_check_credit_overdue_overrides_warning(credit_master, open_items):
    """ABAP: a 'W' result is also replaced by the overdue block."""
    open_items.overdue_amount = Decimal("100.00")
    open_items.overdue_days = 45
    result = check_credit(make_request("55000.00"), credit_master, open_items)

    assert result.status == CreditStatus.BLOCK
    assert result.reason_code == "OVERDUE_ITEMS"
    # Exposure figures from the limit evaluation are retained
    assert result.utilization_pct == Decimal("90.00")


def test_check_credit_limit_exceeded_keeps_its_reason_code(credit_master, open_items):
    """ABAP: the overdue override only runs when status <> 'B'."""
    open_items.overdue_amount = Decimal("100.00")
    open_items.overdue_days = 999
    result = check_credit(make_request("70000.01"), credit_master, open_items)

    assert result.reason_code == "LIMIT_EXCEEDED"


def test_check_credit_high_risk_blocks_on_any_overdue_item(credit_master, open_items):
    """ABAP: ctlpc '003' tolerates 0 overdue days."""
    credit_master.risk_category = RiskCategory.HIGH
    open_items.overdue_amount = Decimal("10.00")
    open_items.overdue_days = 1
    result = check_credit(make_request("1000.00"), credit_master, open_items)

    assert result.status == CreditStatus.BLOCK
    assert result.reason_code == "OVERDUE_ITEMS"
