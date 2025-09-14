# Multiple Network Interface Support for GoveeController

## Summary

This update extends the GoveeController to support listening on multiple network interfaces simultaneously, enabling better device discovery across different network segments, **including physically separated networks**.

## Key Changes

### 1. **New Parameter: `listening_addresses`**

- **Type**: `str | list[str]`
- **Default**: `"0.0.0.0"`
- **Purpose**: Allows specifying one or more IP addresses to listen on

### 2. **Backward Compatibility**

- The old `listening_address` parameter is still supported but deprecated
- Shows a warning when used, directing users to the new parameter
- Seamlessly converts single addresses to the new list format

### 3. **Multiple Transport Support**

- Creates separate UDP endpoints for each listening address
- Each interface gets its own protocol handler (`GoveeControllerProtocol`)
- Proper cleanup of all transports when shutting down

### 4. **Enhanced Broadcast Behavior**

- **Discovery broadcasts are sent from ALL listening interfaces** for maximum coverage
- Better network reach, especially important for multicast traffic
- Increases chances of reaching devices on different network segments

### 5. **Intelligent Transport Selection for Physically Separated Networks** 🆕

- **Smart unicast routing**: Commands are sent via the most appropriate interface
- **Network-aware selection**: Automatically detects which transport can best reach each device
- **Fallback mechanism**: Graceful handling when network matching isn't possible

### 6. **Protocol Architecture**

- New `GoveeControllerProtocol` class handles individual interface connections
- Proper multicast membership management per interface
- Coordinated cleanup signaling when all protocols disconnect

## Usage Examples

### Single Interface (Backward Compatible)

```python
# Original way (still works)
controller = GoveeController(listening_addresses="192.168.1.100")

# Deprecated but supported
controller = GoveeController(listening_address="192.168.1.100")  # Shows warning
```

### Multiple Interfaces

```python
# Listen on multiple network interfaces
controller = GoveeController(
    listening_addresses=["192.168.1.100", "10.0.0.50", "172.16.0.10"]
)

# Access the configured addresses
print(controller.listening_addresses)  # ['192.168.1.100', '10.0.0.50', '172.16.0.10']
```

### Physically Separated Networks

```python
# Example: Home with multiple isolated network segments
controller = GoveeController(
    listening_addresses=[
        "192.168.1.100",  # Main home network
        "10.0.0.50",      # IoT VLAN (isolated)
        "172.16.0.10"     # Guest network (isolated)
    ]
)

# The controller will:
# 1. Send broadcasts from ALL interfaces for maximum discovery
# 2. Intelligently route device commands via the appropriate interface
# 3. Handle cases where networks can't communicate with each other
```

## Benefits for Physically Separated Networks

### 🎯 **Intelligent Transport Selection**

When you have devices on different network segments that cannot directly communicate (VLANs, firewalls, separate switches), the controller now:

- **Analyzes target IP addresses** to determine the best interface for communication
- **Matches devices to interfaces** based on network topology (same /24, /16, or /8 networks)
- **Routes traffic appropriately** instead of trying to send everything from one interface

### 📡 **Maximum Discovery Coverage**

- **Broadcasts sent from every interface** ensure devices on all network segments receive discovery messages
- **Increases discovery success rate** in complex network environments
- **Works with multicast restrictions** common in enterprise/VLAN environments

### 🔄 **Automatic Fallback**

- **Graceful degradation** when network matching fails
- **Prefers specific interfaces** over wildcard (0.0.0.0) addresses
- **Continues working** even with invalid or unreachable network configurations

## Real-World Scenarios

### 1. **VLAN Segmentation**

```
Network Setup:
- VLAN 10: 192.168.10.x (Home devices)
- VLAN 20: 192.168.20.x (IoT devices)
- VLAN 30: 192.168.30.x (Guest devices)

Controller Configuration:
listening_addresses=["192.168.10.100", "192.168.20.100", "192.168.30.100"]

Result: Devices in each VLAN discovered and controlled properly
```

### 2. **Multiple Physical Networks**

```
Network Setup:
- Ethernet: 192.168.1.x (Wired devices)
- WiFi Main: 10.0.0.x (WiFi devices)
- WiFi Guest: 172.16.0.x (Guest devices)

Controller Configuration:
listening_addresses=["192.168.1.100", "10.0.0.100", "172.16.0.100"]

Result: All networks covered despite physical separation
```

### 3. **Firewall/Router Isolation**

```
Network Setup:
- Subnet A: 192.168.1.x (blocked from Subnet B)
- Subnet B: 192.168.2.x (blocked from Subnet A)

Controller Configuration:
listening_addresses=["192.168.1.100", "192.168.2.100"]

Result: Devices in both subnets work despite inter-subnet blocking
```

## Technical Implementation

### Transport Selection Algorithm

1. **Network Matching**: Try to find an interface on the same network as the target device
2. **Subnet Detection**: Use common private network patterns (/24, /16, /8) for matching
3. **Interface Preference**: Prefer specific IP addresses over wildcard addresses
4. **Graceful Fallback**: Use first available transport when matching fails

### Broadcast Strategy

- **All interfaces broadcast**: Discovery messages sent from every configured interface
- **Interface-specific**: Each interface properly joins multicast groups
- **Maximum coverage**: Ensures no network segment is missed

### Error Handling

- **Invalid addresses**: Gracefully handle misconfigured IP addresses
- **Network failures**: Continue operation even if some interfaces fail
- **Cleanup coordination**: Properly close all interfaces during shutdown

## Test Coverage

Comprehensive tests added covering:

- Single and multiple interface initialization
- Backward compatibility with deprecated parameter
- Intelligent transport selection for same/different networks
- Fallback behavior for unknown networks
- Wildcard address handling
- Network matching logic validation
- Broadcast message sending from all transports
- Proper cleanup of all resources

This enhancement transforms the GoveeController from a single-interface solution into a **network-aware, multi-segment device controller** capable of operating in the most complex network environments.
