"""
Extended tests for the Inventory Report service.

Covers gaps in the original test suite:
- build_summary (never tested directly)
- calculate_stock_status boundary conditions
- filter_by_status edge cases
- generate_inventory_report sorting, default values, date parsing
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from python_target.inventory_report.models import (
    InventoryFilters,
    InventoryItem,
    InventoryReportSummary,
    StockStatus,
)
from python_target.inventory_report.service import (
    build_summary,
    calculate_stock_percentage,
    calculate_stock_status,
    filter_by_status,
    generate_inventory_report,
)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _make_item(
    status: StockStatus,
    available_stock: Decimal = Decimal("100"),
    reorder_point: Decimal = Decimal("50"),
    stock_value: Decimal = Decimal("1000"),
    plant: str = "1000",
) -> InventoryItem:
    return InventoryItem(
        material_number="MAT-TEST",
        description="Test Material",
        material_type="FERT",
        material_group="001",
        plant=plant,
        storage_location="0001",
        available_stock=available_stock,
        total_stock=available_stock,
        reorder_point=reorder_point,
        stock_status=status,
        stock_percentage=Decimal("200"),
        stock_value=stock_value,
    )


# ---------------------------------------------------------------------------
# build_summary — never tested directly in the original suite
# ---------------------------------------------------------------------------

class TestBuildSummary:

    def test_counts_critical_items(self):
        items = [
            _make_item(StockStatus.CRITICAL),
            _make_item(StockStatus.CRITICAL),
            _make_item(StockStatus.WARNING),
        ]
        summary = build_summary(items)
        assert summary.critical_count == 2
        assert summary.warning_count == 1
        assert summary.healthy_count == 0

    def test_counts_healthy_items(self):
        items = [
            _make_item(StockStatus.HEALTHY),
            _make_item(StockStatus.HEALTHY),
        ]
        summary = build_summary(items)
        assert summary.healthy_count == 2
        assert summary.critical_count == 0
        assert summary.warning_count == 0

    def test_total_stock_value_aggregation(self):
        items = [
            _make_item(StockStatus.CRITICAL, stock_value=Decimal("250.50")),
            _make_item(StockStatus.WARNING, stock_value=Decimal("749.50")),
        ]
        summary = build_summary(items)
        assert summary.total_stock_value == Decimal("1000.00")

    def test_materials_below_reorder(self):
        """Items where available_stock < reorder_point (and reorder > 0)."""
        items = [
            _make_item(
                StockStatus.CRITICAL,
                available_stock=Decimal("20"),
                reorder_point=Decimal("100"),
            ),
            _make_item(
                StockStatus.HEALTHY,
                available_stock=Decimal("200"),
                reorder_point=Decimal("100"),
            ),
            _make_item(
                StockStatus.CRITICAL,
                available_stock=Decimal("0"),
                reorder_point=Decimal("50"),
            ),
        ]
        summary = build_summary(items)
        assert summary.materials_below_reorder == 2

    def test_materials_below_reorder_zero_reorder_not_counted(self):
        """Items with reorder_point == 0 should not count as below reorder."""
        items = [
            _make_item(
                StockStatus.HEALTHY,
                available_stock=Decimal("0"),
                reorder_point=Decimal("0"),
            ),
        ]
        summary = build_summary(items)
        assert summary.materials_below_reorder == 0

    def test_empty_items_list(self):
        summary = build_summary([])
        assert summary.critical_count == 0
        assert summary.warning_count == 0
        assert summary.healthy_count == 0
        assert summary.total_stock_value == Decimal("0")
        assert summary.materials_below_reorder == 0

    def test_single_item_all_fields(self):
        items = [
            _make_item(
                StockStatus.WARNING,
                available_stock=Decimal("60"),
                reorder_point=Decimal("100"),
                stock_value=Decimal("3000"),
            ),
        ]
        summary = build_summary(items)
        assert summary.warning_count == 1
        assert summary.total_stock_value == Decimal("3000")
        assert summary.materials_below_reorder == 1


# ---------------------------------------------------------------------------
# calculate_stock_status — boundary / edge cases
# ---------------------------------------------------------------------------

class TestCalculateStockStatusBoundaries:

    def test_stock_exactly_at_reorder_point(self):
        """stock == reorder_point → not < reorder, but < 1.5x → WARNING."""
        assert calculate_stock_status(
            available_stock=Decimal("100"),
            reorder_point=Decimal("100"),
            last_receipt_date=date.today(),
            stale_days=90,
        ) == StockStatus.WARNING

    def test_stock_exactly_at_1_5x_reorder(self):
        """stock == 1.5 * reorder_point → not < 1.5x → HEALTHY."""
        assert calculate_stock_status(
            available_stock=Decimal("150"),
            reorder_point=Decimal("100"),
            last_receipt_date=date.today(),
            stale_days=90,
        ) == StockStatus.HEALTHY

    def test_negative_stock_is_critical(self):
        """Negative stock should be CRITICAL (stock <= 0)."""
        assert calculate_stock_status(
            available_stock=Decimal("-10"),
            reorder_point=Decimal("100"),
            last_receipt_date=date.today(),
            stale_days=90,
        ) == StockStatus.CRITICAL

    def test_stale_does_not_downgrade_warning(self):
        """Stale override only applies to HEALTHY → WARNING, not WARNING → CRITICAL."""
        old_receipt = date.today() - timedelta(days=200)
        assert calculate_stock_status(
            available_stock=Decimal("120"),
            reorder_point=Decimal("100"),
            last_receipt_date=old_receipt,
            stale_days=90,
        ) == StockStatus.WARNING

    def test_stale_at_exact_boundary_no_downgrade(self):
        """age == stale_days exactly → not stale (> stale_days required)."""
        receipt = date.today() - timedelta(days=90)
        assert calculate_stock_status(
            available_stock=Decimal("200"),
            reorder_point=Decimal("100"),
            last_receipt_date=receipt,
            stale_days=90,
        ) == StockStatus.HEALTHY

    def test_stale_one_day_over_threshold(self):
        """age == stale_days + 1 → stale, downgrades HEALTHY to WARNING."""
        receipt = date.today() - timedelta(days=91)
        assert calculate_stock_status(
            available_stock=Decimal("200"),
            reorder_point=Decimal("100"),
            last_receipt_date=receipt,
            stale_days=90,
        ) == StockStatus.WARNING

    def test_zero_reorder_with_stale_receipt(self):
        """Zero reorder point + stale receipt → healthy before stale, then downgrade."""
        old_receipt = date.today() - timedelta(days=200)
        assert calculate_stock_status(
            available_stock=Decimal("10"),
            reorder_point=Decimal("0"),
            last_receipt_date=old_receipt,
            stale_days=90,
        ) == StockStatus.WARNING

    def test_explicit_today_parameter(self):
        """Verify the 'today' parameter is used for stale calculation."""
        fixed_today = date(2024, 6, 15)
        receipt = date(2024, 3, 1)  # 106 days before fixed_today
        assert calculate_stock_status(
            available_stock=Decimal("200"),
            reorder_point=Decimal("100"),
            last_receipt_date=receipt,
            stale_days=90,
            today=fixed_today,
        ) == StockStatus.WARNING


# ---------------------------------------------------------------------------
# calculate_stock_percentage — additional cases
# ---------------------------------------------------------------------------

class TestCalculateStockPercentageExtended:

    def test_zero_stock(self):
        result = calculate_stock_percentage(Decimal("0"), Decimal("100"))
        assert result == Decimal("0")

    def test_exactly_at_reorder(self):
        result = calculate_stock_percentage(Decimal("100"), Decimal("100"))
        assert result == Decimal("100")

    def test_fractional_result(self):
        result = calculate_stock_percentage(Decimal("1"), Decimal("3"))
        # 1/3 * 100 ≈ 33.333...
        assert result > Decimal("33") and result < Decimal("34")

    def test_large_stock(self):
        result = calculate_stock_percentage(Decimal("10000"), Decimal("100"))
        assert result == Decimal("10000")


# ---------------------------------------------------------------------------
# filter_by_status — edge cases
# ---------------------------------------------------------------------------

class TestFilterByStatusExtended:

    def test_show_none(self):
        """No statuses selected → empty result."""
        items = [
            _make_item(StockStatus.CRITICAL),
            _make_item(StockStatus.WARNING),
            _make_item(StockStatus.HEALTHY),
        ]
        filters = InventoryFilters(
            show_critical=False, show_warning=False, show_healthy=False
        )
        result = filter_by_status(items, filters)
        assert result == []

    def test_show_only_warning(self):
        items = [
            _make_item(StockStatus.CRITICAL),
            _make_item(StockStatus.WARNING),
            _make_item(StockStatus.HEALTHY),
        ]
        filters = InventoryFilters(
            show_critical=False, show_warning=True, show_healthy=False
        )
        result = filter_by_status(items, filters)
        assert len(result) == 1
        assert result[0].stock_status == StockStatus.WARNING

    def test_show_only_healthy(self):
        items = [
            _make_item(StockStatus.CRITICAL),
            _make_item(StockStatus.WARNING),
            _make_item(StockStatus.HEALTHY),
        ]
        filters = InventoryFilters(
            show_critical=False, show_warning=False, show_healthy=True
        )
        result = filter_by_status(items, filters)
        assert len(result) == 1
        assert result[0].stock_status == StockStatus.HEALTHY

    def test_filter_empty_list(self):
        filters = InventoryFilters(
            show_critical=True, show_warning=True, show_healthy=True
        )
        result = filter_by_status([], filters)
        assert result == []

    def test_multiple_items_same_status(self):
        items = [
            _make_item(StockStatus.CRITICAL),
            _make_item(StockStatus.CRITICAL),
            _make_item(StockStatus.CRITICAL),
        ]
        filters = InventoryFilters(
            show_critical=True, show_warning=False, show_healthy=False
        )
        result = filter_by_status(items, filters)
        assert len(result) == 3


# ---------------------------------------------------------------------------
# generate_inventory_report — additional coverage
# ---------------------------------------------------------------------------

class TestGenerateInventoryReportExtended:

    def test_sorting_by_status_then_plant(self):
        """Items sorted: critical < warning < healthy, then by plant."""
        raw_data = [
            {
                "material_number": "MAT-H",
                "plant": "2000",
                "available_stock": 500,
                "reorder_point": 100,
                "last_receipt_date": date.today().isoformat(),
            },
            {
                "material_number": "MAT-C",
                "plant": "1000",
                "available_stock": 0,
                "reorder_point": 100,
            },
            {
                "material_number": "MAT-W",
                "plant": "3000",
                "available_stock": 120,
                "reorder_point": 100,
                "last_receipt_date": date.today().isoformat(),
            },
            {
                "material_number": "MAT-C2",
                "plant": "2000",
                "available_stock": 50,
                "reorder_point": 100,
            },
        ]
        filters = InventoryFilters(
            show_critical=True, show_warning=True, show_healthy=True
        )
        report = generate_inventory_report(raw_data, filters)

        statuses = [item.stock_status for item in report.items]
        # All CRITICALs before WARNINGs before HEALTHYs
        status_order = {StockStatus.CRITICAL: 1, StockStatus.WARNING: 2, StockStatus.HEALTHY: 3}
        numeric = [status_order[s] for s in statuses]
        assert numeric == sorted(numeric)

        # Within same status group, sorted by plant
        critical_plants = [
            item.plant for item in report.items
            if item.stock_status == StockStatus.CRITICAL
        ]
        assert critical_plants == sorted(critical_plants)

    def test_default_values_for_missing_fields(self):
        """Verify default values when optional fields are missing from raw data."""
        raw_data = [
            {
                "material_number": "MAT-MINIMAL",
                "plant": "1000",
                "available_stock": 0,
                "reorder_point": 10,
            },
        ]
        filters = InventoryFilters(
            show_critical=True, show_warning=True, show_healthy=True
        )
        report = generate_inventory_report(raw_data, filters)

        item = report.items[0]
        assert item.description == ""
        assert item.material_type == ""
        assert item.material_group == ""
        assert item.storage_location == ""
        assert item.inspection_stock == Decimal("0")
        assert item.blocked_stock == Decimal("0")
        assert item.currency == "USD"
        assert item.last_receipt_date is None

    def test_stock_value_calculation(self):
        """total_stock * unit_cost → stock_value."""
        raw_data = [
            {
                "material_number": "MAT-VAL",
                "plant": "1000",
                "available_stock": 10,
                "inspection_stock": 5,
                "blocked_stock": 3,
                "reorder_point": 0,
                "unit_cost": 20,
                "last_receipt_date": date.today().isoformat(),
            },
        ]
        filters = InventoryFilters(
            show_critical=True, show_warning=True, show_healthy=True
        )
        report = generate_inventory_report(raw_data, filters)

        item = report.items[0]
        # total_stock = 10 + 5 + 3 = 18; stock_value = 18 * 20 = 360
        assert item.total_stock == Decimal("18")
        assert item.stock_value == Decimal("360")

    def test_default_unit_cost(self):
        """Default unit_cost is 10 when not provided."""
        raw_data = [
            {
                "material_number": "MAT-DEF",
                "plant": "1000",
                "available_stock": 5,
                "reorder_point": 0,
                "last_receipt_date": date.today().isoformat(),
            },
        ]
        filters = InventoryFilters(
            show_critical=True, show_warning=True, show_healthy=True
        )
        report = generate_inventory_report(raw_data, filters)

        item = report.items[0]
        # total_stock = 5; default unit_cost = 10; stock_value = 50
        assert item.stock_value == Decimal("50")

    def test_report_metadata(self):
        """Verify generated_at, filters_applied, and total_items."""
        filters = InventoryFilters(
            plants=["1000"],
            show_critical=True,
            show_warning=True,
            show_healthy=True,
        )
        report = generate_inventory_report([], filters)

        assert report.generated_at is not None
        assert report.filters_applied == filters
        assert report.total_items == 0

    def test_last_receipt_date_as_date_object(self):
        """Raw data may provide last_receipt_date as a date object."""
        raw_data = [
            {
                "material_number": "MAT-DATE",
                "plant": "1000",
                "available_stock": 200,
                "reorder_point": 100,
                "last_receipt_date": date.today(),
            },
        ]
        filters = InventoryFilters(
            show_critical=True, show_warning=True, show_healthy=True
        )
        report = generate_inventory_report(raw_data, filters)

        assert report.items[0].last_receipt_date == date.today()


# ---------------------------------------------------------------------------
# Model validation tests
# ---------------------------------------------------------------------------

class TestInventoryModels:

    def test_stock_status_enum_values(self):
        assert StockStatus.CRITICAL.value == "critical"
        assert StockStatus.WARNING.value == "warning"
        assert StockStatus.HEALTHY.value == "healthy"

    def test_inventory_filters_defaults(self):
        filters = InventoryFilters()
        assert filters.plants == []
        assert filters.storage_locations == []
        assert filters.material_groups == []
        assert filters.material_types == []
        assert filters.stale_days == 90
        assert filters.show_critical is True
        assert filters.show_warning is True
        assert filters.show_healthy is False

    def test_inventory_report_summary_defaults(self):
        summary = InventoryReportSummary()
        assert summary.critical_count == 0
        assert summary.warning_count == 0
        assert summary.healthy_count == 0
        assert summary.total_stock_value == Decimal("0")
        assert summary.materials_below_reorder == 0
        assert summary.stale_materials == 0
