class CodeseamError(Exception):
    exit_code = 3


class ConfigError(CodeseamError):
    exit_code = 2


class RepositoryContextError(CodeseamError):
    exit_code = 2
