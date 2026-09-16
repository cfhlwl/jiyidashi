from unittest.mock import MagicMock
from uuid import uuid4

from sqlalchemy.exc import IntegrityError

from app.api.objects import create_object
from app.models import ObjectItem
from app.schemas import ObjectCreate


def test_concurrent_duplicate_object_insert_reselects_existing():
    user_id = uuid4()
    existing = ObjectItem(
        id=uuid4(),
        user_id=user_id,
        name="护照",
        normalized_name="护照",
    )
    db = MagicMock()
    db.scalar.side_effect = [None, existing]
    db.commit.side_effect = IntegrityError("INSERT objects", {}, RuntimeError("unique"))

    # [人工注释][S1-FIX-006] 模拟两设备同时首次创建同名 Object：唯一键失败后必须 rollback + reselect，而不是向用户返回 500。
    result = create_object(ObjectCreate(name="护照"), user_id, db)

    assert result is existing
    db.rollback.assert_called_once_with()
    assert db.scalar.call_count == 2
