"""Conservative distinction between tool-envelope repair and actual user choices."""

import pytest
from hub.agent_questions import tool_confirmation


@pytest.mark.parametrize("message", [
    'Fehlende Informationen: Bitte bestätigen Sie den Aufruf von http.verify '
    'mit path="/backup/info" und expected={"/body/name":null}.',
    'Bitte bestätige: http.verify arguments={"path":"/backup/info"}.',
    'Bitte bestätigen Sie den Aufruf von http.verify mit '
    'expected={' + ','.join('"/synthetic/' + str(i) + '":null' for i in range(150)) + '}.',
    'Please confirm the http call with parameters={"path":"/api/config"}.',
    'May I execute http.verify with path="/backup/info"?',
    'Can I call ha.websocket with parameters={"type":"synthetic"}?',
    'Darf ich http.verify mit "path": "/backup/info" ausführen?',
    'Bestätigen Sie bitte den Aufruf von http.verify mit expected={"/body/state":"off"}.',
    'Please confirm this mcp.call: {"arguments": {"synthetic": 1}}.',
])
def test_concrete_tool_confirmation_is_only_a_repair_signal(message):
    assert tool_confirmation(message) is True


@pytest.mark.parametrize("message", [
    'Welches Backup soll ich vor dem Update verwenden?',
    'Welche Backup-ID soll http.verify mit path="/backup/info" prüfen?',
    'Bitte bestätigen Sie, welche Backup-ID ich für http.verify mit '
    'path="/backup/info" verwenden soll.',
    'Please confirm which backup http.verify with path="/backup/info" should inspect.',
    'Ist Home Assistant OS oder eine Containerinstallation vorhanden?',
    'Für http.verify fehlt der erwartete Versionswert. Welche Version ist gewünscht?',
    'http.verify mit path="/backup/info" prüft den gespeicherten Zustand.',
    'Der Benutzer hat den Aufruf von http.verify mit path="/backup/info" bestätigt.',
    'Bitte bestätige die Zielauswahl Home Assistant.',
    'Please confirm the backup name; http.verify is available.',
    'May I ask which host should receive the update? http.verify path="/backup/info".',
    'Bitte bestätige den Aufruf von hypothetical.tool mit path="/backup/info".',
    'Bitte bestätige den Aufruf von http.verify_extra mit path="/backup/info".',
    'Bitte bestätige den Aufruf von other.http.verify mit path="/backup/info".',
    'Please confirm the http.verify call without known parameter labels.',
    'Please confirm the address http://example.invalid with path="/backup/info".',
    '',
])
def test_legitimate_questions_and_explanations_are_not_rewritten(message):
    assert tool_confirmation(message) is False


def test_invalid_or_excessively_large_messages_do_not_trigger_repair():
    assert tool_confirmation(None) is False  # type: ignore[arg-type]
    assert tool_confirmation('Please confirm http path="/"' + 'x' * 12000) is False


@pytest.mark.parametrize("message", [
    'Bitte bestätigen Sie, ob ein Update der HomeAssistantInstanz '
    '(Version 2026.11.4) durchgeführt werden soll. Dies erfordert Neustart.',
    'Bitte bestätige, dass ich die Updates ausführen soll.',
    'Bitte bestätigen Sie den Neustart, bevor ich das Update installieren kann.',
    'Please confirm whether I should install the Home Assistant update. A restart is required.',
    'Please confirm the execution of the pending updates.',
    'May I execute the pending updates?',
])
def test_redundant_execution_approval_is_only_a_repair_signal(message):
    from hub.agent_questions import execution_confirmation

    assert execution_confirmation(message) is True


@pytest.mark.parametrize("message", [
    'Bitte bestätige, ob der Schwellwert 15 oder 20 sein soll, bevor ich das Update ausführe.',
    'Bitte bestätigen Sie die gewünschte Version vor dem Installieren.',
    'Bitte bestätigen Sie, welche Version ich installieren soll.',
    'Welches Ziel soll ich aktualisieren?',
    'Please confirm which host should run the update.',
    'Please confirm whether the threshold should be 15 or 20 before I start.',
    'Please specify the desired state before execution.',
    'Bitte bestätige den Parameter für die Ausführung.',
    'Ein Update erfordert einen Neustart; die Ausführung wurde bereits bestätigt.',
    'Die Updates können installiert werden.',
    'Bitte bestätige den aktuellen Zustand.',
    '',
])
def test_execution_detection_preserves_essential_choices_and_explanations(message):
    from hub.agent_questions import execution_confirmation

    assert execution_confirmation(message) is False


def test_execution_detection_rejects_invalid_or_oversized_messages():
    from hub.agent_questions import execution_confirmation

    assert execution_confirmation(None) is False  # type: ignore[arg-type]
    assert execution_confirmation('Please confirm execution ' + 'x' * 12000) is False
