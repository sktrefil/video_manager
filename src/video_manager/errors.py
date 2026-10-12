"""Errors safe to show directly to CLI users."""


class VideoManagerError(Exception):
    exit_code = 1


class InputError(VideoManagerError):
    exit_code = 2


class ToolError(VideoManagerError):
    exit_code = 3
