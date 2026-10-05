from pydantic import BaseModel, ConfigDict


class Command(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ServiceError(Exception):
    def __init__(self, status: int, code: str) -> None:
        super().__init__(code)
        self.status = status
        self.code = code
