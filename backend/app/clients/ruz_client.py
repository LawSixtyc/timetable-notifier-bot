import httpx
from typing import Any

BASE_URL = "https://ruz.spbstu.ru/api/v1/ruz"


class RuzClient:
    def __init__(self, timeout: float = 20.0):
        self.timeout = timeout

    async def _get_json(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{BASE_URL}{path}"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            return response.json()

    async def get_faculties(self) -> list[dict[str, Any]]:
        data = await self._get_json("/faculties")
        return data.get("faculties", [])

    async def get_groups_by_faculty(self, faculty_id: int) -> list[dict[str, Any]]:
        data = await self._get_json(f"/faculties/{faculty_id}/groups")
        return data.get("groups", [])

    async def search_groups(self, query: str) -> list[dict[str, Any]]:
        data = await self._get_json("/search/groups", params={"q": query})
        return data.get("groups", [])

    async def get_group_schedule(self, group_id: int, date: str | None = None) -> dict[str, Any]:
        params = {"date": date} if date else None
        return await self._get_json(f"/scheduler/{group_id}", params=params)