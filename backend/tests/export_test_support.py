from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

from app.services.export_service import generate_export_file, remove_temp_file


async def export_payload(client, headers: dict[str, str]) -> tuple[dict, str]:
    profile = await client.get("/v1/user", headers=headers)
    assert profile.status_code == 200
    user_id = UUID(profile.json()["id"])
    generated = generate_export_file(
        owner_user_id=user_id,
        authority_check=lambda: None,
    )
    try:
        text = Path(generated.path).read_text(encoding="utf-8")
        return json.loads(text), text
    finally:
        remove_temp_file(generated.path)
