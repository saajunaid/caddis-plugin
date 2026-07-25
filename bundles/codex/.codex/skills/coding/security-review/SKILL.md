---
name: security-review
context: fork
description: "Security review workflow — OWASP, code scanning, cloud infrastructure"
---

# Security Review

Security review workflow covering OWASP Top 10, code scanning, and cloud infrastructure.

## When to Use

- Implementing authentication or authorization
- Handling user input or file uploads
- Creating or modifying API endpoints
- Working with secrets, deploying to cloud, or configuring CI/CD

## Phase 1: OWASP Top 10 Checks

### A01 — Broken Access Control

```python
# BAD — no auth check
@app.route("/admin/users")
def list_users():
    return db.query(User).all()

# GOOD
@app.route("/admin/users")
@require_role("admin")
def list_users():
    return db.query(User).all()
```

- [ ] Every endpoint checks authentication
- [ ] Role-based access control enforced
- [ ] Users cannot access other users' data (IDOR)

### A02 — Cryptographic Failures

```python
# BAD: password_hash = hashlib.md5(password.encode()).hexdigest()
# GOOD:
from passlib.hash import argon2
password_hash = argon2.hash(password)
```

- [ ] Passwords hashed with bcrypt/argon2
- [ ] Sensitive data encrypted at rest and in transit
- [ ] No secrets in source code or logs

### A03 — Injection

```python
# BAD: cursor.execute(f"SELECT * FROM users WHERE email = '{email}'")
# GOOD:
cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
```

- [ ] All queries parameterized or use ORM
- [ ] No `eval()`, `exec()`, or `os.system()` with user input

### A05 — Security Misconfiguration

- [ ] Debug mode disabled in production
- [ ] Default credentials changed
- [ ] Unnecessary endpoints disabled

### A06 — Vulnerable Components

```bash
pip audit          # Python
npm audit          # JavaScript
trivy image app    # Container
```

- [ ] No known vulnerabilities; lock files committed

### A07 — Authentication Failures

- [ ] Session tokens in httpOnly cookies (not localStorage)
- [ ] Account lockout after failed attempts
- [ ] MFA for privileged accounts

### A09 — Logging Failures

```python
# BAD: logger.info(f"Login: user={email}, password={password}")
# GOOD: logger.info(f"Login: user={email}, success={is_valid}")
```

- [ ] Auth events logged; no PII or secrets in logs

### A10 — SSRF

```python
ALLOWED_HOSTS = {"api.example.com"}
parsed = urlparse(user_url)
if parsed.hostname not in ALLOWED_HOSTS:
    raise ValueError("URL not allowed")
```

## Phase 2: Input Validation

```python
from pydantic import BaseModel, EmailStr, constr, conint

class CreateUserRequest(BaseModel):
    email: EmailStr
    name: constr(min_length=1, max_length=100)
    age: conint(ge=0, le=150)

# Validate
try:
    data = CreateUserRequest(**request_json)
except ValidationError as e:
    return {"error": e.errors()}, 400
```

File uploads: check size, extension, and magic bytes.

## Phase 3: Security Headers

```python
@app.after_request
def add_security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'"
    )
    return response
```

## Phase 4: Cloud Infrastructure

### IAM — Least Privilege

```yaml
# GOOD: specific permissions on specific resources
permissions: [s3:GetObject, s3:ListBucket]
resources: [arn:aws:s3:::my-bucket/*]

# BAD: permissions: [s3:*], resources: ["*"]
```

- [ ] No root account in production; MFA on privileged accounts
- [ ] Service accounts use roles, not long-lived keys

### Secrets Management

- [ ] Secrets in a manager (AWS SM, Vault) with rotation
- [ ] No secrets in env vars without rotation policy

### CI/CD Security

```yaml
jobs:
  deploy:
    permissions: { contents: read }
    steps:
      - uses: actions/checkout@v4
      - uses: trufflesecurity/trufflehog@main  # Secret scanning
      - run: pip audit                          # Dep audit
      - run: pytest --cov=myapp --cov-fail-under=80
```

- [ ] OIDC instead of long-lived credentials
- [ ] Branch protection and code review required

### Network

- [ ] Database not publicly accessible
- [ ] Security groups follow least privilege
- [ ] WAF enabled

## Pre-Deployment Checklist

- [ ] No hardcoded secrets
- [ ] All user inputs validated server-side
- [ ] All queries parameterized
- [ ] Auth + authz on every endpoint
- [ ] Rate limiting enabled
- [ ] HTTPS enforced
- [ ] Security headers configured
- [ ] No sensitive data in error responses or logs
- [ ] Dependencies audited
- [ ] Cloud IAM least-privilege applied
- [ ] Backups automated with tested recovery

## Resources

- [OWASP Top 10](https://owasp.org/www-project-top-ten/)
- [OWASP Cheat Sheets](https://cheatsheetseries.owasp.org/)
- [CIS Benchmarks](https://www.cisecurity.org/cis-benchmarks)
