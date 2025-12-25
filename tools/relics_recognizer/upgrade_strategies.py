from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Any

from module.logger import logger

STRATEGY_FILE = Path(__file__).with_name("relic_upgrade_strategies.json")
REPO_ROOT = Path(__file__).resolve().parents[2]
USER_STRATEGY_FILE = REPO_ROOT / "config" / "relic_upgrade_strategies.user.json"


@dataclass
class StrategyRule:
    level: int
    min_hits: Optional[int] = None
    min_total_hits: Optional[int] = None
    min_speed_rolls: Optional[int] = None
    min_speed_value: Optional[int] = None
    # Extended fields
    min_stat_values: Dict[str, float] = field(default_factory=dict)
    on_pass: Optional[str] = None
    on_fail: Optional[str] = None
    promote_to_15: bool = False
    keep_only: bool = False
    stop_if_fail: bool = False


@dataclass
class StrategyProfile:
    id: str
    name: str
    description: List[str]
    rules: Dict[int, StrategyRule]
    # Extended fields
    precheck: Dict[str, Any] = field(default_factory=dict)
    options: Dict[str, Any] = field(default_factory=dict)
    aliases: Dict[str, List[str]] = field(default_factory=dict)


class StrategyManager:
    def __init__(self, path: Path = STRATEGY_FILE, user_path: Optional[Path] = USER_STRATEGY_FILE):
        self.path = path
        self.user_path = user_path
        self.profiles: Dict[str, StrategyProfile] = {}
        self._load()

    def _load(self) -> None:
        base = self._read_json(self.path)
        user = self._read_json(self.user_path) if self.user_path else None
        data_profiles = base.get("profiles", []) if base else []
        # Merge user overrides by id
        if user and user.get("profiles"):
            override_by_id = {p.get("id"): p for p in user["profiles"] if p.get("id")}
            merged: List[dict] = []
            for p in data_profiles:
                pid = p.get("id")
                if pid in override_by_id:
                    merged.append(self._deep_merge(p, override_by_id[pid]))
                    override_by_id.pop(pid, None)
                else:
                    merged.append(p)
            # append new profiles
            merged.extend(override_by_id.values())
            data_profiles = merged

        for profile in data_profiles:
            rules = {}
            for level_str, rule in profile.get("thresholds", {}).items():
                level = int(level_str.strip("+"))
                rules[level] = StrategyRule(
                    level=level,
                    min_hits=rule.get("min_hits"),
                    min_total_hits=rule.get("min_total_hits"),
                    min_speed_rolls=rule.get("min_speed_rolls"),
                    min_speed_value=rule.get("min_speed_value"),
                    min_stat_values={k: float(v) for k, v in (rule.get("min_stat_values") or {}).items()},
                    on_pass=rule.get("on_pass"),
                    on_fail=rule.get("on_fail"),
                    promote_to_15=rule.get("promote_to_15", False),
                    keep_only=rule.get("keep_only", False),
                    stop_if_fail=rule.get("stop_if_fail", False),
                )
            profile_obj = StrategyProfile(
                id=profile.get("id"),
                name=profile.get("name", profile.get("id")),
                description=profile.get("description", []),
                rules=rules,
                precheck=profile.get("precheck", {}),
                options=profile.get("options", {}),
                aliases=profile.get("aliases", {}),
            )
            self.profiles[profile_obj.id] = profile_obj
        logger.info("Loaded %s upgrade strategy profiles", len(self.profiles))

    def get(self, profile_id: str) -> Optional[StrategyProfile]:
        return self.profiles.get(profile_id)

    @staticmethod
    def _read_json(path: Optional[Path]) -> Dict[str, Any]:
        if not path:
            return {}
        try:
            if path.exists():
                return json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Failed to parse strategy file %s: %s", path, exc)
        return {}

    @staticmethod
    def _deep_merge(base: dict, override: dict) -> dict:
        out = dict(base)
        for k, v in override.items():
            if k in out and isinstance(out[k], dict) and isinstance(v, dict):
                out[k] = StrategyManager._deep_merge(out[k], v)
            else:
                out[k] = v
        return out
