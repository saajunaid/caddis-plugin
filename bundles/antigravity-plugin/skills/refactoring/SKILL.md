---
name: refactoring
context: fork
description: Safely refactor code while maintaining behavior. Use when improving code structure, reducing duplication, extracting functions, or modernizing legacy code.
---

# Refactoring Skill

Systematically refactor code to improve quality while preserving functionality.

## Trigger

Activate when:
- User asks to "refactor" or "clean up" code
- Code review identifies structural issues
- User wants to improve maintainability
- Technical debt needs to be addressed

---

## Refactoring Principles

1. **Never change behavior** during refactoring
2. **Small steps** - one change at a time
3. **Tests first** - ensure coverage before changing
4. **Commit often** - after each successful refactoring
5. **One thing at a time** - don't mix refactoring with feature changes

### When NOT to Refactor

- Code that works and won't change again (if it ain't broke...)
- Critical production code without tests (add tests first)
- When under a tight deadline (schedule it for later)
- "Just because" - always have a clear purpose

---

## Phase 1: Assessment

### Objectives
- Understand current code structure
- Identify refactoring opportunities
- Assess test coverage

### Actions

1. **Read and understand the code**
   - What does this code do?
   - What are the inputs/outputs?
   - Where are the dependencies?

2. **Identify code smells**

   | Smell | Signs | Refactoring |
   |-------|-------|-------------|
   | Long Method | >20 lines | Extract Method |
   | Large Class | >200 lines, multiple concerns | Extract Class |
   | Duplicated Code | Same logic in multiple places | Extract Method/Class |
   | Long Parameter List | >3-4 parameters | Parameter Object |
   | Deep Nesting | >3 levels of indentation | Guard Clauses, Extract Method |
   | Magic Numbers | Hardcoded values | Named Constants |
   | Dead Code | Unused functions/variables | Delete |
   | Feature Envy | Method uses another class's data more | Move Method |

3. **Check test coverage**
   ```bash
   pytest --cov=module_name --cov-report=term-missing
   ```

### Output

```markdown
## Refactoring Assessment

### Current State
- File: [filename]
- Lines: [count]
- Test Coverage: [percentage]

### Code Smells Identified
1. [Smell]: [Location] - [Description]
2. [Smell]: [Location] - [Description]

### Recommended Refactorings
1. [Refactoring]: [Expected improvement]
2. [Refactoring]: [Expected improvement]

### Risk Assessment
- Test coverage: [adequate/needs improvement]
- Complexity: [low/medium/high]
- Dependencies: [list affected areas]
```

---

## Phase 2: Preparation

### Objectives
- Ensure adequate test coverage
- Set up for safe refactoring

### Actions

1. **Write missing tests** (if coverage < 80%)
   ```python
   def test_existing_behavior():
       """Capture current behavior before refactoring."""
       result = function_to_refactor(input_data)
       assert result == expected_output
   ```

2. **Create characterization tests** (for legacy code)
   ```python
   def test_characterization():
       """Document current behavior, even if unexpected."""
       # Run function and record actual output
       result = legacy_function(test_input)
       # Assert against actual output (not expected)
       assert result == actual_observed_output
   ```

3. **Run all tests** and ensure they pass
   ```bash
   pytest -v
   ```

4. **Commit current state**
   ```bash
   git add .
   git commit -m "chore: add tests before refactoring"
   ```

---

## Phase 3: Execute Refactoring

### Common Refactoring Patterns

#### Extract Method

```python
# Before: Long method with mixed concerns
def process_complaint(complaint):
    # Validation (10 lines)
    if not complaint.customer_id:
        raise ValueError("Customer ID required")
    if not complaint.description:
        raise ValueError("Description required")
    # ... more validation
    
    # Processing (15 lines)
    complaint.status = "processing"
    # ... processing logic
    
    # Notification (10 lines)
    send_email(complaint.customer_email, "...")
    # ... notification logic

# After: Extracted methods
def process_complaint(complaint):
    validate_complaint(complaint)
    process_complaint_logic(complaint)
    send_complaint_notification(complaint)

def validate_complaint(complaint):
    if not complaint.customer_id:
        raise ValueError("Customer ID required")
    if not complaint.description:
        raise ValueError("Description required")

def process_complaint_logic(complaint):
    complaint.status = "processing"
    # ... processing logic

def send_complaint_notification(complaint):
    send_email(complaint.customer_email, "...")
```

#### Extract Class

```python
# Before: Class doing too much
class ComplaintHandler:
    def __init__(self):
        self.db_connection = create_connection()
    
    def create_complaint(self, data):
        # 20 lines of complaint logic
        pass
    
    def send_email(self, to, subject, body):
        # 15 lines of email logic
        pass
    
    def generate_report(self, date_range):
        # 25 lines of reporting logic
        pass

# After: Separated concerns
class ComplaintHandler:
    def __init__(self, notifier, reporter):
        self.notifier = notifier
        self.reporter = reporter
    
    def create_complaint(self, data):
        # Complaint logic only
        pass

class EmailNotifier:
    def send_email(self, to, subject, body):
        pass

class ComplaintReporter:
    def generate_report(self, date_range):
        pass
```

#### Replace Conditionals with Polymorphism

```python
# Before: Switch-like conditionals
def calculate_priority_score(complaint):
    if complaint.type == "billing":
        return complaint.amount * 0.1
    elif complaint.type == "technical":
        return 50 + complaint.severity * 10
    elif complaint.type == "service":
        return 30 + complaint.wait_time * 2
    else:
        return 10

# After: Strategy pattern
class PriorityCalculator(Protocol):
    def calculate(self, complaint) -> float: ...

class BillingPriorityCalculator:
    def calculate(self, complaint) -> float:
        return complaint.amount * 0.1

class TechnicalPriorityCalculator:
    def calculate(self, complaint) -> float:
        return 50 + complaint.severity * 10

CALCULATORS = {
    "billing": BillingPriorityCalculator(),
    "technical": TechnicalPriorityCalculator(),
    "service": ServicePriorityCalculator(),
}

def calculate_priority_score(complaint):
    calculator = CALCULATORS.get(complaint.type, DefaultCalculator())
    return calculator.calculate(complaint)
```

