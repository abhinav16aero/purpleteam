# DeepTempo Core

Shared core library for DeepTempo AI SOC projects.

## Overview

`deeptempo-core` provides common functionality used across DeepTempo projects:

- **Configuration Management**: Centralized configuration with file and environment support
- **Database Layer**: SQLAlchemy models and services for PostgreSQL
- **Secrets Management**: Secure secrets storage with multiple backends
- **Rate Limiting**: Token bucket and rate limiter implementations
- **Exception Handling**: Common exception types

## Installation

```bash
# Install from source (development)
pip install -e .

# Install from git
pip install git+https://github.com/YOUR_USERNAME/deeptempo-core.git
```

## Usage

```python
# Configuration
from deeptempo_core.config import get_config_dir, is_demo_mode

# Database
from deeptempo_core.database.models import Finding, Case
from deeptempo_core.database.service import DatabaseService
from deeptempo_core.database.connection import get_db_manager

# Secrets
from deeptempo_core.secrets import get_secrets_manager

# Rate Limiting
from deeptempo_core.rate_limit import RateLimiter, get_limiter
```

## Configuration

The library uses `~/.deeptempo/` for configuration files:

- `integrations_config.json` - Integration settings
- `general_config.json` - General configuration
- `.env` - Secrets (if using file backend)

## Database

Set the database connection via environment variable:

```bash
export DATABASE_URL=postgresql://user:pass@localhost:5432/deeptempo_soc
```

Or use the `POSTGRES_*` environment variables:

```bash
export POSTGRES_HOST=localhost
export POSTGRES_PORT=5432
export POSTGRES_DB=deeptempo_soc
export POSTGRES_USER=deeptempo
export POSTGRES_PASSWORD=your_password
```

## Development

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Format code
black deeptempo_core/
ruff check deeptempo_core/
```

## License

MIT License - see LICENSE file for details.

