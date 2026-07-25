---
name: ui-testing
context: fork
description: Create automated UI tests using Playwright for Streamlit and web applications. Use when writing end-to-end tests, automating UI testing, or testing new features.
---

# UI Testing Skill

## Trigger
- User requests "create UI tests for..."
- User requests "write end-to-end tests..."
- User requests "automate testing for..."
- Testing new Streamlit pages or features

## Workflow Steps

### Step 1: Analyze Target Application
```markdown
Examine the application to understand:
1. Key user workflows to test
2. Critical UI components
3. Form inputs and validations
4. Navigation flows
5. Data-dependent features

Questions to answer:
- What are the critical paths users take?
- What data needs to be mocked?
- Are there authentication requirements?
- What assertions validate success?
```

### Step 2: Plan Test Structure
```markdown
Create test plan outline:

## Test Suite: [Feature Name]

### Happy Path Tests
- [ ] Test basic functionality works
- [ ] Test all form inputs accept valid data
- [ ] Test navigation between pages
- [ ] Test data displays correctly

### Error Handling Tests
- [ ] Test form validation errors
- [ ] Test API error handling
- [ ] Test empty state displays
- [ ] Test loading state displays

### Edge Cases
- [ ] Test with minimum input
- [ ] Test with maximum input
- [ ] Test special characters
- [ ] Test concurrent actions

### Accessibility Tests
- [ ] Test keyboard navigation
- [ ] Test focus management
- [ ] Test screen reader compatibility
```

### Step 3: Set Up Test Environment
```python
# tests/conftest.py
import pytest
from playwright.sync_api import Page, expect

# Base URL configuration
BASE_URL = "http://localhost:8501"  # Streamlit default

@pytest.fixture(scope="session")
def browser_context_args(browser_context_args):
    """Configure browser context."""
    return {
        **browser_context_args,
        "viewport": {"width": 1280, "height": 720},
        "base_url": BASE_URL,
    }

@pytest.fixture
def app_page(page: Page):
    """Navigate to app and wait for load."""
    page.goto("/")
    # Wait for Streamlit to initialize
    page.wait_for_selector("[data-testid='stAppViewContainer']")
    return page

@pytest.fixture
def mock_api(page: Page):
    """Mock API responses for isolated testing."""
    def setup_mocks():
        page.route("**/api/data", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"items": [], "total": 0}'
        ))
    setup_mocks()
    return page
```

### Step 4: Create Page Objects
```python
# tests/pages/dashboard_page.py
from playwright.sync_api import Page, expect

class DashboardPage:
    """Page object for Dashboard."""
    
    URL = "/dashboard"
    
    def __init__(self, page: Page):
        self.page = page
        # Define locators
        self.title = page.get_by_role("heading", level=1)
        self.metric_cards = page.get_by_test_id("metric-card")
        self.date_filter = page.get_by_label("Date Range")
        self.refresh_btn = page.get_by_role("button", name="Refresh")
        self.chart = page.locator(".js-plotly-plot")
        self.loading = page.get_by_test_id("loading-spinner")
    
    def navigate(self):
        """Navigate to dashboard."""
        self.page.goto(self.URL)
        self.wait_for_load()
    
    def wait_for_load(self):
        """Wait for dashboard to fully load."""
        expect(self.loading).to_be_hidden()
        expect(self.title).to_be_visible()
    
    def select_date_range(self, option: str):
        """Select date range from filter."""
        self.date_filter.click()
        self.page.get_by_role("option", name=option).click()
        self.wait_for_load()
    
    def refresh_data(self):
        """Click refresh and wait for update."""
        self.refresh_btn.click()
        self.wait_for_load()
    
    def get_metric_count(self) -> int:
        """Get number of metric cards displayed."""
        return self.metric_cards.count()
    
    def assert_chart_visible(self):
        """Verify chart is rendered."""
        expect(self.chart).to_be_visible()
```

