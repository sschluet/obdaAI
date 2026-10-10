# Web research settings

Settings → Webrecherche provides the server-owned research preferences. The
authenticated single-user application can enable or disable research, choose
all languages/German/English, select SafeSearch off/moderate/strict, set 1–8
results and a 5–30 second search timeout. The existing search service address
and allowed IP remain operator configuration; the UI cannot submit arbitrary
URLs or networking targets.

`GET /api/web-settings` reads the current values. `PUT /api/web-settings` requires
the current revision, a valid authenticated session and CSRF/origin checks. A
stale revision is rejected rather than overwriting newer settings. Schema 0028
stores these preferences separately from provider credentials and answer style.

The connection check uses one fixed public example query against the configured
search service. It confirms reachability and result parsing; it does not prove
the quality or availability of every upstream search engine. It does not use a
private chat question, history, files, Vault or Memory.

The personal browser default under General still determines whether the chat's
Websuche switch starts enabled. An enabled server setting makes research
available; it does not override the visible Nur lokal mode or add permission to
transfer a conversation to a cloud model. Each permitted run binds its actual
public query at the API boundary. No per-query confirmation dialog is needed.

Release 8337ebf / schema0028: CI38058159977 passed 667 tests and 18 browser
checks. The dedicated test VM verified the actual settings panel, real search
connection check, reload and mobile layout. Real settings remained unchanged.
Save, conflict, disabled-provider and frozen-run controls use isolated API/browser
and PostgreSQL tests. See STATUS for backup and preserved-data evidence.
