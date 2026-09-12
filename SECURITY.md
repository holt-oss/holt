# Security policy

Holt reads public GitHub data and can send selected evidence to a configured
model provider. A vulnerability that exposes credentials, reads data outside
the requested repository, bypasses the evidence boundary, enables unintended
GitHub writes, or misrepresents a network action is in scope.

## Supported versions

Security fixes are made on `main` and released in the newest published version.
Older releases are not supported during the pre-1.0 period.

## Report a vulnerability privately

Email **aahilminookhan@gmail.com** with the subject `[Holt security]`.

Please include:

- the affected version or commit;
- the operating system and Python version;
- steps to reproduce or a minimal proof of concept;
- the impact you believe is possible; and
- whether the report or any suggested fix may be disclosed publicly.

Do not include live credentials or private repository contents. Use redacted
examples and offer to coordinate a safer transfer if sensitive material is
necessary.

Please do not open a public issue until a fix or disclosure plan has been
agreed. Reports will be acknowledged as soon as practical, investigated
privately, and credited in the eventual advisory unless the reporter prefers to
remain anonymous.

## Not a security vulnerability

An incorrect repository verdict without a boundary or integrity failure is a
product bug and can use the public bug-report form. Disagreement with a cited
public pull-request thread is also not a security report; open a normal issue
and link the evidence in question.
