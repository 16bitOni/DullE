"""Shim — prompts have moved to dulle.llm.prompts."""

from dulle.llm.prompts import executor_system, planner_system, verifier_system

__all__ = ["planner_system", "executor_system", "verifier_system"]
