---
name: sql
description: Write high-quality, optimized SQL with best practices for performance, NULL handling, security, and readability. Database-agnostic patterns with dialect-specific notes.
---

# SQL Expert Skill

Write high-quality, optimized SQL for enterprise environments. Covers performance, edge cases, and real-world gotchas.

## When to Use

- Writing new SQL queries
- Optimizing existing queries
- Handling large datasets (100K+ rows)
- Creating stored procedures or views
- Debugging slow queries

---

## SQL Quality Standards

### 1. Always Include Comments

```sql
-- Get open orders with SLA breach risk
-- Filters: Last 7 days, excludes test data
-- Expected rows: ~500-2000
SELECT
    OrderID,
    CustomerName,
    DATEDIFF(HOUR, CreatedAt, GETDATE()) AS hours_open
FROM Orders
WHERE CreatedAt >= DATEADD(DAY, -7, GETDATE())
    AND Status = 'Open'
ORDER BY hours_open DESC;
```

### 2. Readable Formatting

```sql
SELECT
    o.OrderID,
    o.CustomerName,
    o.Status,
    COUNT(i.ItemID) AS item_count
FROM Orders o
LEFT JOIN OrderItems i ON o.OrderID = i.OrderID
WHERE o.Status = 'Open'
GROUP BY o.OrderID, o.CustomerName, o.Status
HAVING COUNT(i.ItemID) > 0
ORDER BY item_count DESC;
```

---

## Large Dataset Patterns

### Pagination

```sql
-- OFFSET-FETCH (SQL Server 2012+ / PostgreSQL)
SELECT OrderID, CustomerName, Status
FROM Orders
WHERE Status = 'Open'
ORDER BY CreatedAt DESC
OFFSET 50 ROWS FETCH NEXT 25 ROWS ONLY;

-- Keyset pagination (faster for deep pages)
SELECT TOP 25 OrderID, CustomerName, CreatedAt
FROM Orders
WHERE CreatedAt < @lastSeenDate AND Status = 'Open'
ORDER BY CreatedAt DESC;
```

### Batching Large Operations

```sql
DECLARE @BatchSize INT = 5000;
DECLARE @RowsAffected INT = 1;

WHILE @RowsAffected > 0
BEGIN
    UPDATE TOP (@BatchSize) Orders
    SET ProcessedFlag = 1
    WHERE Status = 'Closed' AND ProcessedFlag = 0;
    SET @RowsAffected = @@ROWCOUNT;
    WAITFOR DELAY '00:00:00.100';
END
```

---

## NULL Handling

```sql
-- Use IS NULL (not = NULL)
SELECT * FROM Orders WHERE Category IS NULL;

-- ISNULL (SQL Server) vs COALESCE (ANSI standard)
SELECT ISNULL(Category, 'Unknown') FROM Orders;
SELECT COALESCE(Category, SubCategory, 'Unknown') FROM Orders;

-- NULL in aggregations: COUNT(*) counts all, COUNT(col) excludes NULLs
SELECT COUNT(*) AS total, COUNT(Category) AS non_null FROM Orders;
SELECT ISNULL(SUM(Amount), 0) AS total FROM Orders;
```

---

## Performance Killers to Avoid

1. **Implicit type conversions** -- match parameter types to column types
2. **Functions on indexed columns** -- rewrite `WHERE YEAR(date) = 2026` as range
3. **OR conditions** -- consider UNION ALL for index use
4. **SELECT DISTINCT on large sets** -- use GROUP BY or EXISTS
5. **UNION vs UNION ALL** -- use UNION ALL when duplicates are OK

---

## Window Functions

```sql
-- Running totals
SELECT OrderID, CreatedAt,
    COUNT(*) OVER (ORDER BY CreatedAt) AS running_count,
    SUM(Amount) OVER (ORDER BY CreatedAt) AS running_total
FROM Orders;

-- Latest record per group
WITH ranked AS (
    SELECT *, ROW_NUMBER() OVER (PARTITION BY CustomerID ORDER BY CreatedAt DESC) AS rn
    FROM Orders
)
SELECT * FROM ranked WHERE rn = 1;
```

---

## Error Handling

```sql
BEGIN TRY
    BEGIN TRANSACTION;
    UPDATE Orders SET Status = 'Processed' WHERE OrderID = @OrderID;
    IF @@ROWCOUNT = 0 THROW 50001, 'Order not found', 1;
    COMMIT;
END TRY
BEGIN CATCH
    IF @@TRANCOUNT > 0 ROLLBACK;
    DECLARE @ErrorMsg NVARCHAR(4000) = ERROR_MESSAGE();
    RAISERROR(@ErrorMsg, ERROR_SEVERITY(), ERROR_STATE());
END CATCH;
```

---

## Security (CRITICAL)

```sql
-- NEVER concatenate user input
-- Always use parameterized queries
EXEC sp_executesql N'SELECT * FROM Orders WHERE OrderID = @id',
    N'@id UNIQUEIDENTIFIER', @id = @orderId;
```

```python
# Python: always parameterized
query = "SELECT * FROM Orders WHERE Status = ?"
result = adapter.fetch_dataframe(query, (user_input,))
```

---

## EXISTS vs IN vs JOIN

