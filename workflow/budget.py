"""Fail-closed authorization budgets for multi-CLI model stages."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import time
from typing import Any


class BudgetExceeded(RuntimeError):
    """A model stage would exceed an authorized workflow budget."""


@dataclass(frozen=True)
class StageReservation:
    tokens: int
    cost_usd: float


@dataclass(frozen=True)
class BudgetLimits:
    max_turns: int
    token_budget: int
    cost_budget_usd: float
    total_timeout_seconds: int
    stage_timeout_seconds: int
    reservations: dict[str, StageReservation]

    @classmethod
    def from_config(
        cls,
        config: dict[str, Any],
        *,
        max_turns: int | None = None,
        token_budget: int | None = None,
        cost_budget_usd: float | None = None,
        total_timeout_seconds: int | None = None,
    ) -> "BudgetLimits":
        raw = config.get("budget", {})
        reservations = {
            agent: StageReservation(
                tokens=int(values["tokens"]), cost_usd=float(values["cost_usd"])
            )
            for agent, values in raw.get("stage_reservations", {}).items()
        }
        limits = cls(
            max_turns=(
                max_turns if max_turns is not None else int(raw.get("max_turns", 6))
            ),
            token_budget=(
                token_budget
                if token_budget is not None
                else int(raw.get("token_budget", 300_000))
            ),
            cost_budget_usd=(
                cost_budget_usd
                if cost_budget_usd is not None
                else float(raw.get("cost_budget_usd", 25.0))
            ),
            total_timeout_seconds=(
                total_timeout_seconds
                if total_timeout_seconds is not None
                else int(raw.get("total_timeout_seconds", 3600))
            ),
            stage_timeout_seconds=int(raw.get("stage_timeout_seconds", 900)),
            reservations=reservations,
        )
        limits.validate()
        return limits

    def validate(self) -> None:
        if (
            self.max_turns < 1
            or self.token_budget < 1
            or self.cost_budget_usd <= 0
            or self.total_timeout_seconds < 1
            or self.stage_timeout_seconds < 1
        ):
            raise ValueError("all budget limits must be positive")
        if not self.reservations:
            raise ValueError("at least one agent reservation is required")
        for agent, reservation in self.reservations.items():
            if not agent or reservation.tokens < 1 or reservation.cost_usd <= 0:
                raise ValueError(f"invalid stage reservation for {agent!r}")


def estimate_visible_tokens(text: str) -> int:
    """Conservative visible-I/O estimate; not presented as provider billing usage."""
    return max(1, (len(text.encode("utf-8")) + 3) // 4)


class BudgetLedger:
    def __init__(self, limits: BudgetLimits, path: Path):
        self.limits = limits
        self.path = path
        self.started_monotonic = time.monotonic()
        self.state: dict[str, Any] = {
            "schema_version": 1,
            "enforcement": "preauthorized_stage_reservations",
            "limits": {
                "max_turns": limits.max_turns,
                "token_budget": limits.token_budget,
                "cost_budget_usd": limits.cost_budget_usd,
                "total_timeout_seconds": limits.total_timeout_seconds,
                "stage_timeout_seconds": limits.stage_timeout_seconds,
                "stage_reservations": {
                    agent: asdict(reservation)
                    for agent, reservation in limits.reservations.items()
                },
            },
            "reserved_tokens": 0,
            "reserved_cost_usd": 0.0,
            "visible_estimated_tokens": 0,
            "turns_used": 0,
            "stages": [],
        }
        self._save()

    def _save(self) -> None:
        self.path.write_text(json.dumps(self.state, indent=2) + "\n", encoding="utf-8")

    def remaining_seconds(self) -> int:
        elapsed = time.monotonic() - self.started_monotonic
        return max(0, int(self.limits.total_timeout_seconds - elapsed))

    def reserve(self, *, label: str, agent: str, prompt: str) -> tuple[int, int]:
        reservation = self.limits.reservations.get(agent)
        if reservation is None:
            raise BudgetExceeded(f"no budget reservation configured for agent {agent}")
        prompt_estimate = estimate_visible_tokens(prompt)
        if prompt_estimate > reservation.tokens:
            raise BudgetExceeded(
                f"stage {label} prompt estimate {prompt_estimate} exceeds its "
                f"{reservation.tokens}-token reservation"
            )
        if self.state["turns_used"] + 1 > self.limits.max_turns:
            raise BudgetExceeded("max-turns budget exhausted")
        if (
            self.state["reserved_tokens"] + reservation.tokens
            > self.limits.token_budget
        ):
            raise BudgetExceeded("token reservation budget exhausted")
        if (
            self.state["reserved_cost_usd"] + reservation.cost_usd
            > self.limits.cost_budget_usd + 1e-9
        ):
            raise BudgetExceeded("USD reservation budget exhausted")
        remaining = self.remaining_seconds()
        if remaining < 1:
            raise BudgetExceeded("workflow wall-time budget exhausted")

        stage = {
            "label": label,
            "agent": agent,
            "status": "running",
            "reserved_tokens": reservation.tokens,
            "reserved_cost_usd": reservation.cost_usd,
            "prompt_visible_estimated_tokens": prompt_estimate,
            "output_visible_estimated_tokens": None,
            "measurement": "reserved ceiling plus visible-I/O estimate",
        }
        self.state["stages"].append(stage)
        self.state["turns_used"] += 1
        self.state["reserved_tokens"] += reservation.tokens
        self.state["reserved_cost_usd"] = round(
            self.state["reserved_cost_usd"] + reservation.cost_usd, 6
        )
        self.state["visible_estimated_tokens"] += prompt_estimate
        self._save()
        timeout = min(self.limits.stage_timeout_seconds, remaining)
        return len(self.state["stages"]) - 1, timeout

    def settle(self, stage_index: int, *, output: str, exit_code: int) -> None:
        stage = self.state["stages"][stage_index]
        output_estimate = estimate_visible_tokens(output)
        stage["output_visible_estimated_tokens"] = output_estimate
        stage["status"] = "completed" if exit_code == 0 else "failed"
        stage["exit_code"] = exit_code
        self.state["visible_estimated_tokens"] += output_estimate
        self._save()
        visible_total = stage["prompt_visible_estimated_tokens"] + output_estimate
        if visible_total > stage["reserved_tokens"]:
            stage["status"] = "reservation_overrun"
            self._save()
            raise BudgetExceeded(
                f"stage {stage['label']} visible I/O estimate {visible_total} exceeded "
                f"its {stage['reserved_tokens']}-token reservation"
            )

    def public_state(self) -> dict[str, Any]:
        return json.loads(json.dumps(self.state))
