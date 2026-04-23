# PeopleCode → Python Migration Playbook

> **Purpose**: Reusable playbook for Devin to migrate PeopleSoft PeopleCode objects to Python services targeting Workday.
> Designed for batch execution across hundreds of custom objects.

---

## Scope

This playbook covers migration of **code-based** PeopleSoft customizations:

| Source (PeopleSoft)                  | Target (Python)                         | Pattern     |
|--------------------------------------|-----------------------------------------|-------------|
| Application Engine programs          | FastAPI endpoint + JSON                 | Report      |
| Component Interfaces                 | REST API endpoint                       | Interface   |
| Integration Broker handlers          | Event-driven service (queue-based)      | Interface   |
| Component PeopleCode (record/page)   | Service layer module                    | Enhancement |
| SQR reports                          | PDF generation (WeasyPrint/ReportLab)   | Report      |

**Out of scope** (requires PeopleSoft functional consultants):
- PeopleSoft configuration (SetID, TableSets, Tree Manager)
- Approval workflow engine rules
- Security permission lists and roles
- Process Scheduler job definitions
- nVision report layouts
- Fluid / Classic page redesign

---

## Pre-Migration Checklist

Before starting migration of any PeopleCode object:

- [ ] Source PeopleCode is exported and accessible
- [ ] Business owner has confirmed the object is still in use
- [ ] Target architecture is defined (API framework, database, deployment)
- [ ] Record/table dependencies are mapped (which PS_ tables are read/written)
- [ ] Test data is available (sample inputs and expected outputs)
- [ ] Acceptance criteria defined (functional equivalence tests)

---

## Migration Steps

### Step 1: Analyze the PeopleCode Source

Read the PeopleCode program and identify:

1. **Input parameters**: Run control fields, Component Interface properties, IB message fields
2. **Data sources**: PeopleSoft tables accessed (PS_JOB, PS_VENDOR, PS_PO_HDR, etc.) and their joins
3. **Business logic**: Calculations, Evaluate blocks, validations, conditional flows
4. **Output format**: CSV file, CI output properties, IB response XML, rowset data
5. **Dependencies**: Called Application Packages, SQL objects, Component Interfaces
6. **Error handling**: If/Else checks, Error() calls, MessageBox(), try/catch blocks

Document these in a structured format before writing any Python code.

### Step 2: Design the Python Target

Map each PeopleCode component to its Python equivalent:

| PeopleCode Concept                   | Python Equivalent                        |
|--------------------------------------|------------------------------------------|
| Rowset / CreateRowset()              | `list[Model]`                            |
| Record / GetRecord()                 | Pydantic `BaseModel`                     |
| SQLExec / CreateSQL                  | SQL query → ORM / raw SQL                |
| Fill("WHERE ...")                    | Filtered query / list comprehension      |
| Evaluate / When                      | `if/elif` or `match/case`               |
| &field.Value                         | Model attribute access                   |
| Component Interface                  | REST API endpoint                        |
| Integration Broker message           | JSON message from queue                  |
| %IntBroker.GetMessage()              | Message consumer / webhook               |
| &MSG.GetXmlDoc()                     | JSON deserialization (Pydantic)          |
| XmlNode.FindNode()                   | Dict/model field access                  |
| Run Control record                   | API query parameters / request body      |
| IsUserInRole()                       | JWT / API key middleware                 |
| Error() / MessageBox()               | HTTPException / raise                    |
| CommitWork()                         | Database transaction commit              |
| RollbackWork()                       | Database transaction rollback            |
| Application Engine step              | Python function                          |
| GetFile() / WriteLine()             | JSON response / file export              |
| %Date / %DateTime                    | `date.today()` / `datetime.now()`       |
| DatePart() / AddToDate()            | `date.year` / `timedelta`              |
| All() / None() checks               | Truthiness / `is None`                  |

### Step 3: Create Data Models

