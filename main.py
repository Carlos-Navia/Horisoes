from __future__ import annotations

import sys

from auditoria_pdf.cli import AuditCliApplication
    

def main() -> int:
    app = AuditCliApplication()
    return app.run()


if __name__ == "__main__":
    sys.exit(main())