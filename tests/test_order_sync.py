"""
Tests for the Order Sync service.

Validates functional equivalence between the ABAP Z_IDOC_ORDER_SYNC
function module and the migrated Python implementation.
"""

from datetime import date
from decimal import Decimal
from unittest.mock import patch

import pytest

from python_target.order_sync.models import (
    InboundOrderMessage,
    OrderHeader,
    OrderItem,
    OrderPartner,
    OrderStatus,
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
    """A fully valid order matching a typical ORDERS05 IDoc."""
    return OrderHeader(
        document_type="ZOR",
        sales_org="1000",
        distribution_channel="10",
        division="00",
        sold_to_party="CUST-001",
        ship_to_party="CUST-001",
        customer_po_number="PO-2024-5678",
        customer_po_date=date(2024, 6, 15),
        requested_delivery_date=date(2024, 7, 1),
        currency="USD",
        partners=[
            OrderPartner(role=PartnerRole.SOLD_TO, number="CUST-001"),
            OrderPartner(role=PartnerRole.SHIP_TO, number="CUST-001"),
        ],
        items=[
            OrderItem(
                item_number="000010",
                material_number="MAT-001",
                quantity=Decimal("100"),
                unit_of_measure="EA",
                net_price=Decimal("25.50"),
                plant="1000",
            ),
            OrderItem(
                item_number="000020",
                material_number="MAT-002",
                customer_material="CUST-MAT-002",
                quantity=Decimal("50"),
                unit_of_measure="EA",
                net_price=Decimal("42.00"),
                plant="1000",
            ),
        ],
    )


@pytest.fixture()
def valid_message(valid_order) -> InboundOrderMessage:
    return InboundOrderMessage(
        message_id="MSG-001",
        message_type="ORDERS",
        sender_system="EDI-GATEWAY",
        order=valid_order,
    )


@pytest.fixture()
def sample_idoc_segments() -> list[dict]:
    """Raw IDoc segment data — simulates the EDIDD table rows."""
    return [
        {
            "segment_type": "E1EDK01",
            "BSART": "ZOR",
            "CURCY": "USD",
            "SALES_ORG": "1000",
            "DISTR_CHAN": "10",
            "DIVISION": "00",
        },
        {
            "segment_type": "E1EDK03",
            "IDDAT": "012",
            "DATUM": "2024-07-01",
        },
        {
            "segment_type": "E1EDK03",
            "IDDAT": "022",
            "DATUM": "2024-06-15",
        },
        {
            "segment_type": "E1EDKA1",
            "PARVW": "AG",
            "PARTN": "CUST-001",
        },
        {
            "segment_type": "E1EDKA1",
            "PARVW": "WE",
            "PARTN": "CUST-002",
        },
        {
            "segment_type": "E1EDP01",
            "POSEX": "000010",
            "MENGE": 100,
            "MENEE": "EA",
            "VPREI": 25.50,
        },
        {
            "segment_type": "E1EDP19",
            "QUALF": "002",
            "IDTNR": "MAT-001",
        },
        {
            "segment_type": "E1EDP19",
            "QUALF": "003",
            "IDTNR": "CUST-MAT-A",
        },
        {
            "segment_type": "E1EDP01",
            "POSEX": "000020",
            "MENGE": 50,
            "MENEE": "EA",
            "VPREI": 42.00,
        },
        {
            "segment_type": "E1EDP19",
            "QUALF": "002",
            "IDTNR": "MAT-002",
        },
    ]


# ---------------------------------------------------------------------------
# validate_order — mirrors ABAP validation before BAPI call
# ---------------------------------------------------------------------------

class TestValidateOrder:

    def test_valid_order_passes(self, valid_order):
        errors = validate_order(valid_order)
        assert errors == []

    def test_missing_sold_to(self, valid_order):
        """ABAP: IF ls_header-sold_to IS INITIAL → status '51'."""
        valid_order.sold_to_party = ""
        errors = validate_order(valid_order)
        assert any("sold-to" in e.lower() for e in errors)

    def test_no_items(self, valid_order):
        """ABAP: IF lt_items IS INITIAL → status '51'."""
        valid_order.items = []
        errors = validate_order(valid_order)
        assert any("no order items" in e.lower() for e in errors)

    def test_zero_quantity_item(self, valid_order):
        """Items with non-positive quantity are flagged."""
        valid_order.items[0].quantity = Decimal("0")
        errors = validate_order(valid_order)
        assert any("quantity" in e.lower() for e in errors)

    def test_missing_material_and_customer_material(self, valid_order):
        valid_order.items[0].material_number = None
        valid_order.items[0].customer_material = None
        errors = validate_order(valid_order)
        assert any("material" in e.lower() for e in errors)

    def test_missing_sales_org(self, valid_order):
        valid_order.sales_org = ""
        errors = validate_order(valid_order)
        assert any("sales organization" in e.lower() for e in errors)

    def test_missing_distribution_channel(self, valid_order):
        """ABAP requires distr_chan in BAPI header mapping."""
        valid_order.distribution_channel = ""
        errors = validate_order(valid_order)
        assert any("distribution channel" in e.lower() for e in errors)

    def test_missing_division(self, valid_order):
        """ABAP requires division in BAPI header mapping."""
        valid_order.division = ""
        errors = validate_order(valid_order)
        assert any("division" in e.lower() for e in errors)

    def test_negative_quantity_item(self, valid_order):
        """Negative quantity must be rejected (non-positive check)."""
        valid_order.items[0].quantity = Decimal("-5")
        errors = validate_order(valid_order)
        assert any("quantity" in e.lower() for e in errors)

    def test_customer_material_only_is_valid(self, valid_order):
        """ABAP E1EDP19 qualifier 003 can supply customer material without SAP material."""
        valid_order.items[0].material_number = None
        valid_order.items[0].customer_material = "CUST-MAT-X"
        errors = validate_order(valid_order)
        assert errors == []

    def test_multiple_validation_errors_accumulated(self, valid_order):
        """All validation errors are collected, not short-circuited."""
        valid_order.sold_to_party = ""
        valid_order.sales_org = ""
        valid_order.distribution_channel = ""
        valid_order.division = ""
        valid_order.items = []
        errors = validate_order(valid_order)
        assert len(errors) >= 5

    def test_multiple_items_with_mixed_errors(self, valid_order):
        """Per-item errors are reported for each invalid item."""
        valid_order.items[0].quantity = Decimal("0")
        valid_order.items[0].material_number = None
        valid_order.items[0].customer_material = None
        valid_order.items[1].quantity = Decimal("-1")
        errors = validate_order(valid_order)
        item_errors = [e for e in errors if "item" in e.lower()]
        assert len(item_errors) >= 3  # qty error on both items + material error on first


# ---------------------------------------------------------------------------
# parse_idoc_to_order — mirrors ABAP segment parsing CASE/WHEN logic
# ---------------------------------------------------------------------------

class TestParseIdocToOrder:

    def test_header_fields(self, sample_idoc_segments):
        """ABAP: WHEN 'E1EDK01' → PERFORM parse_header_segment."""
        order = parse_idoc_to_order(sample_idoc_segments)
        assert order.document_type == "ZOR"
        assert order.currency == "USD"
        assert order.sales_org == "1000"

    def test_date_parsing(self, sample_idoc_segments):
        """ABAP: WHEN 'E1EDK03' with IDDAT qualifiers 012, 022, 026."""
        order = parse_idoc_to_order(sample_idoc_segments)
        assert order.requested_delivery_date == date(2024, 7, 1)
        assert order.customer_po_date == date(2024, 6, 15)

    def test_partner_parsing(self, sample_idoc_segments):
        """ABAP: WHEN 'E1EDKA1' → sold-to (AG), ship-to (WE)."""
        order = parse_idoc_to_order(sample_idoc_segments)
        assert order.sold_to_party == "CUST-001"
        assert order.ship_to_party == "CUST-002"
        assert len(order.partners) == 2

    def test_item_parsing(self, sample_idoc_segments):
        """ABAP: WHEN 'E1EDP01' → item number, qty, UOM, price."""
        order = parse_idoc_to_order(sample_idoc_segments)
        assert len(order.items) == 2
        assert order.items[0].item_number == "000010"
        assert order.items[0].quantity == Decimal("100")
        assert order.items[1].item_number == "000020"

    def test_material_identification(self, sample_idoc_segments):
        """ABAP: WHEN 'E1EDP19' → qualifier 002=SAP material, 003=customer material."""
        order = parse_idoc_to_order(sample_idoc_segments)
        assert order.items[0].material_number == "MAT-001"
        assert order.items[0].customer_material == "CUST-MAT-A"
        assert order.items[1].material_number == "MAT-002"

    def test_empty_segments_list(self):
        """Empty EDIDD table → header with defaults, no items or partners."""
        order = parse_idoc_to_order([])
        assert order.sold_to_party == ""
        assert order.items == []
        assert order.partners == []

    def test_unknown_segment_type_ignored(self, sample_idoc_segments):
        """ABAP CASE/WHEN: unrecognised segment types fall through without error."""
        sample_idoc_segments.append(
            {"segment_type": "Z1CUSTOM", "FIELD1": "value"}
        )
        order = parse_idoc_to_order(sample_idoc_segments)
        assert len(order.items) == 2  # unchanged

    def test_pricing_date_qualifier_026(self):
        """ABAP: WHEN '026' → cs_header-price_date = ls_e1edk03-datum."""
        segments = [
            {
                "segment_type": "E1EDK01",
                "BSART": "ZOR",
                "CURCY": "EUR",
                "SALES_ORG": "2000",
                "DISTR_CHAN": "20",
                "DIVISION": "10",
            },
            {
                "segment_type": "E1EDK03",
                "IDDAT": "026",
                "DATUM": "2024-08-01",
            },
        ]
        order = parse_idoc_to_order(segments)
        assert order.pricing_date == date(2024, 8, 1)

    def test_unrecognised_date_qualifier_ignored(self):
        """ABAP CASE: qualifiers other than 012/022/026 are silently skipped."""
        segments = [
            {"segment_type": "E1EDK01", "SALES_ORG": "1000",
             "DISTR_CHAN": "10", "DIVISION": "00"},
            {"segment_type": "E1EDK03", "IDDAT": "999", "DATUM": "2024-01-01"},
        ]
        order = parse_idoc_to_order(segments)
        assert order.requested_delivery_date is None
        assert order.customer_po_date is None
        assert order.pricing_date is None

    def test_bill_to_and_payer_partners(self):
        """ABAP: WHEN 'RE' → bill-to, WHEN 'RG' → payer added to partner table."""
        segments = [
            {"segment_type": "E1EDK01", "SALES_ORG": "1000",
             "DISTR_CHAN": "10", "DIVISION": "00"},
            {"segment_type": "E1EDKA1", "PARVW": "AG", "PARTN": "CUST-001"},
            {"segment_type": "E1EDKA1", "PARVW": "RE", "PARTN": "BILL-001"},
            {"segment_type": "E1EDKA1", "PARVW": "RG", "PARTN": "PAY-001"},
        ]
        order = parse_idoc_to_order(segments)
        assert len(order.partners) == 3
        roles = {p.role for p in order.partners}
        assert PartnerRole.BILL_TO in roles
        assert PartnerRole.PAYER in roles

    def test_unknown_partner_role_skipped(self):
        """ABAP CASE: unknown PARVW values are skipped (no partner appended)."""
        segments = [
            {"segment_type": "E1EDK01", "SALES_ORG": "1000",
             "DISTR_CHAN": "10", "DIVISION": "00"},
            {"segment_type": "E1EDKA1", "PARVW": "ZZ", "PARTN": "UNKNOWN-001"},
        ]
        order = parse_idoc_to_order(segments)
        assert len(order.partners) == 0

    def test_e1edp19_before_any_item_is_ignored(self):
        """ABAP: IF lt_items IS NOT INITIAL before processing E1EDP19.
        E1EDP19 without a preceding E1EDP01 should be safely ignored."""
        segments = [
            {"segment_type": "E1EDK01", "SALES_ORG": "1000",
             "DISTR_CHAN": "10", "DIVISION": "00"},
            {"segment_type": "E1EDP19", "QUALF": "002", "IDTNR": "ORPHAN-MAT"},
            {"segment_type": "E1EDP01", "POSEX": "000010", "MENGE": 10,
             "MENEE": "EA", "VPREI": 5.0},
        ]
        order = parse_idoc_to_order(segments)
        assert len(order.items) == 1
        assert order.items[0].material_number is None

    def test_e1edp19_unknown_qualifier_ignored(self):
        """ABAP CASE: qualifiers other than 002/003 are silently skipped."""
        segments = [
            {"segment_type": "E1EDK01", "SALES_ORG": "1000",
             "DISTR_CHAN": "10", "DIVISION": "00"},
            {"segment_type": "E1EDP01", "POSEX": "000010", "MENGE": 10,
             "MENEE": "EA", "VPREI": 5.0},
            {"segment_type": "E1EDP19", "QUALF": "999", "IDTNR": "IGNORED"},
        ]
        order = parse_idoc_to_order(segments)
        assert order.items[0].material_number is None
        assert order.items[0].customer_material is None

    def test_header_defaults_when_fields_missing(self):
        """ABAP: IF ls_order_header_in-doc_type IS INITIAL → default 'ZOR'."""
        segments = [
            {"segment_type": "E1EDK01", "SALES_ORG": "3000",
             "DISTR_CHAN": "30", "DIVISION": "05"},
        ]
        order = parse_idoc_to_order(segments)
        assert order.document_type == "ZOR"
        assert order.currency == "USD"

    def test_item_defaults_when_fields_missing(self):
        """E1EDP01 with minimal fields uses defaults for UOM and price."""
        segments = [
            {"segment_type": "E1EDK01", "SALES_ORG": "1000",
             "DISTR_CHAN": "10", "DIVISION": "00"},
            {"segment_type": "E1EDP01", "POSEX": "000010", "MENGE": 1},
        ]
        order = parse_idoc_to_order(segments)
        assert order.items[0].unit_of_measure == "EA"
        assert order.items[0].net_price == Decimal("0")

    def test_multiple_material_segments_per_item(self):
        """Both SAP material (002) and customer material (003) on one item."""
        segments = [
            {"segment_type": "E1EDK01", "SALES_ORG": "1000",
             "DISTR_CHAN": "10", "DIVISION": "00"},
            {"segment_type": "E1EDP01", "POSEX": "000010", "MENGE": 5,
             "MENEE": "EA", "VPREI": 10.0},
            {"segment_type": "E1EDP19", "QUALF": "002", "IDTNR": "SAP-MAT-1"},
            {"segment_type": "E1EDP19", "QUALF": "003", "IDTNR": "CUST-MAT-1"},
        ]
        order = parse_idoc_to_order(segments)
        assert order.items[0].material_number == "SAP-MAT-1"
        assert order.items[0].customer_material == "CUST-MAT-1"


# ---------------------------------------------------------------------------
# process_single_order — mirrors ABAP per-IDoc processing loop body
# ---------------------------------------------------------------------------

class TestProcessSingleOrder:

    def test_successful_order_creation(self, valid_message):
        """ABAP: BAPI returns no errors → BAPI_TRANSACTION_COMMIT → status '53'."""
        result = process_single_order(valid_message)

        assert result.status == OrderStatus.CREATED
        assert result.order_number is not None
        assert len(result.order_number) == 10  # SAP VBELN format
        assert result.error_messages == []

    def test_validation_failure(self, valid_message):
        """ABAP: Validation fails → set_idoc_status '51' 'E'."""
        valid_message.order.sold_to_party = ""
        result = process_single_order(valid_message)

        assert result.status == OrderStatus.FAILED
        assert len(result.error_messages) > 0

    def test_target_system_exception_triggers_rollback(self, valid_message):
        """ABAP: BAPI error → BAPI_TRANSACTION_ROLLBACK → status '51'."""
        with patch(
            "python_target.order_sync.service._create_order_in_target_system",
            side_effect=RuntimeError("Connection timeout"),
        ):
            result = process_single_order(valid_message)

        assert result.status == OrderStatus.FAILED
        assert result.order_number is None
        assert any("Connection timeout" in e for e in result.error_messages)

    def test_message_id_preserved_on_failure(self, valid_message):
        """Result always carries the originating message ID (DOCNUM)."""
        valid_message.order.sold_to_party = ""
        result = process_single_order(valid_message)
        assert result.message_id == "MSG-001"

    def test_message_id_preserved_on_success(self, valid_message):
        result = process_single_order(valid_message)
        assert result.message_id == "MSG-001"

    def test_multiple_validation_errors_in_result(self):
        """Multiple validation errors are all surfaced in the result."""
        msg = InboundOrderMessage(
            message_id="MSG-MULTI-ERR",
            order=OrderHeader(
                sales_org="",
                distribution_channel="",
                division="",
                sold_to_party="",
                items=[],
            ),
        )
        result = process_single_order(msg)
        assert result.status == OrderStatus.FAILED
        assert len(result.error_messages) >= 4

    def test_default_document_type_applied(self, valid_message):
        """ABAP: IF ls_order_header_in-doc_type IS INITIAL → default 'ZOR'."""
        valid_message.order.document_type = "ZOR"
        result = process_single_order(valid_message)
        assert result.status == OrderStatus.CREATED

    def test_order_number_format(self, valid_message):
        """Generated order number matches SAP VBELN format (10 digits)."""
        result = process_single_order(valid_message)
        assert result.order_number is not None
        assert result.order_number.isdigit()
        assert len(result.order_number) == 10


# ---------------------------------------------------------------------------
# process_order_batch — mirrors ABAP LOOP AT idoc_contrl
# ---------------------------------------------------------------------------

class TestProcessOrderBatch:

    def test_mixed_batch(self, valid_order):
        """Process batch with mix of valid and invalid orders."""
        messages = [
            InboundOrderMessage(
                message_id="MSG-001",
                order=valid_order,
            ),
            InboundOrderMessage(
                message_id="MSG-002",
                order=OrderHeader(
                    sales_org="1000",
                    distribution_channel="10",
                    division="00",
                    sold_to_party="",  # Invalid: missing sold-to
                    items=[],          # Invalid: no items
                ),
            ),
            InboundOrderMessage(
                message_id="MSG-003",
                order=valid_order,
            ),
        ]

        batch_result = process_order_batch(messages)

        assert batch_result.total_processed == 3
        assert batch_result.successful == 2
        assert batch_result.failed == 1
        assert batch_result.results[1].status == OrderStatus.FAILED

    def test_empty_batch(self):
        batch_result = process_order_batch([])
        assert batch_result.total_processed == 0
        assert batch_result.successful == 0
        assert batch_result.failed == 0

    def test_all_valid_batch(self, valid_order):
        """All orders succeed — successful count equals total."""
        messages = [
            InboundOrderMessage(message_id=f"MSG-{i}", order=valid_order)
            for i in range(3)
        ]
        batch_result = process_order_batch(messages)
        assert batch_result.total_processed == 3
        assert batch_result.successful == 3
        assert batch_result.failed == 0

    def test_all_invalid_batch(self):
        """All orders fail — failed count equals total."""
        invalid_order = OrderHeader(
            sales_org="1000",
            distribution_channel="10",
            division="00",
            sold_to_party="",
            items=[],
        )
        messages = [
            InboundOrderMessage(message_id=f"MSG-{i}", order=invalid_order)
            for i in range(3)
        ]
        batch_result = process_order_batch(messages)
        assert batch_result.total_processed == 3
        assert batch_result.successful == 0
        assert batch_result.failed == 3

    def test_single_order_batch(self, valid_order):
        """Single-element batch processes correctly."""
        messages = [InboundOrderMessage(message_id="MSG-SOLO", order=valid_order)]
        batch_result = process_order_batch(messages)
        assert batch_result.total_processed == 1
        assert batch_result.successful == 1
        assert len(batch_result.results) == 1

    def test_batch_results_preserve_order(self, valid_order):
        """Results list preserves the input message order (like ABAP LOOP)."""
        messages = [
            InboundOrderMessage(message_id=f"MSG-{i:03d}", order=valid_order)
            for i in range(5)
        ]
        batch_result = process_order_batch(messages)
        for i, result in enumerate(batch_result.results):
            assert result.message_id == f"MSG-{i:03d}"

    def test_batch_failure_isolation(self, valid_order):
        """ABAP: Each IDoc is processed independently — one failure does not
        prevent subsequent orders from succeeding."""
        invalid_order = OrderHeader(
            sales_org="1000",
            distribution_channel="10",
            division="00",
            sold_to_party="",
            items=[],
        )
        messages = [
            InboundOrderMessage(message_id="MSG-OK-1", order=valid_order),
            InboundOrderMessage(message_id="MSG-FAIL", order=invalid_order),
            InboundOrderMessage(message_id="MSG-OK-2", order=valid_order),
        ]
        batch_result = process_order_batch(messages)
        assert batch_result.results[0].status == OrderStatus.CREATED
        assert batch_result.results[1].status == OrderStatus.FAILED
        assert batch_result.results[2].status == OrderStatus.CREATED
