from __future__ import annotations

import ipaddress


def _normalize_to_list(value: str | list[str]) -> list[str]:
    """Convert a single string or iterable of strings to a normalized list."""
    if isinstance(value, str):
        return [value]
    return list(value)


def _parse_address_and_mask(
    address_str: str,
) -> tuple[str, ipaddress.IPv4Network | None]:
    """Parse an address string that may contain a network mask.

    Supported formats:
        - "192.168.1.100/24" (CIDR notation)
        - "192.168.1.100/255.255.255.0" (dotted netmask)
        - "192.168.1.100" (no mask, returns None for network)
        - "0.0.0.0" (wildcard, returns None for network)

    Returns:
        Tuple of (ip_address, network_or_none).
    """
    if "/" not in address_str:
        return (address_str, None)

    ip_part, mask_part = address_str.split("/", 1)

    if ip_part == "0.0.0.0":
        return (ip_part, None)

    try:
        network = ipaddress.ip_network(f"{ip_part}/{mask_part}", strict=False)
        if isinstance(network, ipaddress.IPv4Network):
            return (ip_part, network)
        return (ip_part, None)
    except (ValueError, ipaddress.AddressValueError):
        return (ip_part, None)


def _parse_listening_addresses(
    addresses: str | list[str],
) -> tuple[list[str], list[ipaddress.IPv4Network | None]]:
    """Parse listening addresses, extracting embedded network masks.

    Returns:
        Tuple of (list of IP addresses, list of networks or None per address).
    """
    raw_list = _normalize_to_list(addresses)
    ips: list[str] = []
    networks: list[ipaddress.IPv4Network | None] = []
    for entry in raw_list:
        ip, network = _parse_address_and_mask(entry)
        ips.append(ip)
        networks.append(network)
    return (ips, networks)


_RFC1918_172_16 = ipaddress.IPv4Network("172.16.0.0/12")


def _is_ip_in_same_network_heuristic(
    ip1: ipaddress.IPv4Address, ip2: ipaddress.IPv4Address
) -> bool:
    """
    Best-effort check if two IPs are likely on the same network.
    Uses common subnet assumptions for private networks.
    """
    # Check if both are in the same /24 network (common case)
    if ip1.packed[:3] == ip2.packed[:3]:
        return True

    if not (ip1.is_private and ip2.is_private):
        return False

    # 192.168.0.0/16
    if ip1.packed[:2] == b"\xc0\xa8" and ip2.packed[:2] == b"\xc0\xa8":
        return True

    # 10.0.0.0/8
    if ip1.packed[0] == 10 and ip2.packed[0] == 10:
        return True

    # 172.16.0.0/12 — RFC1918 mid-range; same /12 means they're peers.
    if ip1 in _RFC1918_172_16 and ip2 in _RFC1918_172_16:
        return True

    return False
