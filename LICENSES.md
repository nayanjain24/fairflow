# FairFlow - Open Source Licenses

This document records the licenses of all direct dependencies, tools, and datasets used in the FairFlow project in accordance with Rule 7.

## Python Dependencies

| Package | Version Range | License | Purpose | Source / Reference |
|---------|---------------|---------|---------|--------------------|
| `pytest` | >= 8.0.0 | MIT | Unit and integration test runner | https://github.com/pytest-dev/pytest/blob/main/LICENSE |
| `pyyaml` | >= 6.0 | MIT | Scenario and contract YAML parsing | https://github.com/yaml/pyyaml/blob/master/LICENSE |
| `fastapi` | (future milestone) | MIT | User intent API service | https://github.com/fastapi/fastapi/blob/master/LICENSE |
| `streamlit` | (future milestone) | Apache-2.0 | Monitoring and audit dashboard | https://github.com/streamlit/streamlit/blob/develop/LICENSE |
| `sqlite3` | Python 3.12 Standard Library | Python Software Foundation License (PSFL) | Persistent store for decisions & measurements | https://docs.python.org/3/license.html |

## System Utilities (Linux Emulation Host)

| Tool | Project / Origin | License | Purpose |
|------|-------------------|---------|---------|
| `tc` / `ip` | `iproute2` (Linux Foundation) | GPL-2.0-only | Emulated network namespace, veth, and qdisc control |
| `iperf3` | ESnet / Lawrence Berkeley National Laboratory | 3-Clause BSD | Synthetic bulk/streaming traffic generation |

## Third-Party Code Notice
No third-party code has been copied into this repository without explicit attribution and licensing verification.
All code authored herein is developed specifically for the FairFlow project.
