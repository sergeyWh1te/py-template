from fastapi.responses import JSONResponse


class HealthHandler:
    async def handle(self) -> JSONResponse:
        return JSONResponse({"status": "ok"})
