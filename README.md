# PeopleSoft → Python Migration Demo

> **Demo repository** showing how Devin migrates legacy PeopleSoft PeopleCode to modern Python services targeting Workday.
> Three representative objects demonstrate the migration pattern at production quality.

---

## Demo Structure

```
peoplesoft-migration-demo/
├── README.md                              ← This file
├── migration-playbook.md                  ← PeopleCode → Python/Workday playbook
├── requirements.txt
├── peoplecode_source/                     ← Original PeopleCode programs
│   ├── employee_status_report.ppl         ← Application Engine (batch HR report)
│   ├── ci_vendor_lookup.ppl               ← Component Interface (vendor lookup)
│   └── integration_broker_sync.ppl        ← Integration Broker (employee sync)
├── python_target/                         ← Migrated Python services
│   ├── employee_status_report/
│   │   ├── models.py                      ← Pydantic models (from Rowsets/Records)
│   │   └── service.py                     ← Business logic
│   ├── vendor_lookup/
│   │   ├── models.py
│   │   └── service.py
│   └── employee_sync/
│       ├── models.py
│       └── service.py
└── tests/
    ├── test_employee_status_report.py
    ├── test_vendor_lookup.py
    └── test_employee_sync.py
```

---

## Three Migrations

### 1. Employee Status Report

| Attribute        | Source (PeopleSoft)                                | Target (Python)                    |
|------------------|----------------------------------------------------|------------------------------------|
| **Object**       | Application Engine `HR_EMP_STATUS`                 | FastAPI endpoint + JSON response   |
| **Tables**       | PS_JOB, PS_PERSONAL_DATA, PS_EMPLOYMENT            | Data warehouse query               |
| **Pattern**      | CreateRowset → Fill → Evaluate → GetFile/WriteLine | Query → transform → JSON response  |
| **Business logic** | Status categorization (Active/LOA/Terminated/Retired), headcount flag, stale action detection | Same logic, same thresholds |

**Key PeopleCode patterns migrated**:
- `CreateRowset(Record.JOB)` / `Fill("WHERE ...")` → list comprehension over query results
- `Evaluate &emplStatus When = "A" ...` → dictionary-based status mapping
- Run Control record parameters → API query parameters
- CSV file output via `GetFile()` / `WriteLine()` → JSON response body

### 2. Vendor/Supplier Lookup

| Attribute        | Source (PeopleSoft)                                | Target (Python)                    |
|------------------|----------------------------------------------------|------------------------------------|
| **Object**       | Component Interface `CI_VENDOR_LOOKUP`             | REST API endpoint                  |
| **Tables**       | PS_VENDOR, PS_VENDOR_ADDR, PS_VNDR_BANK_ACCT, PS_PO_HDR, PS_PO_LINE | Data warehouse query |
| **Pattern**      | CI.Get() → SQLExec → aggregate → CI output         | Request → query → aggregate → JSON |
| **Business logic** | Vendor master lookup, PO history with date filtering, open PO counting | Same logic, same aggregation |

**Key PeopleCode patterns migrated**:
- `%CompIntfcName` / `&CI.VENDOR_ID` → request body fields
- `IsUserInRole("VENDOR_INQUIRY")` → API key / JWT middleware
- `SQLExec()` with effective-dated joins → SQL query with date parameters
- `Error()` for vendor-not-found → Python `VendorNotFoundError` exception
- CI output collection `&CI.PO_HISTORY(&poCount)` → list of `PurchaseOrderItem` models

### 3. Employee Sync

| Attribute        | Source (PeopleSoft)                                | Target (Python)                    |
|------------------|----------------------------------------------------|------------------------------------|
| **Object**       | Integration Broker handler `EMP_SYNC_SUB`          | Event-driven message consumer      |
| **Tables**       | Inbound XML message                                | JSON message from queue            |
| **Pattern**      | %IntBroker.GetMessage() → parse XML → validate → map → publish response | Consume JSON → validate → transform → call target |
| **Business logic** | HIRE/REHIRE/TRANSFER/TERMINATION validation and mapping to Workday API | Same validation rules, same field mapping |

**Key PeopleCode patterns migrated**:
- `%IntBroker.GetMessage()` / `&MSG.GetXmlDoc()` → JSON deserialization via Pydantic
- `XmlNode.FindNode("EmployeeData")` → model field access
- `Evaluate &transactionType When = "HIRE" ...` → `TransactionType` enum dispatch
- `CommitWork()` / `RollbackWork()` → transaction management in service layer
- `%IntBroker.Publish(&responseMsg)` → `SyncResult` return value

---

## Running the Demo

```bash
# Install dependencies
pip install -r requirements.txt

# Run all tests
pytest tests/ -v

# Run a specific migration's tests
pytest tests/test_employee_status_report.py -v
pytest tests/test_vendor_lookup.py -v
pytest tests/test_employee_sync.py -v
```

