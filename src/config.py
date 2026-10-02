"""Load named Telegram destinations and resolve their secrets at startup."""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field


class DestinationSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bot_token_env: str = Field(min_length=1)
    chat_id_env: str = Field(min_length=1)


class DestinationsFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    destinations: dict[str, DestinationSpec] = Field(min_length=1)


@dataclass(frozen=True)
class Destination:
    bot_token: str
    chat_id: str


@dataclass(frozen=True)
class Config:
    api_key: str
    destinations: dict[str, Destination]


def load_config(
    path: Path = Path("config/destinations.yaml"),
    environ: Mapping[str, str] | None = None,
) -> Config:
    values = os.environ if environ is None else environ

    def required(name: str) -> str:
        value = values.get(name)
        if value is None or not value.strip():
            raise ValueError(f"Missing or empty environment variable: {name}")
        return value

    api_key = required("API_KEY")
    with path.open(encoding="utf-8") as stream:
        specs = DestinationsFile.model_validate(yaml.safe_load(stream))

    destinations = {
        name: Destination(
            bot_token=required(spec.bot_token_env),
            chat_id=required(spec.chat_id_env),
        )
        for name, spec in specs.destinations.items()
    }
    return Config(api_key=api_key, destinations=destinations)
