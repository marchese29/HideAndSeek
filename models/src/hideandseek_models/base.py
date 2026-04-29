from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, String
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    type_annotation_map = {
        StrEnum: String,
        datetime: DateTime(timezone=True),
    }
