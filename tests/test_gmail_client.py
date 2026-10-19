"""Official Gmail transport contract against synthetic HTTP, never a real mailbox."""

import base64
import json
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from hub import gmail_client as gmail

CALLBACK = "https://app.example.test/api/integrations/gmail/oauth/callback"
VERIFIER = "v" * 64


def tokens(**changes):
    return {
        "access_token": "synthetic-access",
        "refresh_token": "synthetic-refresh",
        "token_type": "Bearer",
        "expires_in": 3600,
        "scope": gmail.SCOPE,
        **changes,
    }


def message(text="private text", **changes):
    return {
        "id": "abc123",
        "threadId": "def456",
        "labelIds": ["INBOX"],
        "snippet": "private preview",
        "payload": {
            "mimeType": "text/plain",
            "headers": [{"name": "Subject", "value": "Synthetic subject"}],
            "body": {"data": base64.urlsafe_b64encode(text.encode()).decode()},
        },
        **changes,
    }


def exchange(response, **kwargs):
    return gmail.exchange_code(
        "synthetic-client.apps.googleusercontent.com",
        "synthetic-secret",
        CALLBACK,
        "synthetic-code",
        VERIFIER,
        transport=httpx.MockTransport(lambda request: response(request)),
        **kwargs,
    )


def test_authorization_is_readonly_offline_pkce_without_combined_scopes():
    url = gmail.authorization_url("client", CALLBACK, "s" * 48, VERIFIER)
    assert url.startswith(gmail.AUTH_URL + "?")
    params = parse_qs(urlsplit(url).query)
    assert params["scope"] == [gmail.SCOPE]
    assert params["redirect_uri"] == [CALLBACK]
    assert params["access_type"] == ["offline"]
    assert params["include_granted_scopes"] == ["false"]
    assert params["prompt"] == ["consent select_account"]
    assert params["code_challenge_method"] == ["S256"]
    assert params["code_challenge"] != [VERIFIER]
    assert "client_secret" not in params and "code_verifier" not in params


@pytest.mark.parametrize(
    "callback",
    [
        "http://app.example.test/callback",
        "https://user:pass@app.example.test/callback",
        "https://app.example.test/callback?secret=1",
        "https://app.example.test/../callback",
        "https://app.example.test/callback#x",
        "https://app.example.test/%2fcallback",
    ],
)
def test_callback_constraints(callback):
    with pytest.raises(gmail.GmailError):
        gmail.authorization_url("client", callback, "s" * 48, VERIFIER)


def test_exchange_fixed_endpoint_post_body_and_secret_filtered_result():
    sent, boundary = [], []

    def handler(request):
        sent.append(request)
        assert boundary == [True]
        assert str(request.url) == gmail.TOKEN_URL and request.method == "POST"
        body = parse_qs(request.content.decode())
        assert body["code_verifier"] == [VERIFIER]
        assert body["client_secret"] == ["synthetic-secret"]
        return httpx.Response(200, json=tokens(id_token="never-return-id-token"))

    result = exchange(handler, before_send=lambda: boundary.append(True))
    assert result["refresh_token"] == "synthetic-refresh"
    assert result["scope"] == gmail.SCOPE and result["expires_at"] > 0
    assert "never-return-id-token" not in json.dumps(result)
    assert len(sent) == 1


@pytest.mark.parametrize(
    "change",
    [
        {"scope": None},
        {"scope": ""},
        {"scope": gmail.SCOPE + " openid"},
        {"scope": "https://mail.google.com/"},
        {"token_type": "MAC"},
        {"expires_in": True},
        {"expires_in": -1},
        {"expires_in": float("inf")},
        {"expires_in": 999999},
        {"access_token": ""},
    ],
)
def test_exchange_rejects_wrong_or_missing_grant(change):
    def handler(request):
        body = tokens(**change)
        if change.get("scope", "not-none") is None:
            del body["scope"]
        return httpx.Response(200, json=body)

    with pytest.raises(gmail.GmailError):
        exchange(handler)


def test_refresh_retains_validated_scope_and_refresh_token_when_google_omits_them():
    def handler(request):
        assert str(request.url) == gmail.TOKEN_URL
        assert parse_qs(request.content.decode())["grant_type"] == ["refresh_token"]
        body = tokens()
        del body["scope"]
        del body["refresh_token"]
        return httpx.Response(200, json=body)

    result = gmail.refresh_token(
        "client", "secret", "old-refresh", transport=httpx.MockTransport(handler)
    )
    assert result["scope"] == gmail.SCOPE and result["refresh_token"] == "old-refresh"


