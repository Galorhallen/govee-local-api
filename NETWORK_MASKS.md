# Network Mask Configuration Guide

This guide explains how to use the network mask functionality in the Govee Local API controller for precise subnet-aware device routing.

## Overview

The `GoveeController` now supports network masks to provide precise control over which network interface is used to communicate with devices on specific subnets. This is particularly useful in complex network environments with:

- Multiple VLANs or subnets
- Physically separated networks
- Enterprise networks with specific routing requirements
- IoT devices distributed across different network segments

## Basic Usage

### Single Interface with Network Mask

```python
from govee_local_api import GoveeController

# Listen on specific interface with /24 subnet (255.255.255.0)
controller = GoveeController(
    listening_addresses="192.168.1.100",
    network_masks="/24"
)
```

### Multiple Interfaces with Network Masks

```python
# Multiple interfaces with corresponding masks
controller = GoveeController(
    listening_addresses=[
        "192.168.1.100",    # Main LAN
        "192.168.10.100",   # IoT VLAN
        "10.0.0.100"        # Management network
    ],
    network_masks=[
        "/24",              # 192.168.1.0/24
        "255.255.255.0",    # 192.168.10.0/24 (alternative notation)
        "/8"                # 10.0.0.0/8 (large network)
    ]
)
```

## Network Mask Formats

The controller supports two standard network mask formats:

### CIDR Notation

- `/24` - 255.255.255.0 (254 hosts)
- `/16` - 255.255.0.0 (65,534 hosts)
- `/8` - 255.0.0.0 (16,777,214 hosts)
- `/30` - 255.255.255.252 (2 hosts)

### Dotted Decimal Notation

- `255.255.255.0` - /24 subnet
- `255.255.0.0` - /16 subnet
- `255.0.0.0` - /8 subnet
- `255.255.255.252` - /30 subnet

### Mixed Notation Support

You can mix both formats in the same configuration:

```python
controller = GoveeController(
    listening_addresses=["192.168.1.100", "10.0.0.100", "172.16.1.100"],
    network_masks=["/24", "255.0.0.0", "/20"]
)
```

## How Transport Selection Works

When the controller needs to communicate with a device, it uses the following logic:

1. **Precise Subnet Matching**: If network masks are provided, it calculates which listening interface's subnet contains the target device IP
2. **Best Match Selection**: Uses the most specific (smallest) subnet that matches
3. **Graceful Fallback**: If no subnet matches or masks are invalid, falls back to heuristic matching
4. **Wildcard Handling**: Automatically skips `0.0.0.0` addresses in subnet calculations

### Example Scenarios

#### Scenario 1: Corporate Network with VLANs

```python
controller = GoveeController(
    listening_addresses=[
        "192.168.1.50",     # Main office LAN
        "192.168.10.50",    # Conference room VLAN
        "192.168.20.50"     # Executive floor VLAN
    ],
    network_masks=[
        "/24",              # 192.168.1.0/24
        "/24",              # 192.168.10.0/24
        "/24"               # 192.168.20.0/24
    ]
)

# Device on main LAN → uses 192.168.1.50 interface
await controller.control_device("192.168.1.100", turn_on=True)

# Device on conference VLAN → uses 192.168.10.50 interface
await controller.control_device("192.168.10.25", turn_on=True)
```

#### Scenario 2: Mixed Network Sizes

```python
controller = GoveeController(
    listening_addresses=[
        "192.168.1.100",    # Small office network
        "10.0.0.100"        # Large corporate network
    ],
    network_masks=[
        "/24",              # 192.168.1.0/24 (254 hosts)
        "/8"                # 10.0.0.0/8 (16M+ hosts)
    ]
)

# Precise routing based on network size
await controller.control_device("192.168.1.200", turn_on=True)  # → 192.168.1.100
await controller.control_device("10.50.100.200", turn_on=True)  # → 10.0.0.100
```

#### Scenario 3: Physically Separated Networks

```python
# Building A and Building B with no inter-building routing
controller = GoveeController(
    listening_addresses=[
        "192.168.1.100",    # Building A
        "192.168.1.200"     # Building B (same subnet, different physical network)
    ],
    network_masks=[
        "255.255.255.128",  # 192.168.1.0/25 (hosts 1-126)
        "255.255.255.128"   # 192.168.1.128/25 (hosts 129-254)
    ]
)
```

## Error Handling and Validation

### Address/Mask Count Validation

```python
# This will raise ValueError
controller = GoveeController(
    listening_addresses=["192.168.1.100", "10.0.0.100"],
    network_masks=["/24"]  # Only 1 mask for 2 addresses
)
# ValueError: Number of network_masks must match number of listening_addresses
```

### Invalid Mask Handling

```python
controller = GoveeController(
    listening_addresses=["192.168.1.100"],
    network_masks=["invalid.mask"]
)

# Controller logs warning and falls back to heuristic matching
# Device communication continues to work
```

### IPv6 Support

IPv6 addresses are gracefully handled with fallback to the first available transport:

```python
# IPv6 device will use first transport
await controller.control_device("2001:db8::1", turn_on=True)
```

## Performance Considerations

- **Subnet Calculations**: Performed once during transport selection, cached for duration of operation
- **Memory Overhead**: Minimal - only stores network objects for configured interfaces
- **Network Efficiency**: Reduces broadcast traffic by using correct interface for each subnet
- **Scalability**: Supports any number of interfaces limited only by system resources

## Migration from Heuristic Matching

If you're currently using the controller without network masks, you can migrate gradually:

### Before (Heuristic Matching)

```python
controller = GoveeController(
    listening_addresses=["192.168.1.100", "10.0.0.100"]
    # No network_masks - uses heuristic matching
)
```

### After (Precise Subnet Matching)

```python
controller = GoveeController(
    listening_addresses=["192.168.1.100", "10.0.0.100"],
    network_masks=["/24", "/8"]  # Now uses precise matching
)
```

The migration is backward compatible - existing code continues to work unchanged.

## Best Practices

1. **Use Specific Subnets**: Prefer smaller, more specific subnets (like /24) over large ones (like /8) when possible
2. **Document Network Topology**: Keep clear documentation of which interface serves which network segment
3. **Test Edge Cases**: Verify behavior with devices at subnet boundaries
4. **Monitor Logs**: Watch for warnings about invalid masks or failed subnet calculations
5. **Plan for Growth**: Design subnet assignments to accommodate future network expansion

## Troubleshooting

### Device Not Responding

1. Check if device IP is in the expected subnet range
2. Verify network mask configuration matches actual network topology
3. Enable debug logging to see transport selection decisions
4. Test with a simple ping to verify network connectivity

### Unexpected Transport Selection

1. Verify network mask calculations with a subnet calculator
2. Check for overlapping subnets that might cause ambiguous matching
3. Review logs for subnet matching decisions
4. Test with known good device IPs in each subnet

### Performance Issues

1. Reduce number of listening interfaces if not needed
2. Use more specific network masks to reduce calculation overhead
3. Check system network configuration for routing issues
4. Monitor network traffic to identify bottlenecks
