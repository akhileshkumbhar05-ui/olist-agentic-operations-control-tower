from dataclasses import dataclass
import os


@dataclass(frozen=True)
class Config:
    catalog: str = "workspace"
    schema_prefix: str = "olist"

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            catalog=os.getenv("DATABRICKS_CATALOG", "workspace"),
            schema_prefix=os.getenv("OLIST_SCHEMA_PREFIX", "olist"),
        )

    def schema(self, layer: str) -> str:
        return f"{self.schema_prefix}_{layer}"

    def table(self, layer: str, name: str) -> str:
        return f"{self.catalog}.{self.schema(layer)}.{name}"
