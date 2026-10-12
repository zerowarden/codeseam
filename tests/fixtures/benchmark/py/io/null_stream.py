class NullStream:
    def isatty(self) -> bool:
        return False

    def readable(self) -> bool:
        return False

    def snapshot(self) -> str:
        return ""