### Step 5: Write Tests
```python
# tests/test_dashboard.py
import pytest
from playwright.sync_api import Page, expect
from pages.dashboard_page import DashboardPage

class TestDashboard:
    """Dashboard feature tests."""
    
    @pytest.fixture(autouse=True)
    def setup(self, app_page: Page):
        """Set up test fixtures."""
        self.page = app_page
        self.dashboard = DashboardPage(app_page)
        self.dashboard.navigate()
    
    # Happy Path Tests
    def test_dashboard_loads_successfully(self):
        """Verify dashboard loads with expected elements."""
        expect(self.dashboard.title).to_have_text("Network Dashboard")
        assert self.dashboard.get_metric_count() >= 4
        self.dashboard.assert_chart_visible()
    
    def test_date_filter_updates_data(self):
        """Verify date filter changes displayed data."""
        self.dashboard.select_date_range("Last 7 Days")
        expect(self.page.get_by_text("Last 7 Days")).to_be_visible()
    
    def test_refresh_button_reloads_data(self):
        """Verify refresh button updates the data."""
        self.dashboard.refresh_data()
        # Chart should still be visible after refresh
        self.dashboard.assert_chart_visible()
    
    # Accessibility Tests
    def test_keyboard_navigation(self):
        """Verify all interactive elements are keyboard accessible."""
        # Focus on first interactive element
        self.page.keyboard.press("Tab")
        
        # Navigate through elements
        for _ in range(5):
            focused = self.page.evaluate("document.activeElement.tagName")
            assert focused in ["BUTTON", "A", "INPUT", "SELECT"]
            self.page.keyboard.press("Tab")
    
    def test_focus_visible_on_buttons(self):
        """Verify focus indicators are visible on buttons."""
        self.dashboard.refresh_btn.focus()
        # Check that button has focus styling
        assert self.dashboard.refresh_btn.evaluate(
            "el => window.getComputedStyle(el, ':focus').outline !== 'none'"
        )
```

### Step 6: Add Streamlit-Specific Tests
```python
# tests/test_streamlit_components.py
from playwright.sync_api import Page, expect

class TestStreamlitForm:
    """Tests for Streamlit form components."""
    
    def test_text_input_accepts_value(self, page: Page):
        """Test Streamlit text input."""
        page.goto("/form")
        
        input_field = page.get_by_label("Your Name")
        input_field.fill("Test User")
        
        expect(input_field).to_have_value("Test User")
    
    def test_selectbox_selection(self, page: Page):
        """Test Streamlit selectbox."""
        page.goto("/form")
        
        # Click selectbox to open
        page.get_by_label("Choose Option").click()
        
        # Select option
        page.get_by_role("option", name="Option B").click()
        
        # Verify selection persisted
        expect(page.get_by_text("Selected: Option B")).to_be_visible()
    
    def test_form_submission(self, page: Page):
        """Test complete form submission."""
        page.goto("/form")
        
        # Fill form
        page.get_by_label("Name").fill("Test User")
        page.get_by_label("Email").fill("test@example.com")
        
        # Submit
        page.get_by_role("button", name="Submit").click()
        
        # Verify success message
        expect(page.get_by_text("Form submitted successfully")).to_be_visible()
    
    def test_file_upload(self, page: Page):
        """Test file upload component."""
        page.goto("/upload")
        
        # Upload file
        page.get_by_label("Upload CSV").set_input_files("tests/fixtures/test.csv")
        
        # Verify file processed
        expect(page.get_by_text("File uploaded: test.csv")).to_be_visible()
```

### Step 7: Run Tests and Generate Report
```bash
# Run all tests
pytest tests/ -v

# Run with HTML report
pytest tests/ --html=report.html --self-contained-html

# Run with coverage
pytest tests/ --cov=src --cov-report=html

# Run specific test file
pytest tests/test_dashboard.py -v

# Run tests matching pattern
pytest tests/ -k "dashboard" -v

# Run with tracing for debugging
pytest tests/ --tracing=on
```

## Output Format

```markdown
## UI Test Results

### Test Suite: [Feature Name]

#### Tests Created
- `test_feature_loads_successfully` ✓
- `test_form_validation_errors` ✓
- `test_keyboard_navigation` ✓

#### Coverage
- Pages tested: 3
- Components tested: 12
- User flows covered: 5

#### Files Generated
- `tests/test_[feature].py`
- `tests/pages/[feature]_page.py`
- `tests/conftest.py` (if new)

#### Run Command
```bash
pytest tests/test_[feature].py -v
```
```

