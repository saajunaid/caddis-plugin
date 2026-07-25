---
name: db-testing
context: fork
description: Test, debug, and validate database connectivity and queries. Use when diagnosing connection errors, testing configurations, or validating queries before deployment.
---

# Database Testing Skill

Specialized skill for testing, debugging, and validating database connectivity and queries.

## When to Use

- User reports database connection errors
- Testing a new database configuration
- Validating queries before deployment
- Debugging data retrieval issues
- Verifying authentication configuration

---

## Steps

### Step 1: Network Connectivity Check

```bash
# Test if server is reachable
ping <DB_HOST>

# Test database port
# SQL Server: 1433, PostgreSQL: 5432, MySQL: 3306
telnet <DB_HOST> <DB_PORT>
```

### Step 2: Connection String Validation

Check environment configuration:

```env
DB_HOST=<server_name>
DB_NAME=<database_name>
DB_USER=<username>
DB_PASSWORD=<password>
DB_DRIVER=<driver_name>
```

### Step 3: Connection Test

```python
# Generic connection test pattern
import os

try:
    conn = create_connection(
        host=os.getenv("DB_HOST"),
        database=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
    )
    print("Connection successful!")
    cursor = conn.cursor()
    cursor.execute("SELECT 1")
    print(f"Query test: {cursor.fetchone()}")
    conn.close()
except Exception as e:
    print(f"Connection failed: {e}")
```

### Step 4: Query Validation

```python
query = "SELECT TOP 5 * FROM <table_name>"  # Adjust syntax for your DB
df = pd.read_sql(query, conn)
print(f"Returned {len(df)} rows")
print(df.columns.tolist())
```

---

## Common Issues & Solutions

| Error | Cause | Solution |
|-------|-------|---------|
| Connection refused | Server unreachable | Check network/VPN, firewall rules |
| Login failed | Auth issue | Verify credentials, check auth mode |
| Invalid connection string | Malformed config | Review driver docs for correct format |
| Certificate error | SSL validation | Configure trust settings for your DB |
| Driver not found | Missing driver | Install appropriate database driver |

---

## Output Format

```markdown
## Database Connection Test Results

**Server**: `<server>`
**Database**: `<database>`
**Auth Mode**: <auth_type>

| Test | Status | Details |
|------|--------|---------|
| Network ping | Pass/Fail | Response time |
| Port check | Pass/Fail | TCP connection |
| DB connection | Pass/Fail | Driver info |
| Sample query | Pass/Fail | Row count |

**Conclusion**: [Summary]
```

## Checklist

- [ ] Network connectivity verified
- [ ] Connection string validated
- [ ] Authentication working
- [ ] Sample query returns expected results
- [ ] Error handling tested
- [ ] Connection cleanup (close/dispose) confirmed