---

## Presenter Notes

### Setup (before the meeting)

1. Have this repo open in VS Code or similar
2. Open `peoplecode_source/employee_status_report.ppl` side-by-side with `python_target/employee_status_report/service.py`
3. Run `pytest tests/ -v` to confirm all tests pass
4. Have `migration-playbook.md` open in a preview pane

### Suggested Demo Flow (15 minutes)

1. **Open the PeopleCode source** (2 min)
   - Show `employee_status_report.ppl` — point out the realistic Application Engine structure
   - Highlight the legacy date (Created: 2012-04-18), complex SQL joins, Evaluate block
   - "This is a real-world pattern — 10+ year old PeopleCode, thousands of lines querying HR tables"

2. **Show the migrated Python** (3 min)
   - Switch to `python_target/employee_status_report/service.py`
   - Show the inline comments mapping back to PeopleCode steps
   - Show the Pydantic model fields with `Field(description="PS_JOB.EMPLID")` annotations
   - "Every function traces back to the original PeopleCode. Nothing is lost in translation."

3. **Walk through the translation table** (3 min)
   - Open `migration-playbook.md`
   - Show the PeopleCode → Python mapping table (Rowset → list[Model], etc.)
   - Show the three migration patterns (Application Engine, Component Interface, Integration Broker)
   - "This playbook is what Devin follows for every object. It's deterministic and repeatable."

4. **Run the tests** (2 min)
   - `pytest tests/ -v`
   - Point out test docstrings referencing original PeopleCode logic
   - "Each test validates functional equivalence — same input, same output as PeopleCode"

5. **Show the Component Interface migration** (2 min)
   - Side-by-side: `ci_vendor_lookup.ppl` → `vendor_lookup/service.py`
   - Highlight: CI properties → request/response models, Error() → exceptions
   - "PeopleSoft Component Interfaces become REST APIs — same data, modern access pattern"

6. **Show the Integration Broker migration** (2 min)
   - Side-by-side: `integration_broker_sync.ppl` → `employee_sync/service.py`
   - Highlight: XML parsing → JSON/Pydantic, Evaluate → enum dispatch
   - "Integration Broker XML messages become JSON events — the validation logic is identical"

7. **Close with the value proposition** (1 min)
   - "Three different PeopleSoft patterns, all migrated with full traceability"
   - "This is what Devin does at scale — hundreds of objects, same quality, same approach"

### Talking Points for Q&A

- **"How does Devin handle PeopleCode it hasn't seen before?"**
  The migration playbook defines patterns. Each PeopleCode construct maps to a Python equivalent.
  Devin reads the source, identifies the pattern, and applies the corresponding transformation.

- **"What about PeopleSoft-specific SQL (effective dating, SetID logic)?"**
  These are well-documented PeopleSoft patterns. The playbook explicitly covers effective-dated joins
  and SetID resolution. Devin preserves the same query logic in the Python implementation.

- **"How do you ensure nothing is lost?"**
  Every Python function has inline comments mapping to PeopleCode source.
  Every Pydantic field references the PeopleSoft record.field name.
  Every test cites the original PeopleCode logic it validates.

- **"Can this work with our existing PeopleSoft system?"**
  Yes. The pattern works with any PeopleCode export. We read the source,
  apply the playbook, generate Python with full traceability, and validate with tests.

---

## Key Takeaways

1. **PeopleSoft → Python migration is a pattern-matching problem.** PeopleCode constructs (Rowsets, Component Interfaces, Integration Broker handlers) have direct Python equivalents. Devin applies these mappings systematically.

2. **Functional equivalence is the standard.** We don't optimize during migration — every line of Python matches the original PeopleCode behavior. Optimization comes later, after equivalence is proven.

3. **Traceability is built in, not bolted on.** Every Python function, every model field, every test references the original PeopleCode source. This is critical for audit compliance and consulting partner review.

4. **The 80/20 consulting partner pattern works here.** Infosys PeopleSoft consultants define the migration scope, validate business rules, and handle PeopleSoft configuration. Devin handles the repetitive code translation — the 80% that is mechanical. Infosys focuses on the 20% that requires deep PeopleSoft domain knowledge (effective dating nuances, security configuration, workflow rules).

5. **This scales.** The three examples here cover the most common PeopleSoft customization patterns (Application Engine, Component Interface, Integration Broker). A typical PeopleSoft implementation has hundreds of custom objects following these same patterns. Devin migrates them with the same quality and traceability shown here.

---

## Technical Stack

| Component         | Technology                    |
|-------------------|-------------------------------|
| Data models       | Pydantic v2                   |
| Testing           | pytest                        |
| Type checking     | Standard Python type hints    |
| Target platform   | Workday (via REST/SOAP APIs)  |
| Source platform    | PeopleSoft HCM / FSCM 9.2    |