## Best Practices

1. **Use Page Objects**: Abstract page interactions into reusable classes
2. **Prefer Role-Based Locators**: Use `get_by_role()` for resilience
3. **Avoid Hard Waits**: Use `expect()` auto-retry assertions
4. **Test Accessibility**: Include keyboard and screen reader tests
5. **Mock External APIs**: Isolate tests from external dependencies
6. **Keep Tests Independent**: No test should depend on another
7. **Use Descriptive Names**: Test names should explain what they verify

---

## Regression Test Templates

> Appended from qa-regression: reusable Playwright regression test patterns.

# QA Regression Testing

Build and run automated regression tests using Playwright. Each test is a reusable skill that can be composed into full test suites.

## Setup

```bash
npm init -y
npm install playwright @playwright/test
npx playwright install
```

## Test Structure

Create tests in `tests/` folder:

```
tests/
├── auth/
│   ├── login.spec.ts
│   └── logout.spec.ts
├── dashboard/
│   └── load.spec.ts
├── users/
│   ├── create.spec.ts
│   └── delete.spec.ts
└── regression.spec.ts   # Full suite
```

## Common Test Skills

### Login Test

```typescript
// tests/auth/login.spec.ts
import { test, expect } from '@playwright/test';

test.describe('Login Flow', () => {
  test('should login with valid credentials', async ({ page }) => {
    await page.goto('/login');

    await page.fill('[data-testid="email"]', process.env.TEST_EMAIL!);
    await page.fill('[data-testid="password"]', process.env.TEST_PASSWORD!);
    await page.click('[data-testid="submit"]');

    // Verify redirect to dashboard
    await expect(page).toHaveURL(/dashboard/);
    await expect(page.locator('[data-testid="user-menu"]')).toBeVisible();
  });

  test('should show error for invalid credentials', async ({ page }) => {
    await page.goto('/login');

    await page.fill('[data-testid="email"]', 'wrong@example.com');
    await page.fill('[data-testid="password"]', 'wrongpassword');
    await page.click('[data-testid="submit"]');

    await expect(page.locator('[data-testid="error-message"]')).toBeVisible();
  });
});
```

### Dashboard Load Test

```typescript
// tests/dashboard/load.spec.ts
import { test, expect } from '@playwright/test';
import { login } from '../helpers/auth';

test.describe('Dashboard', () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
  });

  test('should load dashboard within 3 seconds', async ({ page }) => {
    const start = Date.now();
    await page.goto('/dashboard');
    await page.waitForSelector('[data-testid="dashboard-content"]');
    const loadTime = Date.now() - start;

    expect(loadTime).toBeLessThan(3000);
  });

  test('should display all widgets', async ({ page }) => {
    await page.goto('/dashboard');

    await expect(page.locator('[data-testid="stats-widget"]')).toBeVisible();
    await expect(page.locator('[data-testid="chart-widget"]')).toBeVisible();
    await expect(page.locator('[data-testid="activity-widget"]')).toBeVisible();
  });

  test('should refresh data on button click', async ({ page }) => {
    await page.goto('/dashboard');

    const initialValue = await page.locator('[data-testid="last-updated"]').textContent();
    await page.click('[data-testid="refresh-button"]');
    await page.waitForTimeout(1000);
    const newValue = await page.locator('[data-testid="last-updated"]').textContent();

    expect(newValue).not.toBe(initialValue);
  });
});
```

### Create User Test

```typescript
// tests/users/create.spec.ts
import { test, expect } from '@playwright/test';
import { login } from '../helpers/auth';
import { generateTestUser, deleteTestUser } from '../helpers/users';

test.describe('User Creation', () => {
  let testUser: { email: string; name: string };

  test.beforeEach(async ({ page }) => {
    await login(page);
    testUser = generateTestUser();
  });

  test.afterEach(async () => {
    // Cleanup
    await deleteTestUser(testUser.email);
  });

  test('should create new user successfully', async ({ page }) => {
    await page.goto('/users/new');

    await page.fill('[data-testid="user-name"]', testUser.name);
    await page.fill('[data-testid="user-email"]', testUser.email);
    await page.selectOption('[data-testid="user-role"]', 'member');
    await page.click('[data-testid="create-user-btn"]');

    // Verify success
    await expect(page.locator('[data-testid="success-toast"]')).toBeVisible();
    await expect(page).toHaveURL(/users/);

    // Verify user appears in list
    await expect(page.locator(`text=${testUser.email}`)).toBeVisible();
  });

  test('should validate required fields', async ({ page }) => {
    await page.goto('/users/new');
    await page.click('[data-testid="create-user-btn"]');

    await expect(page.locator('[data-testid="name-error"]')).toBeVisible();
    await expect(page.locator('[data-testid="email-error"]')).toBeVisible();
  });
});
```

