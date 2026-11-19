from typing import Generic, TypeVar

from pydantic import BaseModel

DataT = TypeVar("DataT")


class ApiError(BaseModel):
    code: str
    message: str
    field: str | None = None


class Pagination(BaseModel):
    page: int
    page_size: int
    total: int
    total_pages: int


class ApiResponse(BaseModel, Generic[DataT]):
    message: str
    errors: list[ApiError]
    data: DataT | None
    pagination: Pagination | None


ERROR_RESPONSE = {"model": ApiResponse[None]}
