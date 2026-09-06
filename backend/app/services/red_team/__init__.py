"""Adversarial AI safety / red-team laboratory.

Every case in cases.py exercises a REAL, already-deployed defense mechanism
— the same grounding validator, citation validator, attachment-upload
guard, RBAC permission table, PII redactor and sensitive-category scanner
the live product uses — never a mock or a simulated stand-in. A case that
finds a real gap (e.g. the PII redactor not catching a base64-encoded
secret) reports that gap honestly; nothing here is tuned to always pass.
"""
