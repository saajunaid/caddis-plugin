---
name: data-loader
context: fork
description: Load data from files (Excel, JSON, CSV) into databases. Use when user needs to import data files into any database system. Database-agnostic - supports SQL Server, PostgreSQL, MySQL, SQLite, and others.
---

# Data Loader Skill

Systematically load data from various file formats into database tables with validation, transformation, and error handling.

## Trigger

Activate when:
- User says "load this Excel/JSON/CSV into the database"
- User provides a data file for import
- User needs to populate tables from external sources
- User asks about ETL or data ingestion
- User mentions "import data" or "data loading"

---

## Supported Formats

| Format | Extensions | Library |
|--------|-----------|---------|
| Excel | `.xlsx`, `.xls` | `openpyxl`, `xlrd` |
| JSON | `.json` | `json` (built-in) |
| CSV | `.csv` | `pandas` |
| Parquet | `.parquet` | `pyarrow` |
| XML | `.xml` | `lxml` |

## Supported Databases

| Database | Connection String Pattern | Driver |
|----------|--------------------------|--------|
| SQL Server | `mssql+pyodbc://...` | `pyodbc` |
| PostgreSQL | `postgresql://...` | `psycopg2` |
| MySQL | `mysql+pymysql://...` | `pymysql` |
| SQLite | `sqlite:///...` | Built-in |
| Oracle | `oracle+cx_oracle://...` | `cx_Oracle` |

---

## Phase 1: Source Discovery

### Objectives
- Identify source file(s) and format
- Understand data structure and schema
- Assess data quality and volume

### Actions

1. **Identify source files**
   ```python
   from pathlib import Path
   import pandas as pd
   
   # Find data files
   source_path = Path("data/")
   files = list(source_path.glob("*.xlsx")) + \
           list(source_path.glob("*.json")) + \
           list(source_path.glob("*.csv"))
   
   print(f"Found {len(files)} data files:")
   for f in files:
       print(f"  - {f.name} ({f.stat().st_size / 1024:.1f} KB)")
   ```

2. **Load and inspect data**
   ```python
   def load_source_file(file_path: Path) -> pd.DataFrame:
       """Load data from various formats into DataFrame."""
       suffix = file_path.suffix.lower()
       
       if suffix in ['.xlsx', '.xls']:
           # Excel - may have multiple sheets
           xlsx = pd.ExcelFile(file_path)
           print(f"Excel sheets: {xlsx.sheet_names}")
           df = pd.read_excel(file_path, sheet_name=0)  # First sheet
           
       elif suffix == '.json':
           # JSON - handle nested structures
           df = pd.read_json(file_path)
           # For nested JSON:
           # df = pd.json_normalize(json.load(open(file_path)))
           
       elif suffix == '.csv':
           df = pd.read_csv(file_path)
           
       elif suffix == '.parquet':
           df = pd.read_parquet(file_path)
           
       else:
           raise ValueError(f"Unsupported format: {suffix}")
       
       return df
   
   # Load and inspect
   df = load_source_file(Path("data/input.xlsx"))
   print(f"\nShape: {df.shape}")
   print(f"\nColumns:\n{df.dtypes}")
   print(f"\nSample:\n{df.head()}")
   ```

3. **Infer schema**
   ```python
   def infer_sql_types(df: pd.DataFrame) -> dict:
       """Map pandas dtypes to SQL types (database-agnostic)."""
       type_mapping = {
           'int64': 'INTEGER',
           'float64': 'FLOAT',
           'object': 'VARCHAR(255)',
           'bool': 'BOOLEAN',
           'datetime64[ns]': 'TIMESTAMP',
           'date': 'DATE',
       }
       
       schema = {}
       for col in df.columns:
           dtype = str(df[col].dtype)
           sql_type = type_mapping.get(dtype, 'TEXT')
           
           # Refine VARCHAR length based on data
           if dtype == 'object':
               max_len = df[col].astype(str).str.len().max()
               if max_len > 255:
                   sql_type = 'TEXT'
               else:
                   sql_type = f'VARCHAR({min(max_len * 2, 255)})'
           
           schema[col] = sql_type
       
       return schema
   
   schema = infer_sql_types(df)
   print("\nInferred Schema:")
   for col, sql_type in schema.items():
       print(f"  {col}: {sql_type}")
   ```

