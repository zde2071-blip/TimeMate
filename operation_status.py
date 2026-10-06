"""Structured task state, independent of user-facing wording."""


def begin(status, phase, message, kind=None, **counts):
    status['kind']=kind or status.get('kind','operation')
    status.update(phase=phase, message=message, total=0, completed=0,
                  success=0, failed=0, added=0, deferred=0, error_code='')
    status.update(counts)


def progress(status, success, failed):
    status.update(completed=success+failed, success=success, failed=failed)


def finish(status, message, **counts):
    status.update(phase='complete', message=message)
    status.update(counts)


def fail(status, message, code='operation_failed'):
    status.update(phase='error', message=message, error_code=code)
