from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class Outcome(Enum):
    ACK = "ack"
    NACK = "nack"


@dataclass
class FileRecord:
    file_id: str
    user_id: str
    s3_key: str
    status: str
    updated_at: datetime | None
    delete_claimed_at: datetime | None
    error: str | None = None
    object_owner: str = "rag"


@dataclass(frozen=True)
class DeleteMessage:
    message_id: str
    file_id: str
    user_id: str
    s3_key: str
    created_at: datetime