### Output

```markdown
## Source Discovery Report

### Files Found
| File | Format | Size | Records | Columns |
|------|--------|------|---------|---------|
| [filename] | [format] | [size] | [count] | [count] |

### Schema Inference
| Column | Source Type | SQL Type | Nullable | Sample Values |
|--------|-------------|----------|----------|---------------|
| [col] | [pandas dtype] | [SQL type] | [Yes/No] | [examples] |

### Data Quality Notes
- Missing values: [summary]
- Duplicates: [count]
- Date formats: [detected format]
```

---

## Phase 2: Target Configuration

### Objectives
- Configure database connection
- Define target table structure
- Handle existing data (truncate/append/upsert)

### Actions

1. **Configure database connection (database-agnostic)**
   ```python
   from sqlalchemy import create_engine, text
   from urllib.parse import quote_plus
   
   def get_db_engine(db_type: str, config: dict):
       """Create database engine for any supported database."""
       
       if db_type == 'sqlserver':
           # SQL Server with Windows Auth
           conn_str = (
               f"DRIVER={{ODBC Driver 17 for SQL Server}};"
               f"SERVER={config['server']};"
               f"DATABASE={config['database']};"
               f"Trusted_Connection=yes;"
           )
           engine = create_engine(
               f"mssql+pyodbc:///?odbc_connect={quote_plus(conn_str)}"
           )
       
       elif db_type == 'postgresql':
           engine = create_engine(
               f"postgresql://{config['user']}:{config['password']}"
               f"@{config['host']}:{config.get('port', 5432)}"
               f"/{config['database']}"
           )
       
       elif db_type == 'mysql':
           engine = create_engine(
               f"mysql+pymysql://{config['user']}:{config['password']}"
               f"@{config['host']}:{config.get('port', 3306)}"
               f"/{config['database']}"
           )
       
       elif db_type == 'sqlite':
           engine = create_engine(f"sqlite:///{config['database']}")
       
       else:
           raise ValueError(f"Unsupported database: {db_type}")
       
       return engine
   
   # Example usage
   engine = get_db_engine('sqlserver', {
       'server': 'localhost',
       'database': 'mydb'
   })
   ```

2. **Define target table**
   ```python
   def create_table_ddl(
       table_name: str,
       schema: dict,
       db_type: str = 'sqlserver',
       primary_key: str = None
   ) -> str:
       """Generate CREATE TABLE DDL for any database."""
       
       # Database-specific type adjustments
       type_adjustments = {
           'sqlserver': {
               'TIMESTAMP': 'DATETIME2',
               'TEXT': 'NVARCHAR(MAX)',
               'BOOLEAN': 'BIT'
           },
           'postgresql': {
               'DATETIME2': 'TIMESTAMP',
               'NVARCHAR(MAX)': 'TEXT',
               'BIT': 'BOOLEAN'
           },
           'mysql': {
               'DATETIME2': 'DATETIME',
               'NVARCHAR(MAX)': 'LONGTEXT'
           },
           'sqlite': {
               'DATETIME2': 'TEXT',
               'NVARCHAR(MAX)': 'TEXT'
           }
       }
       
       adjustments = type_adjustments.get(db_type, {})
       
       columns = []
       for col, sql_type in schema.items():
           adjusted_type = adjustments.get(sql_type, sql_type)
           pk = ' PRIMARY KEY' if col == primary_key else ''
           columns.append(f"    {col} {adjusted_type}{pk}")
       
       # Add audit columns
       if db_type == 'sqlserver':
           columns.append("    _loaded_at DATETIME2 DEFAULT GETDATE()")
       elif db_type == 'postgresql':
           columns.append("    _loaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
       elif db_type == 'mysql':
           columns.append("    _loaded_at DATETIME DEFAULT CURRENT_TIMESTAMP")
       else:
           columns.append("    _loaded_at TEXT")
       
       ddl = f"CREATE TABLE {table_name} (\n"
       ddl += ",\n".join(columns)
       ddl += "\n);"
       
       return ddl
   ```

