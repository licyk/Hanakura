"""FastAPI dependencies. Services come from ``app.state`` rather than a global locator."""

from typing import Annotated

from fastapi import Depends, Request

from hanakura.core.context import Services


def get_services(request: Request) -> Services:
    return request.app.state.services


ServicesDep = Annotated[Services, Depends(get_services)]
