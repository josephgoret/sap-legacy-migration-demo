"""
Tests for the Order Sync service.

Validates functional equivalence between the ABAP Z_IDOC_ORDER_SYNC
function module and the migrated Python implementation.
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


# ---------------------------------------------------------------------------
# E1EDP19 segment-to-item association — mirrors ABAP parent-child logic
#
# ABAP (lines 132-138):
#   WHEN 'E1EDP19'.
#     IF lt_items IS NOT INITIAL.
#       DATA(lv_last_idx) = lines( lt_items ).
#       PERFORM parse_item_material_segment
#         USING ls_idoc_data-sdata CHANGING lt_items[ lv_last_idx ].
#     ENDIF.
#
# Rules verified:
#   1. E1EDP19 before any E1EDP01 is silently ignored (lt_items IS INITIAL).
#   2. Multiple E1EDP19 segments between two E1EDP01s all attach to the
#      same (last) item — qualifier 002 sets material_number, 003 sets
#      customer_material.
#   3. After a second E1EDP01 is parsed, subsequent E1EDP19 segments attach
#      to the *new* last item, leaving the first item unchanged.
#   4. End-to-end: segments with this ordering parse, validate, and process
#      successfully — proving functional equivalence with the ABAP pipeline.
# ---------------------------------------------------------------------------


class TestE1EDP19SegmentItemAssociation:
    """Verify E1EDP19 material segments attach to the correct parent item.

    The ABAP code uses ``lines( lt_items )`` to always modify the *last*
    item appended by a preceding E1EDP01 segment.  The Python service
    replicates this with a ``current_item`` pointer.  These tests exercise
    ordering edge-cases that the existing suite does not cover.
    """

    def test_e1edp19_before_any_item_is_ignored(self):
        """ABAP: IF lt_items IS NOT INITIAL guards the block — an E1EDP19
        arriving before any E1EDP01 must be silently discarded."""
        segments = [
            # E1EDP19 appears first — no item exists yet
            {"segment_type": "E1EDP19", "QUALF": "002", "IDTNR": "ORPHAN-MAT"},
            # Header so the order has required org fields
            {
                "segment_type": "E1EDK01",
                "BSART": "ZOR",
                "CURCY": "EUR",
                "SALES_ORG": "2000",
                "DISTR_CHAN": "20",
                "DIVISION": "01",
            },
            {"segment_type": "E1EDKA1", "PARVW": "AG", "PARTN": "CUST-100"},
            # First (and only) item — should NOT inherit ORPHAN-MAT
            {"segment_type": "E1EDP01", "POSEX": "000010", "MENGE": 5, "MENEE": "EA"},
            {"segment_type": "E1EDP19", "QUALF": "002", "IDTNR": "REAL-MAT"},
        ]

        order = parse_idoc_to_order(segments)

        assert len(order.items) == 1
        assert order.items[0].material_number == "REAL-MAT"
        # The orphan material must not leak anywhere
        assert order.items[0].customer_material is None

    def test_multiple_e1edp19_on_same_item(self):
        """Two E1EDP19 segments (qualifiers 002 and 003) between two E1EDP01
        segments must both update the *same* last item."""
        segments = [
            {
                "segment_type": "E1EDK01",
                "BSART": "ZOR",
                "CURCY": "USD",
                "SALES_ORG": "1000",
                "DISTR_CHAN": "10",
                "DIVISION": "00",
            },
            {"segment_type": "E1EDKA1", "PARVW": "AG", "PARTN": "CUST-200"},
            # Item 1
            {
                "segment_type": "E1EDP01",
                "POSEX": "000010",
                "MENGE": 10,
                "MENEE": "EA",
                "VPREI": 15.00,
            },
            # Two E1EDP19 segments for item 1 — different qualifiers
            {"segment_type": "E1EDP19", "QUALF": "002", "IDTNR": "SAP-MAT-A"},
            {"segment_type": "E1EDP19", "QUALF": "003", "IDTNR": "CUST-MAT-A"},
            # Item 2 — no E1EDP19 follows
            {
                "segment_type": "E1EDP01",
                "POSEX": "000020",
                "MENGE": 20,
                "MENEE": "KG",
                "VPREI": 8.00,
            },
        ]

        order = parse_idoc_to_order(segments)

        assert len(order.items) == 2

        # Item 1 received both material identifiers
        assert order.items[0].material_number == "SAP-MAT-A"
        assert order.items[0].customer_material == "CUST-MAT-A"

        # Item 2 has no material info — E1EDP19 was not provided for it
        assert order.items[1].material_number is None
        assert order.items[1].customer_material is None

    def test_e1edp19_after_second_item_does_not_affect_first(self):
        """After a second E1EDP01, E1EDP19 must attach to item 2 only.

        ABAP: lv_last_idx = lines( lt_items ) ensures only the tail item
        is modified.  This test proves item 1 is left unchanged."""
        segments = [
            {
                "segment_type": "E1EDK01",
                "BSART": "ZOR",
                "CURCY": "USD",
                "SALES_ORG": "1000",
                "DISTR_CHAN": "10",
                "DIVISION": "00",
            },
            {"segment_type": "E1EDKA1", "PARVW": "AG", "PARTN": "CUST-300"},
            # Item 1 with its own material
            {"segment_type": "E1EDP01", "POSEX": "000010", "MENGE": 7, "MENEE": "EA"},
            {"segment_type": "E1EDP19", "QUALF": "002", "IDTNR": "MAT-FIRST"},
            # Item 2 — E1EDP19 follows, must only touch item 2
            {"segment_type": "E1EDP01", "POSEX": "000020", "MENGE": 3, "MENEE": "EA"},
            {"segment_type": "E1EDP19", "QUALF": "002", "IDTNR": "MAT-SECOND"},
            {"segment_type": "E1EDP19", "QUALF": "003", "IDTNR": "CUST-SECOND"},
        ]

        order = parse_idoc_to_order(segments)

        assert len(order.items) == 2

        # Item 1 — only its own material, no customer_material
        assert order.items[0].material_number == "MAT-FIRST"
        assert order.items[0].customer_material is None

        # Item 2 — received both identifiers
        assert order.items[1].material_number == "MAT-SECOND"
        assert order.items[1].customer_material == "CUST-SECOND"

    def test_end_to_end_parse_validate_process_with_segment_ordering(self):
        """Full pipeline: raw segments → parse → validate → process.

        Exercises the complete ABAP-equivalent flow including:
        - An orphan E1EDP19 that must be ignored
        - Multi-qualifier E1EDP19 on item 1
        - E1EDP19 on item 2 only setting SAP material
        - Date segments with all three qualifiers (012, 022, 026)
        - All four partner roles (AG, WE, RE, RG)
        - Successful order creation (ABAP status '53')
        """
        segments = [
            # Orphan material — must be ignored
            {"segment_type": "E1EDP19", "QUALF": "002", "IDTNR": "IGNORE-ME"},
            # Header
            {
                "segment_type": "E1EDK01",
                "BSART": "ZRUSH",
                "CURCY": "EUR",
                "SALES_ORG": "3000",
                "DISTR_CHAN": "30",
                "DIVISION": "05",
            },
            # Dates — all three qualifiers
            {"segment_type": "E1EDK03", "IDDAT": "012", "DATUM": "2025-08-01"},
            {"segment_type": "E1EDK03", "IDDAT": "022", "DATUM": "2025-07-10"},
            {"segment_type": "E1EDK03", "IDDAT": "026", "DATUM": "2025-07-15"},
            # Partners — all four roles
            {"segment_type": "E1EDKA1", "PARVW": "AG", "PARTN": "SOLD-500"},
            {"segment_type": "E1EDKA1", "PARVW": "WE", "PARTN": "SHIP-501"},
            {"segment_type": "E1EDKA1", "PARVW": "RE", "PARTN": "BILL-502"},
            {"segment_type": "E1EDKA1", "PARVW": "RG", "PARTN": "PAY-503"},
            # Item 1 with two E1EDP19 qualifiers
            {
                "segment_type": "E1EDP01",
                "POSEX": "000010",
                "MENGE": 100,
                "MENEE": "EA",
                "VPREI": 49.99,
                "PSTYV": "TAN",
                "PLANT": "4000",
            },
            {"segment_type": "E1EDP19", "QUALF": "002", "IDTNR": "PROD-A"},
            {"segment_type": "E1EDP19", "QUALF": "003", "IDTNR": "CUST-PROD-A"},
            # Item 2 with only SAP material
            {
                "segment_type": "E1EDP01",
                "POSEX": "000020",
                "MENGE": 25,
                "MENEE": "KG",
                "VPREI": 120.00,
            },
            {"segment_type": "E1EDP19", "QUALF": "002", "IDTNR": "PROD-B"},
        ]

        # --- Parse ---
        order = parse_idoc_to_order(segments)

        # Header
        assert order.document_type == "ZRUSH"
        assert order.currency == "EUR"
        assert order.sales_org == "3000"
        assert order.distribution_channel == "30"
        assert order.division == "05"

        # Dates
        assert order.requested_delivery_date == date(2025, 8, 1)
        assert order.customer_po_date == date(2025, 7, 10)
        assert order.pricing_date == date(2025, 7, 15)

        # Partners
        assert order.sold_to_party == "SOLD-500"
        assert order.ship_to_party == "SHIP-501"
        assert len(order.partners) == 4
        partner_roles = {p.role for p in order.partners}
        assert partner_roles == {
            PartnerRole.SOLD_TO,
            PartnerRole.SHIP_TO,
            PartnerRole.BILL_TO,
            PartnerRole.PAYER,
        }

        # Items — segment association
        assert len(order.items) == 2

        item1 = order.items[0]
        assert item1.item_number == "000010"
        assert item1.quantity == Decimal("100")
        assert item1.unit_of_measure == "EA"
        assert item1.net_price == Decimal("49.99")
        assert item1.item_category == "TAN"
        assert item1.plant == "4000"
        assert item1.material_number == "PROD-A"
        assert item1.customer_material == "CUST-PROD-A"

        item2 = order.items[1]
        assert item2.item_number == "000020"
        assert item2.quantity == Decimal("25")
        assert item2.unit_of_measure == "KG"
        assert item2.net_price == Decimal("120")
        assert item2.material_number == "PROD-B"
        assert item2.customer_material is None  # no qualifier 003 provided

        # --- Validate ---
        errors = validate_order(order)
        assert errors == [], f"Expected no validation errors, got: {errors}"

        # --- Process ---
        message = InboundOrderMessage(
            message_id="E2E-SEGMENT-TEST",
            message_type="ORDERS",
            sender_system="TEST-HARNESS",
            order=order,
        )
        result = process_single_order(message)

        assert result.status == OrderStatus.CREATED
        assert result.order_number is not None
        assert len(result.order_number) == 10
        assert result.error_messages == []
        assert result.message_id == "E2E-SEGMENT-TEST"