3. **Handle existing data**
   ```python
   def prepare_target_table(
       engine,
       table_name: str,
       schema: dict,
       mode: str = 'replace',  # 'replace', 'append', 'fail'
       db_type: str = 'sqlserver'
   ):
       """Prepare target table for data loading."""
       
       with engine.connect() as conn:
           # Check if table exists
           if db_type == 'sqlserver':
               exists_query = text(f"""
                   SELECT 1 FROM INFORMATION_SCHEMA.TABLES 
                   WHERE TABLE_NAME = '{table_name}'
               """)
           elif db_type in ['postgresql', 'mysql']:
               exists_query = text(f"""
                   SELECT 1 FROM information_schema.tables 
                   WHERE table_name = '{table_name}'
               """)
           else:
               exists_query = text(f"""
                   SELECT 1 FROM sqlite_master 
                   WHERE type='table' AND name='{table_name}'
               """)
           
           exists = conn.execute(exists_query).fetchone() is not None
           
           if exists:
               if mode == 'replace':
                   conn.execute(text(f"DROP TABLE {table_name}"))
                   conn.commit()
                   print(f"Dropped existing table: {table_name}")
               elif mode == 'fail':
                   raise ValueError(f"Table {table_name} already exists")
               elif mode == 'append':
                   print(f"Will append to existing table: {table_name}")
                   return  # Don't create, just append
           
           # Create new table
           ddl = create_table_ddl(table_name, schema, db_type)
           conn.execute(text(ddl))
           conn.commit()
           print(f"Created table: {table_name}")
   ```

---

## Phase 3: Data Transformation

### Objectives
- Clean and validate data
- Apply transformations
- Handle data type conversions

### Actions

1. **Clean column names**
   ```python
   import re
   
   def clean_column_names(df: pd.DataFrame) -> pd.DataFrame:
       """Standardize column names for database compatibility."""
       df = df.copy()
       
       new_columns = {}
       for col in df.columns:
           # Convert to lowercase, replace spaces/special chars
           clean = re.sub(r'[^\w]', '_', str(col).lower())
           clean = re.sub(r'_+', '_', clean).strip('_')
           new_columns[col] = clean
       
       df.rename(columns=new_columns, inplace=True)
       return df
   
   df = clean_column_names(df)
   ```

2. **Handle data quality issues**
   ```python
   def clean_data(df: pd.DataFrame, config: dict = None) -> pd.DataFrame:
       """Clean data for database loading."""
       df = df.copy()
       config = config or {}
       
       # Remove completely empty rows
       df.dropna(how='all', inplace=True)
       
       # Handle duplicates
       if config.get('remove_duplicates', False):
           df.drop_duplicates(inplace=True)
       
       # Trim string columns
       for col in df.select_dtypes(include=['object']).columns:
           df[col] = df[col].astype(str).str.strip()
           df[col] = df[col].replace(['nan', 'None', ''], None)
       
       # Convert date columns
       date_columns = config.get('date_columns', [])
       for col in date_columns:
           if col in df.columns:
               df[col] = pd.to_datetime(df[col], errors='coerce')
       
       # Fill nulls for required columns
       required_columns = config.get('required_columns', {})
       for col, default in required_columns.items():
           if col in df.columns:
               df[col].fillna(default, inplace=True)
       
       return df
   
   # Example
   df = clean_data(df, {
       'remove_duplicates': True,
       'date_columns': ['created_date', 'modified_date'],
       'required_columns': {'status': 'unknown'}
   })
   ```

3. **Validate data**
   ```python
   def validate_data(df: pd.DataFrame, rules: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
       """Validate data and separate valid/invalid records."""
       
       errors = []
       
       for idx, row in df.iterrows():
           row_errors = []
           
           # Required fields
           for col in rules.get('required', []):
               if pd.isna(row.get(col)) or row.get(col) == '':
                   row_errors.append(f"Missing required field: {col}")
           
           # Numeric ranges
           for col, (min_val, max_val) in rules.get('ranges', {}).items():
               val = row.get(col)
               if pd.notna(val) and not (min_val <= val <= max_val):
                   row_errors.append(f"{col} out of range: {val}")
           
           # Pattern matching
           for col, pattern in rules.get('patterns', {}).items():
               val = str(row.get(col, ''))
               if val and not re.match(pattern, val):
                   row_errors.append(f"{col} invalid format: {val}")
           
           if row_errors:
               errors.append({'index': idx, 'errors': row_errors})
       
       # Separate valid and invalid
       invalid_indices = [e['index'] for e in errors]
       valid_df = df[~df.index.isin(invalid_indices)]
       invalid_df = df[df.index.isin(invalid_indices)]
       
       print(f"Valid records: {len(valid_df)}")
       print(f"Invalid records: {len(invalid_df)}")
       
       return valid_df, invalid_df
   
   # Example
   valid_df, invalid_df = validate_data(df, {
       'required': ['customer_id', 'amount'],
       'ranges': {'amount': (0, 1000000)},
       'patterns': {'email': r'^[\w\.-]+@[\w\.-]+\.\w+$'}
   })
   ```