def test_revoke_uses_only_fixed_post_endpoint():
    def handler(request):
        assert str(request.url) == gmail.REVOKE_URL and request.method == "POST"
        assert parse_qs(request.content.decode()) == {"token": ["synthetic-refresh"]}
        return httpx.Response(200, content=b"")

    gmail.revoke_token("synthetic-refresh", transport=httpx.MockTransport(handler))


@pytest.mark.parametrize("status", [302, 400, 401, 429, 500])
def test_oauth_errors_and_redirects_neither_leak_nor_retry(status):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            status,
            headers={"Location": "https://evil.example/token"},
            json={"error": "synthetic-secret synthetic-code"},
        )

    with pytest.raises(gmail.GmailError) as error:
        exchange(handler)
    assert "synthetic" not in str(error.value) and len(calls) == 1


def test_transport_exception_does_not_echo_credentials():
    def handler(request):
        raise httpx.ConnectError("synthetic-secret", request=request)

    with pytest.raises(gmail.GmailError) as error:
        exchange(handler)
    assert str(error.value) == "Google request failed" and error.value.__suppress_context__


def test_fresh_boundary_gates_every_read_and_blocks_before_transport():
    events = []

    def before():
        events.append("gate")
        if len(events) > 2:
            raise PermissionError("revoked")

    def handler(request):
        events.append("send")
        assert request.headers["Authorization"] == "Bearer synthetic-access"
        return httpx.Response(200, json={"emailAddress": "aurora@example.test"})

    with gmail.GmailClient(
        "synthetic-access", transport=httpx.MockTransport(handler), before_send=before
    ) as client:
        assert client.profile()["emailAddress"] == "aurora@example.test"
        with pytest.raises(PermissionError):
            client.profile()
    assert events == ["gate", "send", "gate"]


def test_labels_and_search_preserve_private_query_as_encoded_fixed_origin_parameters():
    calls = []

    def handler(request):
        calls.append(request)
        assert request.url.host == "gmail.googleapis.com" and request.method == "GET"
        assert request.url.path.startswith("/gmail/v1/users/me/")
        if request.url.path.endswith("/labels"):
            return httpx.Response(
                200, json={"labels": [{"id": "INBOX", "name": "Inbox", "type": "system"}]}
            )
        assert request.url.params["q"] == 'from:aurora@example.test subject:"my private data"'
        assert request.url.params["pageToken"] == "opaque_next"
        assert request.url.params["maxResults"] == "10"
        assert request.url.params.get_list("labelIds") == ["INBOX", "UNREAD"]
        return httpx.Response(
            200,
            json={"messages": [{"id": "abc123", "threadId": "def456"}], "nextPageToken": "next2"},
        )

    with gmail.GmailClient("token", transport=httpx.MockTransport(handler)) as client:
        assert client.labels()["labels"][0]["id"] == "INBOX"
        assert (
            client.messages(
                'from:aurora@example.test subject:"my private data"',
                "opaque_next",
                10,
                ("INBOX", "UNREAD"),
            )["nextPageToken"]
            == "next2"
        )
    assert len(calls) == 2


@pytest.mark.parametrize(
    "operation",
    [
        lambda c: c.message("../send"),
        lambda c: c.thread("https://evil.example"),
        lambda c: c.messages("x" * 1025),
        lambda c: c.messages(limit=101),
        lambda c: c.messages(page_token="x" * 2049),
        lambda c: c.messages(label_ids=("../x",)),
        lambda c: c.messages(limit=True),
        lambda c: c.message("abc123", max_chars=20001),
    ],
)
def test_invalid_tool_inputs_never_dispatch(operation):
    calls = []
    with gmail.GmailClient(
        "token", transport=httpx.MockTransport(lambda r: calls.append(r))
    ) as client:
        with pytest.raises(gmail.GmailError):
            operation(client)
    assert not calls


