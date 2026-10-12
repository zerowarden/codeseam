class Profile:
    def __init__(self, handle, bio):
        self._handle = handle
        self._bio = bio

    def get_handle(self):
        return self._handle

    def get_bio(self):
        return self._bio
