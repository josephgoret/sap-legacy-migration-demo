"""
Extended tests for the Order Sync service.

Covers gaps in the original test suite:
- OrderValidationError exception (never tested directly)
- validate_order: missing distribution_channel, division, negative qty, multiple errors
- parse_idoc_to_order: unknown segments, invalid partner roles, pricing date,
  empty segments, E1EDP19 without preceding E1EDP01
- process_single_order: message_id preserved
- process_order_batch: all-success, all-failure
- Model defaults and enum values
"""

from datetime import date
from decimal import Decimal

import pytest

from python_target.order_sync.models import (
    InboundOrderMessage,
    OrderHeader,
    OrderItem,
    OrderPartner,
    OrderStatus,
    OrderSyncBatchResult,
    OrderSyncResult,
    PartnerRole,
)
from python_target.order_sync.service import (
    OrderValidationError,
    parse_idoc_to_order,
    process_order_batch,
    process_single_order,
    validate_order,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def valid_order() -> OrderHeader:
    return OrderHeader(
        document_type="ZOR",
        sales_org="1000",
        distribution_channel="10",
        division="00",
        sold_to_party="CUST-001",
        items=[
            OrderItem(
                item_number="000010",
                material_number="MAT-001",
                quantity=Decimal("100"),
                unit_of_measure="EA",
                net_price=Decimal("25.50"),
            ),
        ],
    )


@pytest.fixture()
def valid_message(valid_order) -> InboundOrderMessage:
    return InboundOrderMessage(
        message_id="MSG-EXT-001",
        message_type="ORDERS",
        sender_system="TEST-SYSTEM",
        order=valid_order,
    )


# ---------------------------------------------------------------------------
# OrderValidationError — never tested in the original suite
# ---------------------------------------------------------------------------

class TestOrderValidationError:

    def test_message_contains_message_id(self):
        err = OrderValidationError("MSG-123", ["Error 1"])
        assert "MSG-123" in str(err)

    def test_message_contains_errors(self):
        err = OrderValidationError("MSG-123", ["Missing sold-to", "No items"])
        msg = str(err)
        assert "Missing sold-to" in msg
        assert "No items" in msg

    def test_attributes(self):
        errors = ["err1", "err2"]
        err = OrderValidationError("MSG-456", errors)
        assert err.message_id == "MSG-456"
        assert err.errors == errors

    def test_is_exception(self):
        assert issubclass(OrderValidationError, Exception)

    def test_raise_and_catch(self):
        with pytest.raises(OrderValidationError) as exc_info:
            raise OrderValidationError("MSG-789", ["test error"])
        assert exc_info.value.message_id == "MSG-789"


# ---------------------------------------------------------------------------
# validate_order — additional validation rules
# ---------------------------------------------------------------------------

class TestValidateOrderExtended:

    def test_missing_distribution_channel(self, valid_order):
        valid_order.distribution_channel = ""
        errors = validate_order(valid_order)
        assert any("distribution channel" in e.lower() for e in errors)

    def test_missing_division(self, valid_order):
        valid_order.division = ""
        errors = validate_order(valid_order)
        assert any("division" in e.lower() for e in errors)

    def test_negative_quantity_item(self, valid_order):
        valid_order.items[0].quantity = Decimal("-5")
        errors = validate_order(valid_order)
        assert any("quantity" in e.lower() for e in errors)

    def test_multiple_errors_at_once(self):
        """Order with every possible validation error."""
        order = OrderHeader(
            sales_org="",
            distribution_channel="",
            division="",
            sold_to_party="",
            items=[],
        )
        errors = validate_order(order)
        # Should have at least: sold-to, no items, sales_org, dist_channel, division
        assert len(errors) >= 4

    def test_multiple_items_with_issues(self, valid_order):
        """Multiple items with different validation errors."""
        valid_order.items = [
            OrderItem(
                item_number="000010",
                material_number=None,
                customer_material=None,
                quantity=Decimal("0"),
            ),
            OrderItem(
                item_number="000020",
                material_number=None,
                customer_material=None,
                quantity=Decimal("-1"),
            ),
        ]
        errors = validate_order(valid_order)
        # Each item should generate errors for quantity and material
        item_errors = [e for e in errors if "item" in e.lower()]
        assert len(item_errors) >= 4

    def test_customer_material_is_acceptable(self, valid_order):
        """Item with only customer_material (no material_number) is valid."""
        valid_order.items[0].material_number = None
        valid_order.items[0].customer_material = "CUST-MAT-001"
        errors = validate_order(valid_order)
        assert errors == []


# ---------------------------------------------------------------------------
# parse_idoc_to_order — additional segment parsing coverage
# ---------------------------------------------------------------------------

class TestParseIdocToOrderExtended:

    def test_empty_segments(self):
        """Empty segment list produces an order with defaults."""
        order = parse_idoc_to_order([])
        assert order.sold_to_party == ""
        assert order.sales_org == ""
        assert order.items == []
        assert order.partners == []

    def test_unknown_segment_type_ignored(self):
        """Segments with unrecognized types are silently skipped."""
        segments = [
            {"segment_type": "UNKNOWN_SEG", "FOO": "BAR"},
            {
                "segment_type": "E1EDK01",
                "SALES_ORG": "2000",
                "DISTR_CHAN": "20",
                "DIVISION": "01",
            },
        ]
        order = parse_idoc_to_order(segments)
        assert order.sales_org == "2000"

    def test_invalid_partner_role_skipped(self):
        """E1EDKA1 with invalid PARVW code is skipped."""
        segments = [
            {
                "segment_type": "E1EDK01",
                "SALES_ORG": "1000",
                "DISTR_CHAN": "10",
                "DIVISION": "00",
            },
            {
                "segment_type": "E1EDKA1",
                "PARVW": "XX",  # Invalid role
                "PARTN": "CUST-BAD",
            },
            {
                "segment_type": "E1EDKA1",
                "PARVW": "AG",  # Valid role
                "PARTN": "CUST-GOOD",
            },
        ]
        order = parse_idoc_to_order(segments)
        assert len(order.partners) == 1
        assert order.partners[0].number == "CUST-GOOD"
        assert order.sold_to_party == "CUST-GOOD"

    def test_pricing_date_qualifier_026(self):
        """E1EDK03 with IDDAT '026' maps to pricing_date."""
        segments = [
            {
                "segment_type": "E1EDK03",
                "IDDAT": "026",
                "DATUM": "2024-09-01",
            },
        ]
        order = parse_idoc_to_order(segments)
        assert order.pricing_date == date(2024, 9, 1)

    def test_e1edp19_without_preceding_item(self):
        """E1EDP19 before any E1EDP01 → current_item is None, should not crash."""
        segments = [
            {
                "segment_type": "E1EDP19",
                "QUALF": "002",
                "IDTNR": "MAT-ORPHAN",
            },
        ]
        # Should not raise an exception
        order = parse_idoc_to_order(segments)
        assert order.items == []

    def test_all_partner_roles(self):
        """Verify all four partner roles are parsed correctly."""
        segments = [
            {"segment_type": "E1EDKA1", "PARVW": "AG", "PARTN": "C-SOLD"},
            {"segment_type": "E1EDKA1", "PARVW": "WE", "PARTN": "C-SHIP"},
            {"segment_type": "E1EDKA1", "PARVW": "RE", "PARTN": "C-BILL"},
            {"segment_type": "E1EDKA1", "PARVW": "RG", "PARTN": "C-PAYER"},
        ]
        order = parse_idoc_to_order(segments)
        assert len(order.partners) == 4
        assert order.sold_to_party == "C-SOLD"
        assert order.ship_to_party == "C-SHIP"
        roles = {p.role for p in order.partners}
        assert roles == {PartnerRole.SOLD_TO, PartnerRole.SHIP_TO, PartnerRole.BILL_TO, PartnerRole.PAYER}

    def test_multiple_items_with_materials(self):
        """Multiple E1EDP01 + E1EDP19 pairs parse correctly."""
        segments = [
            {"segment_type": "E1EDP01", "POSEX": "000010", "MENGE": 5, "VPREI": 10},
            {"segment_type": "E1EDP19", "QUALF": "002", "IDTNR": "M1"},
            {"segment_type": "E1EDP01", "POSEX": "000020", "MENGE": 3, "VPREI": 20},
            {"segment_type": "E1EDP19", "QUALF": "003", "IDTNR": "CM2"},
            {"segment_type": "E1EDP01", "POSEX": "000030", "MENGE": 1, "VPREI": 50},
            {"segment_type": "E1EDP19", "QUALF": "002", "IDTNR": "M3"},
            {"segment_type": "E1EDP19", "QUALF": "003", "IDTNR": "CM3"},
        ]
        order = parse_idoc_to_order(segments)
        assert len(order.items) == 3
        assert order.items[0].material_number == "M1"
        assert order.items[1].customer_material == "CM2"
        assert order.items[2].material_number == "M3"
        assert order.items[2].customer_material == "CM3"

    def test_e1edk01_defaults(self):
        """E1EDK01 without optional fields uses defaults."""
        segments = [
            {"segment_type": "E1EDK01"},
        ]
        order = parse_idoc_to_order(segments)
        assert order.document_type == "ZOR"
        assert order.currency == "USD"
        assert order.sales_org == ""

    def test_e1edk03_missing_datum(self):
        """E1EDK03 with qualifier but no DATUM → date stays None."""
        segments = [
            {"segment_type": "E1EDK03", "IDDAT": "012"},
        ]
        order = parse_idoc_to_order(segments)
        assert order.requested_delivery_date is None

    def test_e1edp01_defaults(self):
        """E1EDP01 without optional fields uses defaults."""
        segments = [
            {"segment_type": "E1EDP01"},
        ]
        order = parse_idoc_to_order(segments)
        assert len(order.items) == 1
        assert order.items[0].item_number == "000010"
        assert order.items[0].unit_of_measure == "EA"
        assert order.items[0].quantity == Decimal("0")


# ---------------------------------------------------------------------------
# process_single_order — additional coverage
# ---------------------------------------------------------------------------

class TestProcessSingleOrderExtended:

    def test_message_id_preserved_on_success(self, valid_message):
        result = process_single_order(valid_message)
        assert result.message_id == "MSG-EXT-001"

    def test_message_id_preserved_on_failure(self, valid_message):
        valid_message.order.sold_to_party = ""
        result = process_single_order(valid_message)
        assert result.message_id == "MSG-EXT-001"
        assert result.status == OrderStatus.FAILED

    def test_order_number_format(self, valid_message):
        """Created order number should be exactly 10 digits."""
        result = process_single_order(valid_message)
        assert result.order_number is not None
        assert len(result.order_number) == 10
        assert result.order_number.isdigit()

    def test_successful_result_has_no_errors(self, valid_message):
        result = process_single_order(valid_message)
        assert result.status == OrderStatus.CREATED
        assert result.error_messages == []

    def test_failed_result_has_no_order_number(self, valid_message):
        valid_message.order.sold_to_party = ""
        result = process_single_order(valid_message)
        assert result.status == OrderStatus.FAILED
        assert result.order_number is None


# ---------------------------------------------------------------------------
# process_order_batch — additional coverage
# ---------------------------------------------------------------------------

class TestProcessOrderBatchExtended:

    def test_all_successful(self, valid_order):
        messages = [
            InboundOrderMessage(message_id=f"MSG-{i}", order=valid_order)
            for i in range(3)
        ]
        batch = process_order_batch(messages)
        assert batch.total_processed == 3
        assert batch.successful == 3
        assert batch.failed == 0
        assert all(r.status == OrderStatus.CREATED for r in batch.results)

    def test_all_failed(self):
        invalid_order = OrderHeader(
            sales_org="",
            distribution_channel="",
            division="",
            sold_to_party="",
            items=[],
        )
        messages = [
            InboundOrderMessage(message_id=f"MSG-{i}", order=invalid_order)
            for i in range(3)
        ]
        batch = process_order_batch(messages)
        assert batch.total_processed == 3
        assert batch.successful == 0
        assert batch.failed == 3
        assert all(r.status == OrderStatus.FAILED for r in batch.results)

    def test_batch_preserves_message_ids(self, valid_order):
        messages = [
            InboundOrderMessage(message_id="A", order=valid_order),
            InboundOrderMessage(message_id="B", order=valid_order),
        ]
        batch = process_order_batch(messages)
        ids = [r.message_id for r in batch.results]
        assert ids == ["A", "B"]

    def test_single_message_batch(self, valid_message):
        batch = process_order_batch([valid_message])
        assert batch.total_processed == 1
        assert batch.successful == 1


# ---------------------------------------------------------------------------
# Model defaults and enum values
# ---------------------------------------------------------------------------

class TestOrderSyncModels:

    def test_order_status_values(self):
        assert OrderStatus.CREATED.value == "created"
        assert OrderStatus.FAILED.value == "failed"
        assert OrderStatus.VALIDATED.value == "validated"

    def test_partner_role_values(self):
        assert PartnerRole.SOLD_TO.value == "AG"
        assert PartnerRole.SHIP_TO.value == "WE"
        assert PartnerRole.BILL_TO.value == "RE"
        assert PartnerRole.PAYER.value == "RG"

    def test_order_header_defaults(self):
        header = OrderHeader(
            sales_org="1000",
            distribution_channel="10",
            division="00",
            sold_to_party="C-001",
        )
        assert header.document_type == "ZOR"
        assert header.currency == "USD"
        assert header.ship_to_party is None
        assert header.customer_po_number is None
        assert header.partners == []
        assert header.items == []

    def test_order_item_defaults(self):
        item = OrderItem(
            item_number="000010",
            quantity=Decimal("1"),
        )
        assert item.material_number is None
        assert item.customer_material is None
        assert item.plant is None
        assert item.unit_of_measure == "EA"
        assert item.net_price == Decimal("0")
        assert item.item_category is None

    def test_inbound_order_message_defaults(self):
        header = OrderHeader(
            sales_org="1000",
            distribution_channel="10",
            division="00",
            sold_to_party="C-001",
        )
        msg = InboundOrderMessage(message_id="M-1", order=header)
        assert msg.message_type == "ORDERS"
        assert msg.sender_system is None

    def test_order_sync_result_defaults(self):
        result = OrderSyncResult(
            message_id="M-1",
            status=OrderStatus.CREATED,
        )
        assert result.order_number is None
        assert result.error_messages == []

    def test_order_sync_batch_result_structure(self):
        result = OrderSyncBatchResult(
            total_processed=5,
            successful=3,
            failed=2,
            results=[],
        )
        assert result.total_processed == 5
        assert result.successful == 3
        assert result.failed == 2
