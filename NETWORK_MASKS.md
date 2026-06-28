# Network Mask Configuration Guide

This guide explains how to use the inline network-mask syntax of
`listening_addresses` to get precise subnet-aware transport selection in
multi-NIC setups.

## Overview

`GoveeController` listens on one or more local IP addresses. When multiple
addresses are provided, it must decide which socket to use to talk to a given
device. Two strategies are available:

- **Heuristic matching** (default, no mask): same `/24`, plus special cases
  for `10.0.0.0/8` and `192.168.0.0/16`.
- **Precise subnet matching** (mask provided): the device IP is tested
  against the parsed network of each listening interface.

The mask is supplied **inline in the address string**. There is no separate
`network_masks` parameter.

## Syntax

`listening_addresses` accepts a single string or a list of strings. Each entry
may carry an optional mask in either CIDR or dotted-decimal form:

```text
"192.168.1.100"                  # no mask  → heuristic matching
"192.168.1.100/24"               # CIDR
"192.168.1.100/255.255.255.0"    # dotted netmask
"0.0.0.0"                        # wildcard (mask is ignored if present)
```

## Examples

### Single interface, no mask

```python
from govee_local_api import GoveeController

controller = GoveeController(listening_addresses="192.168.1.100")
```

### Single interface with CIDR

```python
controller = GoveeController(listening_addresses="192.168.1.100/24")
```

### Multiple interfaces, mixed notation

```python
controller = GoveeController(
    listening_addresses=[
        "192.168.1.100/24",            # CIDR
        "10.0.0.100/255.0.0.0",        # dotted netmask
        "172.16.1.100/20",             # CIDR
    ],
)
```

### Wildcard plus specific (wildcard is dropped)

```python
controller = GoveeController(
    listening_addresses=["0.0.0.0", "192.168.1.100/24"],
)
# Effective listening_addresses: ["192.168.1.100"]
```

When `0.0.0.0` is combined with any specific address, the wildcard entry is
dropped to avoid duplicate packet processing (`0.0.0.0` receives on every
local interface).

## Transport selection

For each outbound message the controller picks a transport as follows:

1. If only one transport exists, use it.
2. Otherwise, for each non-wildcard listening address:
   - If it has a parsed network → test `target_ip in network` (precise match).
   - If it has no mask → apply the heuristic.
3. If no match is found, return the first non-wildcard transport.
4. As a last resort, return the first transport.

## Diagnostics

The controller exposes the parsed configuration for inspection:

```python
controller.listening_addresses   # ['192.168.1.100', '10.0.0.100']
controller.networks              # [IPv4Network('192.168.1.0/24'), None]
```

`controller.networks[i]` is `None` for entries supplied without a mask and
for `0.0.0.0`.

## Invalid masks

If the mask portion fails to parse, the address is kept and the network is
recorded as `None`; the entry falls back to heuristic matching. The address
itself is **not** validated by the parser — an invalid IP will surface later
as an `OSError` when the socket is bound in `start()`.
