from py.hooks.collector import collect_errors


def on_setup(item):
    collect_errors(item.config)


def on_call(item):
    collect_errors(item.config)


def on_teardown(item):
    collect_errors(item.config)