#### Guard Clauses

```python
# Before: Deep nesting
def process(data):
    if data is not None:
        if data.is_valid:
            if data.has_permission:
                # Actual logic here
                result = do_something(data)
                return result
            else:
                raise PermissionError()
        else:
            raise ValueError("Invalid data")
    else:
        raise ValueError("Data required")

# After: Guard clauses
def process(data):
    if data is None:
        raise ValueError("Data required")
    if not data.is_valid:
        raise ValueError("Invalid data")
    if not data.has_permission:
        raise PermissionError()
    
    # Actual logic at main level
    return do_something(data)
```

#### Duplicated Code

```python
# Before: Same logic in multiple places
def get_user_discount(user):
    if user.membership == "gold": return user.total * 0.2
    if user.membership == "silver": return user.total * 0.1
    return 0

def get_order_discount(order):
    if order.user.membership == "gold": return order.total * 0.2
    if order.user.membership == "silver": return order.total * 0.1
    return 0

# After: Extract common logic
DISCOUNT_RATES = {"gold": 0.2, "silver": 0.1}

def get_membership_rate(membership: str) -> float:
    return DISCOUNT_RATES.get(membership, 0)
```

#### Long Parameter List → Parameter Object

```python
# Before: Too many parameters
def create_user(email, password, name, age, address, city, country, phone):
    ...

# After: Group into a dataclass
@dataclass
class UserData:
    email: str
    password: str
    name: str
    age: int | None = None
    address: str | None = None
    phone: str | None = None

def create_user(data: UserData):
    ...
```

#### Feature Envy → Move Method

```python
# Before: Method uses another object's data more than its own
class Order:
    def calculate_discount(self, user):
        if user.membership_level == "gold":
            return self.total * 0.2
        if user.account_age > 365:
            return self.total * 0.1
        return 0

# After: Move logic to the object that owns the data
class User:
    def get_discount_rate(self) -> float:
        if self.membership_level == "gold": return 0.2
        if self.account_age > 365: return 0.1
        return 0

class Order:
    def calculate_discount(self, user):
        return self.total * user.get_discount_rate()
```

#### Primitive Obsession → Value Objects

```python
# Before: Using raw strings for domain concepts
def send_email(to: str, subject: str, body: str): ...
send_email("user@example.com", "Hello", "...")

# After: Domain types with validation
class Email:
    def __init__(self, value: str):
        if "@" not in value:
            raise ValueError(f"Invalid email: {value}")
        self.value = value

def send_email(to: Email, subject: str, body: str): ...
```

#### Dead Code → Delete It

```python
# Before: Unused code lingers
def old_implementation(): ...     # Nobody calls this
DEPRECATED_VALUE = 5              # Not referenced
# def commented_out_code(): ...   # Noise

# After: Remove it — git has history if you need it back
```

### After Each Refactoring

1. **Run tests**
   ```bash
   pytest -v
   ```

2. **If tests pass, commit**
   ```bash
   git commit -m "refactor: extract validation to separate method"
   ```

3. **If tests fail, revert**
   ```bash
   git checkout -- .
   ```

---

## Phase 4: Validation

### Objectives
- Verify behavior unchanged
- Confirm quality improved
- Document changes

### Actions

1. **Run full test suite**
   ```bash
   pytest --cov=module_name
   ```

2. **Compare before/after metrics**
   - Lines of code
   - Cyclomatic complexity
   - Test coverage
   - Method/class sizes

3. **Manual smoke test**
   - Test key user flows
   - Verify edge cases

---

## Phase 5: Documentation

### Output

```markdown
## Refactoring Summary

### Changes Made
1. **[Refactoring 1]**: [What was changed and why]
2. **[Refactoring 2]**: [What was changed and why]

### Files Modified
- `path/to/file.py`: [Summary of changes]

### Metrics Comparison
| Metric | Before | After |
|--------|--------|-------|
| Lines of Code | [x] | [y] |
| Methods >20 lines | [x] | [y] |
| Test Coverage | [x]% | [y]% |

### Behavioral Changes
None (refactoring only)

### Tests Added
- `test_function_name`: [What it tests]

### Follow-up Recommendations
- [ ] [Future improvement 1]
- [ ] [Future improvement 2]
```

---

## Common Refactoring Operations Reference

| Operation | Description |
|-----------|-------------|
| Extract Method | Turn code fragment into a method |
| Extract Class | Move behavior to a new class |
| Inline Method | Move method body back to caller |
| Introduce Parameter Object | Group related parameters |
| Replace Conditional with Polymorphism | Use strategy/polymorphism instead of switch/if |
| Replace Magic Number with Constant | Named constants for clarity |
| Decompose Conditional | Break complex conditions into named functions |
| Replace Nested Conditional with Guard Clauses | Early returns |
| Introduce Null Object | Eliminate null checks |
| Replace Type Code with Enum | Strong typing for categories |
| Replace Inheritance with Delegation | Composition over inheritance |

---

## Safety Checklist

- [ ] Tests exist for code being refactored
- [ ] All tests pass before starting
- [ ] Refactoring in small, atomic steps
- [ ] Tests run after each change
- [ ] Commits after each successful refactoring
- [ ] No behavior changes introduced
- [ ] All tests pass after completion
- [ ] Changes documented
