"""Allow running the package directly: python -m github_ingest"""

import sys
from .cli import main

sys.exit(main())
