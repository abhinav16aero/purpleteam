# DeepTempo MCP Servers

Model Context Protocol (MCP) servers for DeepTempo AI SOC.

## Overview

This package provides 4 MCP servers for DeepTempo AI SOC:

1. **deeptempo-findings** - Findings and case management (FastMCP)
2. **tempo-flow** - Investigation workflow orchestration
3. **approval** - Action approval workflow
4. **attack-layer** - MITRE ATT&CK layer generation

## Installation

```bash
# Install from source (development)
pip install -e .

# Install deeptempo-core dependency first
pip install -e ../deeptempo-core

# Install from git
pip install git+https://github.com/YOUR_USERNAME/deeptempo-mcp-servers.git
```

## Usage

### Running Individual Servers

```bash
# deeptempo-findings server (FastMCP)
python servers/deeptempo_findings.py

# tempo-flow server
python servers/tempo_flow.py

# approval server
python servers/approval.py

# attack-layer server
python servers/attack_layer.py
```

### Using with Claude Desktop

Add to your Claude Desktop MCP configuration (`~/.config/claude/mcp.json`):

```json
{
  "mcpServers": {
    "deeptempo-findings": {
      "command": "python3",
      "args": ["/path/to/deeptempo-mcp-servers/servers/deeptempo_findings.py"],
      "cwd": "/path/to/your/project"
    },
    "tempo-flow": {
      "command": "python3",
      "args": ["/path/to/deeptempo-mcp-servers/servers/tempo_flow.py"],
      "cwd": "/path/to/your/project"
    },
    "approval": {
      "command": "python3",
      "args": ["/path/to/deeptempo-mcp-servers/servers/approval.py"],
      "cwd": "/path/to/your/project"
    },
    "attack-layer": {
      "command": "python3",
      "args": ["/path/to/deeptempo-mcp-servers/servers/attack_layer.py"],
      "cwd": "/path/to/your/project"
    }
  }
}
```

## Server Descriptions

### deeptempo-findings

Provides comprehensive access to findings and cases:

**Tools:**
- `list_findings` - List security findings with filters
- `get_finding` - Get detailed finding information
- `list_cases` - List investigation cases
- `get_case` - Get detailed case information
- `create_case` - Create new investigation case
- `update_case` - Update case details
- `add_finding_to_case` - Link finding to case
- And 17+ more tools for case management

### tempo-flow

Investigation workflow orchestration:

**Tools:**
- `tempo_get_workflows` - List available workflows
- `tempo_run_workflow` - Execute investigation workflow

### approval

Action approval workflow:

**Tools:**
- `create_approval_action` - Submit action for approval
- `list_approval_actions` - List pending/approved actions
- `get_approval_action` - Get action details
- `approve_action` - Approve pending action
- `reject_action` - Reject pending action

### attack-layer

MITRE ATT&CK layer generation:

**Tools:**
- `get_attack_layer` - Get ATT&CK Navigator layer
- `get_technique_rollup` - Get technique statistics
- `get_findings_by_technique` - Find findings for technique
- `create_attack_layer` - Create custom layer

## Configuration

The servers use configuration from `deeptempo-core`. Set environment variables:

```bash
# Database
export DATABASE_URL=postgresql://user:pass@localhost:5432/deeptempo_soc

# Or individual components
export POSTGRES_HOST=localhost
export POSTGRES_PORT=5432
export POSTGRES_DB=deeptempo_soc
export POSTGRES_USER=deeptempo
export POSTGRES_PASSWORD=your_password

# Demo mode (uses generated sample data)
export DEMO_MODE=true
```

## Development

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Format code
black servers/
ruff check servers/
```

## Architecture

```
deeptempo-mcp-servers/
├── servers/
│   ├── __init__.py
│   ├── deeptempo_findings.py  # FastMCP server
│   ├── tempo_flow.py           # Standard MCP server
│   ├── approval.py             # Standard MCP server
│   ├── attack_layer.py         # Standard MCP server
│   └── base.py                 # Shared utilities
└── tests/
    └── test_servers.py
```

## License

MIT License - see LICENSE file for details.

