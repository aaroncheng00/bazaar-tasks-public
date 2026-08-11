"""Shared base module for the cascade. Ships the INCOMPLETE / subtly-wrong code
that steps 1-3 build on. Keep a `BUG:` marker so the Dockerfile grep-guard passes."""


class Widget:
    def __init__(self):
        self._state = {}

    # BUG: <describe the shipped defect the cascade repairs/extends; keep it real, not a strawman>
    def do(self, *args, **kwargs):
        raise NotImplementedError  # step 1 implements the base mechanism