---

## Phase 4: Load Data

### Objectives
- Load data into target table
- Handle batch processing for large files
- Track load statistics

### Actions

1. **Load data with pandas**
   ```python
   from datetime import datetime
   
   def load_data(
       df: pd.DataFrame,
       engine,
       table_name: str,
       batch_size: int = 1000,
       if_exists: str = 'append'
   ) -> dict:
       """Load DataFrame to database table."""
       
       start_time = datetime.now()
       total_rows = len(df)
       
       # Add load timestamp
       df['_loaded_at'] = datetime.now()
       
       # Load in batches for large datasets
       if total_rows > batch_size:
           loaded = 0
           for i in range(0, total_rows, batch_size):
               batch = df.iloc[i:i + batch_size]
               batch.to_sql(
                   table_name,
                   engine,
                   if_exists='append' if i > 0 else if_exists,
                   index=False,
                   method='multi'  # Faster bulk insert
               )
               loaded += len(batch)
               print(f"Loaded {loaded}/{total_rows} rows...")
       else:
           df.to_sql(
               table_name,
               engine,
               if_exists=if_exists,
               index=False
           )
       
       elapsed = (datetime.now() - start_time).total_seconds()
       
       return {
           'table': table_name,
           'rows_loaded': total_rows,
           'elapsed_seconds': elapsed,
           'rows_per_second': total_rows / elapsed if elapsed > 0 else 0
       }
   
   # Execute load
   stats = load_data(valid_df, engine, 'staging.customer_data')
   print(f"\nLoad complete: {stats}")
   ```

2. **Handle errors and logging**
   ```python
   from loguru import logger
   
   def load_with_error_handling(
       df: pd.DataFrame,
       engine,
       table_name: str,
       error_table: str = None
   ) -> dict:
       """Load data with comprehensive error handling."""
       
       stats = {
           'attempted': len(df),
           'loaded': 0,
           'failed': 0,
           'errors': []
       }
       
       try:
           result = load_data(df, engine, table_name)
           stats['loaded'] = result['rows_loaded']
           logger.info(f"Successfully loaded {stats['loaded']} rows to {table_name}")
           
       except Exception as e:
           logger.error(f"Bulk load failed: {e}")
           
           # Fall back to row-by-row loading
           logger.info("Attempting row-by-row loading...")
           
           for idx, row in df.iterrows():
               try:
                   pd.DataFrame([row]).to_sql(
                       table_name, engine, if_exists='append', index=False
                   )
                   stats['loaded'] += 1
               except Exception as row_error:
                   stats['failed'] += 1
                   stats['errors'].append({
                       'index': idx,
                       'error': str(row_error)
                   })
           
           # Save failed rows to error table
           if error_table and stats['failed'] > 0:
               failed_indices = [e['index'] for e in stats['errors']]
               failed_df = df.loc[failed_indices]
               failed_df['_error'] = [
                   e['error'] for e in stats['errors']
               ]
               failed_df.to_sql(
                   error_table, engine, if_exists='append', index=False
               )
               logger.info(f"Saved {stats['failed']} failed rows to {error_table}")
       
       return stats
   ```

---

## Phase 5: Verification

### Objectives
- Verify data loaded correctly
- Generate load report
- Clean up staging data if needed

### Actions

1. **Verify load**
   ```python
   def verify_load(engine, table_name: str, expected_count: int) -> dict:
       """Verify data was loaded correctly."""
       
       with engine.connect() as conn:
           # Row count
           result = conn.execute(text(f"SELECT COUNT(*) FROM {table_name}"))
           actual_count = result.scalar()
           
           # Sample data
           result = conn.execute(text(f"SELECT * FROM {table_name} LIMIT 5"))
           sample = result.fetchall()
       
       verification = {
           'expected': expected_count,
           'actual': actual_count,
           'match': expected_count == actual_count,
           'sample_rows': len(sample)
       }
       
       if verification['match']:
           print(f"✅ Verification passed: {actual_count} rows loaded")
       else:
           print(f"❌ Verification failed: expected {expected_count}, got {actual_count}")
       
       return verification
   
   verify_load(engine, 'staging.customer_data', len(valid_df))
   ```

