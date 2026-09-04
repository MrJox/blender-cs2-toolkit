class ImportNote(str):
    # A str subclass, so every existing consumer - the report dialog, the tests' substring checks,
    # joins - keeps treating it as the plain string it always was. Only the operator asks for the
    # severity, which is what keeps "the skeleton was found here" out of the warning channel.
    severity = "INFO"


def severity_of(message) -> str:
    return getattr(message, "severity", "WARNING")


__all__ = ["ImportNote", "severity_of"]
