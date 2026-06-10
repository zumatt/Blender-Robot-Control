# Agent Folder (Human Guide)

This folder contains instructions used by AI coding agents that work on this repository.

## What is inside

- `LLM_Checklist.yaml`: canonical machine-readable instruction set for agent behavior.

## Why this exists

The repository uses a dedicated agent profile so automated edits stay consistent with the Blender PRC architecture, naming conventions, and workflow constraints.

## For humans

- Read this folder if you want to understand why the agent edits files in a specific way.
- If you change repository logic, update `LLM_Checklist.yaml` so agent behavior stays aligned.
- Keep this folder minimal. Avoid adding duplicate instruction documents.

## Source of truth policy

`LLM_Checklist.yaml` is the single source of truth for agent instructions.
If human-facing docs and agent behavior diverge, update the YAML first, then sync user-facing documentation.
