"""Generate a login hash interactively; never request a password in chat."""

from getpass import getpass

from hub.auth import password_hash

password = getpass("Neues Hub-Passwort (mindestens 12 Zeichen): ")
if len(password) < 12 or password != getpass("Bestätigen: "):
    raise SystemExit("Passwörter zu kurz oder verschieden")
print("HUB_PASSWORD_HASH=" + password_hash(password))
