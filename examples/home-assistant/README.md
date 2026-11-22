# Home Assistant: manual Govee IP

This optional patch targets Home Assistant Core `2026.11.2`. Apply it
from the root of a matching Core checkout:

```sh
git apply /path/to/govee-local-api/examples/home-assistant/manual-ip.patch
```

Enter an IPv4 address during setup or under **Configure** for an existing
entry. Leave it blank for multicast-only discovery. Installing the Python
library alone does not add this field to Home Assistant.