## Shared Helpers

```typescript
// tests/helpers/auth.ts
import { Page } from '@playwright/test';

export async function login(page: Page) {
  await page.goto('/login');
  await page.fill('[data-testid="email"]', process.env.TEST_EMAIL!);
  await page.fill('[data-testid="password"]', process.env.TEST_PASSWORD!);
  await page.click('[data-testid="submit"]');
  await page.waitForURL(/dashboard/);
}

export async function logout(page: Page) {
  await page.click('[data-testid="user-menu"]');
  await page.click('[data-testid="logout"]');
  await page.waitForURL(/login/);
}
```

```typescript
// tests/helpers/users.ts
export function generateTestUser() {
  const id = Date.now();
  return {
    name: `Test User ${id}`,
    email: `test-${id}@example.com`,
  };
}

export async function deleteTestUser(email: string) {
  // API call to cleanup test user
  await fetch(`${process.env.API_URL}/admin/users`, {
    method: 'DELETE',
    headers: {
      'Authorization': `Bearer ${process.env.ADMIN_TOKEN}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ email }),
  });
}
```

## Full Regression Suite

```typescript
// tests/regression.spec.ts
import { test } from '@playwright/test';

// Import all test suites
import './auth/login.spec';
import './auth/logout.spec';
import './dashboard/load.spec';
import './users/create.spec';
import './users/delete.spec';

test.describe('Full Regression Suite', () => {
  // Tests run in order defined above
});
```

## Playwright Config

```typescript
// playwright.config.ts
import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './tests',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: [
    ['html'],
    ['json', { outputFile: 'test-results.json' }],
  ],
  use: {
    baseURL: process.env.BASE_URL || 'http://localhost:3000',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
    {
      name: 'firefox',
      use: { ...devices['Desktop Firefox'] },
    },
    {
      name: 'webkit',
      use: { ...devices['Desktop Safari'] },
    },
  ],
});
```

## Running Tests

```bash
# Run all tests
npx playwright test

# Run specific test file
npx playwright test tests/auth/login.spec.ts

# Run tests with UI
npx playwright test --ui

# Run in headed mode (see browser)
npx playwright test --headed

# Generate report
npx playwright show-report
```

## CI Integration

```yaml
# .github/workflows/regression.yml
name: Regression Tests
context: fork

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]
  schedule:
    - cron: '0 6 * * *'  # Daily at 6 AM

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: 20

      - name: Install dependencies
        run: npm ci

      - name: Install Playwright
        run: npx playwright install --with-deps

      - name: Run tests
        run: npx playwright test
        env:
          BASE_URL: ${{ secrets.STAGING_URL }}
          TEST_EMAIL: ${{ secrets.TEST_EMAIL }}
          TEST_PASSWORD: ${{ secrets.TEST_PASSWORD }}

      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: playwright-report
          path: playwright-report/
```

## Best Practices

1. **Use data-testid attributes** - More stable than CSS selectors
2. **Clean up test data** - Always delete what you create
3. **Avoid hardcoded waits** - Use `waitForSelector` instead of `waitForTimeout`
4. **Run in parallel** - Faster feedback on CI
5. **Screenshot on failure** - Easier debugging
6. **Environment variables** - Never commit credentials

## Quick Commands

| Task | Command |
|------|---------|
| Run all | `npx playwright test` |
| Run one file | `npx playwright test login.spec.ts` |
| Debug mode | `npx playwright test --debug` |
| UI mode | `npx playwright test --ui` |
| Update snapshots | `npx playwright test --update-snapshots` |

