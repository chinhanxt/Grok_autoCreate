import os
import json
import uuid
import pytest
from core.exporter import (
    AccountRecord,
    save_account,
    load_accounts,
    load_oauth_accounts,
    save_oauth_router_accounts,
    export_for_router
)


def test_account_record_format():
    rec = AccountRecord(
        email="john.doe@example.com",
        password="SecretPassword123!",
        first_name="John",
        last_name="Doe",
        user_id="usr_98765",
        session_id="sess_12345",
        sso_cookie="sso_jwt_test",
        sso_rw_cookie="sso_rw_jwt_test",
        access_token="at_jwt_123",
        refresh_token="rt_456"
    )
    assert rec.to_line_format() == "john.doe@example.com:SecretPassword123!:sso_jwt_test:usr_98765"
    d = rec.to_dict()
    assert d["email"] == "john.doe@example.com"
    assert d["first_name"] == "John"
    assert d["status"] == "active"

    oauth_d = rec.to_oauth_dict()
    assert oauth_d == {
        "email": "john.doe@example.com",
        "access_token": "at_jwt_123",
        "refresh_token": "rt_456",
        "sso_cookie": "sso_jwt_test",
        "sso_rw_cookie": "sso_rw_jwt_test"
    }


def test_save_and_load_account(tmp_path):
    json_file = str(tmp_path / "accounts.json")
    txt_file = str(tmp_path / "accounts.txt")
    
    rec1 = AccountRecord(
        email="alpha@example.com",
        password="Pass1",
        first_name="A",
        last_name="B",
        user_id="u1",
        sso_cookie="sso1"
    )
    rec2 = AccountRecord(
        email="beta@example.com",
        password="Pass2",
        first_name="C",
        last_name="D",
        user_id="u2",
        sso_cookie="sso2"
    )
    
    save_account(rec1, json_path=json_file, txt_path=txt_file)
    save_account(rec2, json_path=json_file, txt_path=txt_file)
    
    loaded = load_accounts(json_path=json_file)
    assert len(loaded) == 2
    assert loaded[0]["email"] == "alpha@example.com"
    assert loaded[1]["email"] == "beta@example.com"
    
    with open(txt_file, "r") as f:
        lines = [line.strip() for line in f.readlines() if line.strip()]
        assert len(lines) == 2
        assert lines[0] == "alpha@example.com:Pass1:sso1:u1"
        assert lines[1] == "beta@example.com:Pass2:sso2:u2"


def test_load_and_save_oauth_accounts_5_fields(tmp_path):
    json_file = str(tmp_path / "accounts.json")
    router_file = str(tmp_path / "router.json")
    
    rec = AccountRecord(
        email="oauth@example.com",
        password="Pass",
        first_name="A",
        last_name="B",
        user_id="u1",
        sso_cookie="sso_cookie_val",
        sso_rw_cookie="sso_rw_val",
        access_token="eyJ0eXAiOiJhdCtqd3Qi...",
        refresh_token="rt_abc123xyz"
    )
    save_account(rec, json_path=json_file, txt_path=str(tmp_path / "accounts.txt"))
    
    oauth_list = load_oauth_accounts(json_path=json_file)
    assert len(oauth_list) == 1
    assert oauth_list[0] == {
        "email": "oauth@example.com",
        "access_token": "eyJ0eXAiOiJhdCtqd3Qi...",
        "refresh_token": "rt_abc123xyz",
        "sso_cookie": "sso_cookie_val",
        "sso_rw_cookie": "sso_rw_val"
    }

    count = save_oauth_router_accounts(router_file, json_path=json_file)
    assert count == 1
    with open(router_file, "r") as f:
        data = json.load(f)
        assert len(data) == 1
        assert data[0]["email"] == "oauth@example.com"
        assert data[0]["sso_cookie"] == "sso_cookie_val"
        assert data[0]["sso_rw_cookie"] == "sso_rw_val"