2. **Generate load report**
   ```python
   def generate_load_report(
       source_file: str,
       target_table: str,
       stats: dict,
       verification: dict
   ) -> str:
       """Generate markdown load report."""
       
       report = f"""
   ## Data Load Report
   
   ### Summary
   | Metric | Value |
   |--------|-------|
   | Source File | `{source_file}` |
   | Target Table | `{target_table}` |
   | Load Time | {stats.get('elapsed_seconds', 0):.2f}s |
   | Status | {'✅ Success' if verification['match'] else '❌ Failed'} |
   
   ### Row Counts
   | Stage | Count |
   |-------|-------|
   | Source Records | {stats.get('attempted', 0)} |
   | Loaded | {stats.get('loaded', 0)} |
   | Failed | {stats.get('failed', 0)} |
   | Verified in DB | {verification.get('actual', 0)} |
   
   ### Performance
   - **Throughput**: {stats.get('rows_per_second', 0):.0f} rows/second
   
   ### Errors
   {f"- {len(stats.get('errors', []))} errors logged" if stats.get('errors') else "- No errors"}
   """
       return report
   ```

---

## Complete Example

```python
"""Complete data loading pipeline - database agnostic."""

from pathlib import Path
import pandas as pd
from sqlalchemy import create_engine, text
from loguru import logger

# Configuration
CONFIG = {
    'source_file': 'data/customers.xlsx',
    'target_table': 'staging.customers',
    'db_type': 'sqlserver',  # or 'postgresql', 'mysql', 'sqlite'
    'db_config': {
        'server': 'localhost',
        'database': 'mydb'
    },
    'load_mode': 'replace',  # 'replace', 'append', 'fail'
    'validation_rules': {
        'required': ['customer_id', 'name'],
        'date_columns': ['created_date']
    }
}

def main():
    # Phase 1: Source Discovery
    logger.info(f"Loading source: {CONFIG['source_file']}")
    df = load_source_file(Path(CONFIG['source_file']))
    logger.info(f"Found {len(df)} records, {len(df.columns)} columns")
    
    # Phase 2: Target Configuration  
    engine = get_db_engine(CONFIG['db_type'], CONFIG['db_config'])
    schema = infer_sql_types(df)
    prepare_target_table(
        engine, 
        CONFIG['target_table'], 
        schema, 
        CONFIG['load_mode'],
        CONFIG['db_type']
    )
    
    # Phase 3: Transform
    df = clean_column_names(df)
    df = clean_data(df, CONFIG.get('validation_rules', {}))
    valid_df, invalid_df = validate_data(df, CONFIG.get('validation_rules', {}))
    
    # Phase 4: Load
    stats = load_with_error_handling(
        valid_df, 
        engine, 
        CONFIG['target_table'],
        error_table='staging.load_errors'
    )
    
    # Phase 5: Verify
    verification = verify_load(engine, CONFIG['target_table'], len(valid_df))
    
    # Generate report
    report = generate_load_report(
        CONFIG['source_file'],
        CONFIG['target_table'],
        stats,
        verification
    )
    logger.info(report)
    
    return stats

if __name__ == '__main__':
    main()
```

---

## Dependencies

```txt
# requirements.txt additions for data loading
pandas>=2.0.0
openpyxl>=3.1.0      # Excel support
xlrd>=2.0.0          # Legacy Excel (.xls)
sqlalchemy>=2.0.0    # Database abstraction
pyodbc>=4.0.0        # SQL Server
psycopg2-binary>=2.9.0  # PostgreSQL (optional)
pymysql>=1.0.0       # MySQL (optional)
pyarrow>=12.0.0      # Parquet support (optional)
loguru>=0.7.0        # Logging
```

---

## Related Resources

- `@sql-expert` - Database design and query optimization
- `@data-engineer` - ETL pipeline design and orchestration
- `/data-analysis` - Analyze loaded data
- `python.instructions.md` - Python coding standards