For each PeopleCode Record or structure:

```python
from pydantic import BaseModel, Field

class EmployeeRecord(BaseModel):
    """Maps to PeopleCode PS_JOB + PS_PERSONAL_DATA join.

    Source fields: PS_JOB.EMPLID, PS_PERSONAL_DATA.NAME_DISPLAY, etc.
    """
    employee_id: str = Field(description="PS_JOB.EMPLID")
    name: str = Field(description="PS_PERSONAL_DATA.NAME_DISPLAY")
    annual_rate: Decimal = Field(description="PS_JOB.ANNUAL_RT")
```

**Rules**:
- One model per PeopleCode Record or logical data structure
- Include Field descriptions mapping to PeopleSoft record.field names
- Use Python-native types (Decimal for amounts, date for date fields)
- Add docstrings referencing the source PeopleCode record/table name

### Step 4: Implement Business Logic

Translate PeopleCode logic to Python functions:

- Each Application Engine step → one Python function
- Each major Evaluate block → one function with clear mapping
- Preserve the same function name (converted to snake_case)
- Add comments mapping to PeopleCode logic for traceability
- Keep the same control flow structure where possible

**Critical**: Do NOT "improve" the business logic during migration.
The goal is **functional equivalence**, not optimization.
Optimizations come in a separate phase after migration is validated.

### Step 5: Write Equivalence Tests

For each migrated function, write tests that verify:

1. **Happy path**: Same input → same output as PeopleCode
2. **Edge cases**: Empty rowsets, zero values, None/blank fields
3. **Boundary conditions**: Threshold values (e.g., stale days exactly)
4. **Error cases**: Invalid input → same error behavior as PeopleCode

Test naming convention:
```python
def test_<function_name>_<scenario>():
    """PeopleCode: <reference to original logic>."""
```

### Step 6: Validate and Review

- [ ] All tests pass
- [ ] Every PeopleCode step/method has a corresponding Python function
- [ ] Every PeopleCode Record has a corresponding Pydantic model
- [ ] Business logic matches 1:1 (no accidental "improvements")
- [ ] Error handling covers all PeopleCode Error()/MessageBox() paths
- [ ] Comments reference original PeopleCode for traceability

---

## Migration Patterns by Object Type

### Pattern A: Application Engine → FastAPI + JSON

```
PeopleCode Flow:                    Python Flow:
─────────────────                   ────────────
Run Control record  ─────────►     Query Parameters / Request Body
    │                                   │
    ▼                                   ▼
SQLExec / Fill      ─────────►     SQL Query / ORM / Data Warehouse
    │                                   │
    ▼                                   ▼
For loop + Evaluate ─────────►     List comprehension + functions
    │                                   │
    ▼                                   ▼
Filter rowset       ─────────►     filter() + sort()
    │                                   │
    ▼                                   ▼
GetFile / WriteLine ─────────►     JSON Response + Dashboard
```

### Pattern B: Component Interface → REST API

```
PeopleCode Flow:                    Python Flow:
─────────────────                   ────────────
CI.Get() / properties ─────────►   Path/query params or request body
    │                                   │
    ▼                                   ▼
IsUserInRole()       ─────────►    Auth middleware (JWT/API key)
    │                                   │
    ▼                                   ▼
CreateRowset / Fill  ─────────►    Database query
    │                                   │
    ▼                                   ▼
Process + aggregate  ─────────►    Service function
    │                                   │
    ▼                                   ▼
CI output properties ─────────►    JSON response body
    │                                   │
    ▼                                   ▼
Error()              ─────────►    HTTPException / error response
```

### Pattern C: Integration Broker → Event-Driven Service

