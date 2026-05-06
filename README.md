# robocode

Natural language robot control agent for Episode 6-axis robotic arm.

## Overview

robocode is a CLI-based AI agent that translates natural language instructions into robotic arm operations. It uses DeepSeek V4 as the LLM backend and connects to the Episode SDK via TCP.

## Features

- **Natural Language Control**: describe what you want the robot to do in plain language
- **Safety Gates**: three-tier risk system (L0/L1/L2) with workspace bounds, joint limits, speed, and payload checks
- **Operator Approval**: L2 tools require human confirmation via Y/N/A/S interactive prompt
- **Code Sandbox**: LLM-generated SDK code runs in a restricted sandbox with forbidden-pattern scanning
- **Skills System**: pre-defined workflows for 6D calibration, 6D grasping, hand-eye calibration, Gomoku AI
- **Audit Trail**: SQLite database records all tool calls, approvals, and checkpoints
- **DRY-RUN Mode**: fake backend for testing without hardware

## Requirements

- Python >= 3.10
- Episode SDK (for hardware mode)
- conda environment `episode` (for 6D calibration/grasping)

## Quick Start

```bash
# Install dependencies
pip install -e .

# DRY-RUN mode (no hardware required)
python -m robocode --fake

# With hardware
python -m robocode
```

## Usage

Start robocode, then type natural language instructions:

```
you ▸ move to (300, 0, 150)
you ▸ grab the sponge block
you ▸ run 6d calibration
```

### Slash Commands

| Command | Description |
|---|---|
| `/help` | Show all commands |
| `/status` | Robot and system status |
| `/tools` | List all tools by risk level |
| `/audit` | View audit logs |
| `/resume <id>` | Resume a previous session |
| `/clear` | Clear conversation context |
| `/estop` | Emergency stop |
| `/approve-all` | Approve all L2 tools for this session |
| `/exit` | Exit |

## Architecture

```
robocode/
├── agent/          # AgentLoop (ReAct), ContextMemory
├── backends/       # SDK backend adapter + FakeEpisodeAPP
├── cli/            # prompt_toolkit REPL, slash commands, skill loader
├── config/         # Pydantic settings (env-prefixed)
├── llm/            # LLM provider abstraction + DeepSeek provider
├── orchestrator/   # Safety policy, approval gate, tool guard, state machine
├── persistence/    # SQLite audit database
├── skills/         # Skill definitions (6d_calibration, 6d_grasp, etc.)
├── tools/          # Robot tools (motion, gripper, codegen, exec, etc.)
└── utils/          # Shared models, runtime logging, cleanup
```

## Risk Levels

| Level | Description | Approval |
|---|---|---|
| L0 | Read-only (status, list, read files) | Auto-approved |
| L1 | Low-risk actions (home, scripts) | Auto-approved with policy overrides |
| L2 | High-risk actions (move, grasp, code exec) | Operator confirmation required |

## Safety

- Workspace bounds validation (configurable via env vars)
- Joint angle limit checking
- Speed ratio capping
- Payload weight limits
- Forbidden shell command blocking
- Code sandbox with pattern-based restrictions

## Configuration

Set via environment variables (prefix `ROBOCODE_`) or `.env` file:

```bash
export ROBOCODE_PROVIDER__API_KEY="sk-..."
export ROBOCODE_PROVIDER__MODEL="deepseek-v4-flash"
export ROBOCODE_BACKEND__SDK_HOST="localhost"
export ROBOCODE_BACKEND__SDK_PORT="12345"
```

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run linting
ruff check robocode/

# Install git hooks
pre-commit install
```

### Git Hooks

- **pre-commit**: trailing whitespace, end-of-file fixer, YAML check, large file check, private key detection, ruff lint + format
- **commit-msg**: conventional commit enforcement (`feat:`, `fix:`, `refactor:`, `chore:`, `docs:`, `test:`)

To skip hooks in emergencies: `git commit --no-verify`
