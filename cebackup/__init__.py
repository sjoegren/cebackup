class BackupException(Exception):
    """Backup exception type.

    Args:
        message: error message.
        *args: arguments for %s formatting of message.
        retcode: attach a return code to exit the program with.
    """

    _default_retcode = 1

    def __init__(self, message, *args, retcode=None):
        self._message = message
        self._args = args
        self.retcode = retcode if retcode is not None else self._default_retcode
        super().__init__(message, *args)

    def __str__(self):
        return self._message % self._args
