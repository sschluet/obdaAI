"""No-network checks for bounded, fixed-origin Drive OAuth and file operations."""

import json
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from hub import google_drive_client as drive


def metadata(**changes):
    return (
        dict(
            id="synthetic_file",
            name="Synthetic.txt",
            mimeType="text/plain",
            parents=["synthetic_folder"],
            size="4",
            appProperties={},
            trashed=False,
        )
        | changes
    )


def test_authorization_is_minimum_exact_drive_scope_pkce_not_gmail():
    url = drive.authorization_url(
        "synthetic-client",
        "https://app.example.test/callback",
        "s" * 40,
        "v" * 50,
        [drive.READ_SCOPE, drive.WRITE_SCOPE],
    )
    query = parse_qs(urlsplit(url).query)
    assert set(query["scope"][0].split()) == {drive.READ_SCOPE, drive.WRITE_SCOPE}
    assert query["include_granted_scopes"] == ["false"]
    assert query["code_challenge_method"] == ["S256"]
    assert "v" * 50 not in url and "gmail" not in url


@pytest.mark.parametrize(
    "granted",
    [
        drive.READ_SCOPE + " https://www.googleapis.com/auth/gmail.readonly",
        drive.WRITE_SCOPE,
        "",
        drive.READ_SCOPE + " " + drive.READ_SCOPE,
    ],
)
def test_exchange_rejects_additional_missing_or_duplicate_scopes(granted):
    requests = []

    def reply(request):
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "access_token": "private-token",
                "refresh_token": "private-refresh",
                "scope": granted,
                "token_type": "Bearer",
                "expires_in": 3600,
            },
        )

    with pytest.raises(drive.DriveError):
        drive.exchange_code(
            "synthetic-client",
            "private-secret",
            "https://app.example.test/callback",
            "private-code",
            "v" * 50,
            [drive.READ_SCOPE],
            transport=httpx.MockTransport(reply),
        )
    assert len(requests) == 1 and requests[0].url == drive.TOKEN_URL
    assert b"private-secret" in requests[0].content and "private-secret" not in str(requests[0].url)


def test_refresh_missing_scope_keeps_exact_already_granted_capabilities():
    value = drive.refresh_token(
        "synthetic-client",
        "private-secret",
        "private-refresh",
        [drive.WRITE_SCOPE],
        transport=httpx.MockTransport(
            lambda req: httpx.Response(
                200,
                json={
                    "access_token": "next-private-token",
                    "token_type": "bearer",
                    "expires_in": 3600,
                },
            )
        ),
    )
    assert value["scope"] == drive.WRITE_SCOPE and value["refresh_token"] == "private-refresh"


def test_list_and_export_only_contact_official_fixed_endpoint():
    requests = []

    def reply(request):
        requests.append(request)
        if request.url.path.endswith("/export"):
            return httpx.Response(200, content=b"synthetic-docx")
        return httpx.Response(200, json={"files": [metadata()], "nextPageToken": "next-synthetic"})

    with drive.DriveClient("private-token", transport=httpx.MockTransport(reply)) as client:
        page = client.list_files("synthetic_folder", limit=4)
        assert (
            page["files"][0]["id"] == "synthetic_file"
            and page["next_page_token"] == "next-synthetic"
        )
        assert (
            client.download("synthetic_file", "application/vnd.google-apps.document")
            == b"synthetic-docx"
        )
    assert all(
        r.url.host == "www.googleapis.com" and r.headers["authorization"] == "Bearer private-token"
        for r in requests
    )
    assert (
        requests[1].url.params["mimeType"]
        == drive.EXPORTS["application/vnd.google-apps.document"][0]
    )


@pytest.mark.parametrize(
    "identity", ["../private", "https://evil.example/file", "abc' or true", "a\r\nb", "a" * 201]
)
def test_invalid_file_or_parent_identity_never_dispatches(identity):
    requests = []
    with drive.DriveClient(
        "private-token", transport=httpx.MockTransport(lambda req: requests.append(req))
    ) as client:
        with pytest.raises(drive.DriveError):
            client.metadata(identity)
        with pytest.raises(drive.DriveError):
            client.list_files(identity)
    assert not requests


def test_revocation_final_guard_prevents_http():
    requests = []

    def deny():
        raise PermissionError("revoked")

    with drive.DriveClient(
        "private-token",
        before_send=deny,
        transport=httpx.MockTransport(lambda req: requests.append(req)),
    ) as client:
        with pytest.raises(PermissionError):
            client.list_files()
    assert not requests


def test_revocation_after_receipt_prevents_using_private_response():
    checks = []

    def guard():
        checks.append(True)
        if len(checks) == 2:
            raise PermissionError("revoked")

    with drive.DriveClient(
        "private-token",
        before_send=guard,
        transport=httpx.MockTransport(lambda req: httpx.Response(200, json=metadata())),
    ) as client:
        with pytest.raises(PermissionError):
            client.metadata("synthetic_file")
    assert len(checks) == 2


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(302, headers={"Location": "https://evil.example"}),
        httpx.Response(500, text="private-token private-secret"),
        httpx.Response(200, text="private-document", headers={"content-type": "text/plain"}),
    ],
)
def test_redirects_errors_and_wrong_json_content_are_sanitized(response):
    requests = []

    def reply(req):
        requests.append(req)
        return response

    with drive.DriveClient("private-token", transport=httpx.MockTransport(reply)) as client:
        with pytest.raises(drive.DriveError) as error:
            client.metadata("synthetic_file")
    assert len(requests) == 1 and "private" not in str(error.value)


def test_download_limit_and_unsupported_native_type(monkeypatch):
    monkeypatch.setattr(drive, "MAX_BYTES", 4)
    with drive.DriveClient(
        "private-token",
        transport=httpx.MockTransport(lambda req: httpx.Response(200, content=b"12345")),
    ) as client:
        with pytest.raises(drive.DriveError):
            client.download("synthetic_file", "application/pdf")
        with pytest.raises(drive.DriveError):
            client.download("synthetic_file", "application/vnd.google-apps.shortcut")


def test_create_upload_use_reserved_identity_ownership_and_no_update_method():
    requests = []

    def reply(req):
        requests.append(req)
        if req.url.path.endswith("/generateIds"):
            return httpx.Response(200, json={"ids": ["reserved_one"]})
        return httpx.Response(200, json=metadata(id="reserved_one"))

    with drive.DriveClient("private-token", transport=httpx.MockTransport(reply)) as client:
        assert client.generate_ids() == ["reserved_one"]
        client.create_folder("reserved_one", "obdaAI", {"obdaai_transfer": "attempt-one"})
        client.upload(
            "reserved_one",
            "synthetic_folder",
            "Synthetic.txt",
            b"data",
            "text/plain",
            {"obdaai_transfer": "attempt-two"},
        )
    assert [r.method for r in requests] == ["GET", "POST", "POST"]
    assert json.loads(requests[1].content)["appProperties"] == {"obdaai_transfer": "attempt-one"}
    assert b'"id": "reserved_one"' in requests[2].content and b"attempt-two" in requests[2].content


def test_arbitrary_urls_and_methods_not_permitted_even_with_valid_token():
    requests = []
    with drive.client(httpx.MockTransport(lambda req: requests.append(req))) as client:
        for method, url in [
            ("GET", "https://evil.example"),
            ("DELETE", drive.API_BASE + "/files/synthetic"),
            ("PATCH", drive.API_BASE + "/files/synthetic"),
        ]:
            with pytest.raises(drive.DriveError):
                drive.request(client, method, url, token="private-token")
    assert not requests