def test_full_message_extracts_only_bounded_text_and_attachment_metadata():
    body = message(
        payload={
            "mimeType": "multipart/mixed",
            "headers": [{"name": "Subject", "value": "Untrusted subject"}],
            "parts": [
                {
                    "mimeType": "text/plain",
                    "body": {"data": base64.urlsafe_b64encode(b"hello private world").decode()},
                },
                {
                    "mimeType": "text/html",
                    "body": {
                        "data": base64.urlsafe_b64encode(
                            b'<img src="https://evil.example/track">'
                        ).decode()
                    },
                },
                {
                    "mimeType": "application/pdf",
                    "filename": "private.pdf",
                    "body": {"attachmentId": "opaque", "size": 42},
                },
            ],
        }
    )

    def handler(request):
        assert str(request.url) == gmail.API_BASE + "/messages/abc123?format=full"
        return httpx.Response(200, json=body)

    with gmail.GmailClient("token", transport=httpx.MockTransport(handler)) as client:
        result = client.message("abc123", max_chars=5)
    assert result["text"] == "hello" and result["truncated"] and result["html_omitted"]
    assert result["content_trust"] == "untrusted_email"
    assert result["attachments"] == [
        {"filename": "private.pdf", "mimeType": "application/pdf", "size": 42}
    ]
    assert "evil.example" not in json.dumps(result) and "data" not in result


def test_html_only_mail_is_explicitly_omitted_without_fetching_remote_content():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            200, json=message(payload={"mimeType": "text/html", "body": {"data": "PHNjcmlwdD4="}})
        )

    with gmail.GmailClient("token", transport=httpx.MockTransport(handler)) as client:
        result = client.message("abc123")
    assert result["html_omitted"] and result["text"] == "" and len(calls) == 1


def test_mime_nesting_and_identity_are_checked():
    part = {"mimeType": "text/plain", "body": {}}
    for _ in range(12):
        part = {"mimeType": "multipart/mixed", "parts": [part]}
    for body in [message(payload=part), message(id="different")]:
        with gmail.GmailClient(
            "token",
            transport=httpx.MockTransport(lambda r, body=body: httpx.Response(200, json=body)),
        ) as client:
            with pytest.raises(gmail.GmailError):
                client.message("abc123")


def test_thread_total_text_is_bounded():
    rows = [message("abcdefghij"), message("klmnopqrst", id="abc124")]
    with gmail.GmailClient(
        "token",
        transport=httpx.MockTransport(
            lambda r: httpx.Response(200, json={"id": "def456", "messages": rows})
        ),
    ) as client:
        result = client.thread("def456", max_chars=12)
    assert sum(len(m["text"]) for m in result["messages"]) <= 12 and result["truncated"]


def test_response_byte_limit_and_wrong_content_types():
    for response in [
        httpx.Response(200, content=b"x" * (gmail.MAX_RESPONSE_BYTES + 1)),
        httpx.Response(200, text="<html>not API JSON</html>"),
        httpx.Response(200, json=["not an object"]),
    ]:
        with gmail.GmailClient(
            "token", transport=httpx.MockTransport(lambda r, response=response: response)
        ) as client:
            with pytest.raises(gmail.GmailError):
                client.profile()


@pytest.mark.parametrize(
    "url,method",
    [
        (gmail.API_BASE + "/messages/send", "POST"),
        (gmail.API_BASE + "/../other", "GET"),
        ("https://evil.example/gmail/v1/users/me/profile", "GET"),
        ("https://gmail.googleapis.com/gmail/v1/users/another/profile", "GET"),
        ("http://gmail.googleapis.com/gmail/v1/users/me/profile", "GET"),
    ],
)
def test_final_transport_rejects_non_read_operations_and_alternate_origins(url, method):
    sent = []
    with gmail._http_client(httpx.MockTransport(lambda request: sent.append(request))) as client:
        with pytest.raises(gmail.GmailError):
            gmail._request(client, method, url, token="synthetic-access")
    assert not sent


@pytest.mark.parametrize("operation", ["exchange", "refresh", "revoke"])
def test_revocation_blocks_oauth_before_any_credential_dispatch(operation):
    sent = []

    def denied():
        raise PermissionError("profile changed")

    options = {
        "transport": httpx.MockTransport(lambda request: sent.append(request)),
        "before_send": denied,
    }
    with pytest.raises(PermissionError):
        if operation == "exchange":
            gmail.exchange_code("client", "secret", CALLBACK, "code", VERIFIER, **options)
        elif operation == "refresh":
            gmail.refresh_token("client", "secret", "refresh", **options)
        else:
            gmail.revoke_token("refresh", **options)
    assert not sent