```
PeopleCode Flow:                    Python Flow:
─────────────────                   ────────────
%IntBroker.GetMessage() ────────►  Message consumer / webhook
    │                                   │
    ▼                                   ▼
&MSG.GetXmlDoc()       ────────►   JSON deserialization
XmlNode.FindNode()                 (Pydantic model validation)
    │                                   │
    ▼                                   ▼
Validate fields        ────────►   validate_message() function
    │                                   │
    ▼                                   ▼
Build target XML       ────────►   Build target system payload
    │                                   │
    ▼                                   ▼
CallTargetSystem       ────────►   Target API call (Workday)
    │                                   │
    ▼                                   ▼
CommitWork/RollbackWork ───────►   Transaction commit/rollback
    │                                   │
    ▼                                   ▼
%IntBroker.Publish(resp) ──────►   Processing result record
```

---

## Common PeopleCode → Python Translations

### Rowset Operations

```
/* PeopleCode */
&rsEmployees = CreateRowset(Record.JOB);
&rsEmployees.Fill("WHERE BUSINESS_UNIT = :1 AND EMPL_STATUS = :2", &bu, "A");

For &i = 1 To &rsEmployees.ActiveRowCount
   &rec = &rsEmployees(&i).GetRecord(Record.JOB);
   &empName = &rec.NAME_DISPLAY.Value;
End-For;
```

```python
# Python
employees = [
    EmployeeRecord(**row)
    for row in query_results
    if row["business_unit"] == bu and row["empl_status"] == "A"
]

for emp in employees:
    emp_name = emp.name
```

### SQLExec with Parameters

```
/* PeopleCode */
Local string &name, &dept;
SQLExec("SELECT NAME_DISPLAY, DEPTID FROM PS_PERSONAL_DATA A, PS_JOB B WHERE A.EMPLID = B.EMPLID AND B.EMPLID = :1", &emplId, &name, &dept);
```

```python
# Python (SQLAlchemy)
result = session.execute(
    select(PersonalData.name_display, Job.department_id)
    .join(Job, Job.employee_id == PersonalData.employee_id)
    .where(Job.employee_id == empl_id)
).first()
name, dept = result.name_display, result.department_id
```

### Error Handling

```
/* PeopleCode */
try
   &result = CallTargetSystem(&payload);
   CommitWork();
catch Exception &ex
   RollbackWork();
   &errorMsg = &ex.ToString();
   Error("Processing failed: " | &errorMsg);
end-try;
```

```python
# Python
try:
    result = call_target_system(payload)
    db.commit()
    return SyncResult(status=ProcessingStatus.SUCCESS, ...)
except Exception as exc:
    db.rollback()
    return SyncResult(status=ProcessingStatus.ERROR, error_messages=[str(exc)])
```

### Evaluate Block (Status Mapping)

```
/* PeopleCode */
Evaluate &emplStatus
When = "A"
   &category = "ACTIVE";
   Break;
When = "L"
When = "P"
   &category = "LOA";
   Break;
When = "T"
When = "D"
   &category = "TERMINATED";
   Break;
When-Other
   &category = "LOA";
   Break;
End-Evaluate;
```

```python
# Python
STATUS_MAP: dict[str, StatusCategory] = {
    "A": StatusCategory.ACTIVE,
    "L": StatusCategory.LOA,
    "P": StatusCategory.LOA,
    "T": StatusCategory.TERMINATED,
    "D": StatusCategory.TERMINATED,
    "R": StatusCategory.RETIRED,
}
category = STATUS_MAP.get(empl_status, StatusCategory.LOA)
```

---

## Quality Checklist

Before marking any migrated object as complete:

- [ ] All unit tests pass
- [ ] Code follows project style guide (PEP 8, type hints, docstrings)
- [ ] No PeopleCode-isms in Python (e.g., &variable naming, .Value access patterns)
- [ ] Pydantic models validate input/output correctly
- [ ] Error messages are clear and actionable
- [ ] Logging captures key business events
- [ ] Migration comments reference original PeopleCode step/method names
- [ ] No hardcoded values that should be configurable
- [ ] Performance is acceptable for expected data volumes
