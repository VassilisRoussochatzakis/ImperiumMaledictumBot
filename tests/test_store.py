import pytest

from imbot import model
from imbot.store import PermissionDenied, StaleEdit, Store
from tests.conftest import ADMIN, GM, GM_ROLE, GUILD, OTHER_GUILD, OWNER, PLAYER, actor


def test_owner_can_create_and_data_survives_reopen(tmp_path):
    path = str(tmp_path / "chars.db")
    s = Store(path)
    char, v = s.save(actor(OWNER), OWNER, {"name": "Vex", "skills": [{"name": "Lore", "rating": 50}]})
    assert v == 1 and char["skills"][0]["rating"] == 50
    s.close()
    s2 = Store(path)
    loaded, v2 = s2.load(GUILD, OWNER)
    assert loaded == char and v2 == 1
    s2.close()


def test_versions_and_stale_edits():
    s = Store(":memory:")
    _, v1 = s.save(actor(OWNER), OWNER, {"name": "Vex"})
    _, v2 = s.save(actor(OWNER), OWNER, {"description": "new"}, expected_version=v1)
    assert v2 == 2
    with pytest.raises(StaleEdit):
        s.save(actor(OWNER), OWNER, {"description": "stale"}, expected_version=v1)
    assert s.load(GUILD, OWNER)[0]["description"] == "new"  # nothing overwritten
    with pytest.raises(StaleEdit):
        s.save(actor(PLAYER), PLAYER, {"name": "P"}, expected_version=3)  # creating must see version 0


def test_ordinary_player_cannot_edit_others_but_gm_and_admin_can():
    s = Store(":memory:")
    s.save(actor(OWNER), OWNER, {"name": "Vex"})
    with pytest.raises(PermissionDenied):
        s.save(actor(PLAYER), OWNER, {"description": "hacked"})
    with pytest.raises(PermissionDenied):
        s.delete(actor(PLAYER), OWNER)
    with pytest.raises(PermissionDenied):
        s.save(actor(GM, roles=[GM_ROLE]), OWNER, {"description": "x"})  # role not configured yet
    s.set_gm_role(GUILD, GM_ROLE)
    assert s.save(actor(GM, roles=[GM_ROLE]), OWNER, {"description": "gm edit"})[0]["description"] == "gm edit"
    assert s.save(actor(ADMIN, admin=True), OWNER, {"description": "admin edit"})[0]["description"] == "admin edit"
    assert s.load(GUILD, OWNER)[0]["description"] == "admin edit"


def test_guilds_are_isolated():
    s = Store(":memory:")
    s.set_gm_role(GUILD, GM_ROLE)
    s.save(actor(OWNER), OWNER, {"name": "Vex"})
    assert s.load(OTHER_GUILD, OWNER) is None
    # GM role of GUILD grants nothing in OTHER_GUILD; same user id, different server
    with pytest.raises(PermissionDenied):
        s.save(actor(GM, guild_id=OTHER_GUILD, roles=[GM_ROLE]), OWNER, {"name": "x"})
    s.save(actor(OWNER, guild_id=OTHER_GUILD), OWNER, {"name": "Other Vex"})
    assert s.load(GUILD, OWNER)[0]["name"] == "Vex" and s.load(OTHER_GUILD, OWNER)[0]["name"] == "Other Vex"
    assert s.delete(actor(OWNER, guild_id=OTHER_GUILD), OWNER) and s.load(GUILD, OWNER) is not None


def test_validation_failure_writes_nothing():
    s = Store(":memory:")
    s.save(actor(OWNER), OWNER, {"name": "Vex", "talents": [{"name": "T"}]})
    with pytest.raises(model.ValidationError):
        s.save(actor(OWNER), OWNER, {"talents": [{"name": "T2"}], "characteristics": {"WS": "lots"}})
    char, v = s.load(GUILD, OWNER)
    assert v == 1 and char["talents"] == [{"name": "T", "notes": ""}]


def test_lost_gm_role_is_rechecked_on_every_write():
    s = Store(":memory:")
    s.set_gm_role(GUILD, GM_ROLE)
    s.save(actor(OWNER), OWNER, {"name": "Vex"})
    gm_then = actor(GM, roles=[GM_ROLE])
    s.save(gm_then, OWNER, {"description": "ok"})
    s.set_gm_role(GUILD, None)  # role removed from config (or the member lost it: role_ids would be empty)
    with pytest.raises(PermissionDenied):
        s.save(gm_then, OWNER, {"description": "no longer"})
    with pytest.raises(PermissionDenied):
        s.save(actor(GM, roles=[]), OWNER, {"description": "no longer"})