def test_account_with_real_refresh_token_exported_correctly():
    """
    Account có refresh_token thật thì được export đúng:
    - to_oauth_dict(): refresh_token mang giá trị OAuth refresh token thật
    - to_router_node_dict(): refreshToken là refresh token thật, oauthVerified=True
    """
    rec = AccountRecord(
        email="real_oauth@example.com",
        password="Password123!",
        first_name="Jane",
        last_name="Doe",
        user_id="usr_real_123",
        access_token="eyJhbGciOi...",
        refresh_token="rt_valid_oauth_secret_abc123",
        sso_cookie="sso=cookie_val",
        sso_rw_cookie="sso_rw=cookie_rw_val",
    )

    oauth_d = rec.to_oauth_dict()
    assert oauth_d["refresh_token"] == "rt_valid_oauth_secret_abc123"
    assert oauth_d["access_token"] == "eyJhbGciOi..."
    assert oauth_d["sso_cookie"] == "sso=cookie_val"
    assert oauth_d["sso_rw_cookie"] == "sso_rw=cookie_rw_val"

    router_node = rec.to_router_node_dict()
    assert router_node["id"] == "usr_real_123"
    assert router_node["name"] == "real_oauth@example.com"
    assert router_node["email"] == "real_oauth@example.com"
    assert router_node["ssoToken"] == "eyJhbGciOi..."
    assert router_node["refreshToken"] == "rt_valid_oauth_secret_abc123"
    assert router_node["oauthVerified"] is True


def test_account_with_only_sso_cookie_does_not_mistake_cookie_for_refresh_token(tmp_path):
    """
    Account chỉ có sso_cookie thì refresh_token không bị gán nhầm bằng cookie:
    - to_oauth_dict(): refresh_token là rỗng (""), không bị lấy sso_rw_cookie hay sso_cookie thế vào
    - to_router_node_dict(): refreshToken là rỗng (""), oauthVerified=False
    - Trường hợp refresh_token bị nhầm lưu chuỗi cookie (bắt đầu bằng sso hoặc có dấu chấm phẩy)
      cũng không được nhận diện là refresh token thật.
    - load_oauth_accounts() cũng xuất refresh_token rỗng.
    """
    rec_cookie_only = AccountRecord(
        email="cookie_only@example.com",
        password="Pass",
        first_name="Cookie",
        last_name="User",
        user_id="usr_cookie_1",
        access_token="",
        refresh_token="",
        sso_cookie="sso=my_sso_cookie_abc",
        sso_rw_cookie="sso_rw=my_sso_rw_cookie_def",
    )

    oauth_d = rec_cookie_only.to_oauth_dict()
    assert oauth_d["refresh_token"] == ""
    assert oauth_d["sso_cookie"] == "sso=my_sso_cookie_abc"
    assert oauth_d["sso_rw_cookie"] == "sso_rw=my_sso_rw_cookie_def"

    router_node = rec_cookie_only.to_router_node_dict()
    assert router_node["refreshToken"] == ""
    assert router_node["oauthVerified"] is False

    # Trường hợp refresh_token chứa chuỗi cookie dạng 'sso=...' hoặc cookie có ';'
    rec_bad_rt = AccountRecord(
        email="bad_rt@example.com",
        password="Pass",
        first_name="Bad",
        last_name="RT",
        user_id="usr_cookie_2",
        refresh_token="sso=fake_rt_from_cookie; path=/; domain=x.ai",
        sso_cookie="sso=fake_rt_from_cookie",
    )
    assert rec_bad_rt.to_oauth_dict()["refresh_token"] == ""
    bad_node = rec_bad_rt.to_router_node_dict()
    assert bad_node["refreshToken"] == ""
    assert bad_node["oauthVerified"] is False

    # Kiểm tra load_oauth_accounts từ file json
    json_file = str(tmp_path / "cookie_accounts.json")
    save_account(rec_cookie_only, json_path=json_file, txt_path=str(tmp_path / "acc.txt"))
    loaded = load_oauth_accounts(json_path=json_file)
    assert len(loaded) == 1
    assert loaded[0]["refresh_token"] == ""
    assert loaded[0]["sso_cookie"] == "sso=my_sso_cookie_abc"


