# README
A tool to scan for repeated code patterns and surface what can be refactored. 

## Highlights

* **Refactor focused** - Surfaces repeated code patterns that are worth reviewing.
* **Structure-aware** - Compares signatures, control flow, calls, and relation evidence.
* **Agent ready** - Writes compact report artifacts designed for coding-agent workflows.

### Examples

#### Same job, different words

This happens when different functions are essentially doing the same job.

```python
# users.py
def load_users(path):
    raw = path.read_text()
    data = json.loads(raw)
    return [User.from_dict(item) for item in data["users"]]


# products.py
def read_products(file_path):
    contents = file_path.read_text()
    parsed = json.loads(contents)
    return [Product.from_dict(row) for row in parsed["products"]]


# orders.py
def get_orders(source):
    text = source.read_text()
    payload = json.loads(text)
    return [Order.from_dict(order) for order in payload["orders"]]
```

#### Same rule but scattered across the repo

This happens when the same rule appears in several places.

```python
# checkout.py
def can_checkout(user, basket):
    if not user.email_verified:
        return False
    if basket.total <= 0:
        return False
    if user.account_status == "blocked":
        return False
    return True


# discounts.py
def can_apply_discount(customer, cart):
    if customer.account_status == "blocked":
        return False
    if not customer.email_verified:
        return False
    if cart.total <= 0:
        return False
    return True


# invoices.py
def can_generate_invoice(account, order):
    if order.total <= 0:
        return False
    if account.account_status == "blocked":
        return False
    if not account.email_verified:
        return False
    return True
```

## Installation

### Using git

You can alternatively "git clone" this repository to any directory:

```bash
git clone --depth 1 https://github.com/zerowarden/codeseam.git
```

and then run `uv sync`.

## Local Development

```bash
uv sync
uv run codeseam --help
```

Use the Makefile targets to execute commands: 

```bash
make deadcode
make lint
make typecheck
make test
make format
```

For a local scan, run:

```bash
make analyze ANALYZE_ARGS="--repo-root /path/to/repo"
```

## Quick Start

Simply run `codeseam analyze` against your repo.

### Optional: Configuration setup

Run `codeseam init`

## What this tool is not
- Linter
- Clone detector 
- Code quality scanner
- Automated refactoring tool

## Methodology
See [METHODOLOGY](./docs/METHODOLOGY.md)

## License
MIT
