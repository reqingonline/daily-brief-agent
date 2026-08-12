# Contributing

1. Create a branch from `main`.
2. Keep source collection deterministic and treat all external content as untrusted.
3. Never weaken a quality gate merely to make delivery succeed. Add bounded repair or a clear failure marker instead.
4. Add or update deterministic tests for every behavior change.
5. Run:

   ```bash
   python -m compileall -q src tests tools
   python -m unittest discover -s tests -p 'test_*.py' -v
   bash -n scripts/*.sh
   python tools/privacy_scan.py
   ```

6. Do not commit real email addresses, OAuth material, SMTP secrets, subscriber state, logs, generated reports, VPS details, or production paths.
