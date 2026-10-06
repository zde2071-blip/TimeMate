"""Only intentional, credential-free diagnostics cross the API boundary."""


class UserFacingError(ValueError):
    code = 'invalid_input'


def payload(error):
    if isinstance(error, UserFacingError):
        return {'error': str(error), 'error_code': error.code}
    return {'error': '操作未完成，请检查设置和所选邮件。', 'error_code': 'operation_failed'}
