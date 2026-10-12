class ClosedStream:
    def seekable(self) -> bool:
        return False

    def writable(self) -> bool:
        return False

    def snapshot(self) -> str:
        return ""
