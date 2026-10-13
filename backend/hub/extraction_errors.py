"""Stable parser diagnostics; never expose document text or subprocess stderr."""

ERROR_MESSAGES = {
    "PDF_ENCRYPTED": "Das PDF ist passwortgeschützt. Bitte eine ungeschützte Kopie hochladen.",
    "PDF_PAGE_LIMIT": (
        "Das PDF überschreitet das Limit von 100 Seiten. Bitte in "
        "kleinere Dateien aufteilen."
    ),
    "TEXT_LIMIT": (
        "Die extrahierte Textmenge überschreitet das Verarbeitungslimit. "
        "Bitte das Dokument aufteilen."
    ),
    "OCR_RUNTIME_MISSING": (
        "Die lokale OCR oder ihre Sprachdaten sind nicht verfügbar. "
        "Serverinstallation prüfen."
    ),
    "OCR_FAILED": (
        "Die lokale OCR konnte die Scan-Seite nicht verarbeiten. Bitte "
        "einen lesbaren Scan verwenden."
    ),
    "OCR_TIMEOUT": (
        "Eine Scan-Seite überschreitet das OCR-Zeitlimit. Bitte den Scan "
        "vereinfachen oder neu scannen."
    ),
    "PARSER_TIMEOUT": (
        "Die lokale Extraktion hat ihr Zeitlimit erreicht. Bitte das "
        "Dokument in kleinere Dateien aufteilen."
    ),
    "PARSER_RESOURCE_LIMIT": (
        "Die lokale Extraktion hat ihre Ressourcenbegrenzung erreicht. "
        "Bitte das Dokument aufteilen."
    ),
    "PDF_INVALID": (
        "Das PDF ist beschädigt oder nicht lesbar. Bitte eine neu "
        "gespeicherte PDF-Kopie hochladen."
    ),
    "EXTRACTION_FAILED": (
        "Die lokale Extraktion ist fehlgeschlagen. Dateiformat und "
        "Lesbarkeit prüfen."
    ),
}


class ExtractionError(ValueError):
    def __init__(self, code: str):
        self.code = code if code in ERROR_MESSAGES else "EXTRACTION_FAILED"
        super().__init__(f"[{self.code}] {ERROR_MESSAGES[self.code]}")


def classify_error(error: Exception, suffix: str = "") -> ExtractionError:
    if isinstance(error, ExtractionError):
        return error
    # Match only internal fixed exceptions; their original text is never returned.
    fixed = {
        "Passwortgeschütztes PDF": "PDF_ENCRYPTED",
        "PDF-Seitenlimit überschritten": "PDF_PAGE_LIMIT",
        "Extraktionsgrenze überschritten": "TEXT_LIMIT",
        "OCR-Ausgabe zu groß": "TEXT_LIMIT",
    }
    if str(error) in fixed:
        return ExtractionError(fixed[str(error)])
    if isinstance(error, MemoryError):
        return ExtractionError("PARSER_RESOURCE_LIMIT")
    if suffix == ".pdf" and type(error).__module__.startswith("pypdf"):
        return ExtractionError("PDF_INVALID")
    return ExtractionError("EXTRACTION_FAILED")
