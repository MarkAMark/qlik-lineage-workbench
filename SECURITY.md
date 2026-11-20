# Security and data handling

Trace reads Qlik export files from a directory selected on the same machine and keeps an analysis snapshot in the Python process. It does not require Qlik, database or AWS credentials and does not execute imported SQL or Qlik script.

The service binds to `127.0.0.1`. It has no user authentication and is intended for local use only. Local users and processes may access metadata through its HTTP APIs. Avoid exposing the port through a proxy or port forwarding. Treat exports as sensitive; scripts and JSON can contain credentials even when there are no data rows.

Public source and release packages exclude metadata, reports and business screenshots. User exports are not included in public builds. Dependency installation contacts package registries; normal analysis uses local resources. Public Issues and pull requests must use synthetic examples.

For suspected vulnerabilities, use GitHub private vulnerability reporting if the repository maintainer has enabled it. Do not post secrets, exports or exploit details publicly. If private reporting is unavailable, contact the repository maintainer through an available private channel.
