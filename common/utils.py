from uuid import UUID

from fastapi import Header, HTTPException, Request


async def get_header_user_id(x_user_id: str = Header(None)) -> UUID | None:
    if not x_user_id:
        return None
    try:
        # Try to convert the header to a UUID
        return UUID(x_user_id)
    except ValueError as e:
        # The header is not a valid UUID
        raise HTTPException(status_code=400, detail=f'Invalid X-USER-ID header, {e}') from e


def get_client_ip(request: Request) -> str:
    return request.client.host