def test_to_router_node_dict_required_fields_and_defaults():
    """
    to_router_node_dict() xuất đầy đủ các trường:
    id, name, email, ssoToken, refreshToken, oauthVerified, status, createdAt, oauthScope.
    Kiểm tra tự tạo id UUID khi user_id rỗng, và scope mặc định / scope từ extra.
    """
    rec_with_uid = AccountRecord(
        email="test_router@example.com",
        password="Pass",
        first_name="A",
        last_name="B",
        user_id="custom_user_id_456",
        access_token="at_abc",
        refresh_token="rt_xyz",
        status="active",
        created_at="2026-09-29T10:00:00Z",
        extra={"scope": "custom:scope:all"}
    )
    node = rec_with_uid.to_router_node_dict()

    required_fields = ["id", "name", "email", "ssoToken", "refreshToken", "status", "createdAt", "oauthVerified", "oauthScope"]
    for f in required_fields:
        assert f in node, f"Missing required field: {f}"

    assert node["id"] == "custom_user_id_456"
    assert node["name"] == "test_router@example.com"
    assert node["email"] == "test_router@example.com"
    assert node["ssoToken"] == "at_abc"
    assert node["refreshToken"] == "rt_xyz"
    assert node["status"] == "active"
    assert node["createdAt"] == "2026-09-29T10:00:00Z"
    assert node["oauthVerified"] is True
    assert node["oauthScope"] == "custom:scope:all"

    # Kiểm tra khi user_id rỗng thì id là một UUID hợp lệ
    rec_no_uid = AccountRecord(
        email="nouid@example.com",
        password="Pass",
        first_name="No",
        last_name="Uid",
        user_id="",
        access_token="at_123",
        refresh_token="",
        extra={}
    )
    node_no_uid = rec_no_uid.to_router_node_dict()
    assert node_no_uid["id"] != ""
    parsed_uuid = uuid.UUID(node_no_uid["id"])
    assert str(parsed_uuid) == node_no_uid["id"]
    assert node_no_uid["oauthVerified"] is False
    assert node_no_uid["oauthScope"] == "grok-cli:access"


def test_export_for_router(tmp_path):
    """
    Kiểm tra hàm export_for_router():
    - Xuất dữ liệu router từ danh sách AccountRecord hoặc file json
    - Lưu file router.json chuẩn
    - Lọc status qua only_healthy=True
    """
    json_file = str(tmp_path / "accounts.json")
    router_file = str(tmp_path / "router_output.json")

    rec1 = AccountRecord(
        email="healthy_oauth@example.com",
        password="Pass",
        first_name="H",
        last_name="O",
        user_id="usr_h1",
        access_token="at_valid",
        refresh_token="rt_valid_123",
        status="active"
    )
    rec2 = AccountRecord(
        email="cookie_inactive@example.com",
        password="Pass",
        first_name="C",
        last_name="I",
        user_id="usr_c2",
        access_token="",
        refresh_token="",
        sso_cookie="sso=cookie",
        status="suspended"
    )
    save_account(rec1, json_path=json_file, txt_path=str(tmp_path / "acc.txt"))
    save_account(rec2, json_path=json_file, txt_path=str(tmp_path / "acc.txt"))

    # 1. Export tất cả tài khoản
    nodes = export_for_router(output_path=router_file, json_path=json_file, only_healthy=False)
    assert len(nodes) == 2
    assert nodes[0]["email"] == "healthy_oauth@example.com"
    assert nodes[0]["refreshToken"] == "rt_valid_123"
    assert nodes[0]["oauthVerified"] is True
    assert nodes[1]["email"] == "cookie_inactive@example.com"
    assert nodes[1]["refreshToken"] == ""
    assert nodes[1]["oauthVerified"] is False

    with open(router_file, "r") as f:
        saved_data = json.load(f)
        assert len(saved_data) == 2
        assert saved_data[0]["id"] == "usr_h1"

    # 2. Export chỉ các tài khoản healthy
    healthy_nodes = export_for_router(json_path=json_file, only_healthy=True)
    assert len(healthy_nodes) == 1
    assert healthy_nodes[0]["email"] == "healthy_oauth@example.com"

    # 3. Export trực tiếp từ danh sách object
    direct_nodes = export_for_router(accounts=[rec1])
    assert len(direct_nodes) == 1
    assert direct_nodes[0]["id"] == "usr_h1"
