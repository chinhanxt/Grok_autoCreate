import os
import json
import pytest
from core.exporter import (
    AccountRecord,
    save_account,
    load_accounts,
    load_oauth_accounts,
    save_oauth_router_accounts
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