```sql
-- EXISTS: Best for "does any match exist?" - stops at first match
SELECT * FROM Customers c
WHERE EXISTS (SELECT 1 FROM Orders WHERE CustomerID = c.CustomerID);

-- IN: Good for small lists, can be slow with NULLs in subquery
SELECT * FROM Orders WHERE CustomerID IN ('CUST001', 'CUST002', 'CUST003');

-- ⚠️ IN with subquery containing NULLs can return unexpected results
SELECT * FROM Orders 
WHERE CustomerID IN (SELECT CustomerID FROM FlaggedCustomers);  -- If NULL in subquery, watch out!

-- JOIN: Best when you need columns from both tables
SELECT c.*, o.OrderID
FROM Customers c
INNER JOIN Orders o ON c.CustomerID = o.CustomerID;
```

---

## Concurrency & Locking

### Read Patterns

```sql
-- For reports/dashboards (OK with slightly stale data)
SELECT * FROM Orders WITH (NOLOCK)  -- Dirty reads, but no blocking
WHERE Status = 'Open';

-- ⚠️ NOLOCK risks:
-- - Can read uncommitted data (that might roll back)
-- - Can read rows twice or skip rows during scans
-- Only use for approximate counts, dashboards, reports

-- For accurate reads that shouldn't block
SET TRANSACTION ISOLATION LEVEL READ COMMITTED SNAPSHOT;
-- Requires database setting: ALTER DATABASE [DB] SET READ_COMMITTED_SNAPSHOT ON;
```

### Deadlock Prevention

```sql
-- ✅ Always access tables in same order across all processes
-- ✅ Keep transactions short

BEGIN TRANSACTION;
    UPDATE Orders SET Status = 'Processed' WHERE OrderID = @id;
COMMIT;
```

---

## Temp Tables vs Table Variables

```sql
-- TEMP TABLES: Better for large datasets (has statistics)
CREATE TABLE #TempOrders (
    OrderID VARCHAR(50),
    CustomerID VARCHAR(50),
    INDEX IX_Temp_CustomerID (CustomerID)
);
INSERT INTO #TempOrders SELECT OrderID, CustomerID FROM Orders WHERE Status = 'Open';
SELECT * FROM #TempOrders t JOIN Customers c ON t.CustomerID = c.CustomerID;
DROP TABLE #TempOrders;

-- TABLE VARIABLES: Better for small datasets (<1000 rows)
DECLARE @Orders TABLE (OrderID VARCHAR(50), CustomerID VARCHAR(50));
INSERT INTO @Orders SELECT OrderID, CustomerID FROM Orders WHERE Status = 'Closed';
-- ⚠️ Table variables assume 1 row for optimization - bad for large sets
```

---

## Date/Time Gotchas

```sql
-- ❌ BAD: String comparison for dates (locale issues)
SELECT * FROM Orders WHERE CreatedAt > '01/02/2026';  -- Jan 2 or Feb 1?

-- ✅ GOOD: Use unambiguous ISO format
SELECT * FROM Orders WHERE CreatedAt > '2026-01-02';

-- Date range queries (include full day)
-- ❌ WRONG: BETWEEN misses end-of-day records
SELECT * FROM Orders WHERE CreatedAt BETWEEN '2026-01-01' AND '2026-01-31';

-- ✅ CORRECT: Use < next day
SELECT * FROM Orders 
WHERE CreatedAt >= '2026-01-01' AND CreatedAt < '2026-02-01';

-- Get date part only (for grouping)
SELECT CAST(CreatedAt AS DATE) AS created_date, COUNT(*) AS daily_count
FROM Orders GROUP BY CAST(CreatedAt AS DATE);
```

---

## Query Complexity Guidelines

| Guideline | Threshold | If Exceeded |
|-----------|-----------|-------------|
| Max JOINs | 3-4 | Create VIEW or break into CTEs |
| Max subqueries | 2 levels | Use CTEs instead |
| Max CASE statements | 3-4 | Move logic to application layer |
| Max columns | 15-20 | Consider if all are needed |

### CTEs for Complex Logic

```sql
WITH open_orders AS (
    SELECT OrderID, CustomerID, CreatedAt FROM Orders WHERE Status = 'Open'
),
order_metrics AS (
    SELECT o.OrderID, COUNT(i.ItemID) AS item_count, MAX(i.UpdatedAt) AS last_update
    FROM open_orders o
    LEFT JOIN OrderItems i ON o.OrderID = i.OrderID
    GROUP BY o.OrderID
)
SELECT * FROM order_metrics WHERE item_count > 5;
```

---

## Execution Plan Red Flags

| Warning | Meaning | Fix |
|---------|---------|-----|
| Table Scan | No index used | Add index or fix WHERE clause |
| Key Lookup | Extra I/O for non-covered columns | Add columns to index or use covering index |
| CONVERT_IMPLICIT | Type mismatch causing conversion | Match parameter types to column types |
| Sort (high cost) | Sorting large dataset | Add index that matches ORDER BY |
| Hash Match | Large join, possibly missing index | Add indexes on join columns |
| Parallelism | Query is complex/large | May be OK, but check if needed |

---

## Performance Checklist

- [ ] Only selecting needed columns (no SELECT *)
- [ ] Filtering in WHERE, not application code
- [ ] JOINs on indexed columns
- [ ] No functions on indexed columns in WHERE
- [ ] Types match (no implicit conversions)
- [ ] Parameterized (no string concatenation)
- [ ] Pagination for large result sets
- [ ] Comments explain purpose and expected volume
